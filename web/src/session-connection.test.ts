import assert from "node:assert/strict";
import test from "node:test";
import { createActor, SimulatedClock } from "xstate";
import { sessionConnection } from "./session-connection.ts";

test("a dropped viewer reconnects once, discards stale socket events, and releases its socket on exit", (context) => {
  const sockets: SocketBoundary[] = [];
  class SocketBoundary {
    binaryType = "blob";
    onopen: (() => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onmessage: ((event: { data: unknown }) => void) | null = null;
    closed = false;
    constructor() {
      sockets.push(this);
    }
    close() {
      this.closed = true;
    }
  }
  const originalSocket = globalThis.WebSocket;
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    writable: true,
    value: SocketBoundary,
  });
  context.after(() => {
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: originalSocket,
    });
  });
  const clock = new SimulatedClock();
  const received: unknown[] = [];
  let timelineResets = 0;
  const actor = createActor(sessionConnection, {
    clock,
    input: {
      url: new URL("wss://gym.test/ws"),
      onOpen: () => {
        timelineResets++;
      },
      onMessage: (data) => received.push(data),
    },
  });
  actor.start();
  sockets[0].onopen?.();
  const pose = new ArrayBuffer(16);
  sockets[0].onmessage?.({ data: pose });
  assert.deepEqual(received, [pose]);
  sockets[0].onerror?.();
  sockets[0].onclose?.();
  assert.equal(sockets[0].closed, true);
  assert.equal(sockets[0].onmessage, null);
  clock.increment(1500);
  assert.equal(sockets.length, 2);
  sockets[1].onopen?.();
  assert.equal(timelineResets, 2);
  sockets[1].onmessage?.({ data: "fresh scene" });
  assert.deepEqual(received, [pose, "fresh scene"]);
  actor.stop();
  assert.equal(sockets[1].closed, true);
  clock.increment(3000);
  assert.equal(sockets.length, 2);

  const leavingViewer = createActor(sessionConnection, {
    clock,
    input: {
      url: new URL("wss://gym.test/ws"),
      onOpen: () => {},
      onMessage: () => {},
    },
  }).start();
  sockets[2].onclose?.();
  leavingViewer.stop();
  clock.increment(3000);
  assert.equal(sockets.length, 3);
});
