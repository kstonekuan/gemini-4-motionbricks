"""Scene observations and conservative checks for model-generated floor routes."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import (
    SPEED_RANGES,
    BodyObservation,
    MovementStyle,
    Point3,
    SpatialWaypoint,
)

OBJECT_NAMES = {
    "SmallJumpSP": ("small_box", "jump over"),
    "MidJumpSP": ("vault", "vault over"),
    "AvoidanceSP": ("bar", "duck under"),
    "SitSP": ("seat", "sit on"),
}
FLOOR_BOUNDS = (-12.0, -14.0, 12.0, 22.0)
CLEARANCE = 0.55


@dataclass(frozen=True)
class SpatialObject:
    name: str
    position: tuple[float, float]
    interaction: str
    entry: tuple[float, float]
    exit: tuple[float, float]


@dataclass(frozen=True)
class Obstacle:
    name: str
    bounds: tuple[float, float, float, float]
    bottom: float
    top: float
    interaction_target: str | None
    center: Point3 | None = None
    half_extents: Point3 | None = None
    yaw_degrees: float = 0.0
    color: Point3 = (0.7, 0.7, 0.7)

    def expanded_bounds(
        self, margin: float = CLEARANCE
    ) -> tuple[float, float, float, float]:
        minimum_x, minimum_y, maximum_x, maximum_y = self.bounds
        return (
            minimum_x - margin,
            minimum_y - margin,
            maximum_x + margin,
            maximum_y + margin,
        )


@dataclass(frozen=True)
class SceneObservation:
    character_position: tuple[float, float]
    character_heading_degrees: float
    character_state: str
    objects: tuple[SpatialObject, ...]
    obstacles: tuple[Obstacle, ...]
    floor_bounds: tuple[float, float, float, float] = FLOOR_BOUNDS

    body: BodyObservation | None = None

    def to_prompt(self) -> str:
        return json.dumps(asdict(self))


def contains_point(
    bounds: tuple[float, float, float, float], point: tuple[float, float]
) -> bool:
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def segment_intersects_bounds(
    start: tuple[float, float],
    end: tuple[float, float],
    bounds: tuple[float, float, float, float],
) -> bool:
    """Clip a segment against an axis-aligned box, including its boundary."""
    lower_fraction, upper_fraction = 0.0, 1.0
    for axis in range(2):
        delta = end[axis] - start[axis]
        if abs(delta) < 1e-9:
            if not bounds[axis] <= start[axis] <= bounds[axis + 2]:
                return False
            continue
        first = (bounds[axis] - start[axis]) / delta
        second = (bounds[axis + 2] - start[axis]) / delta
        lower_fraction = max(lower_fraction, min(first, second))
        upper_fraction = min(upper_fraction, max(first, second))
        if lower_fraction > upper_fraction:
            return False
    return True


def validate_route(
    waypoints: tuple[SpatialWaypoint, ...],
    observation: SceneObservation,
    start: tuple[float, float],
    style: MovementStyle,
    interaction_target: str | None,
    contact_object: str | None = None,
) -> None:
    """Reject crossings without inventing or silently changing the model's route."""
    distance = 0.0
    for waypoint_index, waypoint in enumerate(waypoints):
        end = waypoint.position
        distance += math.dist(start, end)
        for obstacle in observation.obstacles:
            if (
                obstacle.bottom > (1.2 if style == "crouch" else 1.9)
                or obstacle.top < 0.05
            ):
                continue
            bounds = obstacle.expanded_bounds(
                0.28 if obstacle.name == contact_object else CLEARANCE
            )
            # A newly standing character can start inside the seat's margin.
            if (
                waypoint_index == 0
                and contains_point(bounds, start)
                and not contains_point(bounds, end)
                and (
                    not segment_intersects_bounds(start, end, obstacle.bounds)
                    or (
                        obstacle.interaction_target == "seat"
                        and contains_point(obstacle.bounds, start)
                    )
                )
            ):
                continue
            if (
                interaction_target is not None
                and interaction_target == obstacle.interaction_target
                and waypoint_index == len(waypoints) - 1
            ):
                continue
            if segment_intersects_bounds(start, end, bounds):
                raise ValueError(
                    f"Route segment {waypoint_index + 1} crosses {obstacle.name}; route around its expanded bounds {bounds}."
                )
        start = end
    if distance > SPEED_RANGES[style][0] * 45:
        raise ValueError(
            "Route is too long for one step; split it into shorter move steps."
        )
    if interaction_target is not None:
        target = next(
            item for item in observation.objects if item.name == interaction_target
        )
        if (
            len(waypoints) < 2
            or math.dist(waypoints[-2].position, target.entry) > 0.8
            or math.dist(waypoints[-1].position, target.exit) > 0.8
        ):
            raise ValueError(
                f"Interaction with {interaction_target} must end with its entry {target.entry} then exit {target.exit}."
            )


