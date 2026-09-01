"""Cloud Function: case_get — GET /cases/{id}."""

from common_log import get_request_id, json_response, log_structured
from edge_domain import field_mask, row_to_case, row_to_mandate
from edge_http import error_response, get_contour, get_http_method, get_path_params, require_api_key
from edge_ydb import execute, get_ydb_pool

ROUTE = "GET /cases/{id}"

SELECT_CASE = """
DECLARE $case_id AS Utf8;
SELECT * FROM cases WHERE case_id = $case_id;
"""

SELECT_MANDATE = """
DECLARE $case_id AS Utf8;
SELECT * FROM mandates WHERE case_id = $case_id;
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)
    denied = require_api_key(event, request_id, ROUTE)
    if denied:
        return denied
    if method != "GET":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        pool = get_ydb_pool()
        rows = execute(pool, SELECT_CASE, {"$case_id": case_id})
        if not rows:
            return error_response(404, "not_found", f"case {case_id} not found", request_id)
        contour = get_contour(event)
        mandate_rows = execute(pool, SELECT_MANDATE, {"$case_id": case_id})
        mandate = row_to_mandate(mandate_rows[0], include_credentials=(contour == "ru")) if mandate_rows else None
        payload = {
            "case": row_to_case(rows[0]),
            "fieldMask": field_mask(contour),
        }
        if mandate is not None:
            payload["mandate"] = mandate
        log_structured(request_id, "info", ROUTE, "ok", case_id=case_id, contour=contour)
        return json_response(200, {"data": payload}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
