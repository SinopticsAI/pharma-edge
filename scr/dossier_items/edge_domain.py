"""Case domain: stages, tracks, serialization for SPA camelCase."""

from __future__ import annotations

import json
import random
import string
from typing import Any, Optional

STAGE_ORDER = (
    "onboarding",
    "qualification",
    "case",
    "roadmap",
    "dossier",
    "samples",
    "filing",
    "expertise",
    "registry",
    "postreg",
)

TRACKS = frozenset({"pp1684", "eaeu46", "eaeu78"})
RISK_CLASSES = frozenset({"1", "2a", "2b", "3"})
KINDS = frozenset({"device", "drug"})
ACTORS = frozenset({"hq", "ru", "lab", "gov"})
ITEM_TYPES = frozenset(
    {
        "nmpa-certificate",
        "iso-13485",
        "instruction-cn",
        "instruction-ru",
        "tech-spec",
        "poa-upp",
        "lab-protocol",
        "regulator-letter",
        "other",
    }
)
CALENDAR_ANCHORS = (5, 30, 31, 50, 140)
DEFAULT_ORG_CN = "org-cn-demo"
DEFAULT_ORG_RF = "org-rf-upp"


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads_json(value: Any, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def as_l10n(value: Any, fallback: str = "") -> dict[str, str]:
    if isinstance(value, str) and value.strip():
        text = value.strip()
        return {"ru": text, "en": text, "zh": text}
    if isinstance(value, dict):
        ru = str(value.get("ru") or fallback or "").strip()
        if not ru:
            ru = fallback
        return {
            "ru": ru,
            "en": str(value.get("en") or ru),
            "zh": str(value.get("zh") or ru),
        }
    return {"ru": fallback, "en": fallback, "zh": fallback}


def as_translatable(value: Any) -> dict[str, str]:
    if isinstance(value, str) and value.strip():
        return {"ru": value.strip()}
    if isinstance(value, dict) and value.get("ru"):
        out = {"ru": str(value["ru"])}
        for key in ("en", "zh"):
            if value.get(key):
                out[key] = str(value[key])
        return out
    raise ValueError("text must include ru")


def new_id(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(random.choice(alphabet) for _ in range(6))
    return f"{prefix}-{suffix}"


def new_case_code(case_id: str) -> str:
    tail = case_id.split("-", 1)[-1][:4].upper()
    return f"C-{tail}"


def stage_index(stage: str) -> int:
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def can_advance(current: str, incoming: str) -> bool:
    return stage_index(incoming) > stage_index(current)


def track_is_locked(current_stage: str) -> bool:
    return stage_index(current_stage) > stage_index("qualification")


def filing_blocked(mandate_complete: bool, models_locked: bool) -> bool:
    return not (mandate_complete and models_locked)


def field_mask(contour: str) -> dict[str, bool]:
    is_ru = contour == "ru"
    return {
        "mandateCredentials": is_ru,
        "ledgerPay": is_ru,
        "statusWrite": is_ru,
        "audit": is_ru,
        "chat": not is_ru,
        "roadmap": not is_ru,
    }


def row_to_case(row: dict[str, Any]) -> dict[str, Any]:
    cycle = loads_json(row.get("cycle_months_json"), [12, 18])
    if not isinstance(cycle, list) or len(cycle) != 2:
        cycle = [12, 18]
    return {
        "id": row.get("case_id"),
        "code": row.get("code"),
        "product": loads_json(row.get("product_json"), {"ru": "", "en": "", "zh": ""}),
        "manufacturer": loads_json(row.get("manufacturer_json"), {"ru": "", "en": "", "zh": ""}),
        "kind": row.get("kind") or "device",
        "track": row.get("track") or "pp1684",
        "riskClass": row.get("risk_class") or "1",
        "currentStage": row.get("current_stage") or "qualification",
        "nextActor": row.get("next_actor") or "ru",
        "waitingFor": loads_json(row.get("waiting_for_json"), {"ru": "", "en": "", "zh": ""}),
        "dueWorkingDays": int(row.get("due_working_days") or 0),
        "startedOn": row.get("started_on") or "",
        "cycleMonths": cycle,
        "mandateComplete": bool(row.get("mandate_complete")),
        "modelsLocked": bool(row.get("models_locked")),
        "organizationId": row.get("organization_id"),
    }


def row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("item_id"),
        "caseId": row.get("case_id"),
        "itemType": row.get("item_type"),
        "title": loads_json(row.get("title_json"), {"ru": row.get("file_name") or ""}),
        "fileName": row.get("file_name"),
        "objectKey": row.get("object_key"),
        "status": row.get("status"),
        "parcedData": loads_json(row.get("parced_data"), None),
    }


def row_to_status(row: dict[str, Any]) -> dict[str, Any]:
    entered = row.get("entered_at") or ""
    if isinstance(entered, str) and entered.endswith("Z"):
        entered = entered[:-1]
    return {
        "id": row.get("status_id"),
        "caseId": row.get("case_id"),
        "stage": row.get("stage"),
        "text": loads_json(row.get("text_json"), {"ru": ""}),
        "artifact": row.get("artifact") or "",
        "enteredBy": row.get("entered_by") or "",
        "enteredAt": entered,
    }


def row_to_mandate(row: dict[str, Any], include_credentials: bool) -> Optional[dict[str, Any]]:
    if not row:
        return None
    payload = {
        "caseId": row.get("case_id"),
        "operator": row.get("operator") or "",
        "role": row.get("role") or "upp",
        "complete": bool(row.get("complete")),
        "steps": loads_json(row.get("steps_json"), []),
    }
    if include_credentials:
        payload["credentials"] = loads_json(row.get("credentials_json"), [])
    return payload


def default_mandate_steps() -> list[dict[str, Any]]:
    keys = (
        "service-contract",
        "power-of-attorney",
        "apostille",
        "notarized-translation",
        "representative-registered",
    )
    return [{"key": key, "status": "pending"} for key in keys]
