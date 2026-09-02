"""Cloud Function: cases — GET /cases (list) and POST /cases (create).

A case belongs to a product that both a specialist and the client approved.
The direct POST stays for the operator path and for backfilling; the ordinary
route into a case is the classification approval in the products function.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    KINDS,
    TRACKS,
    as_l10n,
    default_mandate_steps,
    new_case_code,
    new_id,
    row_to_case,
)
from edge_http import error_response, get_http_method, parse_body, resolve_identity
from edge_pg import as_json, execute, query, query_one

ROUTE_GET = "GET /cases"
ROUTE_POST = "POST /cases"

SELECT_CASES = """
SELECT * FROM cases
WHERE account_id = %(account_id)s
ORDER BY started_on DESC NULLS LAST, created_at DESC
LIMIT 200
"""

SELECT_CASE = "SELECT * FROM cases WHERE case_id = %(case_id)s AND account_id = %(account_id)s"

SELECT_ORG = """
SELECT organization_id, name FROM organizations
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
"""

INSERT_CASE = """
INSERT INTO cases
(case_id, account_id, code, organization_id, product_id, product, manufacturer,
 kind, track, risk_class, current_stage, next_actor, waiting_for,
 due_working_days, started_on, cycle_months, intake_session_id)
VALUES
(%(case_id)s, %(account_id)s, %(code)s, %(organization_id)s, %(product_id)s,
 %(product)s, %(manufacturer)s, %(kind)s, %(track)s, %(risk_class)s,
 'qualification', 'ru', %(waiting_for)s, %(due_working_days)s, current_date,
 %(cycle_months)s, %(intake_session_id)s)
"""

INSERT_MANDATE = """
INSERT INTO mandates (case_id, complete, operator, role, steps)
VALUES (%(case_id)s, false, %(operator)s, %(role)s, %(steps)s)
ON CONFLICT (case_id) DO NOTHING
"""


def _list(identity, request_id):
    rows = query(SELECT_CASES, {"account_id": identity.account_id})
    cases = [row_to_case(row) for row in rows]
    log_structured(request_id, "info", ROUTE_GET, "listed cases", count=len(cases))
    return json_response(200, {"data": cases}, request_id)


def _create(event, identity, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    product = as_l10n(body.get("product"))
    manufacturer = as_l10n(body.get("manufacturer"))
    if not product["ru"] or not manufacturer["ru"]:
        return error_response(400, "invalid_body", "product.ru and manufacturer.ru are required", request_id)

    kind = str(body.get("kind") or "device")
    if kind not in KINDS:
        return error_response(400, "invalid_kind", "kind must be device or drug", request_id)

    track = str(body.get("track") or "pp1684")
    if track not in TRACKS:
        return error_response(400, "invalid_track", "track must be pp1684, eaeu46 or eaeu78", request_id)

    organization_id = str(body.get("organizationId") or "")
    if not organization_id:
        return error_response(400, "missing_organization", "organizationId is required", request_id)
    if not query_one(SELECT_ORG, {"organization_id": organization_id, "account_id": identity.account_id}):
        return error_response(404, "not_found", f"organization {organization_id} not found", request_id)

    case_id = new_id("case")
    code = str(body.get("code") or new_case_code(case_id))
    execute(
        INSERT_CASE,
        {
            "case_id": case_id,
            "account_id": identity.account_id,
            "code": code,
            "organization_id": organization_id,
            "product_id": str(body.get("productId") or "") or None,
            "product": as_json(product),
            "manufacturer": as_json(manufacturer),
            "kind": kind,
            "track": track,
            "risk_class": str(body.get("riskClass") or "1"),
            "waiting_for": as_json(as_l10n("Квалификация", "Qualification", "定性")),
            "due_working_days": int(body.get("dueWorkingDays") or 30),
            "cycle_months": as_json(body.get("cycleMonths") or [12, 18]),
            "intake_session_id": str(body.get("intakeSessionId") or "") or None,
        },
    )
    execute(
        INSERT_MANDATE,
        {
            "case_id": case_id,
            "operator": str(body.get("operator") or ""),
            "role": str(body.get("role") or "upp"),
            "steps": as_json(default_mandate_steps()),
        },
    )
    row = query_one(SELECT_CASE, {"case_id": case_id, "account_id": identity.account_id})
    log_structured(request_id, "info", ROUTE_POST, "created case", case_id=case_id)
    return json_response(201, {"data": row_to_case(row)}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    route = ROUTE_POST if method == "POST" else ROUTE_GET
    log_structured(request_id, "info", route, "handler entry", method=method)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied
        if method == "GET":
            return _list(identity, request_id)
        if method == "POST":
            return _create(event, identity, request_id)
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
