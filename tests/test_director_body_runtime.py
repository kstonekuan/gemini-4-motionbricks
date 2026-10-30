"""Verify pose-director geometry on CPU using real skeleton transforms and IK."""

import math
import unittest
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import warp as wp

from app.director.body import BodyPose
from app.director.body_runtime import observe_body, solve_body_target
from app.director.models import SurfaceContact
from motionbricks.animation.skeleton import Skeleton


class BodyRuntimeTests(unittest.TestCase):
    def make_character(self, heading_degrees, root_frame_degrees=0):
        joint_names = [
            "Root",
            "LeftArm",
            "LeftForeArm",
            "LeftHand",
            "RightArm",
            "RightForeArm",
            "RightHand",
            "LeftLeg",
            "LeftShin",
            "LeftFoot",
            "RightLeg",
            "RightShin",
            "RightFoot",
        ]
        parent_indices = [-1, 0, 1, 2, 0, 4, 5, 0, 7, 8, 0, 10, 11]
        translations = [
            (3, -2, 0.95),
            (-0.18, 0, 0.4),
            (-0.12, 0.1, -0.15),
            (0.03, 0.12, -0.2),
            (0.18, 0, 0.4),
            (0.12, 0.1, -0.15),
            (-0.03, 0.12, -0.2),
            (-0.1, 0, -0.1),
            (0, 0.08, -0.35),
            (0, -0.08, -0.35),
            (0.1, 0, -0.1),
            (0, 0.08, -0.35),
            (0, -0.08, -0.35),
        ]
        transforms = np.zeros((len(joint_names), 7), dtype=np.float32)
        transforms[:, :3] = translations
        transforms[:, 6] = 1
        transforms[0, 3:] = np.array(
            wp.quat_from_axis_angle(
                wp.vec3(0, 0, 1), math.radians(heading_degrees - 90)
            )
        )
        root_frame = wp.quat_from_axis_angle(
            wp.vec3(0, 1, 0), math.radians(root_frame_degrees)
        )
        transforms[0, 3:] = np.array(wp.mul(wp.quat(*transforms[0, 3:]), root_frame))
        for child_index in (1, 4, 7, 10):
            transforms[child_index, :3] = np.array(
                wp.quat_rotate_inv(root_frame, wp.vec3(*transforms[child_index, :3]))
            )
            transforms[child_index, 3:] = np.array(wp.quat_inverse(root_frame))
        with wp.ScopedDevice("cpu"):
            skeleton = Skeleton(joint_names, parent_indices, transforms)
            current_pose = wp.array(transforms, dtype=wp.transform)
        character = SimpleNamespace(
            skeleton=skeleton,
            current_pose=current_pose,
            character_ground_position=np.array([3.0, -2.0, 0.0]),
            root_forward_axis=wp.vec3(0, 1, 0),
            model_to_runtime=wp.transform(
                wp.vec3(0.0, 0.0, 0.0), wp.quat(0.0, 0.0, 0.0, 1.0)
            ),
            engine=SimpleNamespace(device=wp.get_device("cpu"), stream=None),
        )

        def pose_facing():
            forward = np.array(
                wp.quat_rotate(
                    wp.quat(*character.current_pose.numpy()[0, 3:]),
                    character.root_forward_axis,
                )
            )
            forward[2] = 0
            return forward / np.linalg.norm(forward)

        character.pose_facing = pose_facing
        return character

    def test_repeated_pose_uses_absolute_lean_and_preserves_actor_frame(self):
        for heading, root_frame_degrees in (
            (0, 0),
            (90, 0),
            (-135, 0),
            (0, 90),
            (90, 90),
            (-135, 90),
        ):
            with (
                wp.ScopedDevice("cpu"),
                self.subTest(heading=heading, root_frame=root_frame_degrees),
            ):
                character = self.make_character(heading, root_frame_degrees)
                observation = observe_body(character)
                constraints = BodyPose(
                    0.83,
                    6,
                    0,
                    (0.25, 0.22, 1.14),
                    (0.1, -0.4, 1.15),
                    observation["effectors"]["left_foot"],
                    observation["effectors"]["right_foot"],
                )
                for _ in range(2):
                    character.current_pose, _ = solve_body_target(
                        character, constraints
                    )
                root_rotation = wp.quat(*character.current_pose.numpy()[0, 3:])
                local_up = wp.vec3(
                    -math.sin(math.radians(root_frame_degrees)),
                    0.0,
                    math.cos(math.radians(root_frame_degrees)),
                )
                actual_up = np.array(wp.quat_rotate(root_rotation, local_up))
                expected_up = np.array(
                    [
                        math.cos(math.radians(heading)) * math.sin(math.radians(6)),
                        math.sin(math.radians(heading)) * math.sin(math.radians(6)),
                        math.cos(math.radians(6)),
                    ]
                )
                np.testing.assert_allclose(actual_up, expected_up, atol=1e-5)

    def test_scene_contact_pins_the_hand_at_the_world_goal_at_different_headings(self):
        for heading in (0, 90, -135):
            with wp.ScopedDevice("cpu"), self.subTest(heading=heading):
                character = self.make_character(heading)
                observation = observe_body(character)
                radians = math.radians(heading)
                world_goal = (
                    3 + 0.25 * math.cos(radians) - 0.22 * math.sin(radians),
                    -2 + 0.25 * math.sin(radians) + 0.22 * math.cos(radians),
                    1.14,
                )
                pose = BodyPose(
                    0.83,
                    6,
                    0,
                    (-0.4, 0.2, 1.3),
                    (0.1, -0.4, 1.15),
                    observation["effectors"]["left_foot"],
                    observation["effectors"]["right_foot"],
                    SurfaceContact("Panel", "left_hand", world_goal),
                )
                target, diagnostics = solve_body_target(character, pose)
                world = wp.empty(
                    character.skeleton.num_joints, dtype=wp.transform, device="cpu"
                )
                character.skeleton.compute_world_transforms(target, world)
                actual = world.numpy()[character.skeleton.joint_index("LeftHand"), :3]
                self.assertLess(float(np.linalg.norm(actual - world_goal)), 0.025)
                self.assertEqual(diagnostics["contact"]["position"], list(world_goal))

    def test_pose_rechecks_grounded_feet_against_live_contacts_before_ik(self):
        with wp.ScopedDevice("cpu"):
            character = self.make_character(0)
            observation = observe_body(character)
            pose = BodyPose(
                0.83,
                6,
                0,
                (0.25, 0.22, 1.14),
                (0.1, -0.4, 1.15),
                observation["effectors"]["left_foot"],
                observation["effectors"]["right_foot"],
            )
            for offset, rejection in (((0.2, 0, 0), "18cm"), ((0, 0, -0.03), "height")):
                with self.subTest(offset=offset):
                    stale_contact = tuple(
                        value + delta for value, delta in zip(pose.left_foot, offset)
                    )
                    with self.assertRaisesRegex(ValueError, rejection):
                        solve_body_target(
                            character, replace(pose, left_foot=stale_contact)
                        )