def observation_from_document(
    document: dict,
    state: str = "Idle",
    *,
    position: tuple[float, float] | None = None,
    heading_degrees: float | None = None,
) -> SceneObservation:
    """Read positions and obstacle bounds from a scene, including parent transforms."""
    all_items = [
        document["character_start"],
        *document["smart_primitives"],
        *document["solid_cubes"],
    ]
    items_by_id = {item["id"]: item for item in all_items}

    def world_transform(item: dict) -> tuple[float, float, float, float]:
        transform = item["transform"]
        translation = transform["translation"]
        quaternion = transform["rotation_xyzw"]
        rotation = math.atan2(
            2 * (quaternion[3] * quaternion[2] + quaternion[0] * quaternion[1]),
            1 - 2 * (quaternion[1] ** 2 + quaternion[2] ** 2),
        )
        parent = items_by_id.get(item.get("parent_id"))
        if parent is None:
            return (*translation, rotation)
        parent_x, parent_y, parent_z, parent_yaw = world_transform(parent)
        return (
            parent_x
            + math.cos(parent_yaw) * translation[0]
            - math.sin(parent_yaw) * translation[1],
            parent_y
            + math.sin(parent_yaw) * translation[0]
            + math.cos(parent_yaw) * translation[1],
            parent_z + translation[2],
            parent_yaw + rotation,
        )

    objects = []
    target_by_id = {}
    for item in document["smart_primitives"]:
        if item["name"] not in OBJECT_NAMES:
            continue
        name, interaction = OBJECT_NAMES[item["name"]]
        target_by_id[item["id"]] = name
        position_x, position_y, _, yaw = world_transform(item)
        forward_yaw = yaw if name == "seat" else yaw + math.pi / 2
        forward_x, forward_y = math.cos(forward_yaw), math.sin(forward_yaw)
        objects.append(
            SpatialObject(
                name,
                (position_x, position_y),
                interaction,
                (position_x - 2.5 * forward_x, position_y - 2.5 * forward_y),
                (position_x + 2 * forward_x, position_y + 2 * forward_y),
            )
        )
    obstacles = []
    for cube in document["solid_cubes"]:
        position_x, position_y, position_z, yaw = world_transform(cube)
        dimensions = cube["dimensions"]
        half_x = (
            abs(math.cos(yaw)) * dimensions["width"]
            + abs(math.sin(yaw)) * dimensions["depth"]
        ) / 2
        half_y = (
            abs(math.sin(yaw)) * dimensions["width"]
            + abs(math.cos(yaw)) * dimensions["depth"]
        ) / 2
        associated_target = target_by_id.get(cube.get("parent_id"))
        if associated_target is None:
            associated_target = next(
                (
                    item.name
                    for item in objects
                    if math.dist(item.position, (position_x, position_y)) < 0.25
                ),
                None,
            )
        obstacles.append(
            Obstacle(
                cube["name"],
                (
                    position_x - half_x,
                    position_y - half_y,
                    position_x + half_x,
                    position_y + half_y,
                ),
                position_z - dimensions["height"] / 2,
                position_z + dimensions["height"] / 2,
                associated_target,
                (position_x, position_y, position_z),
                (
                    dimensions["width"] / 2,
                    dimensions["depth"] / 2,
                    dimensions["height"] / 2,
                ),
                math.degrees(yaw),
                tuple(cube.get("color", (0.7, 0.7, 0.7))),
            )
        )
    start_x, start_y, _, start_yaw = world_transform(document["character_start"])
    return SceneObservation(
        position or (start_x, start_y),
        math.degrees(start_yaw) if heading_degrees is None else heading_degrees,
        state,
        tuple(objects),
        tuple(obstacles),
    )


def default_observation(state: str = "Idle") -> SceneObservation:
    scene_path = (
        Path(__file__).resolve().parents[2] / "assets/scenes/soma_gym.scene.json"
    )
    return observation_from_document(json.loads(scene_path.read_text()), state)
