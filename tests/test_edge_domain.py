from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scr" / "_shared"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_domain import as_l10n  # noqa: E402


def test_as_l10n_three_strings():
    assert as_l10n("Дорожная карта", "Roadmap", "路线图") == {
        "ru": "Дорожная карта",
        "en": "Roadmap",
        "zh": "路线图",
    }


def test_as_l10n_dict():
    assert as_l10n({"ru": "Квалификация", "en": "Qualification", "zh": "定性"}) == {
        "ru": "Квалификация",
        "en": "Qualification",
        "zh": "定性",
    }


def test_as_l10n_value_and_fallback():
    assert as_l10n("Roadmap") == {"ru": "Roadmap", "en": "Roadmap", "zh": "Roadmap"}
    assert as_l10n({}, "Карта") == {"ru": "Карта", "en": "Карта", "zh": "Карта"}
