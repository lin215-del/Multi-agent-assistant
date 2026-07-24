from __future__ import annotations

import hashlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = PROJECT_ROOT / "knowledge_base"
CHECKSUM_PATH = SNAPSHOT_ROOT / "SHA256SUMS.txt"


def main() -> None:
    if not (SNAPSHOT_ROOT / "manifest.json").is_file():
        raise SystemExit(f"Snapshot manifest is missing: {SNAPSHOT_ROOT / 'manifest.json'}")
    rows: list[str] = []
    for path in sorted(item for item in SNAPSHOT_ROOT.rglob("*") if item.is_file()):
        relative = path.relative_to(SNAPSHOT_ROOT).as_posix()
        if relative == CHECKSUM_PATH.name:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{digest}  {relative}")
    temporary = CHECKSUM_PATH.with_suffix(".tmp")
    temporary.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(CHECKSUM_PATH)
    print(f"Rebuilt {CHECKSUM_PATH} for {len(rows)} snapshot files.")


if __name__ == "__main__":
    main()
