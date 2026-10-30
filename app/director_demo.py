"""English director for the bundled gym: uv run python -m app.director_demo."""

from __future__ import annotations

import math
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event
from uuid import uuid4

import numpy as np

from .director.commands import InstructionTicket, QueueRejection, WithdrawalOutcome
from .director.models import MODE_MAX_SPEEDS, ExecutionPhase
from .director.planner import (
    PlanStep,
    generate_plan,
    repair_body_step,
)
from .director.settings import DirectorSettings
from .director.spatial import (
    SceneObservation,
    observation_from_document,
)
from .runtime.common.motion import LocomotionCommand
from .scene_preview import ScenePreview

TARGET_NAMES = {
    "small_box": "SmallJumpSP",
    "vault": "MidJumpSP",
    "bar": "AvoidanceSP",
    "seat": "SitSP",
}
STYLE_MODES = {
    "walk": "linear_1d",
    "run": "linear_1d",
    "skip": "skipping_1d",
    "zombie": "zombie_1d",
    "crouch": "crouch_directional_2d",
}


class DirectorDemo(ScenePreview):
    """Translate plans into commands without blocking the rendering thread."""

    def __init__(
        self,
        viewer,
        scene_path: Path,
        *,
        fp16: bool = False,
        model: str,
        settings: DirectorSettings | None = None,
    ) -> None:
        self.instruction = "Run behind the small box, circle the seat clockwise, then stop facing the bar."
        self.model = model
        self.settings = (
            settings if settings is not None else DirectorSettings(gemini_model=model)
        )
        self.status = "Enter an instruction and press Direct."
        self.steps: tuple[PlanStep, ...] = ()
        self.step_index = 0
        self.phase: ExecutionPhase = "route"
        self.waypoints: list[np.ndarray] = []
        self.waypoint_index = 0
        self.planning_observation: SceneObservation | None = None
        self.step_started = time.monotonic()
        self.request: Future[tuple[PlanStep, ...]] | None = None
        self.body_repair_request: Future[PlanStep] | None = None
        self.body_repair_attempted = False
        self.planning_cancel_event = Event()
        self.planner = ThreadPoolExecutor(max_workers=1)
        self.autonomous = False
        self.pending_instructions: deque[InstructionTicket] = deque()
        self.active_ticket: InstructionTicket | None = None
        self.recent_outcomes: list[dict] = []
        self.body_diagnostics: dict | None = None
        self.planning_image: bytes | None = None
        self.planning_image_revision = 0
        super().__init__(viewer, scene_path, fp16=fp16)
        self.auto_interaction = False

    def close(self) -> None:
        self.planning_cancel_event.set()
        self.planner.shutdown(wait=False, cancel_futures=True)
        super().close()

    def _load_pending_scene(self) -> None:
        self._pending_scene_path = None

    def _dispatch_interaction_input(self) -> None:
        pass

    def _advance_plan(self) -> None:
        self.body_repair_attempted = False
        self.step_index += 1
        self.phase = "route"
        self.waypoints.clear()
        self.waypoint_index = 0
        self.step_started = time.monotonic()
        if self.step_index >= len(self.steps):
            self.autonomous = False
            self.status = "Done. Give the character another instruction."

    def _stop_plan(self) -> None:
        self.planning_cancel_event.set()
        self.body_repair_attempted = False
        if self.body_repair_request is not None:
            self.body_repair_request.cancel()
            self.body_repair_request = None
        self.body_diagnostics = None
        session = getattr(self, "_scene_session", None)
        if (
            session is not None
            and session.state_machine.state.name == "Gemini body pose"
        ):
            session.state_machine.transition_to_idle(session.character)
        self.autonomous = False
        self.steps = ()
        self.waypoints.clear()
        self.status = "Stopped. An interaction in progress finishes in place."
        if self.request is not None:
            self.request.cancel()
            self.request = None

    def _submit_instruction(self) -> None:
        self._stop_plan()
        self.planning_observation = self.scene_observation()
        try:
            self._capture_planning_view()
        except (OSError, RuntimeError, ValueError) as error:
            self.status = f"Scene image capture failed: {error}"
            return
        self.planning_cancel_event = Event()
        self.request = self.planner.submit(
            generate_plan,
            self.instruction,
            self.planning_observation,
            self.model,
            cancellation_event=self.planning_cancel_event,
            settings=self.settings,
            scene_image=self.planning_image,
        )
        self.status = "Gemini is planning…"

    def _capture_planning_view(self) -> None:
        self.planning_image = None
        if self.settings.scene_images:
            from .director.vision import capture_planning_view

            self.planning_image = capture_planning_view(self)
        else:
            self.planning_image = None
        self.planning_image_revision += 1

    def enqueue_instruction(
        self, instruction: str, submitted_by: str
    ) -> InstructionTicket | QueueRejection:
        if len(self.pending_instructions) >= 8:
            return QueueRejection.FULL
        ticket = InstructionTicket(uuid4().hex, instruction, submitted_by)
        self.pending_instructions.append(ticket)
        return ticket

    def withdraw_instruction(
        self, ticket_id: str, submitted_by: str
    ) -> WithdrawalOutcome:
        for index, ticket in enumerate(self.pending_instructions):
            if ticket.id == ticket_id:
                if ticket.submitted_by != submitted_by:
                    return WithdrawalOutcome.DIFFERENT_VIEWER
                del self.pending_instructions[index]
                return WithdrawalOutcome.WITHDRAWN
        return WithdrawalOutcome.NOT_WAITING

    def _finish_ticket(self, outcome: str) -> None:
        if self.active_ticket is not None:
            self.recent_outcomes.insert(
                0,
                {
                    "id": self.active_ticket.id,
                    "instruction": self.active_ticket.instruction,
                    "outcome": outcome,
                },
            )
            del self.recent_outcomes[5:]
            self.active_ticket = None

    def stop_current_instruction(self) -> None:
        self._finish_ticket("Stopped")
        self._stop_plan()

    def clear_instruction_queue(self) -> None:
        self.pending_instructions.clear()

    def _update_instruction_queue(self) -> None:
        if (
            self.active_ticket is not None
            and self.request is None
            and not self.autonomous
        ):
            self._finish_ticket(self.status)
        if (
            self.active_ticket is None
            and self.pending_instructions
            and self.request is None
            and not self.autonomous
        ):
            self.active_ticket = self.pending_instructions.popleft()
            self.instruction = self.active_ticket.instruction
            self._submit_instruction()

    def _accept_steps(self, steps: tuple[PlanStep, ...]) -> None:
        self.body_repair_attempted = False
        self.steps = steps
        self.step_index = 0
        self.phase = "route"
        self.waypoints.clear()
        self.waypoint_index = 0
        self.step_started = time.monotonic()
        self.autonomous = True

    def scene_observation(self) -> SceneObservation:
        """Snapshot live geometry and actor state before the worker request starts."""
        session = self._scene_session

        def transform_document(transform):
            return {
                "translation": list(transform.p),
                "rotation_xyzw": list(transform.q),
            }

        definition = session.definition
        document = {
            "character_start": {
                "id": definition.character_start.id,
                "transform": transform_document(definition.character_start.transform),
            },
            "smart_primitives": [
                {
                    "id": item.id,
                    "name": item.name,
                    "transform": transform_document(item.transform),
                }
                for item in definition.smart_primitives
            ],
            "solid_cubes": [
                {
                    "id": item.id,
                    "name": item.name,
                    "transform": transform_document(item.transform),
                    "color": tuple(item.color),
                    "dimensions": {
                        "width": item.width,
                        "depth": item.depth,
                        "height": item.height,
                    },
                }
                for item in definition.solid_cubes
            ],
        }
        character = session.character
        position = character.character_ground_position
        facing = character.movement.current_facing
        observed_state = session.state_machine.state.name
        if (
            session.state_machine.is_interacting
            and self._active_interaction is not None
        ):
            observed_state += f": {self._active_interaction.definition.name}"
        observation = observation_from_document(
            document,
            observed_state,
            position=(float(position[0]), float(position[1])),
            heading_degrees=math.degrees(
                math.atan2(float(facing[1]), float(facing[0]))
            ),
        )
        from .director.body_runtime import observe_body

        return replace(observation, body=observe_body(character))

    def prepare_command(
        self, command: LocomotionCommand, frame_dt: float
    ) -> LocomotionCommand:
        self._update_instruction_queue()
        session = self._scene_session
        character = session.character
        machine = session.state_machine
        idle = LocomotionCommand(
            facing_direction=character.movement.current_facing, movement=None
        )
        if self.request is not None and self.request.done():
            request, self.request = self.request, None
            try:
                self._accept_steps(request.result())
            except (ValueError, OSError, TimeoutError) as error:
                self.status = str(error)
        if not self.autonomous:
            return idle
        step = self.steps[self.step_index]
        self.status = f"Step {self.step_index + 1}/{len(self.steps)}: {step.action} {step.target or ''}"
        step_timeout = 120 if self.body_repair_request is not None else 60
        if time.monotonic() - self.step_started > step_timeout:
            self._stop_plan()
            self.status = "Step timed out. Try another instruction."
            return idle
        if step.action == "pose":
            if machine.is_interacting:
                return idle
            from .director.body_runtime import GeneratedBodyState, solve_body_target

            if self.body_repair_request is not None:
                self.status = (
                    "Gemini is repairing the body target using the current skeleton…"
                )
                if not self.body_repair_request.done():
                    return idle
                repair_request, self.body_repair_request = (
                    self.body_repair_request,
                    None,
                )
                try:
                    step = repair_request.result()
                    self.steps = (
                        *self.steps[: self.step_index],
                        step,
                        *self.steps[self.step_index + 1 :],
                    )
                    self.step_started = time.monotonic()
                except (ValueError, OSError, TimeoutError) as error:
                    self._stop_plan()
                    self.status = f"Body target repair failed: {error}"
                    return idle
            if self.phase != "body":
                try:
                    assert (
                        step.body_pose is not None
                    )  # Established by the PlanStep contract.
                    constraints = step.body_pose
                    if constraints.contact is not None:
                        from .director.contact import validate_contact_pose

                        observation = self.scene_observation()
                        constraints = validate_contact_pose(
                            constraints,
                            observation,
                            observation.character_position,
                            observation.character_heading_degrees,
                        )
                    target_pose, diagnostics = solve_body_target(character, constraints)
                    diagnostics["repairAttempts"] = int(self.body_repair_attempted)
                    body_state = GeneratedBodyState(
                        target_pose, character, step.seconds, diagnostics
                    )
                    machine.transition_to(character, body_state)
                    self.body_diagnostics = diagnostics
                    self.phase = "body"
                except ValueError as error:
                    if not self.body_repair_attempted:
                        self.body_repair_attempted = True
                        try:
                            self._capture_planning_view()
                        except (OSError, RuntimeError, ValueError) as capture_error:
                            self._stop_plan()
                            self.status = f"Scene image capture failed during repair: {capture_error}"
                            return idle
                        self.body_repair_request = self.planner.submit(
                            repair_body_step,
                            step,
                            self.instruction,
                            self.scene_observation(),
                            str(error),
                            self.model,
                            cancellation_event=self.planning_cancel_event,
                            settings=self.settings,
                            scene_image=self.planning_image,
                        )
                        self.step_started = time.monotonic()
                        self.status = "Gemini is repairing the rejected body target…"
                    else:
                        self._stop_plan()
                        self.status = f"Body target rejected after repair: {error}"
                return idle
            if isinstance(machine.state, GeneratedBodyState) and machine.state.finished:
                self._advance_plan()
            return idle
        if machine.state.name == "Gemini body pose" and step.action not in (
            "wait",
            "stop",
        ):
            machine.transition_to_idle(character)
            self.body_diagnostics = None
        if step.action == "stop":
            self._advance_plan()
            return idle
        if step.action == "wait":
            if time.monotonic() - self.step_started >= step.seconds:
                self._advance_plan()
            return idle
        if self.phase == "interaction":
            if (
                step.target == "seat" and machine.interaction_state.is_looping
            ) or not machine.is_interacting:
                self._advance_plan()
            return idle
        if self.phase == "arrival":
            if character.time_to_transition() <= frame_dt:
                self._advance_plan()
            return idle
        if machine.is_interacting:
            if (
                self.phase != "standing"
                and self._active_interaction is not None
                and self._active_interaction.definition.name == "SitSP"
                and machine.interaction_state.is_looping
            ):
                machine.interact()
                self.phase = "standing"
            return idle
        if step.action == "stand":
            self._advance_plan()
            return idle
        if self.phase == "standing":
            self.phase = "route"
        position = character.character_ground_position
        if not self.waypoints:
            self.waypoints = [
                np.array([*waypoint.position, 0], dtype=np.float32)
                for waypoint in step.waypoints
            ]
            self.waypoint_index = 0
        if step.action == "interact":
            assert step.target is not None  # Established by the PlanStep contract.
            target_name = TARGET_NAMES[step.target]
            target = next(
                instance
                for instance in session.smart_primitives
                if instance.definition.name == target_name
            )
            # Follow the generated approach before using the authored interaction.
            if self.waypoint_index >= len(step.waypoints) - 1 and target.interactable:
                self._start_smart_primitive_interaction(target)
                self.phase = "interaction"
                return idle
        displacement = self.waypoints[0] - position
        displacement[2] = 0
        distance = float(np.linalg.norm(displacement))
        while distance < 0.55 and len(self.waypoints) > 1:
            self.waypoints.pop(0)
            self.waypoint_index += 1
            displacement = self.waypoints[0] - position
            displacement[2] = 0
            distance = float(np.linalg.norm(displacement))
        waypoint = step.waypoints[self.waypoint_index]
        if step.action == "move" and len(self.waypoints) == 1 and distance < 1.25:
            facing = character.movement.current_facing.copy()
            if waypoint.heading_degrees is not None:
                radians = math.radians(waypoint.heading_degrees)
                facing = np.array(
                    [math.cos(radians), math.sin(radians), 0], dtype=np.float32
                )
            character.movement.face(facing)
            self.phase = "arrival"
            return LocomotionCommand(
                facing_direction=facing,
                movement=None,
                stop_position=self.waypoints[0],
                requested_mode=STYLE_MODES[step.style],
            )
        if distance < 0.55:
            self.waypoints.pop(0)
            self.waypoint_index += 1
            if not self.waypoints:
                if step.action == "interact":
                    self._stop_plan()
                    self.status = "Missed the interaction zone. Try approaching again."
                else:
                    self._advance_plan()
            return idle
        direction = displacement / distance
        style = step.style
        return LocomotionCommand(
            facing_direction=direction,
            movement=direction * (waypoint.speed / MODE_MAX_SPEEDS[style]),
            use_max_speed=True,
            requested_mode=STYLE_MODES[style],
        )

    def gui(self, ui) -> None:
        ui.set_next_window_size(ui.ImVec2(470, 360), ui.Cond_.first_use_ever)
        expanded, _ = ui.begin("Direct the character")
        if expanded:
            ui.text_wrapped(
                "Tell the character where to go and what to do in this gym."
            )
            _, self.instruction = ui.input_text_multiline(
                "##instruction", self.instruction, ui.ImVec2(-1, 80)
            )
            if ui.button("Direct"):
                self._submit_instruction()
            ui.same_line()
            if ui.button("Stop"):
                self._stop_plan()
            ui.text_wrapped(self.status)
            ui.separator()
            for index, step in enumerate(self.steps):
                marker = ">" if self.autonomous and index == self.step_index else " "
                ui.text_wrapped(
                    f"{marker} {index + 1}. {step.action} {step.target or ''} ({step.style}, {len(step.waypoints)} spatial targets)"
                )
            ui.separator()
            ui.text_wrapped(
                "Try: Run to the vault and vault over it. Duck under the bar, then sit. Stand up and walk to the small box like a zombie."
            )
        ui.end()


def main() -> None:
    """Launch the fixed gym and its English director panel."""
    import newton.examples

    from .utils.cli import (
        add_model_precision_argument,
        configure_logging,
        create_gl_parser,
    )
    from .utils.model_loading import require_tensorrt

    parser = create_gl_parser()
    add_model_precision_argument(parser)
    parser.add_argument("--model", default=None)
    viewer, arguments = newton.examples.init(parser)
    try:
        settings = DirectorSettings(
            **({"gemini_model": arguments.model} if arguments.model is not None else {})
        )
    except ValueError as error:
        parser.error(str(error))
    configure_logging(arguments)
    require_tensorrt()
    scene_path = (
        Path(__file__).resolve().parents[1] / "assets/scenes/soma_gym.scene.json"
    )
    DirectorDemo(
        viewer,
        scene_path,
        fp16=arguments.model_precision == "fp16",
        model=settings.gemini_model,
        settings=settings,
    ).run(arguments.num_frames if arguments.test else None)


if __name__ == "__main__":
    main()
