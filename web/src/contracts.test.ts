import assert from "node:assert/strict";
import test from "node:test";
import {
  directorStateSchema,
  parsePoseFrame,
  sceneDescriptionSchema,
} from "./contracts.ts";

const waitStep = {
  action: "wait",
  target: null,
  style: "walk",
  seconds: 1,
  waypoints: [],
  body_pose: null,
};
const sessionState = {
  activeInstruction: null,
  queuedInstructions: [],
  recentOutcomes: [],
  viewerCount: 1,
  status: "Ready",
  planning: false,
  active: false,
  stepIndex: 0,
  steps: [waitStep],
  bodyTarget: null,
  targetCount: 0,
  planningOrigin: null,
};

test("unrecognized or contradictory actions cannot reach the renderer", () => {
  assert.ok(directorStateSchema.safeParse(sessionState).success);
  for (const step of [
    { ...waitStep, action: "dance" },
    {
      ...waitStep,
      action: "interact",
      target: null,
      seconds: 0,
      waypoints: [{ position: [1, 2], speed: 2, heading_degrees: null }],
    },
    { ...waitStep, action: "pose", body_pose: null },
  ])
    assert.equal(
      directorStateSchema.safeParse({ ...sessionState, steps: [step] }).success,
      false,
    );
});

test("inconsistent skeleton and skinning dimensions are rejected before mesh creation", () => {
  const scene = {
    jointNames: ["Root"],
    parents: [-1],
    inverseBind: [[0, 0, 0, 0, 0, 0, 1]],
    meshes: [
      {
        positions: [0, 0, 0, 1, 0, 0, 0, 1, 0],
        indices: [0, 1, 2],
        jointIndices: [0, 0, 0],
        jointWeights: [1, 1, 1],
        influences: 1,
      },
    ],
    objects: [],
  };
  assert.ok(sceneDescriptionSchema.safeParse(scene).success);
  assert.equal(
    sceneDescriptionSchema.safeParse({ ...scene, parents: [0] }).success,
    false,
  );
  for (const mesh of [
    { ...scene.meshes[0], influences: 2 },
    { ...scene.meshes[0], indices: [0, 1, 3] },
    { ...scene.meshes[0], indices: [0, 1] },
    { ...scene.meshes[0], jointIndices: [0, 1, 0] },
  ])
    assert.equal(
      sceneDescriptionSchema.safeParse({ ...scene, meshes: [mesh] }).success,
      false,
    );
});

test("malformed binary poses never reach the animation timeline", () => {
  const valid = new Float32Array([1, 0.1, 0, 0, 0, 0, 1, 0, 0, 0, 1]);
  assert.equal(parsePoseFrame(valid.buffer, 1)?.sequence, 1);
  const fractionalCount = valid.slice();
  fractionalCount[2] = 0.5;
  const nonfinitePose = valid.slice();
  nonfinitePose[4] = Number.NaN;
  for (const buffer of [
    new ArrayBuffer(3),
    valid.slice(0, -1).buffer,
    fractionalCount.buffer,
    nonfinitePose.buffer,
  ]) {
    assert.equal(parsePoseFrame(buffer, 1), null);
  }
});
