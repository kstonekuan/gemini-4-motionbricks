"""Exercise command sequencing with a simulated character, without TensorRT."""

import importlib.util
import sys
import time
import unittest
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.director.commands import QueueRejection, WithdrawalOutcome
from app.director.models import BodyPose
from app.director.planner import PlanStep
from app.director.settings import DirectorSettings
from app.director.spatial import SpatialWaypoint, default_observation

# Replace GPU-facing imports only; execute the real DirectorDemo methods.
preview_module = ModuleType("app.scene_preview")
preview_module.__dict__["ScenePreview"] = object
motion_module = ModuleType("app.runtime.common.motion")
motion_module.__dict__["LocomotionCommand"] = SimpleNamespace
director_specification = importlib.util.spec_from_file_location(
    "app._director_executor_test",
    Path(__file__).resolve().parents[1] / "app/director_demo.py",
)
assert director_specification is not None and director_specification.loader is not None
executor_module = importlib.util.module_from_spec(director_specification)
sys.modules[director_specification.name] = executor_module
with patch.dict(
    sys.modules,
    {"app.scene_preview": preview_module, "app.runtime.common.motion": motion_module},
):
    director_specification.loader.exec_module(executor_module)
DirectorDemo = executor_module.DirectorDemo


class ExecutorTests(unittest.TestCase):
    def make_director(self, steps):
        director = DirectorDemo.__new__(DirectorDemo)
        director.settings = DirectorSettings(_env_file=None, scene_images=False)
        director.planning_image = None
        director.planning_image_revision = 0
        director.pending_instructions = deque()
        director.active_ticket = None
        director.recent_outcomes = []
        director.steps = tuple(steps)
        director.step_index = 0
        director.phase = "route"
        director.waypoints = []
        director.waypoint_index = 0
        director.step_started = time.monotonic()
        director.request = None
        director.body_repair_request = None
        director.body_repair_attempted = False
        director.planning_cancel_event = Event()
        director.autonomous = True
        director.status = ""
        director._active_interaction = None
        machine = SimpleNamespace(
            is_interacting=False,
            interaction_state=SimpleNamespace(is_looping=False),
            state=SimpleNamespace(name="Idle"),
        )
        character = SimpleNamespace(
            movement=SimpleNamespace(current_facing=np.array([1.0, 0, 0])),
            character_ground_position=np.array([-8.0, 4, 0]),
        )
        target = SimpleNamespace(
            definition=SimpleNamespace(name="SmallJumpSP", transform=[4, 0, 0]),
            interactable=False,
        )
        director.__dict__["_scene_session"] = SimpleNamespace(
            character=character, state_machine=machine, smart_primitives=[target]
        )
        return director

    def test_shared_queue_caps_waiters_without_replacing_active_work(self):
        active_step = PlanStep("wait", None, "walk", 20)
        director = self.make_director([active_step])
        tickets = [
            director.enqueue_instruction(f"Command {index}", f"viewer-{index % 2}")
            for index in range(8)
        ]
        self.assertEqual(
            director.enqueue_instruction("Overflow", "third-viewer"),
            QueueRejection.FULL,
        )
        self.assertEqual(list(director.pending_instructions), tickets)
        self.assertEqual(director.steps, (active_step,))
        self.assertTrue(director.autonomous)
        director.clear_instruction_queue()
        self.assertFalse(director.pending_instructions)
        self.assertTrue(director.autonomous)

    def test_withdraw_removes_only_the_submitting_tabs_waiting_command(self):
        director = self.make_director([PlanStep("wait", None, "walk", 20)])
        first = director.enqueue_instruction("First", "viewer-one")
        other = director.enqueue_instruction("Other viewer", "viewer-two")
        last = director.enqueue_instruction("Last", "viewer-one")
        self.assertEqual(
            director.withdraw_instruction(other.id, "viewer-one"),
            WithdrawalOutcome.DIFFERENT_VIEWER,
        )
        self.assertEqual(list(director.pending_instructions), [first, other, last])
        self.assertEqual(
            director.withdraw_instruction(first.id, "viewer-one"),
            WithdrawalOutcome.WITHDRAWN,
        )
        self.assertEqual(list(director.pending_instructions), [other, last])
        self.assertEqual(
            director.withdraw_instruction(first.id, "viewer-one"),
            WithdrawalOutcome.NOT_WAITING,
        )
        self.assertTrue(director.autonomous)

    def test_stop_records_current_result_and_preserves_waiters(self):
        director = self.make_director([PlanStep("wait", None, "walk", 20)])
        director.active_ticket = director.enqueue_instruction(
            "Wait twenty seconds", "first"
        )
        director.pending_instructions.popleft()
        waiting = director.enqueue_instruction("Walk forward", "second")
        director.stop_current_instruction()
        self.assertFalse(director.autonomous)
        self.assertIsNone(director.active_ticket)
        self.assertEqual(director.recent_outcomes[0]["outcome"], "Stopped")
        self.assertEqual(list(director.pending_instructions), [waiting])

    def test_move_uses_generated_coordinates_and_speed(self):
        director = self.make_director(
            [
                PlanStep(
                    "move",
                    None,
                    "skip",
                    0,
                    (
                        SpatialWaypoint((-3, 6), 1.3),
                        SpatialWaypoint((-1, 2), 1.4, 90),
                    ),
                )
            ]
        )
        command = director.prepare_command(None, 0.01)
        self.assertEqual(command.requested_mode, "skipping_1d")
        np.testing.assert_allclose(
            command.movement, np.array([5, 2, 0]) / np.sqrt(29) * (1.3 / 1.45)
        )
        np.testing.assert_allclose(director.waypoints[0], [-3, 6, 0])

    def test_spatial_arrival_requests_exact_position_and_heading(self):
        director = self.make_director(
            [PlanStep("move", None, "walk", 0, (SpatialWaypoint((-7, 4), 2, 90),))]
        )
        director._scene_session.character.movement.face = lambda direction: None
        command = director.prepare_command(None, 0.01)
        self.assertEqual(director.phase, "arrival")
        np.testing.assert_allclose(command.stop_position, [-7, 4, 0])
        np.testing.assert_allclose(command.facing_direction, [0, 1, 0], atol=1e-6)

    def test_sit_finishes_only_after_sitting_loop_begins(self):
        director = self.make_director(
            [
                PlanStep(
                    "interact",
                    "seat",
                    "walk",
                    0,
                    (SpatialWaypoint((1.5, -8), 2), SpatialWaypoint((6, -8), 2)),
                )
            ]
        )
        director.phase = "interaction"
        machine = director._scene_session.state_machine
        machine.is_interacting = True
        director.prepare_command(None, 0.01)
        self.assertTrue(director.autonomous)
        machine.interaction_state.is_looping = True
        director.prepare_command(None, 0.01)
        self.assertFalse(director.autonomous)

    def test_stop_discards_pending_reply(self):
        director = self.make_director([PlanStep("stop", None, "walk", 0)])
        pending = Future()
        pending.set_running_or_notify_cancel()
        director.request = pending
        director._stop_plan()
        pending.set_result(
            (PlanStep("move", "small_box", "run", 0, (SpatialWaypoint((-6, 4), 2),)),)
        )
        self.assertIsNone(director.prepare_command(None, 0.01).movement)
        self.assertFalse(director.autonomous)
        self.assertIsNone(director.request)

    def test_timeout_stops_navigation(self):
        director = self.make_director(
            [PlanStep("move", "small_box", "walk", 0, (SpatialWaypoint((-6, 4), 2),))]
        )
        director.step_started -= 61
        self.assertIsNone(director.prepare_command(None, 0.01).movement)
        self.assertIn("timed out", director.status)
        self.assertFalse(director.autonomous)

    def test_replacement_ignores_the_previous_planning_reply(self):
        director = self.make_director([])
        previous_request = Future()
        previous_request.set_running_or_notify_cancel()
        director.request = previous_request
        director.instruction = "wait two seconds"
        director.model = "test-model"
        replacement_plan = (PlanStep("wait", None, "walk", 2),)
        with (
            ThreadPoolExecutor(max_workers=1) as planner,
            patch.object(
                executor_module, "generate_plan", return_value=replacement_plan
            ),
            patch.object(
                director, "scene_observation", return_value=default_observation()
            ),
        ):
            director.planner = planner
            director._submit_instruction()
            self.assertIsNot(director.request, previous_request)
            previous_request.set_result((PlanStep("stop", None, "walk", 0),))
            director.request.result(timeout=2)
            director.prepare_command(None, 0.01)
        self.assertEqual(director.steps, replacement_plan)
        self.assertTrue(director.autonomous)

    def test_failed_repair_image_capture_ends_the_command_without_killing_the_simulation(
        self,
    ):
        pose = BodyPose(
            0.85,
            5,
            0,
            (0.3, 0.2, 1.2),
            (0.1, -0.4, 1.2),
            (0, 0.15, 0.06),
            (0, -0.15, 0.06),
        )
        director = self.make_director(
            [PlanStep("pose", None, "walk", 3, body_pose=pose)]
        )
        with (
            patch(
                "app.director.body_runtime.solve_body_target",
                side_effect=ValueError("unreachable"),
            ),
            patch.object(
                director,
                "_capture_planning_view",
                side_effect=RuntimeError("capture unavailable"),
            ),
        ):
            director.prepare_command(None, 0.01)
        self.assertFalse(director.autonomous)
        self.assertIn("capture unavailable", director.status)


if __name__ == "__main__":
    unittest.main()
