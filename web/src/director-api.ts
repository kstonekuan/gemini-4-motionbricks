import {
  MutationObserver,
  mutationOptions,
  QueryClient,
} from "@tanstack/react-query";
import { commandErrorSchema, sceneDescriptionSchema } from "./contracts.ts";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: Infinity, refetchOnWindowFocus: false },
    // A lost response may already have enqueued the instruction. Never replay it.
    mutations: { retry: false, networkMode: "always" },
  },
});

type DirectorCommand =
  | { path: "instruction"; payload: { instruction: string; viewerId: string } }
  | { path: "withdraw"; payload: { id: string; viewerId: string } }
  | { path: "stop" | "reset" | "clear-queue"; payload?: undefined };

export function loadScene() {
  return queryClient.fetchQuery({
    queryKey: ["scene", document.baseURI],
    queryFn: async ({ signal }) => {
      const response = await fetch(new URL("scene", document.baseURI), {
        signal,
      });
      if (!response.ok)
        throw new Error("The gym is unavailable. Refresh to reconnect.");
      const description = sceneDescriptionSchema.safeParse(
        await response.json(),
      );
      if (!description.success)
        throw new Error("The gym data is incompatible. Refresh to reconnect.");
      return description.data;
    },
  });
}

export const directorCommandOptions = mutationOptions({
  mutationKey: ["director-command"],
  mutationFn: async ({ path, payload }: DirectorCommand): Promise<void> => {
    const response = await fetch(new URL(path, document.baseURI), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) {
      const error = commandErrorSchema.safeParse(await response.json());
      throw new Error(
        error.success
          ? error.data.error
          : "The command could not be sent. Try again.",
      );
    }
  },
});

export function submitCommand(command: DirectorCommand): Promise<void> {
  return new MutationObserver(queryClient, directorCommandOptions).mutate(
    command,
  );
}
