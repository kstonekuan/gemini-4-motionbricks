"""Install the director into a separately downloaded, pinned MotionBricks checkout."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

MOTIONBRICKS_COMMIT = "54fc563aeaaf819a753d72cc9fdc6713989cdd43"
RELEASE_ROOT = Path(__file__).resolve().parents[1]


def run_git(checkout: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(checkout), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def install_director(checkout: Path, *, check_only: bool) -> None:
    """Validate every destination before applying the runtime patch and overlay."""
    checkout = checkout.resolve()
    revision = run_git(checkout, "rev-parse", "HEAD")
    if revision.returncode or revision.stdout.strip() != MOTIONBRICKS_COMMIT:
        raise ValueError(
            f"Use a separate MotionBricks checkout at {MOTIONBRICKS_COMMIT}. "
            "See README.md for the clone and checkout commands."
        )
    if not (checkout / "motionbricks").is_dir():
        raise ValueError("The target does not contain the MotionBricks Python runtime.")
    patch = RELEASE_ROOT / "integration/motionbricks.patch"
    can_apply = run_git(checkout, "apply", "--check", str(patch))
    already_applied = run_git(checkout, "apply", "--reverse", "--check", str(patch))
    if can_apply.returncode and already_applied.returncode:
        raise ValueError(
            "The integration patch conflicts with local runtime changes. "
            "Use a fresh checkout; your files have not been changed.\n"
            + can_apply.stderr.strip()
        )
    frontend = RELEASE_ROOT / "web/dist"
    if not (frontend / "index.html").is_file():
        raise ValueError(
            "Build the frontend first: cd web && pnpm install && pnpm build"
        )
    sources = [
        *sorted((RELEASE_ROOT / "app/director").glob("*.py")),
        RELEASE_ROOT / "app/director_demo.py",
        RELEASE_ROOT / "app/director_web.py",
        *sorted((RELEASE_ROOT / "tests").glob("test_director*.py")),
        *sorted(path for path in frontend.rglob("*") if path.is_file()),
    ]
    for source in sources:
        destination = checkout / source.relative_to(RELEASE_ROOT)
        if not destination.resolve().is_relative_to(checkout):
            raise ValueError(
                f"Refusing a destination outside the checkout: {destination}"
            )
        for ancestor in destination.parents:
            if ancestor == checkout:
                break
            if ancestor.exists() and not ancestor.is_dir():
                raise ValueError(f"A destination parent is not a directory: {ancestor}")
        if destination.exists() and not destination.is_file():
            raise ValueError(f"A destination is not a regular file: {destination}")
        if source.is_relative_to(frontend):
            continue  # Built assets are replaced by each explicit install.
        if destination.exists() and (
            not destination.is_file() or destination.read_bytes() != source.read_bytes()
        ):
            raise ValueError(
                f"Refusing to overwrite a different source file: {destination}. "
                "Use a fresh checkout or move your local changes aside first."
            )
    if check_only:
        print("Compatible checkout; runtime patch and director files can be installed.")
        return
    if can_apply.returncode == 0:
        applied = run_git(checkout, "apply", str(patch))
        if applied.returncode:
            raise ValueError(applied.stderr.strip())
    for source in sources:
        destination = checkout / source.relative_to(RELEASE_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    print(f"Director installed into {checkout}.")
    print(
        "Next: install the extra dependencies and configure .env as described in README.md."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "checkout", type=Path, help="Your separate MotionBricks checkout"
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate without changing files"
    )
    arguments = parser.parse_args()
    try:
        install_director(arguments.checkout, check_only=arguments.check)
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
