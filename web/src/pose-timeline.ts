interface TimedPose {
  seconds: number;
  pose: Float32Array;
}

export interface PoseSample {
  before: Float32Array;
  after: Float32Array;
  blend: number;
}

/** Present server-timed motion smoothly despite irregular packet arrivals. */
export class PoseTimeline {
  private frames: TimedPose[] = [];
  private clockOffsetMs: number | null = null;

  private readonly playbackDelayMs: number;

  constructor(playbackDelayMs = 100) {
    this.playbackDelayMs = playbackDelayMs;
  }

  reset(): void {
    this.frames = [];
    this.clockOffsetMs = null;
  }

  enqueuePose(seconds: number, pose: Float32Array, receivedAtMs: number): void {
    const latest = this.frames.at(-1);
    // Reset the clock with the gym instead of blending across a teleport.
    if (latest && seconds < latest.seconds) this.reset();
    const observedOffsetMs = receivedAtMs - seconds * 1000;
    this.clockOffsetMs =
      this.clockOffsetMs === null
        ? observedOffsetMs
        : Math.min(observedOffsetMs, this.clockOffsetMs + 0.1);
    this.frames.push({ seconds, pose });
    // A suspended tab must not accumulate seconds of stale playback.
    if (this.frames.length > 32) this.frames.shift();
  }

  samplePose(nowMs: number): PoseSample | null {
    if (this.clockOffsetMs === null || this.frames.length === 0) return null;
    const seconds = (nowMs - this.clockOffsetMs - this.playbackDelayMs) / 1000;
    while (this.frames.length > 2 && this.frames[1].seconds <= seconds)
      this.frames.shift();
    const before = this.frames[0];
    const after = this.frames[1] ?? before;
    const duration = after.seconds - before.seconds;
    const blend =
      duration > 0
        ? Math.max(0, Math.min(1, (seconds - before.seconds) / duration))
        : 1;
    return { before: before.pose, after: after.pose, blend };
  }
}
