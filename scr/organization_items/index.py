"""Cloud Function: organization_items — intake documents before any case.

Documents live at two levels. A company document is reused by every product of
that company and is never uploaded twice; a product document that turns out to
belong to the company can be promoted, and then it reaches the other products
too.

The browser uploads to Object Storage itself with a presigned URL. Only
metadata passes through here, and files never travel through the agent.
"""

import os
from urllib.parse import quote

import boto3

from common_log import get_request_id, json_response, log_structured
from edge_domain import ITEM_TYPES, ORG_ITEM_TYPES, as_l10n, new_id, row_to_org_item
from edge_http import (
    error_response,
    get_http_method,
    get_path,
    get_path_params,
    parse_body,
    resolve_identity,
)
from edge_pg import as_json, execute, query, query_one

BUCKET = os.getenv("DOSSIER_BUCKET") or "pharma-dossier"
S3_ENDPOINT = os.getenv("S3_ENDPOINT") or "https://storage.yandexcloud.net"
PRESIGN_TTL = 3600

SELECT_ORG = """
SELECT organization_id FROM organizations
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
"""

SELECT_ITEMS = """
SELECT * FROM organization_items
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
ORDER BY created_at
"""

SELECT_ITEM = """
SELECT * FROM organization_items
WHERE item_id = %(item_id)s AND account_id = %(account_id)s
"""

INSERT_ITEM = """
INSERT INTO organization_items
(item_id, account_id, organization_id, product_id, level, item_type, title,
 file_name, object_key, status)
VALUES
(%(item_id)s, %(account_id)s, %(organization_id)s, %(product_id)s, %(level)s,
 %(item_type)s, %(title)s, %(file_name)s, %(object_key)s, 'pending_upload')
"""

CONFIRM_ITEM = """
UPDATE organization_items
SET status = 'uploaded', updated_at = now()
WHERE item_id = %(item_id)s AND account_id = %(account_id)s
"""

PROMOTE_ITEM = """
UPDATE organization_items
SET level = 'company', promoted_from = product_id, promoted_at = now(),
    product_id = NULL, updated_at = now()
WHERE item_id = %(item_id)s AND account_id = %(account_id)s
"""

FILL_SLOT = """
UPDATE organization_slots
SET status = 'filled', document_id = %(item_id)s, updated_at = now()
WHERE organization_id = %(organization_id)s AND slot_key = %(slot_key)s
"""

INSERT_AUDIT = """
INSERT INTO audit_entries
(entry_id, account_id, subject_type, subject_id, action, actor, actor_role, detail)
VALUES
(%(entry_id)s, %(account_id)s, 'organization', %(subject_id)s, %(action)s,
 %(actor)s, %(actor_role)s, %(detail)s)
"""


def _audit(identity, organization_id, action, detail=None):
    execute(
        INSERT_AUDIT,
        {
            "entry_id": new_id("aud"),
            "account_id": identity.account_id,
            "subject_id": organization_id,
            "action": action,
            "actor": identity.display_name or identity.subject,
            "actor_role": identity.role,
            "detail": as_json(detail or {}),
        },
    )


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
    if path.endswith("/download-url"):
        return "download-url"
    if path.endswith("/promote"):
        return "promote"
    return "items"


def _list(organization_id, identity, request_id):
    rows = query(SELECT_ITEMS, {"organization_id": organization_id, "account_id": identity.account_id})
    items = [row_to_org_item(row) for row in rows]
    return json_response(
        200,
        {
            "data": items,
            # What a product dialog inherits and must not ask for again.
            "companyLevel": [item for item in items if item["level"] == "company"],
        },
        request_id,
    )


