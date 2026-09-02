"""API Gateway event helpers: method, body, path, X-API-Key, contour."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from common_log import json_response


def get_http_method(event: dict) -> str:
    method = event.get("httpMethod")
    if method:
        return str(method).upper()
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    method = http.get("method") or rc.get("httpMethod")
    return str(method).upper() if method else ""


def is_http_event(event: dict) -> bool:
    if not isinstance(event, dict):
        return False
    if event.get("httpMethod"):
        return True
    rc = event.get("requestContext") or {}
    if isinstance(rc, dict) and (rc.get("http") or rc.get("httpMethod")):
        return True
    return bool(event.get("path") or event.get("rawPath"))


def get_headers(event: dict) -> dict[str, str]:
    raw = event.get("headers") or {}
    return {str(k).lower(): str(v) for k, v in raw.items()}


def get_path(event: dict) -> str:
    return str(event.get("rawPath") or event.get("path") or "")


def get_path_params(event: dict) -> dict[str, str]:
    params = event.get("pathParameters") or event.get("pathParams") or {}
    return {str(k): str(v) for k, v in params.items() if v is not None}


def get_query(event: dict) -> dict[str, str]:
    params = event.get("queryStringParameters") or {}
    return {str(k): str(v) for k, v in params.items() if v is not None}


def parse_body(event: dict) -> dict[str, Any]:
    body = event.get("body") or ""
    if event.get("isBase64Encoded") and body:
        body = base64.b64decode(body).decode("utf-8")
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("JSON body must be an object")
    return parsed


def get_contour(event: dict) -> str:
    headers = get_headers(event)
    value = (headers.get("x-pharma-contour") or "ru").strip().lower()
    return value if value in ("cn", "ru") else "ru"


def require_api_key(event: dict, request_id: str, route: str) -> Optional[dict]:
    expected = os.getenv("PHARMA_EDGE_API_KEY") or ""
    if not expected:
        return json_response(
            503,
            {"error": "api_key_not_configured", "message": "PHARMA_EDGE_API_KEY is not set"},
            request_id,
        )
    headers = get_headers(event)
    provided = headers.get("x-api-key") or ""
    if provided != expected:
        return json_response(
            401,
            {"error": "unauthorized", "message": "X-API-Key is missing or invalid"},
            request_id,
        )
    return None


def error_response(status: int, code: str, message: str, request_id: str, **extra) -> dict:
    payload = {"error": code, "message": message}
    payload.update(extra)
    return json_response(status, payload, request_id)


# ------------------------------------------------------------------ identity --
#
# Two ways in, and only two:
#   browser  — a Keycloak token the gateway authorizer already verified;
#              claims arrive in requestContext.authorizer.jwt, nothing here
#              re-checks a signature;
#   service  — X-API-Key plus an explicit account header, used by Mastra tools
#              and Plane webhooks and never by a browser.
#
# The account is not taken from the token: Keycloak owns the identity, this
# product owns tenancy, so `sub` is resolved through account_users.

SERVICE_ROLE = "service"


@dataclass(frozen=True)
class Identity:
    account_id: str
    subject: str
    role: str
    display_name: str = ""

    @property
    def is_service(self) -> bool:
        return self.role == SERVICE_ROLE

    @property
    def can_approve_as_specialist(self) -> bool:
        return self.role in ("specialist", "admin")

    @property
    def can_operate(self) -> bool:
        return self.role in ("operator", "admin", SERVICE_ROLE)


def get_claims(event: dict) -> dict[str, Any]:
    rc = event.get("requestContext") or {}
    authorizer = rc.get("authorizer") or {}
    jwt = authorizer.get("jwt") or {}
    claims = jwt.get("claims") or {}
    return claims if isinstance(claims, dict) else {}


def get_subject(event: dict) -> str:
    return str(get_claims(event).get("sub") or "")


def get_token_roles(event: dict) -> list[str]:
    raw = get_claims(event).get("roles")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str) and raw.strip():
        return [part for part in raw.replace(",", " ").split() if part]
    return []


def check_api_key(event: dict) -> bool:
    expected = os.getenv("PHARMA_EDGE_API_KEY") or ""
    if not expected:
        return False
    return get_headers(event).get("x-api-key") == expected


_SELECT_ACCOUNT_USER = """
SELECT subject, account_id, role, display_name
FROM account_users
WHERE subject = %(subject)s
"""


def resolve_identity(event: dict, request_id: str) -> tuple[Optional["Identity"], Optional[dict]]:
    """Returns (identity, error_response). Exactly one of them is set."""
    from edge_pg import query_one  # late import: not every function needs the DB

    subject = get_subject(event)
    if subject:
        row = query_one(_SELECT_ACCOUNT_USER, {"subject": subject})
        if not row:
            # Authenticated in Keycloak but not attached to a tenant. Accounts
            # are created by a manager, so this is a real state rather than
            # something the user can fix by retrying.
            return None, error_response(
                403,
                "account_not_linked",
                "this user is not attached to an account yet",
                request_id,
                subject=subject,
            )
        return Identity(
            account_id=str(row["account_id"]),
            subject=subject,
            role=str(row["role"]),
            display_name=str(row.get("display_name") or ""),
        ), None

    if check_api_key(event):
        headers = get_headers(event)
        account_id = headers.get("x-pharma-account") or ""
        if not account_id:
            return None, error_response(
                400,
                "missing_account",
                "service calls must pass X-Pharma-Account",
                request_id,
            )
        return Identity(
            account_id=account_id,
            subject=headers.get("x-pharma-subject") or "service",
            role=SERVICE_ROLE,
            display_name=headers.get("x-pharma-actor") or "agent",
        ), None

    return None, error_response(
        401,
        "unauthorized",
        "Bearer token or X-API-Key with X-Pharma-Account is required",
        request_id,
    )
