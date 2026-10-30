import { QueryClientProvider } from "@tanstack/react-query";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { queryClient } from "./director-api";
import { DirectorInterface } from "./interface";
import "./style.css";

const container = document.getElementById("app");
if (!container) throw new Error("Missing director root");
flushSync(() => {
  createRoot(container).render(
    <QueryClientProvider client={queryClient}>
      <DirectorInterface />
    </QueryClientProvider>,
  );
});
void import("./main").catch((error: unknown) => {
  const loadingElement = document.getElementById("loading");
  if (loadingElement)
    loadingElement.textContent =
      error instanceof Error
        ? error.message
        : "The viewer could not load. Refresh to retry.";
});
