r"""Publish a new GitHub release.

    .\.venv\Scripts\python.exe packaging\release.py 0.2.0
    .\.venv\Scripts\python.exe packaging\release.py 0.2.0 --dry-run

Checks, tests, bumps the version everywhere it is written, builds the exe,
commits, tags, pushes, and creates the release with the exe attached. Needs the
GitHub CLI, logged in once with ``gh auth login``.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "aryansaraogi/dxfconvertor"
EXE = ROOT / "dist" / "img2dxf.exe"

#: Every place the version is written, with the pattern that finds it. A
#: release whose badge or ``__version__`` disagrees with its tag is a release
#: nobody can trust, so they move together or not at all.
VERSION_SITES = (
    (ROOT / "pyproject.toml", r'^(version = ")[^"]+(")'),
    (ROOT / "img2dxf" / "__init__.py", r'^(__version__ = ")[^"]+(")'),
    (ROOT / "README.md", r"(badge/version-)[^-]+(-informational)"),
)


def find_gh() -> str | None:
    """Locate the GitHub CLI, including a fresh install the PATH has not seen."""
    found = shutil.which("gh")
    if found:
        return found
    default = Path(r"C:\Program Files\GitHub CLI\gh.exe")
    return str(default) if default.is_file() else None


def run(*cmd: str, capture: bool = False) -> str:
    """Run a command from the repo root, stopping the release if it fails."""
    print("  >", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)
    if result.returncode != 0:
        if capture:
            print(result.stdout, result.stderr, file=sys.stderr)
        raise SystemExit(f"release stopped: {cmd[0]} failed")
    return result.stdout.strip() if capture else ""


def preflight(version: str, gh: str | None) -> None:
    """Refuse to start anything that could only half-finish."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"version must look like 1.2.3, not {version!r}")
    if gh is None:
        raise SystemExit("GitHub CLI not found; install it with: winget install GitHub.cli")
    run(gh, "auth", "status", capture=True)

    if run("git", "branch", "--show-current", capture=True) != "main":
        raise SystemExit("releases are cut from main; switch branches first")
    if run("git", "status", "--porcelain", "--untracked-files=no", capture=True):
        raise SystemExit("commit or stash your changes first, so the tag matches the code")
    run("git", "fetch", "origin", "--tags", capture=True)
    if run("git", "rev-list", "main..origin/main", capture=True):
        raise SystemExit("origin/main has commits you do not; pull first")
    if run("git", "tag", "--list", f"v{version}", capture=True):
        raise SystemExit(f"tag v{version} already exists")


def bump(version: str) -> list[Path]:
    """Write the new version into every site, failing if any has gone missing."""
    changed = []
    for path, pattern in VERSION_SITES:
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(
            pattern, rf"\g<1>{version}\g<2>", text, count=1, flags=re.MULTILINE
        )
        if count != 1:
            raise SystemExit(f"could not find the version in {path.name}")
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="new version, e.g. 0.2.0")
    parser.add_argument(
        "--notes", type=Path,
        help="markdown release notes (default: generated from commits)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="run the checks and tests only; change nothing",
    )
    args = parser.parse_args(argv)
    tag = f"v{args.version}"
    gh = find_gh()

    print("checking the repository")
    preflight(args.version, gh)

    print("running the tests")
    run(sys.executable, "-m", "pytest", "-q")

    if args.dry_run:
        print(f"\ndry run passed; {tag} is ready to release")
        return 0

    print(f"bumping the version to {args.version}")
    changed = bump(args.version)

    print("building the exe")
    run(sys.executable, str(ROOT / "packaging" / "build.py"))
    if not EXE.is_file():
        raise SystemExit("the build produced no exe")

    print("committing and tagging")
    if changed:
        run("git", "add", *(str(p.relative_to(ROOT)) for p in changed))
        run("git", "commit", "-m", f"Release {tag}")
    run("git", "tag", "-a", tag, "-m", f"img2dxf {args.version}")
    run("git", "push", "origin", "main", tag)

    print("publishing the release")
    notes = ["--notes-file", str(args.notes)] if args.notes else ["--generate-notes"]
    url = run(
        gh, "release", "create", tag, str(EXE),
        "--repo", REPO, "--title", f"img2dxf {args.version}", "--verify-tag", *notes,
        capture=True,
    )
    print(f"\nreleased {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
