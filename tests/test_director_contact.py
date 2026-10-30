"""Scene contact contracts: oriented surfaces, fixed world goals and approach clearance."""

import math
import unittest
from dataclasses import replace

from app.director.contact import (
    resolve_contact_pose,
    validate_contact_pose,
    validate_surface_contact,
)
from app.director.models import BodyPose, SpatialWaypoint, SurfaceContact
from app.director.spatial import Obstacle, SceneObservation, validate_route


class SceneContactTests(unittest.TestCase):
    def test_rotated_surface_accepts_real_corner_and_rejects_aabb_corner_and_interior(
        self,
    ):
        obstacle = Obstacle(
            "Panel", (1, 2, 3, 4), 0.6, 1.0, None, (2, 3, 0.8), (1, 0.3, 0.2), 45
        )
        scene = SceneObservation((0, 0), 0, "Idle", (), (obstacle,))
        diagonal = math.sqrt(0.5)
        corner = (2 + 0.7 * diagonal, 3 + 1.3 * diagonal, 1.0)
        self.assertEqual(
            validate_surface_contact(
                SurfaceContact("Panel", "left_hand", corner), scene
            ).name,
            "Panel",
        )
        for point in (
            (2 + 1.3 * diagonal, 3 + 1.3 * diagonal, 1.0),
            (2, 3, 0.8),
            (2, 3, 1.1),
        ):
            with (
                self.subTest(point=point),
                self.assertRaisesRegex(ValueError, "actual surface"),
            ):
                validate_surface_contact(
                    SurfaceContact("Panel", "left_hand", point), scene
                )
        with self.assertRaisesRegex(ValueError, "not uniquely found"):
            validate_surface_contact(
                SurfaceContact("Missing", "left_hand", corner), scene
            )

    def test_contact_world_position_survives_actor_turning_and_arrival_drift(self):
        pose = BodyPose(
            0.9,
            0,
            0,
            (0.1, 0.2, 1.2),
            (0.1, -0.3, 1.2),
            (0, 0.15, 0.06),
            (0, -0.15, 0.06),
            SurfaceContact("Box", "left_hand", (5, -3, 1.1)),
        )
        for heading, expected in (
            (0, (0.4, 0.1, 1.1)),
            (90, (0.1, -0.4, 1.1)),
            (180, (-0.4, -0.1, 1.1)),
        ):
            with self.subTest(heading=heading):
                resolved = resolve_contact_pose(pose, (4.6, -3.1), heading)
                for actual, desired in zip(resolved.left_hand, expected):
                    self.assertAlmostEqual(actual, desired)
                self.assertEqual(resolved.contact, pose.contact)
                self.assertEqual(resolved.right_hand, pose.right_hand)
        arrived = resolve_contact_pose(pose, (4.7, -3.1), 0)
        self.assertAlmostEqual(arrived.left_hand[0], 0.3)

    def test_closer_contact_approach_keeps_other_obstacles_and_target_interior_blocked(
        self,
    ):
        surface = Obstacle("Panel", (0, 0, 1, 1), 0, 1, None)
        scene = SceneObservation((-2, 0.5), 0, "Idle", (), (surface,))
        approach = (SpatialWaypoint((-0.3, 0.5), 2, 0),)
        with self.assertRaisesRegex(ValueError, "crosses Panel"):
            validate_route(approach, scene, scene.character_position, "walk", None)
        validate_route(
            approach,
            scene,
            scene.character_position,
            "walk",
            None,
            contact_object="Panel",
        )
        with self.assertRaisesRegex(ValueError, "crosses Panel"):
            validate_route(
                (SpatialWaypoint((0.5, 0.5), 2, 0),),
                scene,
                scene.character_position,
                "walk",
                None,
                contact_object="Panel",
            )
        # Leaving the relaxed approach margin cannot cross through the solid.
        with self.assertRaisesRegex(ValueError, "crosses Panel"):
            validate_route(
                (SpatialWaypoint((2, 0.5), 2, 0),), scene, (-0.3, 0.5), "walk", None
            )
        validate_route(
            (SpatialWaypoint((-2, 0.5), 2, 0),), scene, (-0.3, 0.5), "walk", None
        )
        blocked = replace(
            scene,
            obstacles=(surface, Obstacle("Other", (-1.5, 0, -1.2, 1), 0, 1, None)),
        )
        with self.assertRaisesRegex(ValueError, "crosses Other"):
            validate_route(
                approach,
                blocked,
                scene.character_position,
                "walk",
                None,
                contact_object="Panel",
            )

    def test_surface_reach_does_not_plant_a_foot_inside_the_solid_margin(self):
        solid = Obstacle(
            "Panel", (0, 0, 1, 1), 0, 1, None, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5)
        )
        scene = SceneObservation((-0.3, 0.5), 0, "Idle", (), (solid,))
        pose = BodyPose(
            0.9,
            0,
            0,
            (0.3, 0.2, 1.2),
            (0.1, -0.4, 1.2),
            (0.25, 0.15, 0.06),
            (-0.03, -0.15, 0.06),
            SurfaceContact("Panel", "left_hand", (0, 0.5, 1)),
        )
        with self.assertRaisesRegex(ValueError, "planted feet outside Panel"):
            validate_contact_pose(pose, scene, scene.character_position, 0)
        clear = replace(pose, left_foot=(0, 0.15, 0.06))
        self.assertEqual(
            validate_contact_pose(clear, scene, scene.character_position, 0).left_hand,
            (0.3, 0, 1),
        )
