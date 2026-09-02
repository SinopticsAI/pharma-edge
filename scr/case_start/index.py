"""Cloud Function: case_start — POST /cases/{id}/actions/start.

Hands the confirmed dossier files to Plane. Edge never calls YaWL directly:
the workflow id is Plane's business, and the cutover is one environment
variable.
"""

import os

from common_log import get_request_id, json_response, log_structured
from edge_http import error_response, get_http_method, get_path_params, parse_body, resolve_identity
from edge_pg import execute, query, query_one
import edge_plane

ROUTE = "POST /cases/{id}/actions/start"
BUCKET = os.getenv("DOSSIER_BUCKET") or "pharma-dossier"

SELECT_CASE = "SELECT * FROM cases WHERE case_id = %(case_id)s AND account_id = %(account_id)s"

SELECT_ITEMS = """
SELECT * FROM case_items
WHERE case_id = %(case_id)s AND account_id = %(account_id)s
  AND status = 'confirmed' AND parced_data IS NULL
ORDER BY created_at
"""

MARK_PROCESSING = """
UPDATE case_items SET status = 'processing', updated_at = now()
WHERE item_id = ANY(%(item_ids)s)
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)

    if method != "POST":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

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

        if not edge_plane.is_configured():
            return error_response(
                503,
                "plane_not_configured",
                "PHARMA_PLANE_BASE_URL and PHARMA_PLANE_API_KEY must be set",
                request_id,
            )

        try:
            body = parse_body(event)
        except (ValueError, TypeError):
            body = {}

        workflow = str(body.get("workflow") or edge_plane.WORKFLOW_DOSSIER)
        rows = query(SELECT_ITEMS, {"case_id": case_id, "account_id": identity.account_id})
        items = [
            edge_plane.item_payload(
                str(row["item_id"]), str(row["item_type"]), str(row["object_key"]), BUCKET
            )
            for row in rows
        ]
        if not items and workflow == edge_plane.WORKFLOW_DOSSIER:
            return error_response(409, "nothing_to_process", "no confirmed unparsed items", request_id)

        try:
            result = edge_plane.start_case(
                case_id=case_id,
                workflow=workflow,
                items=items,
                settings={
                    "product_kind": case_row.get("kind"),
                    "track": case_row.get("track"),
                    "risk_class": case_row.get("risk_class"),
                    "language": str(body.get("language") or "ru"),
                },
                title=str(case_row.get("code") or case_id),
                request_id=request_id,
            )
        except edge_plane.PlaneError as exc:
            log_structured(request_id, "error", ROUTE, "plane rejected", error=str(exc))
            status = 409 if exc.status == 409 else 502
            return error_response(status, "plane_error", exc.message, request_id)

        if items:
            execute(MARK_PROCESSING, {"item_ids": [str(row["item_id"]) for row in rows]})

        log_structured(request_id, "info", ROUTE, "started", case_id=case_id, items=len(items))
        return json_response(202, {"data": result}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
