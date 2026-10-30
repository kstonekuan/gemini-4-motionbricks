import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Button } from "./components/ui/button";
import type { DirectorState } from "./contracts";
import { directorCommandOptions } from "./director-api";
import { describeStep } from "./plan-presentation";
import { sessionStateOptions, viewerId } from "./session-state";

// Select only list inputs: changing hand diagnostics must not rebuild the plan.
const selectPlan = (state: DirectorState | null) =>
  state && {
    steps: state.steps,
    stepIndex: state.stepIndex,
    active: state.active,
    completed: state.status.startsWith("Done."),
  };
const selectCommands = (state: DirectorState | null) =>
  state && {
    active: state.activeInstruction,
    queued: state.queuedInstructions,
  };

export function GeneratedSteps() {
  const { data: state } = useQuery({
    ...sessionStateOptions,
    select: selectPlan,
  });
  const scrollerReference = useRef<HTMLElement>(null);
  const listReference = useRef<HTMLOListElement>(null);
  const activeIndex = state?.active ? state.stepIndex : null;
  const steps = state?.steps;
  useEffect(() => {
    if (activeIndex === null || !steps?.length) return;
    const activeStep = listReference.current?.querySelector<HTMLElement>(
      "[aria-current='step']",
    );
    const scroller = scrollerReference.current;
    if (!activeStep || !scroller) return;
    const stepBounds = activeStep.getBoundingClientRect();
    const scrollBounds = scroller.getBoundingClientRect();
    const overflow =
      stepBounds.left < scrollBounds.left
        ? stepBounds.left - scrollBounds.left
        : stepBounds.right > scrollBounds.right
          ? stepBounds.right - scrollBounds.right
          : 0;
    if (overflow) scroller.scrollBy({ left: overflow, behavior: "smooth" });
  }, [activeIndex, steps]);

  return (
    <section
      ref={scrollerReference}
      className="plan-scroll"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: Focus enables keyboard scrolling of this overflow region.
      tabIndex={0}
      aria-label="Generated execution steps"
    >
      <ol id="plan" ref={listReference}>
        {steps?.map((step, index) => {
          const current = index === activeIndex;
          const detail = step.label
            ? describeStep(step)
            : step.action === "move" || step.action === "interact"
              ? `${step.style} · ${step.waypoints.length} waypoints`
              : step.action === "pose"
                ? `Hands ${step.body_pose.left_hand[2].toFixed(2)} / ${step.body_pose.right_hand[2].toFixed(2)} m high`
                : "";
          return (
            <li
              // A plan is an ordered sequence; duplicate labels/actions are valid.
              // biome-ignore lint/suspicious/noArrayIndexKey: Step position is its identity within a plan.
              key={index}
              data-state={
                state?.completed || index < (state?.stepIndex ?? 0)
                  ? "complete"
                  : current
                    ? "current"
                    : "upcoming"
              }
              aria-current={current ? "step" : undefined}
              className={current ? "active" : undefined}
            >
              <div>
                <strong>{step.label ?? describeStep(step)}</strong>
                <span>{detail}</span>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function QueueCount() {
  const { data: waitingCount = 0 } = useQuery({
    ...sessionStateOptions,
    select: (state) => state?.queuedInstructions.length ?? 0,
  });
  return (
    <span id="queue-count">
      {waitingCount ? `(${waitingCount} waiting)` : ""}
    </span>
  );
}

export function CommandHistory() {
  const { data: commands } = useQuery({
    ...sessionStateOptions,
    select: selectCommands,
  });
  const withdrawal = useMutation(directorCommandOptions);
  const waitingCount = commands?.queued.length ?? 0;
  return (
    <>
      <p id="queue-status">
        {waitingCount ? `${waitingCount} waiting` : "No commands waiting."}
      </p>
      <p className="queue-caption">Current instruction</p>
      <p id="active-instruction">
        {commands?.active?.instruction ?? "Ready for the next command."}
      </p>
      <ol id="instruction-queue">
        {commands?.queued.map((ticket) => (
          <li key={ticket.id}>
            <span>
              {ticket.instruction}
              {ticket.submitted_by === viewerId ? " (yours)" : ""}
            </span>
            {ticket.submitted_by === viewerId ? (
              <Button
                variant="outline"
                size="sm"
                className="withdraw-command"
                type="button"
                disabled={withdrawal.isPending}
                aria-label={`Withdraw ${ticket.instruction}`}
                onClick={() =>
                  withdrawal.mutate({
                    path: "withdraw",
                    payload: { id: ticket.id, viewerId },
                  })
                }
              >
                Withdraw
              </Button>
            ) : null}
          </li>
        ))}
      </ol>
    </>
  );
}

export function RecentOutcomes() {
  const { data: outcomes } = useQuery({
    ...sessionStateOptions,
    select: (state) => state?.recentOutcomes,
  });
  return (
    <details>
      <summary>Recent instructions</summary>
      <ul id="recent-outcomes">
        {outcomes?.map((result) => (
          <li key={result.id}>
            {result.instruction} — {result.outcome}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function SpatialTargets() {
  const { data: steps } = useQuery({
    ...sessionStateOptions,
    select: (state) => state?.steps,
  });
  const targets = steps?.flatMap((step) => step.waypoints) ?? [];
  return (
    <details className="spatial-targets">
      <summary id="spatial-target-summary">
        Gemini’s spatial targets ({targets.length})
      </summary>
      <ol id="spatial-target-list">
        {targets.map((waypoint, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: Position identifies an ordered target; repeated coordinates are valid.
          <li key={index}>
            {`${index + 1}. (${waypoint.position.map((value) => value.toFixed(1)).join(", ")}) m · ${waypoint.speed.toFixed(2)} m/s${waypoint.heading_degrees !== null ? ` · face ${waypoint.heading_degrees.toFixed(0)}°` : ""}`}
          </li>
        ))}
      </ol>
    </details>
  );
}

const selectBodyCoordinates = (state: DirectorState | null) =>
  state?.bodyTarget && {
    pose: state.steps
      .slice(0, state.stepIndex + 1)
      .reverse()
      .find((step) => step.body_pose !== null)?.body_pose,
    pelvisHeight: state.bodyTarget.pelvisHeight,
    largestError: Math.max(...Object.values(state.bodyTarget.residuals)),
    beforeHoldRootError: state.bodyTarget.beforeHoldRootError,
  };

export function BodyCoordinates() {
  const { data: body } = useQuery({
    ...sessionStateOptions,
    select: selectBodyCoordinates,
  });
  const pose = body?.pose;
  const rows = pose
    ? [
        { label: "Left hand", effector: "left_hand", values: pose.left_hand },
        {
          label: "Right hand",
          effector: "right_hand",
          values: pose.right_hand,
        },
        { label: "Left foot", effector: "left_foot", values: pose.left_foot },
        {
          label: "Right foot",
          effector: "right_foot",
          values: pose.right_foot,
        },
      ]
    : [];
  return (
    <>
      <p id="body-target-details" aria-live="polite">
        {body
          ? `Gemini body target · pelvis ${body.pelvisHeight.toFixed(2)} m · largest IK error ${(body.largestError * 100).toFixed(1)} cm`
          : ""}
      </p>
      <details id="body-coordinates" hidden={!body}>
        <summary>Body target coordinates</summary>
        <p>
          Forward, left, height in meters. A pinned surface hand is shown in
          world coordinates.
        </p>
        <dl id="body-coordinate-list">
          {rows.map(({ label, effector, values }) => {
            const contact = pose?.contact;
            const pinned = contact?.effector === effector;
            return (
              <CoordinateRow
                key={effector}
                label={`${label}${pinned ? " (world)" : ""}`}
                values={pinned ? contact.position : values}
              />
            );
          })}
        </dl>
        <p id="body-tracking-details">
          {body?.beforeHoldRootError !== undefined
            ? `Before hold: pelvis ${(body.beforeHoldRootError * 100).toFixed(1)} cm from target.`
            : ""}
        </p>
      </details>
    </>
  );
}

function CoordinateRow({
  label,
  values,
}: {
  label: string;
  values: readonly [number, number, number];
}) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{values.map((coordinate) => coordinate.toFixed(2)).join(", ")}</dd>
    </>
  );
}
