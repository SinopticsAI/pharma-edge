"""Cloud Function: status_ingest — GET/POST /cases/{id}/statuses."""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    STAGE_ORDER,
    as_l10n,
    as_translatable,
    can_advance,
    dumps_json,
    filing_blocked,
    new_id,
    row_to_case,
    row_to_status,
    stage_index,
)
from edge_http import (
    error_response,
    get_http_method,
    get_path_params,
    parse_body,
    require_api_key,
)
from edge_ydb import execute, get_ydb_pool

ROUTE_GET = "GET /cases/{id}/statuses"
ROUTE_POST = "POST /cases/{id}/statuses"

SELECT_CASE = """
DECLARE $case_id AS Utf8;
SELECT * FROM cases WHERE case_id = $case_id;
"""

SELECT_STATUSES = """
DECLARE $case_id AS Utf8;
SELECT * FROM status_entries VIEW idx_status_entries_case WHERE case_id = $case_id;
"""

INSERT_STATUS = """
DECLARE $status_id AS Utf8;
DECLARE $case_id AS Utf8;
DECLARE $stage AS Utf8;
DECLARE $text_json AS Utf8;
DECLARE $artifact AS Utf8;
DECLARE $entered_by AS Utf8;
UPSERT INTO status_entries
(status_id, case_id, stage, text_json, artifact, entered_by, entered_at)
VALUES
($status_id, $case_id, $stage, $text_json, $artifact, $entered_by, CurrentUtcTimestamp());
"""

UPDATE_CASE_STAGE = """
DECLARE $case_id AS Utf8;
DECLARE $current_stage AS Utf8;
DECLARE $next_actor AS Utf8;
DECLARE $waiting_for_json AS Utf8;
UPDATE cases SET
    current_stage = $current_stage,
    next_actor = $next_actor,
    waiting_for_json = $waiting_for_json,
    updated_at = CurrentUtcTimestamp()
WHERE case_id = $case_id;
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    route = ROUTE_POST if method == "POST" else ROUTE_GET
    log_structured(request_id, "info", route, "handler entry", method=method)
    denied = require_api_key(event, request_id, route)
    if denied:
        return denied

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        pool = get_ydb_pool()
        case_rows = execute(pool, SELECT_CASE, {"$case_id": case_id})
        if not case_rows:
            return error_response(404, "not_found", f"case {case_id} not found", request_id)

        if method == "GET":
            rows = execute(pool, SELECT_STATUSES, {"$case_id": case_id})
            items = [row_to_status(row) for row in rows]
            items.sort(key=lambda item: item.get("enteredAt") or "", reverse=True)
            return json_response(200, {"data": items}, request_id)

        if method != "POST":
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        try:
            body = parse_body(event)
            text = as_translatable(body.get("text"))
        except (ValueError, TypeError) as exc:
            return error_response(400, "invalid_json", str(exc), request_id)

        artifact = str(body.get("artifact") or "").strip()
        if not artifact:
            return error_response(400, "artifact_required", "status artifact is required", request_id)

        stage = str(body.get("stage") or "")
        if stage not in STAGE_ORDER:
            return error_response(400, "invalid_stage", "unknown stage", request_id)

        current = row_to_case(case_rows[0])
        if stage_index(stage) >= stage_index("filing") and filing_blocked(
            current["mandateComplete"], current["modelsLocked"]
        ):
            return error_response(
                409,
                "filing_blocked",
                "filing requires mandateComplete and modelsLocked",
                request_id,
            )

        status_id = new_id("st")
        execute(
            pool,
            INSERT_STATUS,
            {
                "$status_id": status_id,
                "$case_id": case_id,
                "$stage": stage,
                "$text_json": dumps_json(text),
                "$artifact": artifact,
                "$entered_by": str(body.get("enteredBy") or ""),
            },
        )

        if can_advance(current["currentStage"], stage):
            next_actor = "gov" if stage == "expertise" else "ru"
            waiting = as_l10n(text.get("ru") or "")
            execute(
                pool,
                UPDATE_CASE_STAGE,
                {
                    "$case_id": case_id,
                    "$current_stage": stage,
                    "$next_actor": next_actor,
                    "$waiting_for_json": dumps_json(waiting),
                },
            )

        created = execute(
            pool,
            "DECLARE $status_id AS Utf8; SELECT * FROM status_entries WHERE status_id = $status_id;",
            {"$status_id": status_id},
        )
        log_structured(request_id, "info", ROUTE_POST, "ingested", status_id=status_id, case_id=case_id)
        return json_response(201, {"data": row_to_status(created[0])}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
