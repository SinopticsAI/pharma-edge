"""Cloud Function: intake — dialog sessions and the message journal.

The chat lives on a session, not on a case: a company is added before any case
exists. Mastra keeps its own working memory in pharma_agent; what lands here is
the record that ships to the client with the case.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import CHAT_ROLES, INTAKE_SCOPES, as_l10n, new_id, row_to_message, row_to_session
from edge_http import (
    error_response,
    get_http_method,
    get_path,
    get_path_params,
    parse_body,
    resolve_identity,
)
from edge_pg import as_json, execute, query, query_one

SELECT_SESSION = """
SELECT * FROM intake_sessions
WHERE session_id = %(session_id)s AND account_id = %(account_id)s
"""

INSERT_SESSION = """
INSERT INTO intake_sessions
(session_id, account_id, scope, organization_id, product_id, locale)
VALUES
(%(session_id)s, %(account_id)s, %(scope)s, %(organization_id)s, %(product_id)s, %(locale)s)
"""

SELECT_MESSAGES = """
SELECT * FROM chat_messages
WHERE session_id = %(session_id)s AND account_id = %(account_id)s
ORDER BY created_at
LIMIT 500
"""

INSERT_MESSAGE = """
INSERT INTO chat_messages (message_id, account_id, session_id, role, text, item_id, payload)
VALUES (%(message_id)s, %(account_id)s, %(session_id)s, %(role)s, %(text)s, %(item_id)s, %(payload)s)
"""

TOUCH_SESSION = """
UPDATE intake_sessions SET updated_at = now()
WHERE session_id = %(session_id)s AND account_id = %(account_id)s
"""

SELECT_ORG = """
SELECT organization_id FROM organizations
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
"""


def _is_messages(event) -> bool:
    return get_path(event).rstrip("/").endswith("/messages")


def _create_session(event, identity, request_id):
    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    scope = str(body.get("scope") or "organization")
    if scope not in INTAKE_SCOPES:
        return error_response(400, "invalid_scope", "scope must be organization or product", request_id)

    organization_id = str(body.get("organizationId") or "") or None
    product_id = str(body.get("productId") or "") or None
    if scope == "organization" and not organization_id:
        return error_response(400, "missing_organization", "organizationId is required", request_id)
    if scope == "product" and not product_id:
        return error_response(400, "missing_product", "productId is required", request_id)

    if organization_id and not query_one(
        SELECT_ORG, {"organization_id": organization_id, "account_id": identity.account_id}
    ):
        return error_response(404, "not_found", f"organization {organization_id} not found", request_id)

    session_id = new_id("ses")
    execute(
        INSERT_SESSION,
        {
            "session_id": session_id,
            "account_id": identity.account_id,
            "scope": scope,
            "organization_id": organization_id,
            "product_id": product_id,
            "locale": str(body.get("locale") or "zh"),
        },
    )
    row = query_one(SELECT_SESSION, {"session_id": session_id, "account_id": identity.account_id})
    log_structured(request_id, "info", "POST /intake/sessions", "created", session_id=session_id, scope=scope)
    return json_response(201, {"data": row_to_session(row)}, request_id)


def _get_session(session_id, identity, request_id):
    row = query_one(SELECT_SESSION, {"session_id": session_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"session {session_id} not found", request_id)
    payload = row_to_session(row)
    payload["messages"] = [
        row_to_message(item)
        for item in query(SELECT_MESSAGES, {"session_id": session_id, "account_id": identity.account_id})
    ]
    return json_response(200, {"data": payload}, request_id)


def _list_messages(session_id, identity, request_id):
    if not query_one(SELECT_SESSION, {"session_id": session_id, "account_id": identity.account_id}):
        return error_response(404, "not_found", f"session {session_id} not found", request_id)
    rows = query(SELECT_MESSAGES, {"session_id": session_id, "account_id": identity.account_id})
    return json_response(200, {"data": [row_to_message(row) for row in rows]}, request_id)


def _append_message(event, session_id, identity, request_id):
    if not query_one(SELECT_SESSION, {"session_id": session_id, "account_id": identity.account_id}):
        return error_response(404, "not_found", f"session {session_id} not found", request_id)

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    role = str(body.get("role") or "agent")
    if role not in CHAT_ROLES:
        return error_response(400, "invalid_role", "role must be user, agent or system", request_id)

    message_id = new_id("msg")
    execute(
        INSERT_MESSAGE,
        {
            "message_id": message_id,
            "account_id": identity.account_id,
            "session_id": session_id,
            "role": role,
            "text": as_json(as_l10n(body.get("text") or "")),
            "item_id": str(body.get("itemId") or "") or None,
            "payload": as_json(body.get("payload")) if body.get("payload") is not None else None,
        },
    )
    execute(TOUCH_SESSION, {"session_id": session_id, "account_id": identity.account_id})
    row = query_one(
        "SELECT * FROM chat_messages WHERE message_id = %(message_id)s",
        {"message_id": message_id},
    )
    return json_response(201, {"data": row_to_message(row)}, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    params = get_path_params(event)
    session_id = params.get("id") or params.get("sessionId") or ""
    messages = _is_messages(event)
    route = f"{method} /intake/sessions" + ("/{id}" if session_id else "") + ("/messages" if messages else "")
    log_structured(request_id, "info", route, "handler entry", method=method)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        if messages:
            if not session_id:
                return error_response(400, "missing_id", "path parameter id is required", request_id)
            if method == "GET":
                return _list_messages(session_id, identity, request_id)
            if method == "POST":
                return _append_message(event, session_id, identity, request_id)
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        if method == "POST" and not session_id:
            return _create_session(event, identity, request_id)
        if method == "GET" and session_id:
            return _get_session(session_id, identity, request_id)
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
