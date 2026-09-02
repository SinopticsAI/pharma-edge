"""Cloud Function: status_ingest — GET/POST /cases/{id}/statuses.

Statuses are entered by a human with an artifact attached. That is the system
of record until a government channel offers a stable API, and a status without
an artifact is refused.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    STAGE_ORDER,
    as_l10n,
    can_advance,
    filing_blocked,
    new_id,
    row_to_case,
    row_to_status,
    stage_index,
)
from edge_http import error_response, get_http_method, get_path_params, parse_body, resolve_identity
from edge_pg import as_json, execute, query, query_one

ROUTE_GET = "GET /cases/{id}/statuses"
ROUTE_POST = "POST /cases/{id}/statuses"

SELECT_CASE = "SELECT * FROM cases WHERE case_id = %(case_id)s AND account_id = %(account_id)s"

SELECT_STATUSES = """
SELECT * FROM status_entries
WHERE case_id = %(case_id)s AND account_id = %(account_id)s
ORDER BY entered_at DESC
"""

INSERT_STATUS = """
INSERT INTO status_entries (status_id, account_id, case_id, stage, text, artifact, entered_by)
VALUES (%(status_id)s, %(account_id)s, %(case_id)s, %(stage)s, %(text)s, %(artifact)s, %(entered_by)s)
"""

UPDATE_CASE_STAGE = """
UPDATE cases SET current_stage = %(current_stage)s, next_actor = %(next_actor)s,
                 waiting_for = %(waiting_for)s, updated_at = now()
WHERE case_id = %(case_id)s AND account_id = %(account_id)s
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    route = ROUTE_POST if method == "POST" else ROUTE_GET
    log_structured(request_id, "info", route, "handler entry", method=method)

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        case_row = query_one(SELECT_CASE, {"case_id": case_id, "account_id": identity.account_id})
        if not case_row:
            return error_response(404, "not_found", f"case {case_id} not found", request_id)

        if method == "GET":
            rows = query(SELECT_STATUSES, {"case_id": case_id, "account_id": identity.account_id})
            return json_response(200, {"data": [row_to_status(row) for row in rows]}, request_id)

        if method != "POST":
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        if not identity.can_operate:
            return error_response(403, "forbidden", "only an operator records a status", request_id)

        try:
            body = parse_body(event)
        except (ValueError, TypeError) as exc:
            return error_response(400, "invalid_json", str(exc), request_id)

        text = as_l10n(body.get("text") or "")
        if not text["ru"]:
            return error_response(400, "invalid_body", "text is required", request_id)

        artifact = str(body.get("artifact") or "").strip()
        if not artifact:
            return error_response(400, "artifact_required", "status artifact is required", request_id)

        stage = str(body.get("stage") or "")
        if stage not in STAGE_ORDER:
            return error_response(400, "invalid_stage", "unknown stage", request_id)

        current = row_to_case(case_row)
        if stage_index(stage) >= stage_index("filing") and filing_blocked(
            current["mandateComplete"], current["modelsLocked"]
        ):
            return error_response(
                409, "filing_blocked", "filing requires mandateComplete and modelsLocked", request_id
            )

        status_id = new_id("st")
        execute(
            INSERT_STATUS,
            {
                "status_id": status_id,
                "account_id": identity.account_id,
                "case_id": case_id,
                "stage": stage,
                "text": as_json(text),
                "artifact": artifact,
                "entered_by": str(body.get("enteredBy") or identity.display_name or identity.subject),
            },
        )

        if can_advance(current["currentStage"], stage):
            execute(
                UPDATE_CASE_STAGE,
                {
                    "case_id": case_id,
                    "account_id": identity.account_id,
                    "current_stage": stage,
                    "next_actor": "gov" if stage == "expertise" else "ru",
                    "waiting_for": as_json(text),
                },
            )

        created = query_one(
            "SELECT * FROM status_entries WHERE status_id = %(status_id)s", {"status_id": status_id}
        )
        log_structured(request_id, "info", ROUTE_POST, "ingested", status_id=status_id, case_id=case_id)
        return json_response(201, {"data": row_to_status(created)}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
