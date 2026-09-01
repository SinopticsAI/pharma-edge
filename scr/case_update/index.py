"""Cloud Function: case_update — PATCH /cases/{id}."""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    ACTORS,
    KINDS,
    RISK_CLASSES,
    STAGE_ORDER,
    TRACKS,
    as_l10n,
    dumps_json,
    filing_blocked,
    row_to_case,
    stage_index,
    track_is_locked,
)
from edge_http import error_response, get_http_method, get_path_params, parse_body, require_api_key
from edge_ydb import execute, get_ydb_pool

ROUTE = "PATCH /cases/{id}"

SELECT_CASE = """
DECLARE $case_id AS Utf8;
SELECT * FROM cases WHERE case_id = $case_id;
"""

UPDATE_CASE = """
DECLARE $case_id AS Utf8;
DECLARE $product_json AS Utf8;
DECLARE $manufacturer_json AS Utf8;
DECLARE $kind AS Utf8;
DECLARE $track AS Utf8;
DECLARE $risk_class AS Utf8;
DECLARE $current_stage AS Utf8;
DECLARE $next_actor AS Utf8;
DECLARE $waiting_for_json AS Utf8;
DECLARE $due_working_days AS Int32;
DECLARE $cycle_months_json AS Utf8;
DECLARE $mandate_complete AS Bool;
DECLARE $models_locked AS Bool;
UPDATE cases SET
    product_json = $product_json,
    manufacturer_json = $manufacturer_json,
    kind = $kind,
    track = $track,
    risk_class = $risk_class,
    current_stage = $current_stage,
    next_actor = $next_actor,
    waiting_for_json = $waiting_for_json,
    due_working_days = $due_working_days,
    cycle_months_json = $cycle_months_json,
    mandate_complete = $mandate_complete,
    models_locked = $models_locked,
    updated_at = CurrentUtcTimestamp()
WHERE case_id = $case_id;
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)
    denied = require_api_key(event, request_id, ROUTE)
    if denied:
        return denied
    if method != "PATCH":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    try:
        pool = get_ydb_pool()
        rows = execute(pool, SELECT_CASE, {"$case_id": case_id})
        if not rows:
            return error_response(404, "not_found", f"case {case_id} not found", request_id)
        current = rows[0]
        current_case = row_to_case(current)

        track = str(body.get("track") or current_case["track"])
        if track not in TRACKS:
            return error_response(400, "invalid_track", "track must be pp1684, eaeu46 or eaeu78", request_id)
        if track != current_case["track"] and track_is_locked(current_case["currentStage"]):
            return error_response(409, "track_locked", "track is fixed after qualification", request_id)

        kind = str(body.get("kind") or current_case["kind"])
        if kind not in KINDS:
            return error_response(400, "invalid_kind", "kind must be device or drug", request_id)

        risk = str(body.get("riskClass") or current_case["riskClass"])
        if risk not in RISK_CLASSES:
            return error_response(400, "invalid_risk", "riskClass must be 1, 2a, 2b or 3", request_id)

        stage = str(body.get("currentStage") or current_case["currentStage"])
        if stage not in STAGE_ORDER:
            return error_response(400, "invalid_stage", "unknown currentStage", request_id)

        mandate_complete = bool(body["mandateComplete"]) if "mandateComplete" in body else current_case["mandateComplete"]
        models_locked = bool(body["modelsLocked"]) if "modelsLocked" in body else current_case["modelsLocked"]
        if stage_index(stage) >= stage_index("filing") and filing_blocked(mandate_complete, models_locked):
            return error_response(
                409,
                "filing_blocked",
                "filing requires mandateComplete and modelsLocked",
                request_id,
            )

        next_actor = str(body.get("nextActor") or current_case["nextActor"])
        if next_actor not in ACTORS:
            return error_response(400, "invalid_actor", "nextActor must be hq, ru, lab or gov", request_id)

        product = current_case["product"] if body.get("product") is None else as_l10n(body.get("product"))
        manufacturer = (
            current_case["manufacturer"] if body.get("manufacturer") is None else as_l10n(body.get("manufacturer"))
        )
        waiting = current_case["waitingFor"] if "waitingFor" not in body else as_l10n(body.get("waitingFor"))
        cycle = body.get("cycleMonths") or current_case["cycleMonths"]
        due = int(body["dueWorkingDays"]) if "dueWorkingDays" in body else current_case["dueWorkingDays"]

        execute(
            pool,
            UPDATE_CASE,
            {
                "$case_id": case_id,
                "$product_json": dumps_json(product),
                "$manufacturer_json": dumps_json(manufacturer),
                "$kind": kind,
                "$track": track,
                "$risk_class": risk,
                "$current_stage": stage,
                "$next_actor": next_actor,
                "$waiting_for_json": dumps_json(waiting),
                "$due_working_days": due,
                "$cycle_months_json": dumps_json(cycle),
                "$mandate_complete": mandate_complete,
                "$models_locked": models_locked,
            },
        )
        updated = execute(pool, SELECT_CASE, {"$case_id": case_id})
        log_structured(request_id, "info", ROUTE, "updated", case_id=case_id)
        return json_response(200, {"data": row_to_case(updated[0])}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
