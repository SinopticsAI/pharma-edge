from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scr" / "_shared"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_plane import already_started, wants_plane  # noqa: E402


def test_wants_plane_only_explicit_true():
    assert wants_plane(True) is True
    assert wants_plane("true") is True
    assert wants_plane("1") is True
    assert wants_plane(1) is True
    assert wants_plane(False) is False
    assert wants_plane(None) is False
    assert wants_plane("") is False
    assert wants_plane("yes-please") is False


def test_already_started_reads_facade_message():
    assert already_started({"message": "Case already started (pharma-intake)"}) is True
    assert already_started({"message": "Case started (pharma-intake)"}) is False
    assert already_started({}) is False
