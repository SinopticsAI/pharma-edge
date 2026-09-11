"""Cloud Function: organizations — companies, their slots, and the risk gate.

A company is collected in chat, not in a form. Status walks
collecting -> draft -> profile_approved. Completeness of the legalization
checklist is tracked separately and never blocks adding a product.

The risk report is a gate, not a reference: a rejected company stops here.
Raw sources stay in the database and are not part of any response.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    ORG_STATUSES,
    as_l10n,
    new_id,
    row_to_org_slot,
    row_to_organization,
    row_to_risk_report,
)
from psycopg.errors import UniqueViolation

from edge_http import (
    error_response,
    get_http_method,
    get_path,
    get_path_params,
    get_query,
    parse_body,
    resolve_identity,
)
from edge_intake import (
    default_org_slots,
    empty_slot_fills,
    inferred_item_type_updates,
    org_completeness,
    plain_profile,
    profile_is_sufficient,
    registration_number_of,
    suspect_org_fields,
)
from edge_pg import as_json, execute, find_org_by_uscc, list_orgs_by_uscc, query, query_one

SELECT_ALL = """
SELECT * FROM organizations
WHERE account_id = %(account_id)s
ORDER BY created_at DESC
LIMIT 200
"""

SELECT_ONE = """
SELECT * FROM organizations
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
"""

SELECT_SLOTS = """
SELECT * FROM organization_slots
WHERE organization_id = %(organization_id)s
ORDER BY slot_key
"""

SELECT_ORG_ITEMS = """
SELECT item_id, item_type, file_name, status, parced_data, level
FROM organization_items
WHERE organization_id = %(organization_id)s
"""

FILL_SLOT = """
UPDATE organization_slots
SET status = 'filled', document_id = %(item_id)s, updated_at = now()
WHERE organization_id = %(organization_id)s AND slot_key = %(slot_key)s
"""

UPDATE_ITEM_TYPE = """
UPDATE organization_items
SET item_type = %(item_type)s, updated_at = now()
WHERE item_id = %(item_id)s AND item_type IS DISTINCT FROM %(item_type)s
"""

INSERT_ORG = """
INSERT INTO organizations (organization_id, account_id, kind, name, status, draft, profile)
VALUES (%(organization_id)s, %(account_id)s, %(kind)s, %(name)s, 'collecting', %(draft)s, '{}'::jsonb)
"""

UPDATE_ORG = """
UPDATE organizations
SET name = %(name)s, status = %(status)s, draft = %(draft)s,
    profile = %(profile)s, updated_at = now()
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
"""

INSERT_SLOT = """
INSERT INTO organization_slots
(organization_id, slot_key, section, title, needs_notary, needs_apostille,
 needs_translation, optional, status)
VALUES
(%(organization_id)s, %(slot_key)s, %(section)s, %(title)s, %(needs_notary)s,
 %(needs_apostille)s, %(needs_translation)s, %(optional)s, 'pending')
ON CONFLICT (organization_id, slot_key) DO NOTHING
"""

SELECT_RISK = """
SELECT * FROM company_risk_reports
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
ORDER BY created_at DESC
LIMIT 1
"""

INSERT_RISK = """
INSERT INTO company_risk_reports
(report_id, organization_id, account_id, level, verdict, reasoning, checks,
 raw_sources, checked_by, checked_at)
VALUES
(%(report_id)s, %(organization_id)s, %(account_id)s, %(level)s, %(verdict)s,
 %(reasoning)s, %(checks)s, %(raw_sources)s, %(checked_by)s, now())
"""

INSERT_AUDIT = """
INSERT INTO audit_entries
(entry_id, account_id, subject_type, subject_id, action, actor, actor_role, detail)
VALUES
(%(entry_id)s, %(account_id)s, %(subject_type)s, %(subject_id)s, %(action)s,
 %(actor)s, %(actor_role)s, %(detail)s)
