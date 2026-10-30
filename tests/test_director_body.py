"""Protect numerical pose generation at the untrusted model-plan boundary."""

import copy
import unittest

from app.director.planner import validate_plan


def body_step():
    return {
        "action": "pose",
        "target": None,
        "style": "walk",
        "seconds": 3,
        "waypoints": [],
        "body_pose": {
            "pelvis_height": 0.82,
            "forward_lean_degrees": 5,
            "side_lean_degrees": -3,
            "left_hand": [0.35, 0.25, 1.3],
            "right_hand": [0.1, -0.5, 1.2],
            "left_foot": [0, 0.15, 0.08],
            "right_foot": [0, -0.15, 0.08],
        },
    }


class BodyPlanTests(unittest.TestCase):
    def test_novel_asymmetric_constraints_survive_plan_validation(self):
        step = validate_plan({"steps": [body_step()]})[0]
        assert step.body_pose is not None
        self.assertEqual(step.body_pose.left_hand, (0.35, 0.25, 1.3))
        self.assertEqual(step.body_pose.right_hand, (0.1, -0.5, 1.2))
        self.assertEqual(step.body_pose.pelvis_height, 0.82)
        self.assertEqual(step.seconds, 3)
        self.assertFalse(step.waypoints)

    def test_rejects_unbounded_or_unsupported_body_targets(self):
        for field, value in (
            ("pelvis_height", float("nan")),
            ("pelvis_height", True),
            ("forward_lean_degrees", 90),
            ("left_hand", [0, 0, float("inf")]),
            ("left_foot", [0, -0.15, 0.08]),
            ("left_foot", [0, 0.15, 1]),
        ):
            with self.subTest(field=field, value=value):
                step = copy.deepcopy(body_step())
                step["body_pose"][field] = value
                with self.assertRaises(ValueError):
                    validate_plan({"steps": [step]})

    def test_pose_constraints_cannot_be_hidden_in_other_actions(self):
        step = body_step()
        step.update(action="wait")
        with self.assertRaisesRegex(ValueError, "Only pose"):
            validate_plan({"steps": [step]})
        step = body_step()
        step["seconds"] = 0
        with self.assertRaisesRegex(ValueError, "1–10"):
            validate_plan({"steps": [step]})
