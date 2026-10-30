"""Surface-goal geometry and world-to-actor projection for grounded hand reaches."""

from __future__ import annotations

import math
from dataclasses import replace

from .models import BodyPose, Point2, SurfaceContact
from .spatial import Obstacle, SceneObservation


def validate_surface_contact(
    contact: SurfaceContact, observation: SceneObservation
) -> Obstacle:
    matches = [
        obstacle
        for obstacle in observation.obstacles
        if obstacle.name == contact.object_name
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Surface goal must name one scene solid: {contact.object_name!r} was not uniquely found."
        )
    obstacle = matches[0]
    if obstacle.center is None or obstacle.half_extents is None:
        raise ValueError("Surface goal needs the object's oriented geometry.")
    yaw = math.radians(obstacle.yaw_degrees)
    delta_x, delta_y, delta_z = (
        value - origin for value, origin in zip(contact.position, obstacle.center)
    )
    local = (
        math.cos(yaw) * delta_x + math.sin(yaw) * delta_y,
        -math.sin(yaw) * delta_x + math.cos(yaw) * delta_y,
        delta_z,
    )
    distances = [
        abs(value) - half_extent
        for value, half_extent in zip(local, obstacle.half_extents)
    ]
    if max(distances) > 0.015 or min(abs(distance) for distance in distances) > 0.02:
        raise ValueError(
            f"Hand goal must lie on {obstacle.name}'s actual surface (within 2cm), not inside or beyond its oriented box."
        )
    return obstacle


def resolve_contact_pose(
    pose: BodyPose, position: Point2, heading_degrees: float
) -> BodyPose:
    """The world goal owns the pinned hand; resolve it again at the actual arrival."""
    if pose.contact is None:
        return pose
    target_x, target_y, target_z = pose.contact.position
    delta_x, delta_y = target_x - position[0], target_y - position[1]
    heading = math.radians(heading_degrees)
    local_target = (
        math.cos(heading) * delta_x + math.sin(heading) * delta_y,
        -math.sin(heading) * delta_x + math.cos(heading) * delta_y,
        target_z,
    )
    if pose.contact.effector == "left_hand":
        return replace(pose, left_hand=local_target)
    return replace(pose, right_hand=local_target)


def validate_contact_pose(
    pose: BodyPose,
    observation: SceneObservation,
    position: Point2,
    heading_degrees: float,
) -> BodyPose:
    """Check the same world goal and planted-foot clearance at plan and execution time."""
    if pose.contact is None:
        return pose
    validate_surface_contact(pose.contact, observation)
    resolved = resolve_contact_pose(pose, position, heading_degrees)
    heading = math.radians(heading_degrees)
    for foot in (resolved.left_foot, resolved.right_foot):
        world_foot = (
            position[0] + math.cos(heading) * foot[0] - math.sin(heading) * foot[1],
            position[1] + math.sin(heading) * foot[0] + math.cos(heading) * foot[1],
        )
        for obstacle in observation.obstacles:
            if obstacle.bottom <= foot[2] + 0.08 and obstacle.top >= foot[2] - 0.04:
                minimum_x, minimum_y, maximum_x, maximum_y = obstacle.expanded_bounds(
                    0.06
                )
                if (
                    minimum_x <= world_foot[0] <= maximum_x
                    and minimum_y <= world_foot[1] <= maximum_y
                ):
                    raise ValueError(
                        f"Keep planted feet outside {obstacle.name}; move the standing position or foot away from the solid."
                    )
    return resolved
