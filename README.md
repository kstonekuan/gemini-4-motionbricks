# Gemini 4 Argon × MotionBricks

Give Gemini 4 Argon an instruction and watch MotionBricks bring it to life in a 3D gym.
Gemini sees a rendered scene and structured geometry, then generates routes,
headings, surface goals and numerical body targets. MotionBricks turns those
validated targets into motion.

This is an independent project built with Google's Gemini API and
[NVIDIA MotionBricks](https://github.com/NVlabs/motionbricks). It is not an official
Google or NVIDIA demo. The web viewer, shared queue and Gemini integration are
custom code in this repository.

## What to try

- “Reach my left hand to the yellow wall’s top corner nearest the seat.”
- “Create a shallow crouch and extend my right hand to the side.”
- “Circle the seat clockwise, then stop facing the bar.”
- “Run behind the small box, then vault over the wall.”

Inspect the generated route, cyan target pose, amber surface goal and measured
hand error. Open **What Gemini saw** to view the actual planning image. The plan board stays above the scene, showing generation and active steps.
Waiting commands and history live in the optional Commands section.

## What Gemini does

| Component | Responsibility |
| --- | --- |
| Gemini | Reads instructions, the scene image and geometry; generates routes, headings, action order and hand/foot/pelvis/lean constraints. Receives bounded validation feedback to repair rejected targets. |
| Director | Checks floor bounds, obstacle clearance, surface placement and limb reach; schedules the shared queue. |
| MotionBricks | Supplies the character, scene, motion assets and existing IK; generates transitions toward the resulting target poses. Walking and gym interactions use authored assets. |
| Custom Three.js viewer | Renders the character locally in the browser, interpolates skeletal updates and visualizes goals and measurements. No desktop video stream. |

Surface reaches currently target hand-joint positions on static cuboids. They do
not model grasping, hand orientation or contact forces. Collision and balance are
not fully proven. Held-pose accuracy is distinct from tracking during a transition.

## Install

You need an NVIDIA GPU with a compatible driver and the MotionBricks TensorRT
runtime on Linux or Windows. The browser can run on a laptop or phone. The full
runtime does not run on macOS. Install Git LFS, uv, Node.js 22.18+ and pnpm first.
The shell commands below use a Linux checkout and headless EGL.

**Download MotionBricks yourself and review its asset licenses.** This repository
contains only the director/viewer source and a small source-code integration patch.
It does not redistribute MotionBricks, pretrained models or sample motion clips.

Starting with this repository checked out in `gemini-spatial-director`:

```sh
# From the directory containing gemini-spatial-director:
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/NVlabs/motionbricks.git MotionBricks
cd MotionBricks
git checkout 54fc563aeaaf819a753d72cc9fdc6713989cdd43
git lfs pull
uv sync
cd ../gemini-spatial-director/web
pnpm install --frozen-lockfile
pnpm build
cd ..
uv run --no-project python scripts/install.py ../MotionBricks --check
uv run --no-project python scripts/install.py ../MotionBricks
cd ../MotionBricks
uv add --requirements ../gemini-spatial-director/requirements.txt
cp ../gemini-spatial-director/.env.example .env
```

Edit `.env` in **MotionBricks**, supplying your own `GEMINI_API_KEY`. Set
`GEMINI_MODEL` to a model ID your key can access. The demonstration uses
`gemini-4-argon`; that model ID is not a promise of access for every account.
The header displays the configured model received from the backend.

```sh
# Run from MotionBricks, where the installer placed the integration:
PYGLET_HEADLESS=true PYOPENGL_PLATFORM=egl uv run python -m app.director_web
```

Open **http://127.0.0.1:6090/** on that machine. The first run builds TensorRT
engines and can take several minutes. See [configuration and controls](docs/director_demo.md)
and [architecture](docs/architecture.md).

The installer validates the pinned upstream commit, checks patch compatibility
and refuses to overwrite different source files. It does not download assets,
change upstream license notices, install dependencies, copy credentials or start
a server. For an updated director, use a fresh pinned MotionBricks checkout;
built frontend assets can be installed again.

## Keys, privacy and hosting

The host supplies the Gemini key through environment variables, `.env` or stdin.
**The backend receives and uses that key. Browser-only bring-your-own-key is not
implemented.** Instructions, scene images and geometry are sent to Google's API;
API charges apply to the configured host account. All viewers see the shared
instructions and outcomes. Do not enter private information.

The server binds to loopback by default. This is a research demo, with no user
authentication or per-user rate limits. Stop, Clear and Reset are shared controls.
For an internet-facing deployment, add access controls, budget limits and service
supervision; use a proxy that supports WebSockets. Run one backend worker per
shared GPU session. Publishing this source does not publish a hosted demo.

## Development

After installation, run the [CPU checks](docs/development.md) in the MotionBricks
checkout. The director suite covers generated-plan validation, scene-relative
reaching, IK targets, repair behavior and queue outcomes without an API key or
TensorRT. Frontend checks run here in `web`:

```sh
pnpm format
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

## License and credits

Director/viewer source is available under [Apache-2.0](LICENSE). The integration
patch modifies Apache-2.0 MotionBricks source; upstream attribution is in [NOTICE](NOTICE).
MotionBricks code, documentation, models and sample motion data have distinct
upstream terms. Obtaining assets separately does not remove their usage terms;
review them for your intended use, including a hosted demo.

The viewer uses Three.js, React, TanStack Query, XState, ts-pattern, Zod,
AI Elements, shadcn/ui, Radix UI, Motion, Lucide and Manrope. See [third-party notices](THIRD_PARTY_NOTICES.md).
