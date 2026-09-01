"""API Gateway event helpers: method, body, path, X-API-Key, contour."""

from __future__ import annotations

import base64
import json
import os
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
