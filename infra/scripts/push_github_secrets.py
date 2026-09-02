"""Push local secr_env.env keys to GitHub Actions repo secrets. Does not print values."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = "SinopticsAI/pharma-edge"
ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / "secr_env.env"


def git_token() -> str:
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git credential fill failed: {proc.stderr.strip()}")
    token = ""
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            token = line.split("=", 1)[1]
    if not token:
        raise SystemExit("no github password/token in credential helper")
    return token


def load_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if value:
            pairs.append((key, value))
    return pairs


def main() -> None:
    env = os.environ.copy()
    env["GH_TOKEN"] = git_token()
    env["GH_PROMPT_DISABLED"] = "1"
    names: list[str] = []
    for key, value in load_pairs():
        result = subprocess.run(
            ["gh", "secret", "set", key, "--repo", REPO, "--body", value],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise SystemExit(f"FAIL {key}: {err}")
        names.append(key)
    listed = subprocess.run(
        ["gh", "secret", "list", "--repo", REPO],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    print("SET", ", ".join(names))
    print(listed.stdout)
    if listed.returncode != 0:
        raise SystemExit(listed.stderr)


if __name__ == "__main__":
    main()
