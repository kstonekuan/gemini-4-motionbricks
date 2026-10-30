import { queryOptions, skipToken } from "@tanstack/react-query";
import type { DirectorState } from "./contracts";
import { queryClient } from "./director-api";

// JSON state is cached; binary poses stay in the Three.js animation timeline.
export const sessionStateOptions = queryOptions<DirectorState | null>({
  queryKey: ["director-session"],
  queryFn: skipToken,
  initialData: null,
});

export const viewerId = crypto.randomUUID();

export function publishSessionState(state: DirectorState): void {
  queryClient.setQueryData(sessionStateOptions.queryKey, state);
}
