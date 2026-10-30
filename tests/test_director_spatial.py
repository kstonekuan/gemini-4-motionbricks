"""Check model-produced route coordinates against independent geometric outcomes."""

import json
import math
import unittest
from dataclasses import replace
from pathlib import Path

from app.director.planner import validate_plan
from app.director.spatial import default_observation, observation_from_document


def movement_step(positions, *, action="move", target=None, heading=None):
    return {
        "action": action,
        "target": target,
        "style": "walk",
        "seconds": 0,
        "waypoints": [
            {
                "position": list(position),
                "speed": 2.0,
                "heading_degrees": heading if index == len(positions) - 1 else None,
            }
            for index, position in enumerate(positions)
        ],
    }


class SpatialPlannerTests(unittest.TestCase):
    def test_arbitrary_clear_route_and_stopping_heading_are_preserved(self):
        observation = replace(default_observation(), character_position=(-8, 0))
        step = validate_plan(
            {"steps": [movement_step([(-2, -2), (6, -2), (6, 0)], heading=90)]},
            observation,
        )[0]
        self.assertEqual(
            [waypoint.position for waypoint in step.waypoints],
            [(-2, -2), (6, -2), (6, 0)],
        )
        self.assertEqual(step.waypoints[-1].heading_degrees, 90)
        self.assertIsNone(step.target)

    def test_route_through_box_is_rejected_instead_of_rerouted(self):
        observation = replace(default_observation(), character_position=(-8, 0))
        with self.assertRaisesRegex(ValueError, "crosses Box"):
            validate_plan({"steps": [movement_step([(6, 0)])]}, observation)

    def test_interaction_allows_only_its_final_crossing(self):
        observation = default_observation()
        valid = movement_step([(1.5, 0), (6, 0)], action="interact", target="small_box")
        self.assertEqual(
            validate_plan({"steps": [valid]}, observation)[0].target, "small_box"
        )
        wrong_approach = movement_step(
            [(-2, 0), (6, 0)], action="interact", target="small_box"
        )
        with self.assertRaisesRegex(ValueError, "entry"):
            validate_plan({"steps": [wrong_approach]}, observation)

    def test_moved_scene_object_changes_observed_targets_and_footprint(self):
        document = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "assets/scenes/soma_gym.scene.json"
            ).read_text()
        )
        document["smart_primitives"][0]["transform"]["translation"] = [6, 3, 0]
        observation = observation_from_document(document, position=(-5, 2))
        target = next(item for item in observation.objects if item.name == "small_box")
        obstacle = next(item for item in observation.obstacles if item.name == "Box")
        self.assertEqual(target.position, (6, 3))
        self.assertAlmostEqual((obstacle.bounds[0] + obstacle.bounds[2]) / 2, 6)
        self.assertAlmostEqual((obstacle.bounds[1] + obstacle.bounds[3]) / 2, 3)
        self.assertAlmostEqual(math.dist(target.entry, target.position), 2.5)
        self.assertEqual(observation.character_position, (-5, 2))

    def test_rejects_unbounded_or_incompatible_spatial_targets(self):
        valid = movement_step([(-6, 4)])
        for change in (
            {"position": [math.nan, 4]},
            {"position": [math.inf, 4]},
            {"position": [True, 4]},
            {"position": [100, 4]},
            {"speed": 0.1},
            {"speed": 100},
            {"speed": True},
            {"heading_degrees": math.nan},
            {"heading_degrees": 360},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_plan(
                    {"steps": [valid | {"waypoints": [valid["waypoints"][0] | change]}]}
                )


if __name__ == "__main__":
    unittest.main()
