# English character director

This independent extension adds Gemini planning and a custom browser viewer to
NVIDIA MotionBricks. For a source-only installation, obtain MotionBricks yourself
and follow the [README](../README.md). After installation, open http://127.0.0.1:6090/.

The browser renders the SOMA character and gym locally with WebGL. The GPU server
sends skeletal poses over a WebSocket, rather than streaming a desktop or video.
Camera orbit and zoom run entirely in the browser. The current demo is one shared
character: commands from any connected browser affect that character.

Pose playback follows simulation timestamps with a 100 ms interpolation buffer,
so uneven network arrivals do not directly set animation speed. The follow-camera
uses the interpolated character position. This trades 100 ms of playback delay
for smoother motion; it does not remove command latency or network round trips.

Gemini receives a structured snapshot of the live scene: character position and
heading, object positions, oriented solid dimensions/colors, obstacle bounds, floor
bounds, body/limb measurements, and interaction entry and exit points. It generates world-space waypoints, speeds, final headings,
and action order. Routes are generated for each instruction rather than selected
from a preset route list. At the front of the queue, the GPU also renders a clean
960×540 live overview and sends its JPEG to Gemini alongside the geometry through
the official SDK. One image is captured per planning/repair request; the steady
pose stream stays skeletal. Expand **What Gemini saw** to inspect that image or
open it at full size. `MOTIONBRICKS_SCENE_IMAGES=false` keeps geometry-only planning.

Gemini can also generate **new numerical body targets**: both hand positions,
both foot positions, pelvis height and forward/side lean. Coordinates are in the
character's ground frame: forward, left, height in meters. The runtime seeds from
the current pose and uses MotionBricks' existing two-bone IK to build a new full
skeleton pose, without selecting a pose asset for this action. Lowering the pelvis
with planted feet bends the legs; this is not restricted to upper-body movement.
MotionBricks generates the transition toward that pose, then the exact solved pose
is held for inspection. These are grounded, modest stances, not arbitrary dynamic
acrobatic poses. If a pose fails the exact runtime reach check, Gemini gets one chance to repair
only that pose using a fresh skeleton observation. Earlier actions are not replayed,
and the remaining plan stays in order. A failed repair ends that command so the
queue can continue. Lean is absolute relative to the rig's reference posture,
so repeated pose commands do not accumulate it.
IK reach and support-stance limits are checked; balance, all
self-collisions and general obstacle contact are not proven.

Scene-relative **surface reaches** add `body_pose.contact`:

```json
{"object_name": "Wall", "effector": "left_hand", "position": [3.875, 7.0, 0.81814]}
```

Gemini chooses an actual world-space surface point, an approach route/final
heading, pelvis/lean and free-limb constraints. The pinned hand's actor-frame
compatibility tuple is overridden by this world goal. The runtime resolves that
goal using the character's actual position and heading after arrival, and builds
the pose with existing IK. The amber marker shows the goal; green shows the
measured hand joint, with a line between them. The **Surface reach** card reports
current hand distance and the separate error immediately before the exact held
pose begins. Ordinary body-coordinate rows stay actor-relative; a pinned hand is
shown as a world coordinate.

Surface checks use the solid's oriented center, half-extents and yaw, with a 2cm
surface tolerance. The immediately preceding approach can use a .28m clearance
from that solid; other obstacles retain .55m. Planting feet within 6cm of a solid
is rejected. A route escaping an object's margin cannot pass through the solid.
These reaches evaluate hand-joint placement on static cuboids. Finger placement,
hand orientation and contact forces are beyond this version. Runtime repair keeps
the selected object/hand/world point fixed and can adjust the rest of the pose;
a goal that remains unreachable ends the command. Initial validation feedback
includes the rejected plan and measured reach distances for one bounded retry.

Walking and authored jump/vault/duck/sit interactions still use motion assets.
**Show targets** shows generated routes in blue, final-heading arrows, pink hand
and foot constraint markers, and the actual body target as a cyan ghost. During
custom pose commands that ghost is the newly constructed pose, including while
held. A separate cyan target preview stays readable when the character overlaps
its target. Expand **Body target coordinates** for the numerical constraints and
the pelvis distance just before hold. IK solve accuracy and pre-hold motion
tracking are reported separately.

The plan board above the scene shows planning/repair progress and the current
execution step. Gemini supplies a short label for each step; the board keeps the
underlying action visible below it. Older plans without labels remain supported.
The optional **Commands** section contains waiting instructions and history.
**See pose** moves the camera to a closer front view for inspecting body targets.

Enter an instruction and select **Direct character**. Examples:

- Walk beside the yellow wall and reach my left hand to its top west corner nearest the seat. Hold for five seconds.
- Reach my right hand to the yellow wall’s top west corner nearest the overhead bar.
- Create a shallow crouch, reach my left hand forward at shoulder height and extend my right hand sideways. Hold for four seconds.
- Raise both hands in a wide overhead V and hold for three seconds.
- Walk to (-6, 6), then run to (-3, 10), then stop facing the small box.
- Circle the seat clockwise once at a radius of three meters, then face the bar.
- Run behind the small box, then walk to the vault and vault over it.

**Direct character** appends an instruction to the single shared character's queue.
All viewers see the same active command, waiting list and five recent outcomes.
Up to eight instructions can wait; a full queue returns HTTP 429. The instruction
is sent to Gemini only when its turn starts, using the scene and body state at
that time. Viewer IDs are ephemeral tab labels, not authenticated identities.
The queue is held in memory and does not survive a backend restart.

