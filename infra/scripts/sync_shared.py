"""Copy scr/_shared helpers into each function folder (Logos vendor-copy)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "scr" / "_shared"
MANIFEST = REPO / ".github" / "functions-paths.json"
FILES = (
    "common_log.py",
    "edge_http.py",
    "edge_pg.py",
    "edge_domain.py",
    "edge_intake.py",
    "edge_plane.py",
    "requirements.txt",
)

# Files a function folder must not keep after the move off YDB.
STALE = ("edge_ydb.py",)


def main() -> None:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for entry in entries:
        dest = REPO / entry["path"]
        dest.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            src = SHARED / name
            if src.exists():
                shutil.copy2(src, dest / name)
                print(f"copied {name} -> {dest}")
        for name in STALE:
            leftover = dest / name
            if leftover.exists():
                leftover.unlink()
                print(f"removed stale {name} <- {dest}")


if __name__ == "__main__":
    main()
