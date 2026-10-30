"""Turn Gemini's limb constraints into novel SOMA poses with MotionBricks IK."""

from __future__ import annotations

import math
import time

import numpy as np
import warp as wp

from motionbricks.animation.animation_buffer import AnimationBuffer
from motionbricks.animation.ik import TwoBoneIKChain, apply_two_bone_ik_chains_kernel
from motionbricks.model.contract import MODEL_POSES_PER_TOKEN, MODEL_SAMPLE_RATE
from motionbricks.runtime.target_pose import (
    IKPin,
    TargetPoseInferenceParams,
    create_soma_target_pose_ik_rig,
)

from ..runtime.common.motion import AnimationClip
from ..runtime.common.states import State
from .body import EFFECTOR_NAMES, BodyPose
from .contact import resolve_contact_pose
from .models import BodyObservation, EffectorName, LimbObservation, Point3

JOINT_NAMES: dict[EffectorName, str] = {
    "left_hand": "LeftHand",
    "right_hand": "RightHand",
    "left_foot": "LeftFoot",
    "right_foot": "RightFoot",
}


def ground_frame(character) -> tuple[np.ndarray, np.ndarray]:
    origin = character.character_ground_position.copy()
    facing = character.pose_facing()
    left = np.array([-facing[1], facing[0], 0.0])
    return origin, np.column_stack((facing, left, np.array([0.0, 0.0, 1.0])))


def _position_tuple(vector: np.ndarray) -> Point3:
    return float(vector[0]), float(vector[1]), float(vector[2])


def observe_body(character) -> BodyObservation:
    skeleton = character.skeleton
    world = wp.empty(
        skeleton.num_joints, dtype=wp.transform, device=character.engine.device
    )
    skeleton.compute_world_transforms(
        character.current_pose, world, stream=character.engine.stream
    )
    transforms = world.numpy()
    origin, basis = ground_frame(character)
    effectors = {
        name: _position_tuple(
            basis.T @ (transforms[skeleton.joint_index(joint), :3] - origin)
        )
        for name, joint in JOINT_NAMES.items()
    }
    chains = create_soma_target_pose_ik_rig(skeleton)
    limbs: dict[EffectorName, LimbObservation] = {}
    for name, chain in zip(EFFECTOR_NAMES, chains):
        start, middle, tip = (
            transforms[index, :3]
            for index in (chain.root_index, chain.mid_index, chain.tip_index)
        )
        limbs[name] = {
            "start": _position_tuple(basis.T @ (start - origin)),
            "length": float(
                np.linalg.norm(middle - start) + np.linalg.norm(tip - middle)
            ),
        }
    return {
        "pelvis_height": float(transforms[0, 2]),
        "effectors": effectors,
        "limbs": limbs,
    }


