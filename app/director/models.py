"""Immutable director contracts shared by parsing, execution and JSON schemas."""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict, get_args

from pydantic import ConfigDict, Field, StringConstraints, TypeAdapter
from pydantic.dataclasses import dataclass

MAX_INSTRUCTION_CHARACTERS = 2000

Action = Literal["move", "interact", "stand", "wait", "stop", "pose"]
ObjectName = Literal["small_box", "vault", "bar", "seat"]
MovementStyle = Literal["walk", "run", "skip", "zombie", "crouch"]
ExecutionPhase = Literal["route", "body", "interaction", "arrival", "standing"]
EffectorName = Literal["left_hand", "right_hand", "left_foot", "right_foot"]
EFFECTOR_NAMES: tuple[EffectorName, ...] = get_args(EffectorName)
SPEED_RANGES: dict[MovementStyle, tuple[float, float]] = {
    "walk": (1.84, 2.3),
    "run": (1.84, 4.5),
    "skip": (1.3, 1.45),
    "zombie": (0.7, 0.85),
    "crouch": (1.2, 2.5),
}
MODE_MAX_SPEEDS: dict[MovementStyle, float] = {
    "walk": 4.5,
    "run": 4.5,
    "skip": 1.45,
    "zombie": 0.85,
    "crouch": 2.5,
}
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Point2 = tuple[FiniteNumber, FiniteNumber]
Point3 = tuple[FiniteNumber, FiniteNumber, FiniteNumber]
HandPosition = tuple[
    Annotated[FiniteNumber, Field(ge=-0.65, le=0.8)],
    Annotated[FiniteNumber, Field(ge=-1, le=1)],
    Annotated[FiniteNumber, Field(ge=0.35, le=2.2)],
]
FootPosition = tuple[
    Annotated[FiniteNumber, Field(ge=-0.25, le=0.25)],
    Annotated[FiniteNumber, Field(ge=-0.4, le=0.4)],
    Annotated[FiniteNumber, Field(ge=0.02, le=0.18)],
]
MODEL_CONFIG = ConfigDict(extra="forbid", validate_default=True)


class LimbObservation(TypedDict):
    start: Point3
    length: float


class BodyObservation(TypedDict):
    pelvis_height: float
    effectors: dict[EffectorName, Point3]
    limbs: dict[EffectorName, LimbObservation]


@dataclass(frozen=True, config=MODEL_CONFIG)
class SurfaceContact:
    """A generated world-space hand goal on an actual scene object's surface."""

    object_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    effector: Literal["left_hand", "right_hand"]
    position: Point3


@dataclass(frozen=True, config=MODEL_CONFIG)
class BodyPose:
    """Actor-ground coordinates: forward, left, height, in meters."""

    pelvis_height: Annotated[FiniteNumber, Field(ge=0.68, le=1.08)]
    forward_lean_degrees: Annotated[FiniteNumber, Field(ge=-15, le=15)]
    side_lean_degrees: Annotated[FiniteNumber, Field(ge=-12, le=12)]
    left_hand: HandPosition
    right_hand: HandPosition
    left_foot: FootPosition
    right_foot: FootPosition
    contact: SurfaceContact | None = None

    def __post_init__(self) -> None:
        if not 0.16 <= self.left_foot[1] - self.right_foot[1] <= 0.65:
            raise ValueError(
                "Feet must form a grounded stance, left foot to the actor's left of the right foot."
            )
        if (
            abs((self.left_foot[0] + self.right_foot[0]) / 2) > 0.12
            or abs((self.left_foot[1] + self.right_foot[1]) / 2) > 0.1
        ):
            raise ValueError(
                "The pelvis must remain over the center of the support stance."
            )


@dataclass(frozen=True, config=MODEL_CONFIG)
class SpatialWaypoint:
    position: Point2
    speed: Annotated[FiniteNumber, Field(ge=0.7, le=4.5)]
    heading_degrees: Annotated[FiniteNumber, Field(ge=-180, le=180)] | None = None


@dataclass(frozen=True, config=MODEL_CONFIG)
class PlanStep:
    action: Action
    target: ObjectName | None
    style: MovementStyle
    seconds: Annotated[FiniteNumber, Field(ge=0, le=30)]
    waypoints: Annotated[tuple[SpatialWaypoint, ...], Field(max_length=64)] = ()
    body_pose: BodyPose | None = None

    def __post_init__(self) -> None:
        if self.action == "interact" and self.target is None:
            raise ValueError("Interactions need an object target.")
        if self.action not in ("move", "interact") and self.target is not None:
            raise ValueError(
                "Standing, waiting, stopping and posing must use a null target."
            )
        if self.action == "interact" and self.target == "bar" and self.style != "walk":
            raise ValueError(
                "Approach the bar interaction with walk, so its trigger is reached."
            )
        if (self.action == "pose") != (self.body_pose is not None):
            raise ValueError(
                "Only pose steps can contain body targets, and a pose needs body targets."
            )
        if self.action == "pose" and not 1 <= self.seconds <= 10:
            raise ValueError("Hold a generated body pose for 1–10 seconds.")
        if self.action not in ("wait", "pose") and self.seconds != 0:
            raise ValueError("Only wait or pose steps can specify a duration.")
        if bool(self.waypoints) != (self.action in ("move", "interact")):
            raise ValueError("Only move/interact steps require nonempty waypoints.")
        minimum_speed, maximum_speed = SPEED_RANGES[self.style]
        for index, waypoint in enumerate(self.waypoints):
            if not minimum_speed <= waypoint.speed <= maximum_speed:
                raise ValueError(
                    f"{self.style} speed must be between {minimum_speed} and {maximum_speed} m/s."
                )
            if waypoint.heading_degrees is not None and (
                self.action != "move" or index != len(self.waypoints) - 1
            ):
                raise ValueError(
                    "Only the final waypoint of a move may specify a stopping heading."
                )


@dataclass(frozen=True, config=MODEL_CONFIG)
class PlanDocument:
    steps: Annotated[tuple[PlanStep, ...], Field(min_length=1, max_length=12)]

    def __post_init__(self) -> None:
        if sum(len(step.waypoints) for step in self.steps) > 128:
            raise ValueError("A plan can contain at most 128 waypoints.")


InstructionText = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_INSTRUCTION_CHARACTERS,
    ),
]
ViewerId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]


@dataclass(frozen=True, config=MODEL_CONFIG)
class InstructionSubmission:
    instruction: InstructionText
    viewer_id: ViewerId = Field(default="viewer", alias="viewerId")


@dataclass(frozen=True, config=MODEL_CONFIG)
class WithdrawalSubmission:
    ticket_id: ViewerId = Field(alias="id")
    viewer_id: ViewerId = Field(alias="viewerId")


PLAN_ADAPTER = TypeAdapter(PlanDocument)
BODY_POSE_ADAPTER = TypeAdapter(BodyPose)
INSTRUCTION_ADAPTER = TypeAdapter(InstructionText)
SUBMISSION_ADAPTER = TypeAdapter(InstructionSubmission)
WITHDRAWAL_ADAPTER = TypeAdapter(WithdrawalSubmission)
