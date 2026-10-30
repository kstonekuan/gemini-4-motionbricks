import { fromCallback, setup } from "xstate";

type ConnectionEvent = { type: "OPEN" } | { type: "CLOSE" };
interface ConnectionInput {
  url: URL;
  onOpen: () => void;
  onMessage: (data: unknown) => void;
}

// The socket belongs to this invocation; exiting it also removes its listeners.
const socketActor = fromCallback<ConnectionEvent, ConnectionInput>(
  ({ input, sendBack }) => {
    const socket = new WebSocket(input.url);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      input.onOpen();
      sendBack({ type: "OPEN" });
    };
    socket.onmessage = (event) => input.onMessage(event.data);
    socket.onclose = () => sendBack({ type: "CLOSE" });
    socket.onerror = () => sendBack({ type: "CLOSE" });
    return () => {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    };
  },
);

export const sessionConnection = setup({
  types: {
    context: {} as ConnectionInput,
    input: {} as ConnectionInput,
    events: {} as ConnectionEvent,
  },
  actors: { socketActor },
}).createMachine({
  context: ({ input }) => input,
  initial: "connecting",
  states: {
    connecting: {
      initial: "opening",
      invoke: { src: "socketActor", input: ({ context }) => context },
      on: { CLOSE: "reconnecting" },
      states: {
        opening: { on: { OPEN: "live" } },
        live: {},
      },
    },
    reconnecting: { after: { 1500: "connecting" } },
  },
});
