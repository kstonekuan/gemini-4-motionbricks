"""Boundary checks for plans returned by a remote model."""

import json
import unittest
from dataclasses import asdict, replace
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import errors

from app.director.models import BodyPose, SurfaceContact
from app.director.planner import (
    PlannerServiceError,
    PlanningStoppedError,
    PlanStep,
    generate_plan,
    repair_body_step,
    validate_plan,
)
from app.director.spatial import default_observation


class PlannerTests(unittest.TestCase):
    def test_accepts_sequential_interactions_and_waits(self):
        steps = validate_plan(
            {
                "steps": [
                    {
                        "action": "interact",
                        "label": "Jump over the box",
                        "target": "small_box",
                        "style": "skip",
                        "seconds": 0,
                        "waypoints": [
                            {
                                "position": [1.5, 0],
                                "speed": 1.4,
                                "heading_degrees": None,
                            },
                            {"position": [6, 0], "speed": 1.4, "heading_degrees": None},
                        ],
                    },
                    {
                        "action": "wait",
                        "target": None,
                        "style": "walk",
                        "seconds": 2,
                        "waypoints": [],
                    },
                    {
                        "action": "interact",
                        "target": "seat",
                        "style": "walk",
                        "seconds": 0,
                        "waypoints": [
                            {
                                "position": [1.5, -8],
                                "speed": 2,
                                "heading_degrees": None,
                            },
                            {"position": [6, -8], "speed": 2, "heading_degrees": None},
                        ],
                    },
                ]
            }
        )
        self.assertEqual([step.target for step in steps], ["small_box", None, "seat"])
        self.assertEqual(steps[0].label, "Jump over the box")
        self.assertIsNone(steps[1].label)

    def test_rejects_invalid_model_outputs(self):
        valid = {
            "action": "move",
            "target": "seat",
            "style": "walk",
            "seconds": 0,
            "waypoints": [{"position": [2, -8], "speed": 2, "heading_degrees": None}],
        }
        for changes in (
            {"target": "window"},
            {"waypoints": []},
            {"action": "wave"},
            {"seconds": float("nan")},
            {"seconds": True},
            {"style": []},
            {"seconds": 2},
            {"action": "wait", "target": "seat"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_plan({"steps": [valid | changes]})
        for payload in (None, {}, {"steps": []}, {"steps": [valid] * 13}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_plan(payload)

    def test_direct_construction_cannot_bypass_step_invariants(self):
        with self.assertRaises(ValueError):
            PlanStep("move", None, "walk", 0)
        with self.assertRaises(ValueError):
            PlanStep("pose", None, "walk", 2)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"})
    @patch("app.director.planner.genai.Client")
    def test_provider_response_is_parsed_into_a_valid_plan(self, client_factory):
        generate = (
            client_factory.return_value.__enter__.return_value.models.generate_content
        )
        generate.return_value = SimpleNamespace(
            text=json.dumps(
                {
                    "steps": [
                        {
                            "action": "stop",
                            "target": None,
                            "style": "walk",
                            "seconds": 0,
                            "waypoints": [],
                        }
                    ]
                }
            )
        )
        self.assertEqual(generate_plan("stop", "Idle", "test-model")[0].action, "stop")

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"})
    @patch("app.director.planner.genai.Client")
    def test_stopped_request_never_launches_a_validation_repair(self, client_factory):
        cancellation = Event()

        def stopped_response(**_request):
            cancellation.set()
            return SimpleNamespace(text=json.dumps({"steps": []}))

        generate = (
            client_factory.return_value.__enter__.return_value.models.generate_content
        )
        generate.side_effect = stopped_response
        with self.assertRaises(PlanningStoppedError):
            generate_plan("stop", "Idle", "test-model", cancellation_event=cancellation)
        self.assertEqual(generate.call_count, 1)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_credentials_are_actionable(self):
        with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            generate_plan("walk", "Idle", "test-model")

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"})
    @patch("app.director.planner.genai.Client")
    def test_invalid_provider_plan_exhausts_one_repair(self, client_factory):
        generate = (
            client_factory.return_value.__enter__.return_value.models.generate_content
        )
        for text in (None, "not JSON", '{"steps": []}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                generate.reset_mock()
                generate.return_value = SimpleNamespace(text=text)
                generate_plan("sit down", "Idle", "test-model")
            self.assertEqual(generate.call_count, 2)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"})
    @patch("app.director.planner.genai.Client")
    def test_provider_failure_is_not_retried_as_an_invalid_plan(self, client_factory):
        generate = (
            client_factory.return_value.__enter__.return_value.models.generate_content
        )
        generate.side_effect = errors.ClientError(
            403, {"error": {"message": "Forbidden", "status": "PERMISSION_DENIED"}}
        )
        with self.assertRaisesRegex(PlannerServiceError, "HTTP 403"):
            generate_plan("sit down", "Idle", "test-model")
        self.assertEqual(generate.call_count, 1)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "test-secret"})
    @patch("app.director.planner.genai.Client")
    def test_repair_keeps_the_surface_goal_and_accepts_a_long_original_instruction(
        self, client_factory
    ):
        observation = replace(
            default_observation(),
            character_position=(3.35, 6.9),
            character_heading_degrees=0,
        )
        contact = SurfaceContact("Wall", "left_hand", (3.875, 7, 0.8181389272))
        pose = BodyPose(
            0.8512345678901234,
            5.123456789012345,
            0,
            (0.4123456789012345, 0.2123456789012345, 0.9123456789012345),
            (0.1123456789012345, -0.4123456789012345, 1.2123456789012345),
            (0.01234567890123456, 0.15123456789012345, 0.06123456789012345),
            (0.01234567890123456, -0.15123456789012345, 0.06123456789012345),
            contact,
        )
        step = PlanStep("pose", None, "walk", 5, body_pose=pose)
        candidate = replace(
            step,
            seconds=1,
            body_pose=replace(
                pose, contact=replace(contact, position=(3.9, 7, 0.8181389272))
            ),
        )
        generate = (
            client_factory.return_value.__enter__.return_value.models.generate_content
        )
        generate.return_value = SimpleNamespace(
            text=json.dumps({"steps": [asdict(candidate)]})
        )
        repaired = repair_body_step(
            step, "reach " * 333, observation, "unreachable target " * 30, "test-model"
        )
        self.assertEqual(repaired.seconds, 5)
        assert repaired.body_pose is not None
        self.assertEqual(repaired.body_pose.contact, contact)
        self.assertEqual(generate.call_count, 1)


if __name__ == "__main__":
    unittest.main()
