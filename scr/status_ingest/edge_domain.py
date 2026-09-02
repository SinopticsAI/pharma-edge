"""Cabinet domain: stages, tracks, node map, serialization for the SPA.

Rows arrive from psycopg as dicts with jsonb already decoded, so mappers here
only rename to camelCase and fill defaults.
"""

from __future__ import annotations

import random
import string
from datetime import date, datetime
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
        "business-license",
        "company-registry",
        "site-docs",
        "gmp-cn",
        "trademark",
        "other",
    }
)

# Company documents are reused across every product of that company.
ORG_ITEM_TYPES = frozenset(
    {
        "business-license",
        "company-registry",
        "site-docs",
        "gmp-cn",
        "iso-13485",
        "poa-upp",
        "trademark",
        "other",
    }
)
PRODUCT_ITEM_TYPES = frozenset(
    {
        "instruction-cn",
        "instruction-ru",
        "tech-spec",
        "nmpa-certificate",
        "iso-13485",
        "lab-protocol",
        "other",
    }
)

ORG_STATUSES = ("collecting", "draft", "profile_approved")
PRODUCT_STATUSES = (
    "collecting",
    "draft",
    "data_approved",
    "variants_pending",
    "variant_selected",
    "ru_confirmed",
)
INTAKE_SCOPES = frozenset({"organization", "product"})
CHAT_ROLES = frozenset({"user", "agent", "system"})
VARIANT_TYPES = frozenset({"recommended", "alternative", "forbidden"})
RISK_LEVELS = frozenset({"low", "medium", "high", "unknown"})

CALENDAR_ANCHORS = (5, 30, 31, 50, 140)

# Enough company data to open a product. Not enough to file.
ORG_PROFILE_REQUIRED = ("legalName", "registrationNumber")

PROFILE_SECTIONS = ("identity", "documents", "authority", "banking", "risk")


def new_id(prefix: str) -> str:
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(random.choice(alphabet) for _ in range(8))
    return f"{prefix}-{suffix}"


def new_case_code(case_id: str) -> str:
    tail = case_id.split("-", 1)[-1][:4].upper()
    return f"RU-{tail}"


def iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


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


# ------------------------------------------------------------------ mappers --

def row_to_organization(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("organization_id"),
        "accountId": row.get("account_id"),
        "kind": row.get("kind") or "cn",
        "name": row.get("name") or {},
        "status": row.get("status") or "collecting",
        "draft": row.get("draft") or {},
        "profile": row.get("profile") or {},
        "createdAt": iso(row.get("created_at")),
        "updatedAt": iso(row.get("updated_at")),
    }


def row_to_org_slot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row.get("slot_key"),
        "section": row.get("section") or "documents",
        "title": row.get("title") or {},
        "requirement": row.get("requirement"),
        "needsNotary": bool(row.get("needs_notary")),
        "needsApostille": bool(row.get("needs_apostille")),
        "needsTranslation": bool(row.get("needs_translation")),
        "optional": bool(row.get("optional")),
        "status": row.get("status") or "pending",
        "documentId": row.get("document_id") or "",
    }


def row_to_org_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("item_id"),
        "organizationId": row.get("organization_id"),
        "productId": row.get("product_id") or "",
        "level": row.get("level") or "company",
        "itemType": row.get("item_type"),
        "title": row.get("title") or {},
        "fileName": row.get("file_name") or "",
        "objectKey": row.get("object_key") or "",
        "status": row.get("status"),
        "parcedData": row.get("parced_data"),
        "version": int(row.get("version") or 1),
        "promotedFrom": row.get("promoted_from") or "",
        "promotedAt": iso(row.get("promoted_at")),
        "updatedAt": iso(row.get("updated_at")),
    }


def row_to_product(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("product_id"),
        "accountId": row.get("account_id"),
        "organizationId": row.get("organization_id"),
        "name": row.get("name") or {},
        "kind": row.get("kind") or "",
        "status": row.get("status") or "collecting",
        "draft": row.get("draft") or {},
        "completeness": int(row.get("completeness") or 0),
        "selectedVariantId": row.get("selected_variant_id") or "",
        "specialistApprovedBy": row.get("specialist_approved_by") or "",
        "specialistApprovedAt": iso(row.get("specialist_approved_at")),
        "clientApprovedBy": row.get("client_approved_by") or "",
        "clientApprovedAt": iso(row.get("client_approved_at")),
        "caseId": row.get("case_id") or "",
        "updatedAt": iso(row.get("updated_at")),
    }


