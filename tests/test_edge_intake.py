from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scr" / "_shared"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_intake import (  # noqa: E402
    merge_org_draft,
    missing_org_fields,
    normalize_registration_number,
    registration_number_of,
    suspect_org_fields,
    uscc_looks_wrong,
)


def test_merge_maps_chinese_name_key():
    draft = merge_org_draft(
        {},
        {
            "extracted": {
                "名称": "杭州信纳智析科技有限公司",
                "统一社会信用代码": "91330106MAK20KYJ17",
            }
        },
        source="business-license · bussines_licence.jpg",
    )
    assert draft["legalName"]["value"] == "杭州信纳智析科技有限公司"
    assert draft["registrationNumber"]["value"] == "91330106MAK20KYJ17"
    assert missing_org_fields(draft) == []


def test_org_z5eynpwj_uscc_only_still_misses_name():
    """Cabinet card for org-z5eynpwj: 注册号 present, name missing."""
    draft = merge_org_draft(
        {},
        {
            "extracted": {
                "unified_social_credit_code": "91330106MAK20KYJ17",
                "company_name": None,
            }
        },
        source="business-license · bussines_licence.jpg",
    )
    assert draft["registrationNumber"]["value"] == "91330106MAK20KYJ17"
    assert missing_org_fields(draft) == ["legalName"]


def test_normalize_registration_number_strips_and_uppercases():
    assert normalize_registration_number(" 91330106mak20kyj17 ") == "91330106MAK20KYJ17"
    assert normalize_registration_number("") == ""
    assert normalize_registration_number(None) == ""


def test_registration_number_of_reads_draft_then_profile():
    assert (
        registration_number_of({"registrationNumber": {"value": "91330106mak20kyj17"}})
        == "91330106MAK20KYJ17"
    )
    assert registration_number_of({}, {"registrationNumber": "91330106MAK20KYJ17"}) == "91330106MAK20KYJ17"
    assert registration_number_of({}, {}) == ""


def test_uscc_check_digit_separates_two_readings_of_one_licence():
    assert uscc_looks_wrong("91330106MAK20KYJ17") is False
    assert uscc_looks_wrong("91330106MA2KXYYJ17") is True
    # I, O, S, V and Z are not in the alphabet: an 18-character code with them is a misread.
    assert uscc_looks_wrong("91330106MAI20KYJ17") is True
    # An old 15-digit 注册号 is not a USCC and must pass untouched.
    assert uscc_looks_wrong("330106000012345") is False
    assert uscc_looks_wrong("") is False


def test_misread_code_lands_on_the_card_but_blocks_approval():
    draft = merge_org_draft(
        {},
        {
            "extracted": {
                "company_name": "杭州信纳智析科技有限公司",
                "unified_social_credit_code": "91330106MA2KXYYJ17",
            }
        },
        source="business-license · bussines_licence.jpg",
    )
    # The value is shown, because a person has to compare it with the paper.
    assert draft["registrationNumber"]["value"] == "91330106MA2KXYYJ17"
    assert draft["registrationNumber"]["verified"] is False
    assert missing_org_fields(draft) == []
    assert suspect_org_fields(draft) == ["registrationNumber"]


def test_a_code_that_adds_up_carries_no_flag():
    draft = merge_org_draft(
        {},
        {"extracted": {"unified_social_credit_code": "91330106MAK20KYJ17"}},
        source="business-license · bussines_licence.jpg",
    )
    assert "verified" not in draft["registrationNumber"]
    assert suspect_org_fields(draft) == []


def test_a_typed_number_clears_the_flag():
    """Otherwise a genuinely non-standard code leaves a profile nobody can approve."""
    draft = merge_org_draft(
        {},
        {"extracted": {"unified_social_credit_code": "91330106MA2KXYYJ17"}},
        source="business-license · bussines_licence.jpg",
    )
    assert suspect_org_fields(draft) == ["registrationNumber"]
    # patch-company-draft replaces the whole entry, provenance and all.
    draft["registrationNumber"] = {"value": "91330106MAK20KYJ17", "source": "сказал клиент"}
    assert suspect_org_fields(draft) == []
