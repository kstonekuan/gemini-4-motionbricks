"""Serve a native browser director with skeletal poses instead of desktop video."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
from collections.abc import AsyncGenerator
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from pydantic import SecretStr
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .director.commands import InstructionTicket, QueueRejection, WithdrawalOutcome
from .director.models import InstructionSubmission, WithdrawalSubmission
from .director.settings import DirectorSettings

if TYPE_CHECKING:
    from .director_demo import DirectorDemo

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RequestBodyLimit:
    """Bound buffered command JSON even when a client uses chunked transfer."""

    def __init__(self, app: ASGIApp, max_bytes: int = 16384) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        received_bytes = 0

        async def receive_bounded_body() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise HTTPException(
                        status_code=413, detail="Command body is too large."
                    )
            return message

        await self.app(
            scope, receive_bounded_body if scope["type"] == "http" else receive, send
        )


class BrowserDirector:
    """Keep GPU commands on one thread and stream only the newest frame per client."""

    def __init__(self, director: DirectorDemo, assets_path: Path) -> None:
        self.director = director
        self.assets_path = assets_path.resolve()
        self.clients: set[asyncio.Queue[tuple[bytes, str]]] = set()
        self.sequence = 0
        self.scene_description = self.describe_scene()

    def describe_scene(self) -> dict:
        from motionbricks.renderers.skeletal_mesh_renderer import SkeletalMeshRenderer

        session = self.director._scene_session
        if not isinstance(session.mesh_renderer, SkeletalMeshRenderer):
            raise TypeError("The browser director requires the SOMA skeletal mesh.")
        skeletal_mesh = session.mesh_renderer.skeletal_mesh
        return {
            "jointNames": skeletal_mesh.skeleton.joint_names,
            "parents": skeletal_mesh.skeleton.parent_indices.numpy().tolist(),
            "inverseBind": skeletal_mesh.inverse_bind_transforms.numpy().tolist(),
            "meshes": [
                {
                    "positions": mesh.points.numpy().reshape(-1).tolist(),
                    "indices": mesh.indices.numpy().tolist(),
                    "jointIndices": mesh.joint_indices.numpy().tolist(),
                    "jointWeights": mesh.joint_weights.numpy().tolist(),
                    "influences": mesh.num_influences,
                }
                for mesh in skeletal_mesh.skinned_meshes
            ],
            "objects": [
                {
                    "name": cube.name,
                    "transform": list(cube.transform),
                    "size": [cube.width, cube.depth, cube.height],
                    "color": list(cube.color),
                }
                for cube in session.definition.solid_cubes
            ],
        }

    def snapshot(self) -> tuple[bytes, str]:
        from .director.body_runtime import GeneratedBodyState
        from .runtime.common.motion import PlaybackSource

        director = self.director
        character = director._scene_session.character
        target_count = (
            0
            if character._playback_source is PlaybackSource.CLIP
            else character.player.target.num_poses
        )
        # These are the exact target poses consumed by the motion player, not
        # decorative poses or positions inferred from the language plan.
        body_state = director._scene_session.state_machine.state
        if isinstance(body_state, GeneratedBodyState):
            target_count = 1
            targets = body_state.targets[:1].numpy()
        else:
            targets = director._scene_session.target_poses[:target_count].numpy()
        pose = character.current_pose.numpy()
        route = np.asarray(director.waypoints, dtype=np.float32).reshape(-1, 3)
        header = np.array(
            [self.sequence, director.time, target_count, len(route)], dtype=np.float32
        )
        binary = (
            np.concatenate(
                [header, pose.reshape(-1), targets.reshape(-1), route.reshape(-1)]
            )
            .astype("<f4")
            .tobytes()
        )
        state = json.dumps(
            {
                "model": director.model,
                "status": director.status,
                "planning": director.request is not None
                or director.body_repair_request is not None,
                "active": director.autonomous,
                "stepIndex": director.step_index,
                "steps": [asdict(step) for step in director.steps],
                "characterState": director._scene_session.state_machine.state.name,
                "targetCount": target_count,
                "planningView": {
                    "available": director.planning_image is not None,
                    "revision": director.planning_image_revision,
                },
                "bodyTarget": director.body_diagnostics,
                "activeInstruction": asdict(director.active_ticket)
                if director.active_ticket
                else None,
                "queuedInstructions": [
                    asdict(ticket) for ticket in director.pending_instructions
                ],
                "recentOutcomes": director.recent_outcomes,
                "viewerCount": len(self.clients),
                "planningOrigin": director.planning_observation.character_position
                if director.planning_observation
                else None,
            }
        )
        return binary, state

    async def run_simulation(self) -> None:
        import warp as wp

        while True:
            frame_started = time.monotonic()
            with wp.ScopedStream(self.director._scene_session.character.engine.stream):
                self.director.step()
                self.sequence += 1
                if self.clients:
                    frame = self.snapshot()
                    for queue in tuple(self.clients):
                        if queue.full():
                            queue.get_nowait()
                        queue.put_nowait(frame)
            await asyncio.sleep(max(0, 1 / 30 - (time.monotonic() - frame_started)))

    async def scene(self) -> JSONResponse:
        return JSONResponse(self.scene_description)

    async def planning_view(self) -> Response:
        if self.director.planning_image is None:
            raise HTTPException(status_code=404, detail="No planning image available.")
        return Response(
            self.director.planning_image,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    async def instruction(self, submission: InstructionSubmission) -> JSONResponse:
        outcome = self.director.enqueue_instruction(
            submission.instruction, submission.viewer_id
        )
        match outcome:
            case InstructionTicket(id=ticket_id):
                return JSONResponse(
                    {"accepted": True, "id": ticket_id}, status_code=202
                )
            case QueueRejection.FULL:
                return JSONResponse(
                    {
                        "error": "The shared queue is full (8 waiting commands). Try again shortly."
                    },
                    status_code=429,
                )
        assert_never(outcome)

    async def stop(self) -> JSONResponse:
        self.director.stop_current_instruction()
        return JSONResponse({"stopped": True})

    async def reset(self) -> JSONResponse:
        self.director.clear_instruction_queue()
        self.director.stop_current_instruction()
        self.director.planning_image = None
        self.director.planning_image_revision += 1
        self.director.load_scene(REPOSITORY_ROOT / "assets/scenes/soma_gym.scene.json")
        self.director.status = "Gym reset. Give the character an instruction."
        return JSONResponse({"reset": True})

    async def withdraw(self, submission: WithdrawalSubmission) -> JSONResponse:
        outcome = self.director.withdraw_instruction(
            submission.ticket_id, submission.viewer_id
        )
        match outcome:
            case WithdrawalOutcome.WITHDRAWN:
                return JSONResponse({"withdrawn": True})
            case WithdrawalOutcome.DIFFERENT_VIEWER:
                message = "Only the submitting tab can withdraw this waiting command."
            case WithdrawalOutcome.NOT_WAITING:
                message = "This command has started or is no longer waiting."
            case _:
                assert_never(outcome)
        return JSONResponse({"error": message}, status_code=409)

    async def clear_queue(self) -> JSONResponse:
        self.director.clear_instruction_queue()
        return JSONResponse({"cleared": True})

    async def websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        queue: asyncio.Queue[tuple[bytes, str]] = asyncio.Queue(maxsize=1)
        self.clients.add(queue)

        async def send_latest_frames() -> None:
            previous_state = ""
            while True:
                binary, state = await queue.get()
                await websocket.send_bytes(binary)
                if state != previous_state:
                    await websocket.send_text(state)
                    previous_state = state

        async def receive_disconnect() -> None:
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass

        sender = asyncio.create_task(send_latest_frames())
        receiver = asyncio.create_task(receive_disconnect())
        try:
            await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            self.clients.discard(queue)
            sender.cancel()
            receiver.cancel()
            for task in (sender, receiver):
                with contextlib.suppress(
                    asyncio.CancelledError, WebSocketDisconnect, ConnectionError
                ):
                    await task

    async def static_file(self, path: str) -> FileResponse | RedirectResponse:
        relative_path = path or "index.html"
        file_path = (self.assets_path / relative_path).resolve()
        if not file_path.is_relative_to(self.assets_path):
            raise HTTPException(status_code=404)
        if not file_path.is_file():
            if relative_path == "vnc.html":
                return RedirectResponse("./", status_code=302)
            raise HTTPException(status_code=404)
        return FileResponse(file_path, headers={"Cache-Control": "no-cache"})

    @contextlib.asynccontextmanager
    async def lifecycle(self, application: FastAPI) -> AsyncGenerator[None]:
        import warp as wp

        simulation = asyncio.create_task(self.run_simulation())
        try:
            yield
        finally:
            simulation.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await simulation
            session = self.director._scene_session
            if session.state_machine.is_interacting:
                with wp.ScopedStream(session.character.engine.stream):
                    session.state_machine.interaction_state.exit(
                        session.character, session.state_machine
                    )
            self.director.close()
            self.director.viewer.close()

    def application(self) -> FastAPI:
        application = FastAPI(
            title="MotionBricks Director",
            lifespan=self.lifecycle,
            docs_url=None,
            redoc_url=None,
            servers=[{"url": "."}],
        )
        application.add_middleware(GZipMiddleware, minimum_size=1024)
        application.add_middleware(RequestBodyLimit)

        @application.exception_handler(RequestValidationError)
        async def invalid_command(
            request: Request, error: RequestValidationError
        ) -> JSONResponse:
            if request.url.path.endswith("/withdraw"):
                return JSONResponse(
                    {"error": "Enter a valid waiting command ID and viewer ID."},
                    status_code=409,
                )
            return JSONResponse(
                {
                    "error": "Enter an instruction of 1–2000 characters and a valid viewer ID."
                },
                status_code=400,
            )

        @application.get("/docs", include_in_schema=False)
        async def api_documentation() -> HTMLResponse:
            # A relative schema URL also works behind Tailscale's path proxy.
            return get_swagger_ui_html(
                openapi_url="openapi.json",
                title="MotionBricks Director API",
                swagger_ui_parameters={"syntaxHighlight": False},
            )

        application.add_api_route("/scene", self.scene, methods=["GET"])
        application.add_api_route(
            "/planning-view.jpg",
            self.planning_view,
            methods=["GET"],
            include_in_schema=False,
        )
        application.add_api_websocket_route("/ws", self.websocket)
        application.add_api_route(
            "/instruction", self.instruction, methods=["POST"], status_code=202
        )
        application.add_api_route("/stop", self.stop, methods=["POST"])
        application.add_api_route("/clear-queue", self.clear_queue, methods=["POST"])
        application.add_api_route("/withdraw", self.withdraw, methods=["POST"])
        application.add_api_route("/reset", self.reset, methods=["POST"])
        application.add_api_route(
            "/{path:path}",
            self.static_file,
            methods=["GET"],
            response_model=None,
            include_in_schema=False,
        )
        return application


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    import newton.viewer
    import warp as wp

    from .director_demo import DirectorDemo

    parser.add_argument("--port", type=int)
    parser.add_argument("--host")
    parser.add_argument("--model")
    parser.add_argument("--secret-stdin", action="store_true")
    parser.add_argument("--assets", type=Path)
    arguments = parser.parse_args()
    overrides = {
        name: value
        for name, value in {
            "port": arguments.port,
            "host": arguments.host,
            "gemini_model": arguments.model,
            "assets": arguments.assets,
        }.items()
        if value is not None
    }
    if arguments.secret_stdin:
        overrides["gemini_api_key"] = SecretStr(sys.stdin.readline().strip())
    try:
        settings = DirectorSettings(**overrides)
    except ValueError as error:
        parser.error(str(error))
    if not (settings.assets / "index.html").is_file():
        parser.error(
            "Build the browser app first: cd web && pnpm install && pnpm build"
        )
    wp.config.log_level = wp.LOG_WARNING
    viewer = newton.viewer.ViewerGL(headless=True, width=960, height=540)
    director = DirectorDemo(
        viewer,
        REPOSITORY_ROOT / "assets/scenes/soma_gym.scene.json",
        fp16=True,
        model=settings.gemini_model,
        settings=settings,
    )
    director.status = "Ready. Tell the character what to do."
    server = BrowserDirector(director, settings.assets)
    uvicorn.run(
        server.application(),
        host=settings.host,
        port=settings.port,
        access_log=False,
        workers=1,
        ws="websockets",
        ws_per_message_deflate=False,
        ws_max_queue=1,
        ws_ping_interval=20,
        ws_ping_timeout=20,
    )


if __name__ == "__main__":
    main()
