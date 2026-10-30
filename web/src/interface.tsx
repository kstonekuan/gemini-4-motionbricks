import { useIsMutating, useMutationState } from "@tanstack/react-query";
import {
  Eye,
  Focus,
  Hand,
  ListX,
  Move3D,
  PersonStanding,
  RotateCcw,
  Route,
  Scan,
  Send,
  Sparkles,
  Square,
  Users,
} from "lucide-react";
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
          <a className="system-guide" href="#how-it-works">
            How it works
          </a>
          <Badge variant="outline" id="connection" role="status">
            Connecting…
          </Badge>
        </div>
      </header>
      <main>
        <section className="stage" aria-label="Interactive character view">
          <canvas
            id="scene"
            aria-label="Live 3D character. Drag to orbit, scroll to zoom."
          ></canvas>
          <div className="stage-heading">
            <h1>
              Language,
              <br />
              placed in space.
            </h1>
            <p>
              Gemini generates the targets. MotionBricks brings them to life.
            </p>
          </div>
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
            <p className="intro">
              Gemini reads the gym and generates routes and body targets.
              MotionBricks builds the poses and generates the motion.
            </p>
          </div>
          <form id="instruction-form">
            <label htmlFor="instruction">Your instruction</label>
            <Textarea
              id="instruction"
              maxLength={2000}
              rows={3}
              placeholder="Reach my left hand to the yellow wall’s top corner nearest the seat."
              required
              defaultValue="Walk to a reachable place beside the yellow wall. Reach my left hand to its top west corner on the side nearest the seat, and hold the surface goal for five seconds."
            />
            <div className="action-row">
              <Button className="flex-1" id="direct" type="submit" disabled>
                <Send aria-hidden="true" />
                Queue command
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
                data-instruction="Create a shallow crouch with both feet planted, reach my left hand forward at shoulder height and extend my right hand to the side. Hold for four seconds."
              >
                <PersonStanding aria-hidden="true" />
                Invent a pose
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
                data-instruction="Walk to (-6, 6), run to (-3, 10), then stop facing the small box."
              >
                <Move3D aria-hidden="true" />
                Choose coordinates
              </Button>
              <Button
                variant="secondary"
                size="sm"
                type="button"
                data-instruction="Run behind the small box, then walk to the vault and vault over it."
              >
                Route and vault
              </Button>
            </div>
          </div>
          <section className="shared-queue">
            <div className="section-heading">
              <Users aria-hidden="true" />
              <h2>One character, everyone’s ideas</h2>
            </div>
            <p id="queue-status">Commands run one at a time, in order.</p>
            <p className="queue-caption">Active command</p>
            <p id="active-instruction">Ready for the next command.</p>
            <ol id="instruction-queue"></ol>
            <Button variant="outline" id="clear-queue" type="button" disabled>
              <ListX aria-hidden="true" />
              Clear waiting commands
            </Button>
            <details>
              <summary>Recent commands</summary>
              <ul id="recent-outcomes"></ul>
            </details>
          </section>
          <div className="execution">
            <div className="section-heading">
              <Sparkles aria-hidden="true" />
              <h2>Gemini’s plan</h2>
            </div>
            <p id="status" role="status" aria-live="polite">
              Connecting to the gym…
            </p>
            <ol id="plan"></ol>
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
            <p className="planning-caption mt-2 text-xs text-muted-foreground">
              A fresh overview is sent with the current geometry when your
              command reaches the front of the queue.
            </p>
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
          <details className="target-controls">
            <summary>Read the target markers</summary>
            <p>
              Blue points and the dashed route are Gemini’s generated
              coordinates. The arrow shows its final heading. Pink dots mark
              Gemini’s hand and foot constraints. Amber marks a generated
              surface goal; the line shows the hand’s remaining distance. Cyan
              ghosts are the actual body targets: newly built Gemini poses
              during pose commands, or motion-asset targets while walking and
              interacting.
            </p>
          </details>
          <section
            id="how-it-works"
            className="division-of-work"
            aria-label="How the character is directed"
          >
            <h2>From instruction to motion</h2>
            <ol className="model-pipeline">
              <li>
                <Eye aria-hidden="true" />
                <div>
                  <strong>Gemini sees the scene</strong>
                  <p>
                    A fresh image, object geometry and the character’s current
                    position.
                  </p>
                </div>
              </li>
              <li>
                <Move3D aria-hidden="true" />
                <div>
                  <strong>Gemini generates targets</strong>
                  <p>
                    Routes, headings, hand and foot positions, pelvis height and
                    lean.
                  </p>
                </div>
              </li>
              <li>
                <PersonStanding aria-hidden="true" />
                <div>
                  <strong>MotionBricks makes it move</strong>
                  <p>
                    IK builds the pose. The motion model generates the
                    transition. Gym interactions use authored assets.
                  </p>
                </div>
              </li>
            </ol>
          </section>
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
          <p className="project-credit">
            An independent experiment with Gemini and NVIDIA MotionBricks.
          </p>
        </aside>
      </main>
    </>
  );
}
