from __future__ import annotations

import re
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> None:
    version = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Invalid VERSION: {version!r}; expected MAJOR.MINOR.PATCH")

    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")

    status = run_git("status", "--short")
    print(f"Version: v{version}")
    print("CHANGELOG: ready")
    print("Working tree: clean" if not status else "Working tree: has uncommitted changes")
    if status:
        print(status)


if __name__ == "__main__":
    main()
