"""Runtime failures must release GPU and planner resources without waiting for exit."""

import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.director_web import BrowserDirector

if TYPE_CHECKING:
    from app.director_demo import DirectorDemo


class FailingSimulation(BrowserDirector):
    # Replace only the GPU boundary; run the actual server resource lifecycle.
    def describe_scene(self) -> dict:
        return {}

    async def run_simulation(self) -> None:
        raise RuntimeError("GPU simulation failed")


class GpuRuntimeBoundary:
    def __init__(self, cleanup_fails: bool) -> None:
        self.cleanup_fails = cleanup_fails
        self.released_resources: set[str] = set()
        self._scene_session = SimpleNamespace(
            state_machine=SimpleNamespace(is_interacting=False)
        )
        self.viewer = SimpleNamespace(close=self.close_viewer)

    def close(self) -> None:
        self.released_resources.add("director")
        if self.cleanup_fails:
            raise RuntimeError("Engine cleanup failed")

    def close_viewer(self) -> None:
        self.released_resources.add("viewer")


class BrowserLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_simulation_interrupts_serving_and_releases_resources(
        self,
    ) -> None:
        for cleanup_fails in (False, True):
            with self.subTest(cleanup_fails=cleanup_fails):
                gpu_runtime = GpuRuntimeBoundary(cleanup_fails)
                browser = FailingSimulation(
                    cast("DirectorDemo", gpu_runtime), Path(".")
                )
                expected_failure = RuntimeError if cleanup_fails else ExceptionGroup
                with self.assertRaises(expected_failure):
                    async with asyncio.timeout(2):
                        async with browser.lifecycle(FastAPI()):
                            # A dead simulation must interrupt an otherwise running lifespan.
                            await asyncio.Future()
                self.assertEqual(gpu_runtime.released_resources, {"director", "viewer"})
                async with AsyncClient(
                    transport=ASGITransport(app=browser.application()),
                    base_url="http://viewer.test",
                ) as client:
                    for path in (
                        "/stop",
                        "/reset",
                        "/clear-queue",
                        "/instruction",
                        "/withdraw",
                    ):
                        response = await client.post(path, json={})
                        self.assertEqual(response.status_code, 503)