def _upload_url(event, organization_id, identity, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    item_type = str(body.get("itemType") or "other")
    if item_type not in ITEM_TYPES:
        return error_response(400, "invalid_item_type", "unknown itemType", request_id)

    product_id = str(body.get("productId") or "") or None
    level = "product" if product_id else "company"
    if level == "company" and item_type not in ORG_ITEM_TYPES:
        # A product-only document without a product is a mistake worth catching.
        return error_response(
            400,
            "invalid_level",
            f"itemType {item_type} needs productId because it is not a company document",
            request_id,
        )

    file_name = str(body.get("fileName") or "file.bin")
    content_type = str(body.get("contentType") or "application/octet-stream")
    item_id = new_id("it")
    object_key = f"orgs/{organization_id}/items/{item_id}/{file_name}"

    execute(
        INSERT_ITEM,
        {
            "item_id": item_id,
            "account_id": identity.account_id,
            "organization_id": organization_id,
            "product_id": product_id,
            "level": level,
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
    log_structured(request_id, "info", "POST /organizations/{id}/items/upload-url", "presign", item_id=item_id)
    return json_response(
        200,
        {"data": {"uploadUrl": url, "itemId": item_id, "objectKey": object_key, "expiresIn": PRESIGN_TTL}},
        request_id,
    )


def _content_disposition(file_name: str) -> str:
    """Names come from Chinese scans, so the ASCII form is only a fallback."""
    ascii_name = file_name.encode("ascii", "replace").decode("ascii").replace('"', "")
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name, safe='')}"


def _download_url(organization_id, item_id, identity, request_id):
    """Presigned GET so the browser can open the scan the agent read."""
    row = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    if not row or row.get("organization_id") != organization_id:
        return error_response(404, "not_found", f"item {item_id} not found", request_id)

    object_key = str(row.get("object_key") or "")
    if not object_key or row.get("status") == "pending_upload":
        # Nothing reached the bucket yet: a link would only 404 in a new tab.
        return error_response(409, "not_uploaded", f"item {item_id} has no file yet", request_id)

    file_name = str(row.get("file_name") or "document")
    url = _s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET,
            "Key": object_key,
            "ResponseContentDisposition": _content_disposition(file_name),
        },
        ExpiresIn=PRESIGN_TTL,
        HttpMethod="GET",
    )
    log_structured(
        request_id,
        "info",
        "POST /organizations/{id}/items/{itemId}/download-url",
        "presign get",
        item_id=item_id,
    )
    return json_response(
        200,
        {"data": {"url": url, "fileName": file_name, "expiresIn": PRESIGN_TTL}},
        request_id,
    )


def _confirm(event, organization_id, item_id, identity, request_id):
    row = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    if not row or row.get("organization_id") != organization_id:
        return error_response(404, "not_found", f"item {item_id} not found", request_id)

    execute(CONFIRM_ITEM, {"item_id": item_id, "account_id": identity.account_id})

    # A confirmed document closes its slot when the type maps to one.
    slot_key = str(row.get("item_type") or "")
    execute(FILL_SLOT, {"organization_id": organization_id, "slot_key": slot_key, "item_id": item_id})

    # Intake OCR is Mastra POST /extract, kicked by the cabinet when it sees
    # uploaded. Plane stays on dossier cases; starting it here left items stuck
    # in uploaded when the webhook was deduped.
    _audit(identity, organization_id, "document.uploaded", {"itemId": item_id, "itemType": row.get("item_type")})
    confirmed = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    return json_response(200, {"data": row_to_org_item(confirmed), "extractionStarted": False}, request_id)


def _promote(organization_id, item_id, identity, request_id):
    """MM-E4: a document first seen in a product dialog joins the company."""
    row = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    if not row or row.get("organization_id") != organization_id:
        return error_response(404, "not_found", f"item {item_id} not found", request_id)
    if row.get("level") == "company":
        return json_response(200, {"data": row_to_org_item(row), "promoted": False}, request_id)

    execute(PROMOTE_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    execute(
        FILL_SLOT,
        {"organization_id": organization_id, "slot_key": str(row.get("item_type") or ""), "item_id": item_id},
    )
    _audit(
        identity,
        organization_id,
        "document.promoted",
        {"itemId": item_id, "fromProduct": row.get("product_id")},
    )
    promoted = query_one(SELECT_ITEM, {"item_id": item_id, "account_id": identity.account_id})
    log_structured(request_id, "info", "POST .../promote", "promoted", item_id=item_id)
    return json_response(200, {"data": row_to_org_item(promoted), "promoted": True}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    params = get_path_params(event)
    organization_id = params.get("id") or params.get("organizationId") or ""
    item_id = params.get("itemId") or ""
    sub = _sub_route(event)
    route = f"{method} /organizations/{{id}}/items/{sub}"
    log_structured(request_id, "info", route, "handler entry", method=method)

    if not organization_id:
        return error_response(400, "missing_id", "path parameter id is required", request_id)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        if not query_one(SELECT_ORG, {"organization_id": organization_id, "account_id": identity.account_id}):
            return error_response(404, "not_found", f"organization {organization_id} not found", request_id)

        if method == "GET" and sub == "items":
            return _list(organization_id, identity, request_id)
        if method == "POST" and sub == "upload-url":
            return _upload_url(event, organization_id, identity, request_id)
        if method == "POST" and sub == "confirm-upload":
            if not item_id:
                return error_response(400, "missing_item_id", "path parameter itemId is required", request_id)
            return _confirm(event, organization_id, item_id, identity, request_id)
        if method == "POST" and sub == "download-url":
            if not item_id:
                return error_response(400, "missing_item_id", "path parameter itemId is required", request_id)
            return _download_url(organization_id, item_id, identity, request_id)
        if method == "POST" and sub == "promote":
            if not item_id:
                return error_response(400, "missing_item_id", "path parameter itemId is required", request_id)
            return _promote(organization_id, item_id, identity, request_id)
        return error_response(405, "method_not_allowed", f"{method} {sub} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
