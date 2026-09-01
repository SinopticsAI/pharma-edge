"""Cloud Function: cases — GET /cases (list) and POST /cases (create)."""

from datetime import date

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    DEFAULT_ORG_CN,
    KINDS,
    TRACKS,
    as_l10n,
    default_mandate_steps,
    dumps_json,
    new_case_code,
    new_id,
    row_to_case,
)
from edge_http import (
    error_response,
    get_http_method,
    parse_body,
    require_api_key,
)
from edge_ydb import execute, get_ydb_pool, now_ts

ROUTE_GET = "GET /cases"
ROUTE_POST = "POST /cases"

SELECT_CASES = """
DECLARE $limit AS Int32;
SELECT * FROM cases LIMIT $limit;
"""

INSERT_CASE = """
DECLARE $case_id AS Utf8;
DECLARE $code AS Utf8;
DECLARE $organization_id AS Utf8;
DECLARE $product_id AS Utf8;
DECLARE $product_json AS Utf8;
DECLARE $manufacturer_json AS Utf8;
DECLARE $kind AS Utf8;
DECLARE $track AS Utf8;
DECLARE $risk_class AS Utf8;
DECLARE $current_stage AS Utf8;
DECLARE $next_actor AS Utf8;
DECLARE $waiting_for_json AS Utf8;
DECLARE $due_working_days AS Int32;
DECLARE $started_on AS Utf8;
DECLARE $cycle_months_json AS Utf8;
DECLARE $mandate_complete AS Bool;
DECLARE $models_locked AS Bool;
UPSERT INTO cases
(case_id, code, organization_id, product_id, product_json, manufacturer_json,
 kind, track, risk_class, current_stage, next_actor, waiting_for_json,
 due_working_days, started_on, cycle_months_json, mandate_complete, models_locked,
 created_at, updated_at)
VALUES
($case_id, $code, $organization_id, $product_id, $product_json, $manufacturer_json,
 $kind, $track, $risk_class, $current_stage, $next_actor, $waiting_for_json,
 $due_working_days, $started_on, $cycle_months_json, $mandate_complete, $models_locked,
 CurrentUtcTimestamp(), CurrentUtcTimestamp());
"""

INSERT_MANDATE = """
DECLARE $case_id AS Utf8;
DECLARE $operator AS Utf8;
DECLARE $role AS Utf8;
DECLARE $steps_json AS Utf8;
UPSERT INTO mandates
(case_id, complete, operator, role, steps_json, credentials_json, updated_at)
VALUES
($case_id, false, $operator, $role, $steps_json, "[]", CurrentUtcTimestamp());
"""


def _list_cases(pool, request_id: str):
    rows = execute(pool, SELECT_CASES, {"$limit": 200})
    cases = [row_to_case(row) for row in rows]
    cases.sort(key=lambda item: item.get("startedOn") or "", reverse=True)
    log_structured(request_id, "info", ROUTE_GET, "listed cases", count=len(cases))
    return json_response(200, {"data": cases}, request_id)


def _create_case(event, pool, request_id: str):
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

    organization_id = str(body.get("organizationId") or DEFAULT_ORG_CN)
    case_id = new_id("c")
    code = str(body.get("code") or new_case_code(case_id))
    waiting = as_l10n("Квалификация", "Qualification")

    execute(
        pool,
        INSERT_CASE,
        {
            "$case_id": case_id,
            "$code": code,
            "$organization_id": organization_id,
            "$product_id": str(body.get("productId") or ""),
            "$product_json": dumps_json(product),
            "$manufacturer_json": dumps_json(manufacturer),
            "$kind": kind,
            "$track": track,
            "$risk_class": str(body.get("riskClass") or "1"),
            "$current_stage": "qualification",
            "$next_actor": "ru",
            "$waiting_for_json": dumps_json(waiting),
            "$due_working_days": int(body.get("dueWorkingDays") or 30),
            "$started_on": date.today().isoformat(),
            "$cycle_months_json": dumps_json(body.get("cycleMonths") or [12, 18]),
            "$mandate_complete": False,
            "$models_locked": False,
        },
    )
    execute(
        pool,
        INSERT_MANDATE,
        {
            "$case_id": case_id,
            "$operator": str(body.get("operator") or ""),
            "$role": str(body.get("role") or "upp"),
            "$steps_json": dumps_json(default_mandate_steps()),
        },
    )
    rows = execute(
        pool,
        "DECLARE $case_id AS Utf8; SELECT * FROM cases WHERE case_id = $case_id;",
        {"$case_id": case_id},
    )
    created = row_to_case(rows[0]) if rows else {"id": case_id, "code": code}
    log_structured(request_id, "info", ROUTE_POST, "created case", case_id=case_id)
    return json_response(201, {"data": created}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    route = ROUTE_POST if method == "POST" else ROUTE_GET
    log_structured(request_id, "info", route, "handler entry", method=method)
    denied = require_api_key(event, request_id, route)
    if denied:
        return denied
    try:
        pool = get_ydb_pool()
        if method == "GET":
            return _list_cases(pool, request_id)
        if method == "POST":
            return _create_case(event, pool, request_id)
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
