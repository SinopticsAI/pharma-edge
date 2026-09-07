from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "scr" / "_shared"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge_intake import merge_org_draft, missing_org_fields  # noqa: E402


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
