"""Cloud Function: case_get — GET /cases/{id}.

Returns the card, the mandate and the node map. Nodes past filing come back
with status 'later' rather than being hidden: the horizon is the point.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import field_mask, row_to_case, row_to_mandate, row_to_node
from edge_http import error_response, get_contour, get_http_method, get_path_params, resolve_identity
from edge_pg import query, query_one

ROUTE = "GET /cases/{id}"

SELECT_CASE = "SELECT * FROM cases WHERE case_id = %(case_id)s AND account_id = %(account_id)s"
SELECT_MANDATE = "SELECT * FROM mandates WHERE case_id = %(case_id)s"
SELECT_NODES = "SELECT * FROM node_map_items WHERE case_id = %(case_id)s ORDER BY position"


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)

    if method != "GET":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        row = query_one(SELECT_CASE, {"case_id": case_id, "account_id": identity.account_id})
        if not row:
            return error_response(404, "not_found", f"case {case_id} not found", request_id)

        contour = get_contour(event)
        mandate_row = query_one(SELECT_MANDATE, {"case_id": case_id})
        nodes = [row_to_node(item) for item in query(SELECT_NODES, {"case_id": case_id})]

        payload = {
            "case": row_to_case(row),
            "fieldMask": field_mask(contour),
            "nodeMap": nodes,
            # The one next action. The map and the task list must agree.
            "criticalNode": next((node for node in nodes if node["critical"]), None),
        }
        mandate = row_to_mandate(mandate_row, include_credentials=(contour == "ru")) if mandate_row else None
        if mandate is not None:
            payload["mandate"] = mandate

        log_structured(request_id, "info", ROUTE, "ok", case_id=case_id, contour=contour)
        return json_response(200, {"data": payload}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
