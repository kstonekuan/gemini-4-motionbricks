"""Check live Gemini planning without importing the graphics or GPU runtime."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .planner import generate_plan
from .settings import DirectorSettings


def main() -> None:
    """Print a validated plan for one English instruction."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("instruction", help="English instruction for the character")
    parser.add_argument("--state", default="Idle", help="Current character state")
    parser.add_argument("--model", default=None)
    arguments = parser.parse_args()
    try:
        settings = DirectorSettings(
            **({"gemini_model": arguments.model} if arguments.model is not None else {})
        )
        steps = generate_plan(
            arguments.instruction,
            arguments.state,
            settings.gemini_model,
            settings=settings,
        )
    except (ValueError, OSError, TimeoutError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps({"steps": [asdict(step) for step in steps]}, indent=2))


if __name__ == "__main__":
    main()
