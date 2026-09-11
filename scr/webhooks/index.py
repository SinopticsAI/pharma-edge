"""Cloud Function: webhooks — extraction results from Mastra or Plane.

Service-to-service only: X-API-Key, no Keycloak token, never a browser.

An intake run carries a technical case id of the form intake-<session or org>,
so the same webhook contract serves both dossier items and intake documents
without Plane needing to know the difference.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import ITEM_TYPES
from edge_http import error_response, get_http_method, get_path, get_path_params, parse_body, require_api_key
from psycopg.errors import UniqueViolation

from edge_intake import (
    infer_org_item_type,
    merge_org_draft,
    merge_product_draft,
    product_completeness,
    registration_number_of,
)
from edge_pg import as_json, execute, find_org_by_uscc, query_one

SELECT_ORG_ITEM = "SELECT * FROM organization_items WHERE item_id = %(item_id)s"
SELECT_CASE_ITEM = "SELECT * FROM case_items WHERE item_id = %(item_id)s"

UPDATE_ORG_ITEM = """
UPDATE organization_items
SET parced_data = %(parced_data)s, status = %(status)s, item_type = %(item_type)s, updated_at = now()
WHERE item_id = %(item_id)s
"""

FILL_SLOT = """
UPDATE organization_slots
SET status = 'filled', document_id = %(item_id)s, updated_at = now()
WHERE organization_id = %(organization_id)s AND slot_key = %(slot_key)s
"""

UPDATE_CASE_ITEM = """
UPDATE case_items
SET parced_data = %(parced_data)s, status = %(status)s, updated_at = now()
WHERE item_id = %(item_id)s
"""

SELECT_ORG = "SELECT * FROM organizations WHERE organization_id = %(organization_id)s"
SELECT_PRODUCT = "SELECT * FROM products WHERE product_id = %(product_id)s"

UPDATE_ORG_DRAFT = """
UPDATE organizations
SET draft = %(draft)s,
    status = CASE WHEN status = 'collecting' THEN 'draft' ELSE status END,
    updated_at = now()
WHERE organization_id = %(organization_id)s
"""

UPDATE_PRODUCT_DRAFT = """
UPDATE products
SET draft = %(draft)s, completeness = %(completeness)s,
    status = CASE WHEN status = 'collecting' THEN 'draft' ELSE status END,
    updated_at = now()
