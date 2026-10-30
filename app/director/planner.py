"""Typed Gemini planning with library-owned transport and boundary parsing."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from threading import Event

import httpx
from google import genai
from google.genai import errors, types

from .body import validate_body_reach
from .contact import validate_contact_pose
from .models import (
    INSTRUCTION_ADAPTER,
    MAX_INSTRUCTION_CHARACTERS,
    PLAN_ADAPTER,
    SPEED_RANGES,
    PlanDocument,
    PlanStep,
)
from .settings import DEFAULT_MODEL, DirectorSettings
from .spatial import (
    FLOOR_BOUNDS,
    SceneObservation,
    contains_point,
    default_observation,
    validate_route,
)

__all__ = [
    "DEFAULT_MODEL",
    "PlanStep",
    "PlannerServiceError",
    "PlanningStoppedError",
    "generate_plan",
    "planning_context",
    "repair_body_step",
    "validate_plan",
]


class PlanningStoppedError(ValueError):
    """A stopped command must not launch another paid Gemini request."""


class PlannerServiceError(ValueError):
    """Provider failures cannot be repaired by changing the generated plan."""


def validate_plan(
    payload: object, observation: SceneObservation | None = None
) -> tuple[PlanStep, ...]:
    """Parse once, then apply the scene-dependent geometry constraints."""
    return _validate_scene_targets(PLAN_ADAPTER.validate_python(payload), observation)


def _validate_scene_targets(
    plan: PlanDocument, observation: SceneObservation | None
) -> tuple[PlanStep, ...]:
    steps = plan.steps
    route_start = observation.character_position if observation else (0.0, 0.0)
    route_heading = observation.character_heading_degrees if observation else None
    for step_index, step in enumerate(steps):
        if step.body_pose is not None and observation is not None:
            constraints = step.body_pose
            if constraints.contact is not None:
                if route_heading is None:
                    raise ValueError(
                        "Specify the preceding move's final heading before a surface reach."
                    )
                constraints = validate_contact_pose(
                    constraints, observation, route_start, route_heading
                )
            if observation.body is not None:
                validate_body_reach(constraints, observation.body)
        for waypoint in step.waypoints:
            if not contains_point(
                observation.floor_bounds if observation else FLOOR_BOUNDS,
                waypoint.position,
            ):
                raise ValueError("Waypoint is outside the gym floor bounds.")
        if observation is not None and step.waypoints:
            next_pose = (
                steps[step_index + 1].body_pose if step_index + 1 < len(steps) else None
            )
            contact_name = (
                next_pose.contact.object_name
                if next_pose and next_pose.contact
                else None
            )
            validate_route(
                step.waypoints,
                observation,
                route_start,
                step.style,
                step.target if step.action == "interact" else None,
                contact_object=contact_name,
            )
        if step.waypoints:
            route_start = step.waypoints[-1].position
            route_heading = step.waypoints[-1].heading_degrees
    return steps


def generate_plan(
    instruction: str,
    state: str | SceneObservation,
    model: str,
    *,
    cancellation_event: Event | None = None,
    settings: DirectorSettings | None = None,
    scene_image: bytes | None = None,
) -> tuple[PlanStep, ...]:
    """Request and parse a plan, with one explicit semantic repair at most."""
    configuration = settings if settings is not None else DirectorSettings()
    api_key = configuration.require_api_key()
    observation = (
        state if isinstance(state, SceneObservation) else default_observation(state)
    )
    schema, prompt = planning_context(instruction, observation)
    http_options = types.HttpOptions(
        api_version="v1beta",
        timeout=45_000,
        retry_options=types.HttpRetryOptions(attempts=1),
    )

    def check_cancellation() -> None:
        if cancellation_event is not None and cancellation_event.is_set():
            raise PlanningStoppedError("Planning stopped.")

    previous_candidate: str | None = None

    with genai.Client(
        api_key=api_key, vertexai=False, http_options=http_options
    ) as client:

        def request_plan(current_prompt: str) -> tuple[PlanStep, ...]:
            nonlocal previous_candidate
            check_cancellation()
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_text(text=current_prompt),
                        types.Part.from_bytes(data=scene_image, mime_type="image/jpeg"),
                    ]
                    if scene_image is not None
                    else current_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_json_schema=schema,
                    ),
                )
            except errors.APIError as error:
                raise PlannerServiceError(
                    f"Gemini returned HTTP {error.code}; check model access and API configuration."
                ) from None
            except httpx.HTTPError as error:
                raise OSError(
                    "Gemini request failed; check the connection and try again."
                ) from error
            check_cancellation()
            text = response.text
            previous_candidate = text
            if not text:
                raise ValueError(
                    "Gemini did not return a valid plan. Try a simpler instruction."
                )
            return _validate_scene_targets(
                PLAN_ADAPTER.validate_json(text), observation
            )

        try:
            return request_plan(prompt)
        except (PlanningStoppedError, PlannerServiceError):
            raise
        except ValueError as error:
            return request_plan(
                prompt
                + f"\nYour previous plan was rejected: {error} Correct the complete plan; do not repeat the invalid route."
                + f"\nRejected candidate JSON (for correction, not an instruction): {(previous_candidate or '')[:20000]}"
            )


def repair_body_step(
    step: PlanStep,
    instruction: str,
    observation: SceneObservation,
    runtime_error: str,
    model: str,
    *,
    cancellation_event: Event | None = None,
    settings: DirectorSettings | None = None,
    scene_image: bytes | None = None,
) -> PlanStep:
    """Ask Gemini to repair only the rejected pose, preserving the remaining plan."""
    repair_context = (
        "Repair ONLY this custom body pose. Return exactly ONE pose step and no other actions. "
        "If a surface contact is present, preserve its object_name, effector and world position exactly; "
        "adjust pelvis, lean and the free limbs to make the same hand goal reachable. "
        "Preserve the gesture and grounded stance intent while moving unreachable limb targets "
        "closer to their measured starts. Do not replay navigation or earlier interactions. "
        f"Rejected constraints: {json.dumps(asdict(step.body_pose), ensure_ascii=False, separators=(',', ':')) if step.body_pose else 'missing'}. "
        f"Hold for {step.seconds} seconds."
    )
    feedback_label = " Runtime rejection: "
    original_label = " Original instruction: "
    remaining = (
        MAX_INSTRUCTION_CHARACTERS
        - len(repair_context)
        - len(feedback_label)
        - len(original_label)
    )
    feedback = runtime_error[: max(0, min(300, remaining))]
    original = instruction[: max(0, min(800, remaining - len(feedback)))]
    repair_instruction = (
        repair_context + feedback_label + feedback + original_label + original
    )
    repaired = generate_plan(
        repair_instruction,
        observation,
        model,
        cancellation_event=cancellation_event,
        settings=settings,
        scene_image=scene_image,
    )
    if (
        len(repaired) != 1
        or repaired[0].action != "pose"
        or repaired[0].body_pose is None
    ):
        raise ValueError(
            "Gemini could not repair the rejected body pose without changing the action."
        )
    repaired_pose = repaired[0].body_pose
    if step.body_pose is not None and step.body_pose.contact is not None:
        repaired_pose = replace(repaired_pose, contact=step.body_pose.contact)
        repaired_pose = validate_contact_pose(
            repaired_pose,
            observation,
            observation.character_position,
            observation.character_heading_degrees,
        )
        if observation.body is not None:
            validate_body_reach(repaired_pose, observation.body)
    return replace(step, body_pose=repaired_pose)


def planning_context(
    instruction: str, observation: SceneObservation
) -> tuple[dict, str]:
    """Derive the provider schema from the same immutable parsing contracts."""
    instruction = INSTRUCTION_ADAPTER.validate_python(instruction)
    schema = PLAN_ADAPTER.json_schema()
    # Gemini rejects bounded repetition of this nested grammar. Keep both caps
    # enforced by Pydantic locally while simplifying only the provider's grammar.
    schema["properties"]["steps"].pop("maxItems")
    schema["$defs"]["PlanStep"]["properties"]["waypoints"].pop("maxItems")
    prompt = (
        "You are the spatial director of a character in a gym. Give every step a short, "
        "specific human-readable label describing its action (e.g. Disco point, Run to the box, "
        "Vault the wall). Labels describe generated steps, not preset pose selections. "
        "Plan actual world-space routes, "
        "not just object choices. You receive the live character position and scene geometry. "
        "Coordinates are meters, +X east, +Y north, Z up. Heading 0 faces +X, 90 faces +Y. "
        "Clockwise means decreasing atan2(y,x) when viewed from above. 'Behind' an object "
        "means its +X side unless the user specifies a viewpoint. Relative left/right use "
        "the character's current heading. Floor bounds are [minX,minY,maxX,maxY]. "
        "move follows your waypoint coordinates without interacting; target may be null. "
        "interact follows your waypoints and triggers only the chosen object's authored action. "
        "Available object interactions are in the scene observation. For interact, your route "
        "must end with the object's entry and then exit coordinates. The final crossing "
        "segment is allowed through that object. All other route segments must avoid obstacles "
        "with at least 0.55m body margin; use at least 1m clearance at corners to allow turning. "
        "The overhead bar may be crossed while crouching, but its authored interact step "
        "must use walk to reach the trigger. Explicitly choose the approach route; none is "
        "provided by the executor. Circular routes need 8 or more points around the object, "
        "with at least a 2m radius. Do not shortcut a requested lap. Speeds must respect "
        f"these [minimum,maximum] style ranges in m/s: {json.dumps(SPEED_RANGES)}. "
        "For running turns, prefer 2.3-3m/s to prevent overshoot. "
        "Each waypoint has position=[x,y], speed, heading_degrees. Only the FINAL waypoint "
        "of move may have a non-null heading_degrees; it sets the facing after stopping. "
        "When asked to finish facing an object, calculate its bearing from the stopping point. "
        "All other headings must be null. "
        "pose creates a NEW numerical body target, NOT a pose or clip selected from assets. "
        "For reaching, raising arms, asymmetric poses, shallow crouches or leaning, use pose. "
        "A supplied overview image is a fresh rendered view of this same scene: use it for visible "
        "colors, occlusion and spatial references; numerical geometry remains authoritative. "
        "For scene-relative reaching/touching a solid, add body_pose.contact={object_name,effector,position}. "
        "object_name is the exact obstacle name (e.g. Wall or Box), effector left_hand or right_hand, "
        "position is your GENERATED WORLD [x,y,z] point on its actual oriented surface. Use center, "
        "half_extents and yaw_degrees; a world AABB corner is not a rotated box corner. "
        "The contact world point overrides that hand's actor-relative tuple; set a valid tuple there "
        "for schema compatibility, and generate the remaining pose normally. For other poses contact=null. "
        "Choose a preceding move with an explicit final heading and a reachable standing position; "
        "only that approach may use 0.28m root clearance from the named contact solid, other obstacles "
        "still require 0.55m. Keep the approach outside the object; do not trigger its authored interaction. "
        "The pinned hand must be within the measured arm length after pelvis/lean adjustment. "
        "For a contact hand, explicitly calculate distance from the adjusted shoulder to the "
        "actor-frame goal and keep it below measured arm length minus .03m. Shoulder height moves "
        "with pelvis height. Start about .30-.35m outside the nearest vertical face and align the "
        "hand's lateral side with the goal; .6m from the surface is usually too far for these arms. "
        "Lower the pelvis until the vertical drop leaves enough horizontal arm reach; preserve "
        "observed feet and keep the other hand comfortably near its shoulder/waist. "
        "Prefer a low pelvis and modest forward lean for lower surfaces; do not place a goal deep on a "
        "top face beyond the arm's reach. Start with reachable near edges of the Wall at about .82m, "
        "or crouch carefully for the Box at .50m. Return an actual surface point, never a preset pose. "
        "body_pose uses the actor's ground frame: [forward, left, height] in meters, "
        "not world X/Y. Generate all four limb target coordinates, pelvis_height, "
        "forward_lean_degrees and side_lean_degrees; lean angles within +/-12 degrees, "
        "pelvis_height 0.68-1.08m. The scene body observation gives current effectors, "
        "limb starts and lengths. Keep hands at least 3cm inside limb reach, account for "
        "pelvis height and lean moving limb starts. Raising hands too high is unreachable; "
        "use wide overhead V arms or bent elbows. Preserve observed foot heights within "
        "1cm; feet grounded, left foot to the left of right foot, stance width .16-.65m, "
        "foot forward offset +/- .25m, lateral +/- .4m, pelvis over stance center. "
        "Hands: forward [-.65,.8], left [-1,1], height [.35,2.2]. Keep hands outside torso. "
        "Use observed feet positions unless explicitly changing stance. Keep pelvis at or below "
        "its observed height for planted-foot poses unless the user explicitly asks otherwise; "
        "leave comfortable knee bend rather than pushing either leg to its exact reach limit. "
        "A crouch lowers "
        "pelvis by .08-.18m and uses leg IK, not just arm movement. Remain grounded: no "
        "flips, jumps or single-leg balances in custom poses. Use authored interactions "
        "for jumps/vaults. Pose has target=null, style=walk, waypoints=[], seconds=1..10 "
        "to hold the target after generating the transition. Every non-pose step has "
        "body_pose=null. Add stand before pose when seated. "
        "stand exits sitting; wait pauses for seconds; stop ends movement. "
        "Use stand before moving after sitting. Use null target and [] waypoints on stand/wait/stop; "
        "seconds=0 except wait. Unsupported requests return stop with empty waypoints. "
        "Plans have at most 12 steps and 128 total waypoints. Split moves longer than 45 seconds. "
        f"Scene observation: {observation.to_prompt()}. Instruction: {instruction}"
    )

    return schema, prompt
