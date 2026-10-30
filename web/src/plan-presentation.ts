import { match } from "ts-pattern";
import type { DirectorState } from "./contracts";

export function describeStep(step: DirectorState["steps"][number]): string {
  const interactions = {
    small_box: "Jump over the small box",
    vault: "Vault over the wall",
    bar: "Duck under the bar",
    seat: "Sit on the seat",
  };
  return match(step)
    .with({ action: "wait" }, ({ seconds }) => `Wait ${seconds} seconds`)
    .with({ action: "stand" }, () => "Stand up")
    .with({ action: "stop" }, () => "Stop moving")
    .with({ action: "interact" }, ({ target }) => interactions[target])
    .with({ action: "pose" }, ({ seconds, body_pose }) =>
      body_pose.contact
        ? `Reach ${body_pose.contact.effector.replace("_", " ")} to ${body_pose.contact.object_name} and hold for ${seconds}s`
        : `Generate a body pose and hold for ${seconds}s`,
    )
    .with(
      { action: "move" },
      ({ style, waypoints }) =>
        `${style === "run" ? "Run" : style === "skip" ? "Skip" : "Move"} along ${waypoints.length} spatial targets${["zombie", "crouch"].includes(style) ? ` (${style})` : ""}`,
    )
    .exhaustive();
}