WHERE product_id = %(product_id)s
"""

MARK_PROCESSED = """
INSERT INTO processed_messages (consumer, message_id)
VALUES (%(consumer)s, %(message_id)s)
ON CONFLICT (consumer, message_id) DO NOTHING
"""

SEEN = """
SELECT 1 FROM processed_messages
WHERE consumer = %(consumer)s AND message_id = %(message_id)s
"""


def _already_processed(consumer: str, message_id: str) -> bool:
    if not message_id:
        return False
    if query_one(SEEN, {"consumer": consumer, "message_id": message_id}):
        return True
    execute(MARK_PROCESSED, {"consumer": consumer, "message_id": message_id})
    return False


def _source_label(row: dict) -> str:
    """What the draft card shows next to a field, e.g. 'business-license'."""
    item_type = str(row.get("item_type") or "document")
    file_name = str(row.get("file_name") or "")
    return f"{item_type} · {file_name}" if file_name else item_type


def _duplicate_uscc_item(
    item_id,
    org_item,
    parced,
    status,
    item_type,
    previous_type,
    other,
    uscc,
    request_id,
):
    """Keep the OCR result, do not copy the number onto this empty card."""
    flagged = dict(parced) if isinstance(parced, dict) else {}
    flagged["duplicate_uscc"] = {
        "organizationId": other["organization_id"],
        "registrationNumber": uscc,
    }
    execute(
        UPDATE_ORG_ITEM,
        {
            "item_id": item_id,
            "parced_data": as_json(flagged),
            "status": status,
            "item_type": item_type or previous_type,
        },
    )
    log_structured(
        request_id,
        "info",
        "webhook item_update",
        "duplicate uscc, draft not merged",
        item_id=item_id,
        existing_organization_id=other["organization_id"],
    )
    return json_response(
        200,
        {
            "data": {
                "itemId": item_id,
                "level": org_item.get("level"),
                "duplicateUscc": True,
                "existingOrganizationId": other["organization_id"],
            }
        },
        request_id,
    )


def _item_update(event, item_id, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    if _already_processed("webhook_item_update", str(body.get("messageId") or item_id)):
        return json_response(200, {"data": {"itemId": item_id, "duplicate": True}}, request_id)

    parced = body.get("parcedData") or body.get("parced_data") or {}
    status = str(body.get("status") or "parsed")

    org_item = query_one(SELECT_ORG_ITEM, {"item_id": item_id})
    if org_item:
        requested_type = str(body.get("itemType") or body.get("item_type") or "").strip()
        previous_type = str(org_item.get("item_type") or "")
        raw_type = requested_type if requested_type in ITEM_TYPES else previous_type
        item_type = infer_org_item_type(raw_type, str(org_item.get("file_name") or ""), parced)
        execute(
            UPDATE_ORG_ITEM,
            {
                "item_id": item_id,
                "parced_data": as_json(parced),
                "status": status,
                "item_type": item_type or previous_type,
            },
        )
        if item_type and item_type != "other":
            execute(
                FILL_SLOT,
                {
                    "organization_id": org_item["organization_id"],
                    "slot_key": item_type,
                    "item_id": item_id,
                },
            )
        source = _source_label({**org_item, "item_type": item_type or previous_type})
        if org_item.get("level") == "product" and org_item.get("product_id"):
            product = query_one(SELECT_PRODUCT, {"product_id": org_item["product_id"]})
            if product:
                draft = merge_product_draft(product.get("draft") or {}, parced, source)
                execute(
                    UPDATE_PRODUCT_DRAFT,
                    {
                        "product_id": product["product_id"],
                        "draft": as_json(draft),
                        "completeness": product_completeness(draft),
                    },
                )
        else:
            org = query_one(SELECT_ORG, {"organization_id": org_item["organization_id"]})
            if org:
                draft = merge_org_draft(org.get("draft") or {}, parced, source)
                uscc = registration_number_of(draft, org.get("profile") or {})
                other = (
                    find_org_by_uscc(str(org["account_id"]), uscc, str(org["organization_id"]))
                    if uscc
                    else None
                )
                if other:
                    return _duplicate_uscc_item(
                        item_id,
                        org_item,
                        parced,
                        status,
                        item_type,
                        previous_type,
                        other,
                        uscc,
                        request_id,
                    )
                try:
                    execute(
                        UPDATE_ORG_DRAFT,
                        {"organization_id": org["organization_id"], "draft": as_json(draft)},
                    )
                except UniqueViolation:
                    raced = find_org_by_uscc(
                        str(org["account_id"]), uscc, str(org["organization_id"])
                    )
                    if raced:
                        return _duplicate_uscc_item(
                            item_id,
                            org_item,
                            parced,
                            status,
                            item_type,
                            previous_type,
                            raced,
                            uscc,
                            request_id,
                        )
                    raise
        log_structured(request_id, "info", "webhook item_update", "intake item stored", item_id=item_id)
        return json_response(200, {"data": {"itemId": item_id, "level": org_item.get("level")}}, request_id)

    if query_one(SELECT_CASE_ITEM, {"item_id": item_id}):
        execute(UPDATE_CASE_ITEM, {"item_id": item_id, "parced_data": as_json(parced), "status": status})
        log_structured(request_id, "info", "webhook item_update", "dossier item stored", item_id=item_id)
        return json_response(200, {"data": {"itemId": item_id}}, request_id)

    return error_response(404, "not_found", f"item {item_id} not found", request_id)


def _completed(event, case_id, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError):
        body = {}
    log_structured(
        request_id,
        "info",
        "webhook completed",
        "pipeline finished",
        case_id=case_id,
        status=body.get("status"),
    )
    return json_response(200, {"data": {"caseId": case_id, "acknowledged": True}}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    path = get_path(event).rstrip("/")
    params = get_path_params(event)
    route = f"{method} {path}"
    log_structured(request_id, "info", route, "handler entry")

    denied = require_api_key(event, request_id, route)
    if denied:
        return denied

    if method != "POST":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    try:
        if path.endswith("/completed"):
            return _completed(event, params.get("id") or "", request_id)
        item_id = params.get("itemId") or ""
        if not item_id:
            return error_response(400, "missing_item_id", "path parameter itemId is required", request_id)
        return _item_update(event, item_id, request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
