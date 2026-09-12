from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scr" / "_shared"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_domain import as_l10n, item_type_of  # noqa: E402


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


def test_item_type_of_folds_unknown_and_l10n():
    assert item_type_of("nmpa-certificate") == "nmpa-certificate"
    assert item_type_of("NMPA-Certificate") == "nmpa-certificate"
    assert item_type_of("expectedUse") == "other"
    assert item_type_of("intended-use") == "other"
    assert item_type_of({"zh": "instruction-cn"}) == "instruction-cn"
    assert item_type_of({"zh": "预期用途"}) == "other"
    assert item_type_of(None) == "other"