def row_to_variant(row: dict[str, Any]) -> dict[str, Any]:
    cycle = row.get("cycle_months") or [12, 18]
    if not isinstance(cycle, list) or len(cycle) != 2:
        cycle = [12, 18]
    return {
        "id": row.get("variant_id"),
        "productId": row.get("product_id"),
        "variantType": row.get("variant_type") or "alternative",
        "kind": row.get("kind") or "device",
        "track": row.get("track") or "pp1684",
        "riskClass": row.get("risk_class") or "1",
        "title": row.get("title") or {},
        "summary": row.get("summary") or {},
        "pros": row.get("pros") or [],
        "cons": row.get("cons") or [],
        "reason": row.get("reason"),
        "budget": row.get("budget") or {},
        "distribution": row.get("distribution") or {},
        "cycleMonths": cycle,
        "selected": bool(row.get("selected")),
    }


def row_to_case(row: dict[str, Any]) -> dict[str, Any]:
    cycle = row.get("cycle_months") or [12, 18]
    if not isinstance(cycle, list) or len(cycle) != 2:
        cycle = [12, 18]
    return {
        "id": row.get("case_id"),
        "accountId": row.get("account_id"),
        "code": row.get("code"),
        "product": row.get("product") or {},
        "manufacturer": row.get("manufacturer") or {},
        "kind": row.get("kind") or "device",
        "track": row.get("track") or "pp1684",
        "riskClass": row.get("risk_class") or "1",
        "trackConfirmed": bool(row.get("track_confirmed")),
        "currentStage": row.get("current_stage") or "qualification",
        "nextActor": row.get("next_actor") or "ru",
        "waitingFor": row.get("waiting_for") or {},
        "dueWorkingDays": int(row.get("due_working_days") or 0),
        "startedOn": iso(row.get("started_on")),
        "cycleMonths": cycle,
        "mandateComplete": bool(row.get("mandate_complete")),
        "modelsLocked": bool(row.get("models_locked")),
        "organizationId": row.get("organization_id"),
        "productId": row.get("product_id") or "",
        "intakeSessionId": row.get("intake_session_id") or "",
    }


def row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("item_id"),
        "caseId": row.get("case_id"),
        "itemType": row.get("item_type"),
        "title": row.get("title") or {},
        "fileName": row.get("file_name") or "",
        "objectKey": row.get("object_key") or "",
        "status": row.get("status"),
        "parcedData": row.get("parced_data"),
    }


def row_to_status(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("status_id"),
        "caseId": row.get("case_id"),
        "stage": row.get("stage"),
        "text": row.get("text") or {},
        "artifact": row.get("artifact") or "",
        "enteredBy": row.get("entered_by") or "",
        "enteredAt": iso(row.get("entered_at")),
    }


def row_to_mandate(row: dict[str, Any], include_credentials: bool) -> Optional[dict[str, Any]]:
    if not row:
        return None
    payload = {
        "caseId": row.get("case_id"),
        "operator": row.get("operator") or "",
        "role": row.get("role") or "upp",
        "complete": bool(row.get("complete")),
        "steps": row.get("steps") or [],
    }
    if include_credentials:
        payload["credentials"] = row.get("credentials") or []
    return payload


def row_to_session(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("session_id"),
        "accountId": row.get("account_id"),
        "scope": row.get("scope") or "organization",
        "organizationId": row.get("organization_id") or "",
        "productId": row.get("product_id") or "",
        "status": row.get("status") or "open",
        "locale": row.get("locale") or "zh",
        "planeCaseId": row.get("plane_case_id") or "",
    }


def row_to_message(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("message_id"),
        "sessionId": row.get("session_id"),
        "role": row.get("role") or "agent",
        "text": row.get("text") or {},
        "itemId": row.get("item_id") or "",
        "payload": row.get("payload"),
        "at": iso(row.get("created_at")),
    }


def row_to_node(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row.get("code"),
        "position": int(row.get("position") or 0),
        "title": row.get("title") or {},
        "note": row.get("note"),
        "status": row.get("status") or "later",
        "owner": row.get("owner") or "us",
        "dueHint": row.get("due_hint"),
        "blockedBy": list(row.get("blocked_by") or []),
        "critical": bool(row.get("critical")),
    }


def row_to_risk_report(row: dict[str, Any]) -> dict[str, Any]:
    """Raw sources deliberately absent: they never leave the database."""
    return {
        "id": row.get("report_id"),
        "organizationId": row.get("organization_id"),
        "level": row.get("level") or "unknown",
        "verdict": row.get("verdict") or "pending",
        "reasoning": row.get("reasoning") or {},
        "checks": row.get("checks") or [],
        "checkedBy": row.get("checked_by") or "",
        "checkedAt": iso(row.get("checked_at")),
    }


def default_mandate_steps() -> list[dict[str, Any]]:
    keys = (
        "service-contract",
        "power-of-attorney",
        "apostille",
        "notarized-translation",
        "representative-registered",
    )
    return [{"key": key, "status": "pending"} for key in keys]
