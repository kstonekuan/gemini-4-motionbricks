# Development and checks

Build the frontend in this repository. Run Python checks from the separate
MotionBricks checkout after installing the director, so the runtime imports and
scene files resolve there. The CPU suite needs no API key, TensorRT or GPU.
Warp may report that CUDA is unavailable; its CPU backend is sufficient.

```sh
# In the patched MotionBricks checkout:
uv run --no-project --with google-genai --with pydantic-settings --with fastapi --with httpx --with 'uvicorn[standard]' --with numpy --with warp-lang==1.17.0 python -m unittest discover -s tests -p 'test_director*.py'
uv run --no-project --with ruff ruff check --fix app/director app/director_demo.py app/director_web.py tests/test_director*.py
uv run --no-project --with ruff ruff format app/director app/director_demo.py app/director_web.py tests/test_director*.py
uv run --no-project --with ty --with google-genai --with pydantic-settings --with pillow --with fastapi --with 'uvicorn[standard]' --with numpy --with newton==1.6.0 --with warp-lang==1.17.0 python -c 'import glob, pathlib, subprocess, numpy; raise SystemExit(subprocess.call(["ty", "check", "--extra-search-path", str(pathlib.Path(numpy.__file__).parents[1]), "app/director", "app/director_demo.py", "app/director_web.py", *glob.glob("tests/test_director*.py")]))'
```

In the director repository:

```sh
uv run --no-project --with ruff ruff check --fix scripts
uv run --no-project --with ruff ruff format scripts
uv run --no-project --with ty ty check scripts
cd web
pnpm format
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Live verification additionally requires a configured Gemini key and NVIDIA GPU.
Useful scenarios are a surface reach, a generated crouch followed by walking,
queued commands from two viewers, withdrawing a waiting instruction and
reconnecting the browser. To evaluate grounding, repeat the same instruction in
a separately edited scene and compare its generated goal with the new geometry.
Do not infer full-transition accuracy from an exact held-pose measurement.

The integration patch is pinned deliberately. When updating upstream, regenerate
and inspect the four-file runtime patch and verify real stop/pose/walk behavior.
Source and frontend changes should be installed into a fresh pinned checkout;
the installer refuses to overwrite different director source files.
