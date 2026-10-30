import assert from "node:assert/strict";
import test from "node:test";
import { PoseTimeline } from "./pose-timeline.ts";

function samplePosition(timeline: PoseTimeline, nowMs: number): number {
  const sample = timeline.samplePose(nowMs);
  assert.ok(sample);
  return sample.before[0] + (sample.after[0] - sample.before[0]) * sample.blend;
}

test("bursty packets play at the simulation clock rather than their arrival times", () => {
  const timeline = new PoseTimeline(100);
  timeline.enqueuePose(0, new Float32Array([0]), 0);
  timeline.enqueuePose(1 / 30, new Float32Array([1]), 200 / 3);
  timeline.enqueuePose(2 / 30, new Float32Array([2]), 200 / 3);
  timeline.enqueuePose(3 / 30, new Float32Array([3]), 100);
  assert.ok(Math.abs(samplePosition(timeline, 150) - 1.5) < 0.001);
  assert.ok(Math.abs(samplePosition(timeline, 160) - 1.8) < 0.001);
});

test("a connection gap holds the last real pose instead of inventing movement", () => {
  const timeline = new PoseTimeline(100);
  assert.equal(timeline.samplePose(0), null);
  timeline.enqueuePose(0, new Float32Array([5]), 100);
  timeline.enqueuePose(1 / 30, new Float32Array([6]), 134);
  assert.equal(samplePosition(timeline, 5000), 6);
});

test("resetting the gym does not interpolate through the previous location", () => {
  const timeline = new PoseTimeline(100);
  timeline.enqueuePose(10, new Float32Array([30]), 11000);
  timeline.enqueuePose(0, new Float32Array([-8]), 11033);
  assert.equal(samplePosition(timeline, 11050), -8);
});

test("reconnecting clears the old server clock and pose", () => {
  const timeline = new PoseTimeline(100);
  timeline.enqueuePose(10, new Float32Array([30]), 11000);
  timeline.reset();
  assert.equal(timeline.samplePose(11001), null);
  timeline.enqueuePose(20, new Float32Array([8]), 22000);
  assert.equal(samplePosition(timeline, 22100), 8);
});