**Stop current** cancels planning/navigation and advances to the next waiting
command. An authored jump, vault or sit transition already underway finishes;
a seated character stays seated until a subsequent command stands up. **Clear
waiting commands** removes only pending instructions. **Reset the gym** cancels
active and waiting work and restores the character. **Withdraw** removes one of
your own waiting commands without affecting other viewers. This uses an ephemeral
submitting-tab identifier, not authentication; these are shared demo controls.
Replies from stopped requests
are discarded. An obsolete Gemini call already in flight can occupy the single
planner worker for up to its 45-second timeout before the next request starts.
Each planner job can make one validation-repair request. Stopping sets a
cancellation token that prevents an obsolete response from launching that retry;
the already-running network read can still take up to 45 seconds to finish.

Available interaction targets are small_box, vault, bar, and seat. Plans support
move, interact, stand, wait, stop, and pose; styles are walk, run, skip, zombie, and
crouch. Movement destinations can be arbitrary floor coordinates. The bar
interaction approaches standing so its raised trigger can be reached.

Validation checks finite coordinates, floor limits, style speed limits, route
length, stopping headings, and segments against obstacle bounds with a 0.55 m
margin. Interaction paths must include the object's supplied entry and exit.
One rejected plan can be sent back to Gemini with geometry feedback for repair.
These conservative planar checks are not full-body collision or balance proofs;
the generated character can deviate from a waypoint polyline around corners.
The bundled scene uses floor-aligned geometry. Each execution step times out
after 60 seconds (the bounded runtime-pose repair phase allows 120 seconds). Coordinates use world X/Y on the floor and Z up; clockwise
means viewed from above. A view-independent “behind” means the object's +X side.

## Run the web app

For shared GPU scheduling and stopping unused allocations, see
[shared deployment](deployment.md).

The backend requires an NVIDIA GPU and MotionBricks dependencies on Linux or
Windows. The supplied TensorRT runtime does not run on macOS. The frontend can
render in a normal browser on a laptop or phone.

First follow the source-only [installation steps](../README.md#install). The
installer puts the director and built viewer into your separate MotionBricks
checkout. Configure `.env` there, then run from that checkout:

```sh
PYGLET_HEADLESS=true PYOPENGL_PLATFORM=egl uv run python -m app.director_web
```

Open `http://127.0.0.1:6090/` on that host. The application listens on loopback by
default; `--host`, `--port`, `--model`, and `--assets` can override settings.
`DirectorSettings` loads configuration once at application startup: explicit CLI
values (and `--secret-stdin`) override exported environment variables, which
override the current directory’s `.env`, then defaults. `GEMINI_API_KEY` and
`GEMINI_MODEL` retain their names; server variables are `MOTIONBRICKS_HOST`,
`MOTIONBRICKS_PORT` and `MOTIONBRICKS_ASSETS`. Shared `.env` files can contain
unrelated settings. Empty keys allow viewing the gym but produce an actionable
error when planning is requested. Credentials use `SecretStr` so ordinary
configuration representations and JSON dumps redact them.

FastAPI validates command bodies using the existing Pydantic contracts and runs
under Uvicorn with exactly one worker for the shared GPU session. HTTP request
bodies retain the 16 KiB limit, including chunked requests. Legacy 202/400/409/429
responses and the binary WebSocket layout are preserved. Interactive API docs are
at `/docs`, including through the existing `/motionbricks/docs` Tailscale path. The
headless EGL viewer initializes the existing gym/runtime; its desktop UI is not
rendered or streamed. Browser skinning preserves all ten SOMA mesh influences
per vertex. Pose delivery retains at most one unsent frame per client.

The default model is `gemini-4-argon`; override it with `--model MODEL_ID` or
`GEMINI_MODEL`. The API key stays on the backend and is sent to Gemini only as an
HTTPS header. Instructions are sent to Google's Gemini API and incur normal API
usage. The key is never sent to the browser. `--secret-stdin` reads the key from
stdin for process launchers without putting it in files or command arguments.

The original desktop app remains available for local debugging:

```sh
uv run python -m app.director_demo --model-precision fp16
```

## Hosting

Run one backend worker per shared GPU session. The default loopback binding is
suitable for local development or a private proxy; publishing source does not
make the app internet-accessible. A hosted service needs HTTPS/WebSocket routing,
service supervision, access controls and spending limits. The current queue and
viewer labels are not authentication, and Stop/Clear/Reset affect all viewers.

A launcher may inject the Gemini key through environment variables or stdin.
The app has no cloud-secret-manager dependency and never sends the key to the
browser. Browser-only bring-your-own-key is not implemented.

The director uses frozen Pydantic contracts and the official Google Gen AI SDK;
the browser validates incoming data with Zod Mini. React mounts the control panel
with shadcn/ui and Lucide. TanStack Query owns the cached scene request and command
mutations; commands never retry automatically or wait to replay when connectivity
returns. XState owns socket lifetime and reconnect delays; ts-pattern exhaustively
labels action variants. Three.js and the binary pose timeline run outside React
updates. The server remains authoritative for the shared queue. See [the architecture](architecture.md)
for the integration boundaries and responsibilities.

## Verification and limitations

The director has 41 CPU tests and the viewer has eight behavior tests. Live
Gemini/GPU checks covered left/right surface reaches, generated body poses,
walking after poses, shared FIFO commands, overflow and withdrawal. The same
instruction produced a different valid goal after the wall was moved and rotated.
A provider timeout occurred during that evaluation; an explicit retry succeeded.
These are development checks, not a general task-success benchmark.

The browser receives skeletal updates at roughly 30 Hz and interpolates poses.
Held-pose IK accuracy and motion tracking before the hold are measured separately.
Neither is a proof of balance, full-body collision avoidance or physical grasping.

For reproducible CPU and frontend commands, see the release development guide.
