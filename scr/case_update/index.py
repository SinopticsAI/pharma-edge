"""Cloud Function: case_update — PATCH /cases/{id}.

Two invariants survive from the previous contour: the track is fixed once
qualification is behind, and filing needs both a complete mandate and a locked
model list.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    ACTORS,
    KINDS,
    RISK_CLASSES,
    STAGE_ORDER,
    TRACKS,
    as_l10n,
    filing_blocked,
    row_to_case,
    stage_index,
    track_is_locked,
)
from edge_http import error_response, get_http_method, get_path_params, parse_body, resolve_identity
from edge_pg import as_json, execute, query_one

ROUTE = "PATCH /cases/{id}"

SELECT_CASE = "SELECT * FROM cases WHERE case_id = %(case_id)s AND account_id = %(account_id)s"

UPDATE_CASE = """
UPDATE cases SET
    product = %(product)s,
    manufacturer = %(manufacturer)s,
    kind = %(kind)s,
    track = %(track)s,
    risk_class = %(risk_class)s,
    current_stage = %(current_stage)s,
    next_actor = %(next_actor)s,
    waiting_for = %(waiting_for)s,
    due_working_days = %(due_working_days)s,
    cycle_months = %(cycle_months)s,
    mandate_complete = %(mandate_complete)s,
    models_locked = %(models_locked)s,
    updated_at = now()
WHERE case_id = %(case_id)s AND account_id = %(account_id)s
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)

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
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        row = query_one(SELECT_CASE, {"case_id": case_id, "account_id": identity.account_id})
        if not row:
            return error_response(404, "not_found", f"case {case_id} not found", request_id)
        current = row_to_case(row)

        track = str(body.get("track") or current["track"])
        if track not in TRACKS:
            return error_response(400, "invalid_track", "track must be pp1684, eaeu46 or eaeu78", request_id)
        if track != current["track"] and track_is_locked(current["currentStage"]):
            return error_response(409, "track_locked", "track is fixed after qualification", request_id)

        kind = str(body.get("kind") or current["kind"])
        if kind not in KINDS:
            return error_response(400, "invalid_kind", "kind must be device or drug", request_id)

        risk = str(body.get("riskClass") or current["riskClass"])
        if risk not in RISK_CLASSES:
            return error_response(400, "invalid_risk", "riskClass must be 1, 2a, 2b or 3", request_id)

        stage = str(body.get("currentStage") or current["currentStage"])
        if stage not in STAGE_ORDER:
            return error_response(400, "invalid_stage", "unknown currentStage", request_id)

        mandate_complete = bool(body["mandateComplete"]) if "mandateComplete" in body else current["mandateComplete"]
        models_locked = bool(body["modelsLocked"]) if "modelsLocked" in body else current["modelsLocked"]
        if stage_index(stage) >= stage_index("filing") and filing_blocked(mandate_complete, models_locked):
            return error_response(
                409, "filing_blocked", "filing requires mandateComplete and modelsLocked", request_id
            )

        next_actor = str(body.get("nextActor") or current["nextActor"])
        if next_actor not in ACTORS:
            return error_response(400, "invalid_actor", "nextActor must be hq, ru, lab or gov", request_id)

        product = current["product"] if body.get("product") is None else as_l10n(body.get("product"))
        manufacturer = (
            current["manufacturer"] if body.get("manufacturer") is None else as_l10n(body.get("manufacturer"))
        )
        waiting = current["waitingFor"] if "waitingFor" not in body else as_l10n(body.get("waitingFor"))
        cycle = body.get("cycleMonths") or current["cycleMonths"]
        due = int(body["dueWorkingDays"]) if "dueWorkingDays" in body else current["dueWorkingDays"]

        execute(
            UPDATE_CASE,
            {
                "case_id": case_id,
                "account_id": identity.account_id,
                "product": as_json(product),
                "manufacturer": as_json(manufacturer),
                "kind": kind,
                "track": track,
                "risk_class": risk,
                "current_stage": stage,
                "next_actor": next_actor,
                "waiting_for": as_json(waiting),
                "due_working_days": due,
                "cycle_months": as_json(cycle),
                "mandate_complete": mandate_complete,
                "models_locked": models_locked,
            },
        )
        updated = query_one(SELECT_CASE, {"case_id": case_id, "account_id": identity.account_id})
        log_structured(request_id, "info", ROUTE, "updated", case_id=case_id)
        return json_response(200, {"data": row_to_case(updated)}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
