import { useIsMutating, useMutationState } from "@tanstack/react-query";
import {
  Eye,
  Focus,
  Hand,
  ListX,
  LoaderCircle,
  PersonStanding,
  RotateCcw,
  Route,
  Scan,
  Send,
  Sparkles,
  Square,
} from "lucide-react";
import {
  Plan,
  PlanContent,
  PlanHeader,
  PlanTitle,
} from "./components/ai-elements/plan";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { Textarea } from "./components/ui/textarea";

// Mount once: Three.js owns the canvases and the session adapter owns the empty
// status/list outlets. React never reconciles streamed poses or these outlets.
function CommandFeedback() {
  const pendingCount = useIsMutating({ mutationKey: ["director-command"] });
  const submissions = useMutationState({
    filters: { mutationKey: ["director-command"] },
    select: (mutation) => mutation.state,
  });
  const latest = submissions.reduce<(typeof submissions)[number] | undefined>(
    (newest, submission) =>
      !newest || submission.submittedAt >= newest.submittedAt
        ? submission
        : newest,
    undefined,
  );
  if (latest?.status === "error")
    return (
      <p role="alert" className="text-sm text-destructive">
        {latest.error?.message ?? "The command could not be sent."}
      </p>
    );
  return pendingCount > 0 ? (
    <p role="status" className="text-sm text-muted-foreground">
      Sending command…
    </p>
  ) : null;
}

