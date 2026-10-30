"""Scene-relative reach constraints for parsed body-pose contracts."""

from __future__ import annotations

import math

from .models import (
    BODY_POSE_ADAPTER,
    EFFECTOR_NAMES,
    BodyObservation,
    BodyPose,
    EffectorName,
    Point3,
)


def validate_body_pose(payload: object) -> BodyPose:
    """Parse numerical body targets once at the model boundary."""
    return BODY_POSE_ADAPTER.validate_python(payload)


def validate_body_reach(pose: BodyPose, observation: BodyObservation) -> None:
    """Check the requested constraints against measured limb lengths before GPU work."""
    height_delta = pose.pelvis_height - observation["pelvis_height"]
    for name in EFFECTOR_NAMES:
        start = list(observation["limbs"][name]["start"])
        start[2] += height_delta
        target = getattr(pose, name)
        # The exact leaned/seeded pose is checked again by the runtime solver.
        required_reach = math.dist(start, target)
        maximum_reach = observation["limbs"][name]["length"] - (
            0.001 if "foot" in name else 0.025
        )
        if required_reach > maximum_reach:
            raise ValueError(
                f"{name} actor-frame target {target} needs {required_reach:.3f}m from shoulder/hip {start}, "
                f"but the usable limb length is {maximum_reach:.3f}m at pelvis height {pose.pelvis_height:.3f}m. "
                "For a fixed surface point, move the preceding standing position closer and/or lower pelvis; "
                "do not move the surface goal off its object."
            )
    validate_grounded_feet(pose, observation["effectors"])


def validate_grounded_feet(
    pose: BodyPose, observed_effectors: dict[EffectorName, Point3]
) -> None:
    """Grounded poses may adjust feet slightly, but cannot step or levitate."""
    for name in ("left_foot", "right_foot"):
        target = getattr(pose, name)
        observed = observed_effectors[name]
        if abs(target[2] - observed[2]) > 0.025:
            raise ValueError(
                f"Keep {name} at its observed ground-contact height {observed[2]:.3f}m."
            )
        if math.dist(target[:2], observed[:2]) > 0.18:
            raise ValueError(
                f"Keep {name} within 18cm of its observed grounded position."
            )
