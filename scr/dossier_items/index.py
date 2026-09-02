"""Cloud Function: dossier_items — list, presigned upload-url, confirm-upload.

Dossier files of a case. Intake documents that arrive before a case exists live
in organization_items instead.
"""

import os

import boto3

from common_log import get_request_id, json_response, log_structured
from edge_domain import ITEM_TYPES, as_l10n, new_id, row_to_item
from edge_http import (
    error_response,
    get_http_method,
    get_path,
    get_path_params,
    parse_body,
    resolve_identity,
)
from edge_pg import as_json, execute, query, query_one

ROUTE_LIST = "GET /cases/{id}/items"
ROUTE_UPLOAD = "POST /cases/{id}/items/upload-url"
ROUTE_CONFIRM = "POST /cases/{id}/items/{itemId}/confirm-upload"

BUCKET = os.getenv("DOSSIER_BUCKET") or "pharma-dossier"
S3_ENDPOINT = os.getenv("S3_ENDPOINT") or "https://storage.yandexcloud.net"
PRESIGN_TTL = 3600

SELECT_CASE = "SELECT case_id FROM cases WHERE case_id = %(case_id)s AND account_id = %(account_id)s"

SELECT_ITEMS = """
SELECT * FROM case_items
WHERE case_id = %(case_id)s AND account_id = %(account_id)s
ORDER BY created_at
"""

SELECT_ITEM = "SELECT * FROM case_items WHERE item_id = %(item_id)s AND account_id = %(account_id)s"

INSERT_ITEM = """
INSERT INTO case_items
(item_id, account_id, case_id, item_type, title, file_name, object_key, status)
VALUES
(%(item_id)s, %(account_id)s, %(case_id)s, %(item_type)s, %(title)s,
 %(file_name)s, %(object_key)s, 'pending_upload')
"""

CONFIRM_ITEM = """
UPDATE case_items SET status = 'confirmed', updated_at = now()
WHERE item_id = %(item_id)s AND account_id = %(account_id)s
"""


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("YC_REGION") or "ru-central1",
    )


def _sub_route(event) -> str:
    path = get_path(event).rstrip("/")
    if path.endswith("/upload-url"):
        return "upload-url"
    if path.endswith("/confirm-upload"):
        return "confirm-upload"
    return "items"


def _list_items(case_id, identity, request_id):
    rows = query(SELECT_ITEMS, {"case_id": case_id, "account_id": identity.account_id})
    return json_response(200, {"data": [row_to_item(row) for row in rows]}, request_id)


def _upload_url(event, case_id, identity, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    item_type = str(body.get("itemType") or "other")
    if item_type not in ITEM_TYPES:
        return error_response(400, "invalid_item_type", "unknown itemType", request_id)

    file_name = str(body.get("fileName") or "file.bin")
    content_type = str(body.get("contentType") or "application/octet-stream")
    item_id = new_id("it")
    object_key = f"cases/{case_id}/items/{item_id}/{file_name}"

    execute(
        INSERT_ITEM,
        {
            "item_id": item_id,
            "account_id": identity.account_id,
            "case_id": case_id,
            "item_type": item_type,
            "title": as_json(as_l10n(body.get("title") or file_name)),
            "file_name": file_name,
            "object_key": object_key,
        },
    )
    url = _s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": object_key, "ContentType": content_type},
        ExpiresIn=PRESIGN_TTL,
        HttpMethod="PUT",
    )
    log_structured(request_id, "info", ROUTE_UPLOAD, "presign", item_id=item_id, object_key=object_key)
    return json_response(
        200,
        {"data": {"uploadUrl": url, "itemId": item_id, "objectKey": object_key, "expiresIn": PRESIGN_TTL}},
        request_id,
    )


def _confirm(case_id, item_id, identity, request_id):
    row = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    if not row or row.get("case_id") != case_id:
        return error_response(404, "not_found", f"item {item_id} not found", request_id)
    execute(CONFIRM_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    confirmed = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    log_structured(request_id, "info", ROUTE_CONFIRM, "confirmed", item_id=item_id)
    return json_response(200, {"data": row_to_item(confirmed)}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    sub = _sub_route(event)
    route = ROUTE_UPLOAD if sub == "upload-url" else (ROUTE_CONFIRM if sub == "confirm-upload" else ROUTE_LIST)
    log_structured(request_id, "info", route, "handler entry", method=method)

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    item_id = params.get("itemId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        if not query_one(SELECT_CASE, {"case_id": case_id, "account_id": identity.account_id}):
            return error_response(404, "not_found", f"case {case_id} not found", request_id)

        if method == "GET" and sub == "items":
            return _list_items(case_id, identity, request_id)
        if method == "POST" and sub == "upload-url":
            return _upload_url(event, case_id, identity, request_id)
        if method == "POST" and sub == "confirm-upload":
            if not item_id:
                return error_response(400, "missing_item_id", "path parameter itemId is required", request_id)
            return _confirm(case_id, item_id, identity, request_id)
        return error_response(405, "method_not_allowed", f"{method} {sub} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