export function DirectorInterface() {
  return (
    <>
      <a className="skip-link" href="#instruction">
        Skip to instruction
      </a>
      <header className="app-header">
        <a
          className="brand"
          href="./"
          aria-label="Spatial character director home"
        >
          <span className="brand-type">
            <span className="brand-names">
              <strong id="model-name">Gemini 4 Argon</strong>
              <span className="brand-cross" aria-hidden="true">
                ×
              </span>
              <strong>MotionBricks</strong>
            </span>
            <span className="brand-description">
              Spatial reasoning meets motion generation
            </span>
          </span>
        </a>
        <div className="header-session">
          <Badge variant="outline" id="connection" role="status">
            Connecting…
          </Badge>
        </div>
      </header>
      <section className="plan-region" aria-labelledby="plan-title">
        <Plan id="plan-board" className="plan-board" open>
          <PlanHeader className="plan-header">
            <div className="plan-heading">
              <Sparkles aria-hidden="true" />
              <PlanTitle id="plan-title" role="heading" aria-level={2}>
                Gemini’s plan
              </PlanTitle>
              <Badge id="plan-phase" variant="outline">
                Ready
              </Badge>
              <LoaderCircle id="plan-spinner" aria-hidden="true" />
            </div>
            <p id="plan-instruction" />
          </PlanHeader>
          <PlanContent className="plan-content">
            <p id="status" role="status" aria-live="polite">
              Give the character an instruction.
            </p>
            <section
              className="plan-scroll"
              // biome-ignore lint/a11y/noNoninteractiveTabindex: Focus enables keyboard scrolling of this overflow region.
              tabIndex={0}
              aria-label="Generated execution steps"
            >
              <ol id="plan" />
            </section>
          </PlanContent>
        </Plan>
      </section>
      <main>
        <section className="stage" aria-label="Interactive character view">
          <canvas
            id="scene"
            aria-label="Live 3D character. Drag to orbit, scroll to zoom."
          ></canvas>
          <div className="view-tools">
            <Button
              variant="outline"
              id="follow"
              type="button"
              aria-pressed="true"
            >
              <Focus aria-hidden="true" />
              Follow character
            </Button>
            <Button variant="outline" id="pose-view" type="button">
              <PersonStanding aria-hidden="true" />
              See pose
            </Button>
            <Button variant="outline" id="overview" type="button">
              <Scan aria-hidden="true" />
              See the gym
            </Button>
          </div>
          <label className="stage-target-toggle">
            <input id="show-targets" type="checkbox" defaultChecked />
            Show targets
          </label>
          <div className="legend">
            <span>
              <i className="actual-swatch" aria-hidden="true"></i>Character
            </span>
            <span>
              <i className="target-swatch" aria-hidden="true"></i>Target pose
            </span>
          </div>
          <p className="camera-hint">Drag to orbit · Scroll to zoom</p>
          <figure id="target-preview" className="target-preview" hidden>
            <figcaption>Gemini target pose</figcaption>
            <canvas
              id="target-preview-canvas"
              aria-label="Separate preview of the generated body target pose"
            ></canvas>
          </figure>
          <div id="loading" role="status">
            Loading the character…
          </div>
        </section>
        <aside className="director-panel">
          <div className="composer-heading">
            <h2>What should it do?</h2>
            <p className="intro">Describe a route, a jump or a pose.</p>
          </div>
          <form id="instruction-form">
            <label htmlFor="instruction">Your instruction</label>
            <Textarea
              id="instruction"
              maxLength={2000}
              rows={3}
              placeholder="Reach my left hand to the yellow wall’s top corner nearest the seat."
              required
              defaultValue="Run to a clear approach, jump over the small box, then run to the vault and vault over it."
            />
            <div className="action-row">
              <Button className="flex-1" id="direct" type="submit" disabled>
                <Send aria-hidden="true" />
                Direct character
              </Button>
              <Button variant="outline" id="stop" type="button" disabled>
                <Square aria-hidden="true" />
                Stop current
              </Button>
            </div>
          </form>
          <CommandFeedback />
          <div className="example-section">
            <p className="section-caption">Try an instruction</p>
            <div className="examples">
              <Button
                variant="secondary"
                size="sm"
                type="button"
                data-instruction="Walk to a reachable place beside the yellow wall. Reach my left hand to its top west corner on the side nearest the seat, and hold the surface goal for five seconds."
              >
                <Hand aria-hidden="true" />
                Reach to a surface
              </Button>
              <Button
                variant="secondary"
                size="sm"
                type="button"
                data-instruction="Create three playful full-body poses in sequence with both feet planted: a disco point with one hand high and the other low; a low surfer stance with asymmetric outstretched arms and a sideways lean; then a triumphant overhead V. Hold each for two seconds. Keep the pelvis at the observed height or lower, preserve the exact observed foot positions, and keep all hand targets comfortably inside measured reach."
              >
                <PersonStanding aria-hidden="true" />
                Disco, surf, celebrate
              </Button>
              <Button
                variant="secondary"
                size="sm"
                type="button"
                data-instruction="Circle the seat clockwise once at a radius of three meters, then stop facing the bar."
              >
                <Route aria-hidden="true" />
                Circle the seat
              </Button>
              <Button
                variant="secondary"
                size="sm"
                type="button"
                data-instruction="Run to a clear approach, jump over the small box, then run to the vault and vault over it."
              >
                Run, jump, vault
              </Button>
            </div>
          </div>
          <details className="spatial-targets">
            <summary id="spatial-target-summary">
              Gemini’s spatial targets (0)
            </summary>
            <ol id="spatial-target-list"></ol>
          </details>
          <Card id="surface-reach" hidden className="gap-3 py-3">
            <CardHeader className="px-3">
              <CardTitle
                role="heading"
                aria-level={2}
                className="flex items-center gap-2 text-sm"
              >
                <Hand className="size-4" aria-hidden="true" />
                Surface reach
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3">
              <p id="surface-reach-goal" className="text-sm text-foreground" />
              <p
                id="surface-reach-error"
                className="mt-2 text-sm tabular-nums text-muted-foreground"
              />
            </CardContent>
          </Card>
          <details id="planning-view" hidden>
            <summary className="flex cursor-pointer items-center gap-2 text-sm">
              <Eye className="size-4" aria-hidden="true" />
              What Gemini saw
            </summary>
            <a
              id="planning-view-link"
              href="./planning-view.jpg"
              target="_blank"
              rel="noreferrer"
              aria-label="Open Gemini's planning image at full size"
            >
              <img
                id="planning-view-image"
                className="mt-3 w-full rounded-lg border border-border"
                alt="Live overview rendered for Gemini at the start of the most recent planning request"
              />
            </a>
          </details>
          <p id="body-target-details" aria-live="polite"></p>
          <details id="body-coordinates" hidden>
            <summary>Body target coordinates</summary>
            <p>
              Forward, left, height in meters. A pinned surface hand is shown in
              world coordinates.
            </p>
            <dl id="body-coordinate-list"></dl>
            <p id="body-tracking-details"></p>
          </details>
          <details className="command-history">
            <summary>
              Commands <span id="queue-count" />
            </summary>
            <p id="queue-status">No commands waiting.</p>
            <p className="queue-caption">Current instruction</p>
            <p id="active-instruction">Ready for the next instruction.</p>
            <ol id="instruction-queue" />
            <Button variant="outline" id="clear-queue" type="button" disabled>
              <ListX aria-hidden="true" />
              Clear waiting commands
            </Button>
            <details>
              <summary>Recent instructions</summary>
              <ul id="recent-outcomes" />
            </details>
          </details>
          <Button
            variant="ghost"
            className="self-start"
            id="reset"
            type="button"
            disabled
          >
            <RotateCcw aria-hidden="true" />
            Reset the gym
          </Button>
        </aside>
      </main>
    </>
  );
}