"""


def _audit(identity, subject_type, subject_id, action, detail=None):
    execute(
        INSERT_AUDIT,
        {
            "entry_id": new_id("aud"),
            "account_id": identity.account_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "action": action,
            "actor": identity.display_name or identity.subject,
            "actor_role": identity.role,
            "detail": as_json(detail or {}),
        },
    )


def _seed_slots(organization_id: str) -> None:
    for slot in default_org_slots():
        execute(
            INSERT_SLOT,
            {
                "organization_id": organization_id,
                "slot_key": slot["key"],
                "section": slot.get("section") or "documents",
                "title": as_json(slot["title"]),
                "needs_notary": bool(slot.get("needs_notary")),
                "needs_apostille": bool(slot.get("needs_apostille")),
                "needs_translation": bool(slot.get("needs_translation")),
                "optional": bool(slot.get("optional")),
            },
        )


def _with_slots(row: dict) -> dict:
    payload = row_to_organization(row)
    organization_id = payload["id"]
    items = query(SELECT_ORG_ITEMS, {"organization_id": organization_id})
    for item_id, item_type in inferred_item_type_updates(items):
        execute(UPDATE_ITEM_TYPE, {"item_id": item_id, "item_type": item_type})
        for item in items:
            if item.get("item_id") == item_id:
                item["item_type"] = item_type
    slots = [row_to_org_slot(item) for item in query(SELECT_SLOTS, {"organization_id": organization_id})]
    for slot_key, item_id in empty_slot_fills(slots, items):
        execute(
            FILL_SLOT,
            {"organization_id": organization_id, "slot_key": slot_key, "item_id": item_id},
        )
    slots = [row_to_org_slot(item) for item in query(SELECT_SLOTS, {"organization_id": organization_id})]
    payload["slots"] = slots
    payload["completeness"] = org_completeness(slots)
    return payload


def _sub_route(event) -> str:
    return "risk" if get_path(event).rstrip("/").endswith("/risk") else "organizations"


def _duplicate_uscc(request_id, uscc: str, existing_id: str):
    return error_response(
        409,
        "duplicate_uscc",
        f"registration number {uscc} is already on company {existing_id}",
        request_id,
        existingOrganizationId=existing_id,
        registrationNumber=uscc,
    )


def _uscc_taken(account_id: str, uscc: str, exclude_organization_id: str = ""):
    if not uscc:
        return None
    return find_org_by_uscc(account_id, uscc, exclude_organization_id)


def _list(event, identity, request_id):
    uscc = (get_query(event).get("uscc") or "").strip()
    if uscc:
        rows = list_orgs_by_uscc(identity.account_id, uscc)
    else:
        rows = query(SELECT_ALL, {"account_id": identity.account_id})
    return json_response(200, {"data": [row_to_organization(row) for row in rows]}, request_id)


def _create(event, identity, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    draft = body.get("draft") if isinstance(body.get("draft"), dict) else {}
    uscc = registration_number_of(draft)
    taken = _uscc_taken(identity.account_id, uscc)
    if taken:
        return _duplicate_uscc(request_id, uscc, str(taken["organization_id"]))

    organization_id = new_id("org")
    try:
        execute(
            INSERT_ORG,
            {
                "organization_id": organization_id,
                "account_id": identity.account_id,
                "kind": str(body.get("kind") or "cn"),
                "name": as_json(as_l10n(body.get("name") or "")),
                "draft": as_json(draft),
            },
        )
    except UniqueViolation:
        taken = _uscc_taken(identity.account_id, uscc)
        if taken:
            return _duplicate_uscc(request_id, uscc, str(taken["organization_id"]))
        raise
    _seed_slots(organization_id)
    _audit(identity, "organization", organization_id, "organization.created")
    row = query_one(SELECT_ONE, {"organization_id": organization_id, "account_id": identity.account_id})
    log_structured(request_id, "info", "POST /organizations", "created", organization_id=organization_id)
    return json_response(201, {"data": _with_slots(row)}, request_id)


def _get(organization_id, identity, request_id):
    row = query_one(SELECT_ONE, {"organization_id": organization_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"organization {organization_id} not found", request_id)
    return json_response(200, {"data": _with_slots(row)}, request_id)


def _patch(event, organization_id, identity, request_id):
    row = query_one(SELECT_ONE, {"organization_id": organization_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"organization {organization_id} not found", request_id)
    current = row_to_organization(row)

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    draft = dict(current["draft"])
    if isinstance(body.get("draft"), dict):
        draft.update(body["draft"])

    status = str(body.get("status") or current["status"])
    if status not in ORG_STATUSES:
        return error_response(400, "invalid_status", f"status must be one of {ORG_STATUSES}", request_id)

    profile = current["profile"]
    if status == "profile_approved":
        profile = plain_profile(draft)
        if not profile_is_sufficient(profile):
            return error_response(
                409,
                "profile_incomplete",
                "legalName and registrationNumber are required before approval",
                request_id,
            )
        # A number that fails its own check digit was misread. Approving it
        # would carry the error into every document built from the profile.
        suspect = suspect_org_fields(draft)
        if suspect:
            return error_response(
                409,
                "uscc_checksum",
                f"{', '.join(suspect)} contradicts its check digit; confirm the value against the licence",
                request_id,
            )
        # A company that failed the risk gate is not taken on, no exceptions.
        risk = query_one(SELECT_RISK, {"organization_id": organization_id, "account_id": identity.account_id})
        if risk and risk.get("verdict") == "rejected":
            return error_response(
                409,
                "risk_rejected",
                "company was rejected by the risk check and cannot be approved",
                request_id,
            )

    uscc = registration_number_of(draft, profile)
    taken = _uscc_taken(identity.account_id, uscc, organization_id)
    if taken:
        return _duplicate_uscc(request_id, uscc, str(taken["organization_id"]))

    name = current["name"]
    if body.get("name"):
        name = as_l10n(body["name"])
    elif draft.get("legalName"):
        from edge_intake import draft_value

        legal = draft_value(draft, "legalName")
        legal_en = draft_value(draft, "legalNameEn") or legal
        name = {"ru": legal_en, "en": legal_en, "zh": legal}

    try:
        execute(
            UPDATE_ORG,
            {
                "organization_id": organization_id,
                "account_id": identity.account_id,
                "name": as_json(name),
                "status": status,
                "draft": as_json(draft),
                "profile": as_json(profile),
            },
        )
    except UniqueViolation:
        taken = _uscc_taken(identity.account_id, uscc, organization_id)
        if taken:
            return _duplicate_uscc(request_id, uscc, str(taken["organization_id"]))
        raise
    if status != current["status"]:
        _audit(identity, "organization", organization_id, f"organization.{status}")

    updated = query_one(SELECT_ONE, {"organization_id": organization_id, "account_id": identity.account_id})
    return json_response(200, {"data": _with_slots(updated)}, request_id)


def _get_risk(organization_id, identity, request_id):
    row = query_one(SELECT_RISK, {"organization_id": organization_id, "account_id": identity.account_id})
    if not row:
        return json_response(200, {"data": None}, request_id)
    return json_response(200, {"data": row_to_risk_report(row)}, request_id)


def _post_risk(event, organization_id, identity, request_id):
    if not identity.can_operate:
        return error_response(403, "forbidden", "only an operator records a risk verdict", request_id)
    org = query_one(SELECT_ONE, {"organization_id": organization_id, "account_id": identity.account_id})
    if not org:
        return error_response(404, "not_found", f"organization {organization_id} not found", request_id)

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    level = str(body.get("level") or "unknown")
    if level not in ("low", "medium", "high", "unknown"):
        return error_response(400, "invalid_level", "level must be low, medium, high or unknown", request_id)
    verdict = str(body.get("verdict") or "pending")
    if verdict not in ("pending", "accepted", "rejected"):
        return error_response(400, "invalid_verdict", "verdict must be pending, accepted or rejected", request_id)

    report_id = new_id("risk")
    execute(
        INSERT_RISK,
        {
            "report_id": report_id,
            "organization_id": organization_id,
            "account_id": identity.account_id,
            "level": level,
            "verdict": verdict,
            "reasoning": as_json(as_l10n(body.get("reasoning") or "")),
            "checks": as_json(body.get("checks") or []),
            # Kept for the record and never returned by the API.
            "raw_sources": as_json(body.get("rawSources") or {}),
            "checked_by": identity.display_name or identity.subject,
        },
    )
    _audit(identity, "organization", organization_id, f"risk.{verdict}", {"level": level})
    row = query_one(SELECT_RISK, {"organization_id": organization_id, "account_id": identity.account_id})
    log_structured(request_id, "info", "POST /organizations/{id}/risk", verdict, level=level)
    return json_response(201, {"data": row_to_risk_report(row)}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    params = get_path_params(event)
    organization_id = params.get("id") or params.get("organizationId") or ""
    sub = _sub_route(event)
    route = f"{method} /organizations" + ("/{id}" if organization_id else "") + ("/risk" if sub == "risk" else "")
    log_structured(request_id, "info", route, "handler entry", method=method)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        if sub == "risk":
            if not organization_id:
                return error_response(400, "missing_id", "path parameter id is required", request_id)
            if method == "GET":
                return _get_risk(organization_id, identity, request_id)
            if method == "POST":
                return _post_risk(event, organization_id, identity, request_id)
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        if method == "GET" and organization_id:
            return _get(organization_id, identity, request_id)
        if method == "GET":
            return _list(event, identity, request_id)
        if method == "POST":
            return _create(event, identity, request_id)
        if method == "PATCH" and organization_id:
            return _patch(event, organization_id, identity, request_id)
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
