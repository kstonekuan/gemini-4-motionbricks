/** Parse network data once; infer renderer/domain types from these contracts. */
import * as z from "zod/mini";

const finiteNumber = z.number();
const nonnegativeNumber = z.number().check(z.gte(0));
const nonnegativeInteger = z.int().check(z.gte(0));
const point2 = z.tuple([finiteNumber, finiteNumber]);
const point3 = z.tuple([finiteNumber, finiteNumber, finiteNumber]);
const transform = z.tuple([
  finiteNumber,
  finiteNumber,
  finiteNumber,
  finiteNumber,
  finiteNumber,
  finiteNumber,
  finiteNumber,
]);
const movementStyle = z.enum(["walk", "run", "skip", "zombie", "crouch"]);
const objectName = z.enum(["small_box", "vault", "bar", "seat"]);
const handEffector = z.enum(["left_hand", "right_hand"]);
const surfaceContact = z.object({
  object_name: z.string(),
  effector: handEffector,
  position: point3,
});
const bodyPose = z.object({
  pelvis_height: finiteNumber,
  forward_lean_degrees: finiteNumber,
  side_lean_degrees: finiteNumber,
  left_hand: point3,
  right_hand: point3,
  left_foot: point3,
  right_foot: point3,
  contact: z.optional(z.nullable(surfaceContact)),
});
const waypoint = z.object({
  position: point2,
  speed: finiteNumber,
  heading_degrees: z.nullable(finiteNumber),
});
const route = z.array(waypoint).check(z.minLength(1), z.maxLength(64));
const stepFields = {
  label: z.optional(
    z.nullable(z.string().check(z.minLength(1), z.maxLength(80))),
  ),
  style: movementStyle,
  seconds: finiteNumber,
  target: z.nullable(objectName),
  waypoints: route,
  body_pose: z.nullable(bodyPose),
};
const stationaryFields = {
  ...stepFields,
  target: z.null(),
  waypoints: z.array(waypoint).check(z.maxLength(0)),
  body_pose: z.null(),
};
const planStep = z.discriminatedUnion("action", [
  z.object({
    ...stepFields,
    action: z.literal("move"),
    seconds: z.literal(0),
    body_pose: z.null(),
  }),
  z.object({
    ...stepFields,
    action: z.literal("interact"),
    target: objectName,
    seconds: z.literal(0),
    body_pose: z.null(),
  }),
  z.object({
    ...stationaryFields,
    action: z.literal("pose"),
    seconds: z.number().check(z.gte(1), z.lte(10)),
    body_pose: bodyPose,
  }),
  z.object({
    ...stationaryFields,
    action: z.literal("wait"),
    seconds: z.number().check(z.gte(0), z.lte(30)),
  }),
  z.object({
    ...stationaryFields,
    action: z.literal("stand"),
    seconds: z.literal(0),
  }),
  z.object({
    ...stationaryFields,
    action: z.literal("stop"),
    seconds: z.literal(0),
  }),
]);
const effectorValues = <Value extends z.ZodMiniType>(value: Value) =>
  z.object({
    left_hand: value,
    right_hand: value,
    left_foot: value,
    right_foot: value,
  });
const instructionTicket = z.object({
  id: z.string(),
  instruction: z.string(),
  submitted_by: z.string(),
});
export const commandErrorSchema = z.object({ error: z.string() });
export const directorStateSchema = z.object({
  model: z.optional(z.string().check(z.minLength(1))),
  activeInstruction: z.nullable(instructionTicket),
  queuedInstructions: z.array(instructionTicket).check(z.maxLength(8)),
  recentOutcomes: z
    .array(
      z.object({
        id: z.string(),
        instruction: z.string(),
        outcome: z.string(),
      }),
    )
    .check(z.maxLength(5)),
  viewerCount: nonnegativeInteger,
  status: z.string(),
  planning: z.boolean(),
  active: z.boolean(),
  stepIndex: nonnegativeInteger,
  steps: z.array(planStep).check(z.maxLength(12)),
  planningView: z.optional(
    z.object({ available: z.boolean(), revision: nonnegativeInteger }),
  ),
  bodyTarget: z.nullable(
    z.object({
      contact: z.optional(
        z.object({
          objectName: z.string(),
          effector: handEffector,
          position: point3,
          actual: z.optional(point3),
          errorMeters: z.optional(nonnegativeNumber),
          beforeHoldError: z.optional(nonnegativeNumber),
        }),
      ),
      desired: effectorValues(point3),
      residuals: effectorValues(nonnegativeNumber),
      pelvisHeight: finiteNumber,
      beforeHoldErrors: z.optional(effectorValues(nonnegativeNumber)),
      beforeHoldRootError: z.optional(nonnegativeNumber),
      repairAttempts: z.optional(nonnegativeInteger),
    }),
  ),
  targetCount: z.int().check(z.gte(0), z.lte(4)),
  planningOrigin: z.nullable(point2),
});

const meshDescription = z
  .object({
    positions: z.array(finiteNumber),
    indices: z.array(nonnegativeInteger),
    jointIndices: z.array(nonnegativeInteger),
    jointWeights: z.array(finiteNumber),
    influences: z.int().check(z.gte(1), z.lte(12)),
  })
  .check(
    z.refine(
      (mesh) =>
        mesh.positions.length % 3 === 0 &&
        mesh.jointIndices.length ===
          (mesh.positions.length / 3) * mesh.influences &&
        mesh.jointWeights.length === mesh.jointIndices.length,
      "Mesh vertex and skinning dimensions do not match.",
    ),
  );
export const sceneDescriptionSchema = z
  .object({
    jointNames: z.array(z.string()).check(z.minLength(1)),
    parents: z.array(z.int()),
    inverseBind: z.array(transform),
    meshes: z.array(meshDescription).check(z.minLength(1)),
    objects: z.array(
      z.object({ name: z.string(), transform, size: point3, color: point3 }),
    ),
  })
  .check(
    z.refine(
      (scene) =>
        scene.parents.length === scene.jointNames.length &&
        scene.inverseBind.length === scene.jointNames.length &&
        scene.parents.every((parent, index) =>
          index === 0 ? parent === -1 : parent >= 0 && parent < index,
        ),
      "Skeleton hierarchy and bind dimensions do not match.",
    ),
  );

export type DirectorState = z.infer<typeof directorStateSchema>;
export type SceneDescription = z.infer<typeof sceneDescriptionSchema>;
export type MeshDescription = z.infer<typeof meshDescription>;

const poseFrameHeader = z.tuple([
  nonnegativeInteger,
  nonnegativeNumber,
  z.int().check(z.gte(0), z.lte(4)),
  z.int().check(z.gte(0), z.lte(128)),
]);

export function parsePoseFrame(data: ArrayBuffer, jointCount: number) {
  // The binary stream is four float32 header values, local joint transforms,
  // target transforms, then route points. Preserve this existing wire format.
  if (data.byteLength < 16 || data.byteLength % 4 !== 0) return null;
  const frame = new Float32Array(data);
  const header = poseFrameHeader.safeParse(Array.from(frame.subarray(0, 4)));
  if (!header.success) return null;
  const [sequence, simulationSeconds, targetCount, waypointCount] = header.data;
  if (
    frame.length !==
      4 + jointCount * 7 * (1 + targetCount) + waypointCount * 3 ||
    !frame.every(Number.isFinite)
  )
    return null;
  return { frame, sequence, simulationSeconds, targetCount, waypointCount };
}