def solve_body_target(character, constraints: BodyPose) -> tuple[wp.array, dict]:
    """Use upstream IK, rejecting unreachable limbs and excessive solve residuals."""
    skeleton = character.skeleton
    device = character.engine.device
    origin, basis = ground_frame(character)
    constraints = resolve_contact_pose(
        constraints,
        (float(origin[0]), float(origin[1])),
        math.degrees(math.atan2(float(basis[1, 0]), float(basis[0, 0]))),
    )
    local_transforms = character.current_pose.numpy().copy()
    local_transforms[0, 2] = constraints.pelvis_height
    forward_rotation = wp.quat_from_axis_angle(
        wp.vec3(*basis[:, 1]), math.radians(constraints.forward_lean_degrees)
    )
    side_rotation = wp.quat_from_axis_angle(
        wp.vec3(*basis[:, 0]), math.radians(-constraints.side_lean_degrees)
    )
    heading = math.atan2(float(basis[1, 0]), float(basis[0, 0]))
    reference_root = character.skeleton.reference_local_transforms.numpy()[0]
    reference_rotation = wp.mul(
        character.model_to_runtime.q, wp.quat(*reference_root[3:])
    )
    reference_forward = np.array(
        wp.quat_rotate(reference_rotation, character.root_forward_axis)
    )
    reference_heading = math.atan2(reference_forward[1], reference_forward[0])
    heading_rotation = wp.quat_from_axis_angle(
        wp.vec3(0.0, 0.0, 1.0), heading - reference_heading
    )
    upright_rotation = wp.mul(heading_rotation, reference_rotation)
    local_transforms[0, 3:] = np.array(
        wp.mul(wp.mul(forward_rotation, side_rotation), upright_rotation)
    )
    target_pose = wp.array(local_transforms, dtype=wp.transform, device=device)
    world = wp.empty(skeleton.num_joints, dtype=wp.transform, device=device)
    skeleton.compute_world_transforms(
        target_pose, world, stream=character.engine.stream
    )
    transforms = world.numpy()
    configurations = create_soma_target_pose_ik_rig(skeleton)
    chains, pins, desired_positions = [], [], {}
    for name, configuration in zip(EFFECTOR_NAMES, configurations):
        desired = origin + basis @ np.array(getattr(constraints, name))
        start, middle, tip = (
            transforms[index, :3]
            for index in (
                configuration.root_index,
                configuration.mid_index,
                configuration.tip_index,
            )
        )
        upper_length, lower_length = (
            np.linalg.norm(middle - start),
            np.linalg.norm(tip - middle),
        )
        reach = float(np.linalg.norm(desired - start))
        reach_margin = 0.001 if "foot" in name else 0.012
        if (
            not abs(upper_length - lower_length) + 0.005
            < reach
            < upper_length + lower_length - reach_margin
        ):
            raise ValueError(
                f"Generated {name} target is unreachable ({reach:.2f} m from limb start). Request a closer point or less pelvis lowering."
            )
        if "foot" in name:
            seed_tip = character.current_pose
            # Grounded poses may reposition feet slightly, not step or levitate.
            current_world = wp.empty_like(world)
            skeleton.compute_world_transforms(
                seed_tip, current_world, stream=character.engine.stream
            )
            current_tip = current_world.numpy()[configuration.tip_index, :3]
            if abs(float(desired[2] - current_tip[2])) > 0.025:
                raise ValueError(
                    "Keep both foot heights at the observed floor-contact heights."
                )
        chain = TwoBoneIKChain()
        chain.pin = int(configuration.pin)
        chain.root_index, chain.mid_index, chain.tip_index = (
            configuration.root_index,
            configuration.mid_index,
            configuration.tip_index,
        )
        chain.hint_offset_local = wp.vec3(*configuration.hint_offset_local)
        chains.append(chain)
        pins.append(
            wp.transform(
                wp.vec3(*desired), wp.quat(*transforms[configuration.tip_index, 3:])
            )
        )
        desired_positions[name] = desired.tolist()
    wp.launch(
        apply_two_bone_ik_chains_kernel,
        dim=len(chains),
        inputs=[
            1.0,
            int(IKPin.ALL),
            wp.array(chains, dtype=TwoBoneIKChain, device=device),
            wp.array(pins, dtype=wp.transform, device=device),
            skeleton.parent_indices,
            world,
        ],
        outputs=[target_pose],
        stream=character.engine.stream,
    )
    skeleton.compute_world_transforms(
        target_pose, world, stream=character.engine.stream
    )
    solved = world.numpy()
    residuals = {
        name: float(
            np.linalg.norm(
                solved[skeleton.joint_index(JOINT_NAMES[name]), :3]
                - desired_positions[name]
            )
        )
        for name in EFFECTOR_NAMES
    }
    if not np.isfinite(target_pose.numpy()).all() or max(residuals.values()) > 0.025:
        raise ValueError("Generated body target could not be solved within 2.5 cm.")
    diagnostics = {
        "desired": desired_positions,
        "residuals": residuals,
        "pelvisHeight": constraints.pelvis_height,
    }
    if constraints.contact is not None:
        diagnostics["contact"] = {
            "objectName": constraints.contact.object_name,
            "effector": constraints.contact.effector,
            "position": list(constraints.contact.position),
        }
    return target_pose, diagnostics


