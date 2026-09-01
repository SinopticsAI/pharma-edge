"""Cloud Function: dossier_items — list, presigned upload-url, confirm-upload."""

import os

import boto3

from common_log import get_request_id, json_response, log_structured
from edge_domain import ITEM_TYPES, as_l10n, dumps_json, new_id, row_to_item
from edge_http import (
    error_response,
    get_http_method,
    get_path,
    get_path_params,
    parse_body,
    require_api_key,
)
from edge_ydb import execute, get_ydb_pool

ROUTE_LIST = "GET /cases/{id}/items"
ROUTE_UPLOAD = "POST /cases/{id}/items/upload-url"
ROUTE_CONFIRM = "POST /cases/{id}/items/{itemId}/confirm-upload"

BUCKET = os.getenv("DOSSIER_BUCKET") or "pharma-dossier"
S3_ENDPOINT = os.getenv("S3_ENDPOINT") or "https://storage.yandexcloud.net"
PRESIGN_TTL = 3600

SELECT_CASE = """
DECLARE $case_id AS Utf8;
SELECT case_id FROM cases WHERE case_id = $case_id;
"""

SELECT_ITEMS = """
DECLARE $case_id AS Utf8;
SELECT * FROM case_items VIEW idx_case_items_case WHERE case_id = $case_id;
"""

SELECT_ITEM = """
DECLARE $item_id AS Utf8;
SELECT * FROM case_items WHERE item_id = $item_id;
"""

UPSERT_ITEM = """
DECLARE $item_id AS Utf8;
DECLARE $case_id AS Utf8;
DECLARE $item_type AS Utf8;
DECLARE $title_json AS Utf8;
DECLARE $file_name AS Utf8;
DECLARE $object_key AS Utf8;
DECLARE $status AS Utf8;
DECLARE $parced_data AS Utf8;
UPSERT INTO case_items
(item_id, case_id, item_type, title_json, file_name, object_key, status, parced_data, created_at, updated_at)
VALUES
($item_id, $case_id, $item_type, $title_json, $file_name, $object_key, $status, $parced_data,
 CurrentUtcTimestamp(), CurrentUtcTimestamp());
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
    path = get_path(event)
    if path.endswith("/upload-url"):
        return "upload-url"
    if path.endswith("/confirm-upload"):
        return "confirm-upload"
    return "items"


def _require_case(pool, case_id: str, request_id: str):
    rows = execute(pool, SELECT_CASE, {"$case_id": case_id})
    if not rows:
        return error_response(404, "not_found", f"case {case_id} not found", request_id)
    return None


def _list_items(pool, case_id: str, request_id: str):
    rows = execute(pool, SELECT_ITEMS, {"$case_id": case_id})
    return json_response(200, {"data": [row_to_item(row) for row in rows]}, request_id)


def _upload_url(event, pool, case_id: str, request_id: str):
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
    title = as_l10n(body.get("title") or file_name)
    execute(
        pool,
        UPSERT_ITEM,
        {
            "$item_id": item_id,
            "$case_id": case_id,
            "$item_type": item_type,
            "$title_json": dumps_json(title),
            "$file_name": file_name,
            "$object_key": object_key,
            "$status": "pending_upload",
            "$parced_data": "",
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
        {
            "data": {
                "uploadUrl": url,
                "itemId": item_id,
                "objectKey": object_key,
                "expiresIn": PRESIGN_TTL,
            }
        },
        request_id,
    )


def _confirm(pool, case_id: str, item_id: str, request_id: str):
    rows = execute(pool, SELECT_ITEM, {"$item_id": item_id})
    if not rows or rows[0].get("case_id") != case_id:
        return error_response(404, "not_found", f"item {item_id} not found", request_id)
    row = rows[0]
    execute(
        pool,
        """
        DECLARE $item_id AS Utf8;
        UPDATE case_items SET status = "confirmed", updated_at = CurrentUtcTimestamp()
        WHERE item_id = $item_id;
        """,
        {"$item_id": item_id},
    )
    confirmed = execute(pool, SELECT_ITEM, {"$item_id": item_id})
    log_structured(request_id, "info", ROUTE_CONFIRM, "confirmed", item_id=item_id)
    return json_response(200, {"data": row_to_item(confirmed[0])}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    sub = _sub_route(event)
    route = ROUTE_UPLOAD if sub == "upload-url" else (ROUTE_CONFIRM if sub == "confirm-upload" else ROUTE_LIST)
    log_structured(request_id, "info", route, "handler entry", method=method)
    denied = require_api_key(event, request_id, route)
    if denied:
        return denied

    params = get_path_params(event)
    case_id = params.get("id") or params.get("caseId")
    item_id = params.get("itemId")
    if not case_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        pool = get_ydb_pool()
        missing = _require_case(pool, case_id, request_id)
        if missing:
            return missing
        if method == "GET" and sub == "items":
            return _list_items(pool, case_id, request_id)
        if method == "POST" and sub == "upload-url":
            return _upload_url(event, pool, case_id, request_id)
        if method == "POST" and sub == "confirm-upload":
            if not item_id:
                return error_response(400, "missing_item_id", "path parameter itemId is required", request_id)
            return _confirm(pool, case_id, item_id, request_id)
        return error_response(405, "method_not_allowed", f"{method} {sub} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
