from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scr" / "_shared"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_intake import (  # noqa: E402
    empty_slot_fills,
    infer_org_item_type,
    inferred_item_type_updates,
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


def test_merge_prefers_chinese_名称_over_english_name_on_andon_licence():
    draft = merge_org_draft(
        {},
        {
            "extracted": {
                "company_name": "Andon Health Co., Ltd.",
                "name": "Andon Health Co., Ltd.",
                "英文名称": "Andon Health Co., Ltd.",
                "名称": "天津九安医疗电子股份有限公司",
                "unified_social_credit_code": "911200006008904220",
            }
        },
        source="business-license · 01-yingye-zhizhao.jpg",
    )
    assert draft["legalName"]["value"] == "天津九安医疗电子股份有限公司"
    assert draft["legalNameEn"]["value"] == "Andon Health Co., Ltd."
    assert draft["registrationNumber"]["value"] == "911200006008904220"


def test_merge_skips_营业执照_title_as_legal_name():
    draft = merge_org_draft(
        {},
        {
            "extracted": {
                "name": "营业执照",
                "名称": "天津九安医疗电子股份有限公司",
                "unified_social_credit_code": "911200006008904220",
            }
        },
        source="business-license · 01-yingye-zhizhao.jpg",
    )
    assert draft["legalName"]["value"] == "天津九安医疗电子股份有限公司"


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


def test_infer_cofoe_bank_from_extracted_fields():
    assert (
        infer_org_item_type(
            "business-license",
            "scan.jpg",
            {
                "extracted": {
                    "company_name": "可孚医疗科技股份有限公司",
                    "account_number": "7559000020071119001",
                    "permit_no": "TEST-J430111071119",
                    "bank_name": "中国银行长沙雨花支行",
                }
            },
        )
        == "bank-account"
    )


def test_infer_cofoe_bank_from_filename_when_vision_kept_licence_fields():
    assert (
        infer_org_item_type(
            "business-license",
            "07-bank-account.jpg",
            {
                "extracted": {
                    "company_name": "可孚医疗科技股份有限公司",
                    "unified_social_credit_code": "91430111696240992G",
                    "legal_representative": "张敏",
                }
            },
        )
        == "bank-account"
    )


def test_infer_cofoe_signatory_from_id_number():
    assert (
        infer_org_item_type(
            "other",
            "scan.jpg",
            {"extracted": {"legal_representative": "张敏", "公民身份号码": "00000019800101000X"}},
        )
        == "signatory"
    )


def test_infer_cofoe_signatory_from_filename():
    assert (
        infer_org_item_type(
            "other",
            "06-signatory.jpg",
            {
                "extracted": {
                    "company_name": "可孚医疗科技股份有限公司",
                    "legal_representative": "张敏",
                }
            },
        )
        == "signatory"
    )


def test_infer_keeps_real_business_license():
    assert (
        infer_org_item_type(
            "business-license",
            "01-yingye-zhizhao.jpg",
            {
                "extracted": {
                    "company_name": "可孚医疗科技股份有限公司",
                    "注册资本": "贰亿叁仟伍佰捌拾玖万柒仟元整",
                    "经营范围": "家用医疗器械的研发、生产与销售",
                    "title": "营业执照",
                }
            },
        )
        == "business-license"
    )


def test_empty_slot_fills_closes_authority_and_bank_on_other_items():
    slots = [
        {"key": "poa-upp", "status": "filled"},
        {"key": "signatory", "status": "pending"},
        {"key": "bank-account", "status": "pending"},
        {"key": "business-license", "status": "filled"},
    ]
    items = [
        {
            "item_id": "it-poa",
            "item_type": "poa-upp",
            "file_name": "05-poa-upp.pdf",
            "status": "parsed",
            "level": "company",
            "parced_data": {},
        },
        {
            "item_id": "it-sig",
            "item_type": "other",
            "file_name": "06-signatory.jpg",
            "status": "parsed",
            "level": "company",
            "parced_data": {"extracted": {"公民身份号码": "00000019800101000X"}},
        },
        {
            "item_id": "it-bank",
            "item_type": "business-license",
            "file_name": "07-bank-account.jpg",
            "status": "parsed",
            "level": "company",
            "parced_data": {"extracted": {"account_number": "7559000020071119001"}},
        },
        {
            "item_id": "it-lic",
            "item_type": "business-license",
            "file_name": "01-yingye-zhizhao.jpg",
            "status": "parsed",
            "level": "company",
            "parced_data": {"extracted": {"注册资本": "贰亿", "经营范围": "器械", "title": "营业执照"}},
        },
    ]
    assert empty_slot_fills(slots, items) == [("signatory", "it-sig"), ("bank-account", "it-bank")]
    assert inferred_item_type_updates(items) == [("it-sig", "signatory"), ("it-bank", "bank-account")]