class GeneratedBodyState(State):
    """Generate toward an IK-built pose, then hold that exact pose for inspection."""

    name = "Gemini body pose"

    def __init__(
        self, target_pose: wp.array, character, hold_seconds: float, diagnostics: dict
    ) -> None:
        self.targets = wp.array(
            np.repeat(target_pose.numpy()[None, :, :], MODEL_POSES_PER_TOKEN, axis=0),
            dtype=wp.transform,
            device=character.engine.device,
        )
        self.diagnostics = diagnostics
        animation = AnimationBuffer(character.skeleton, MODEL_SAMPLE_RATE, self.targets)
        self.clip = AnimationClip(
            animation,
            wp.transform(wp.vec3(0.0, 0.0, 0.0), wp.quat(0.0, 0.0, 0.0, 1.0)),
            animation.duration,
            wp.transform(wp.vec3(0.0, 0.0, 0.0), wp.quat(0.0, 0.0, 0.0, 1.0)),
            self.targets.numpy()[:, 0, :3],
        )
        self.hold_seconds = hold_seconds
        self.hold_started: float | None = None
        self.last_contact_sample = 0.0

    @property
    def finished(self) -> bool:
        return (
            self.hold_started is not None
            and time.monotonic() - self.hold_started >= self.hold_seconds
        )

    def enter(self, character, state_machine) -> None:
        character.movement.reset_desired_velocity()
        character.generate_to_target_poses(
            self.targets, TargetPoseInferenceParams(0, MODEL_POSES_PER_TOKEN, IKPin.ALL)
        )

    def update(self, character, state_machine, delta_time: float) -> None:
        if self.hold_started is None and character.time_to_transition() <= delta_time:
            world = wp.empty(
                character.skeleton.num_joints,
                dtype=wp.transform,
                device=character.engine.device,
            )
            character.skeleton.compute_world_transforms(
                character.current_pose, world, stream=character.engine.stream
            )
            before_hold = world.numpy()
            self.diagnostics["beforeHoldErrors"] = {
                name: float(
                    np.linalg.norm(
                        before_hold[
                            character.skeleton.joint_index(JOINT_NAMES[name]), :3
                        ]
                        - position
                    )
                )
                for name, position in self.diagnostics["desired"].items()
            }
            self.diagnostics["beforeHoldRootError"] = float(
                np.linalg.norm(
                    character.current_pose.numpy()[0, :3]
                    - self.targets.numpy()[0, 0, :3]
                )
            )
            if "contact" in self.diagnostics:
                contact = self.diagnostics["contact"]
                contact["beforeHoldError"] = self.diagnostics["beforeHoldErrors"][
                    contact["effector"]
                ]
            character.start_clip(self.clip, loop=True)
            self.hold_started = time.monotonic()
        if (
            "contact" in self.diagnostics
            and time.monotonic() - self.last_contact_sample >= 0.2
        ):
            world = wp.empty(
                character.skeleton.num_joints,
                dtype=wp.transform,
                device=character.engine.device,
            )
            character.skeleton.compute_world_transforms(
                character.current_pose, world, stream=character.engine.stream
            )
            contact = self.diagnostics["contact"]
            actual = world.numpy()[
                character.skeleton.joint_index(JOINT_NAMES[contact["effector"]]), :3
            ]
            contact["actual"] = actual.tolist()
            contact["errorMeters"] = float(np.linalg.norm(actual - contact["position"]))
            self.last_contact_sample = time.monotonic()

    def exit(self, character, state_machine) -> None:
        character.clear_ik_pins()
        character.face_pose()
