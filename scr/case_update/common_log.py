"""
Shared structured logging and request-ID helpers for Yandex Cloud Functions.

Usage in handler:
    from common_log import get_request_id, log_structured, json_response

    def handler(event, context):
        request_id = get_request_id(event)
        log_structured(request_id, "info", "GET /cases/{id}", "handler entry")
        ...
        return json_response(200, {"data": ...}, request_id)

Slack alerts (level=error only):
    Set SLACK_WEBHOOK_URL and optionally YC_FUNCTION_NAME, DEPLOY_ENV.
    Disable with SLACK_ALERTS_ENABLED=0.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from urllib import request as urllib_request


def get_request_id(event: dict) -> str:
    headers = event.get("headers") or {}
    rid = headers.get("X-Request-Id") or headers.get("x-request-id")
    if rid:
        return str(rid)

    rc = event.get("requestContext") or {}
    rid = rc.get("requestId")
    if rid:
        return str(rid)

    return str(uuid.uuid4())


def _slack_alerts_enabled() -> bool:
    return os.getenv("SLACK_ALERTS_ENABLED", "1") != "0"


def _function_name() -> str:
    return os.getenv("YC_FUNCTION_NAME") or "unknown"


def _deploy_env() -> str:
    return os.getenv("DEPLOY_ENV") or "unknown"


def _format_slack_text(entry: dict) -> str:
    fn = _function_name()
    env = _deploy_env()
    route = entry.get("route", "")
    message = entry.get("message", "")
    request_id = entry.get("requestId", "")
    data = entry.get("data")
    lines = [
        f":red_circle: *{fn}* (`{env}`) `{route}`",
        f"*{message}*",
        f"requestId: `{request_id}`",
    ]
    if data:
        payload = json.dumps(data, default=str)
        if len(payload) > 1500:
            payload = payload[:1500] + "..."
        lines.append(f"```{payload}```")
    return "\n".join(lines)


def _notify_slack(entry: dict) -> None:
    if entry.get("level", "").lower() != "error":
        return
    if not _slack_alerts_enabled():
        return
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return
    try:
        body = json.dumps({"text": _format_slack_text(entry)}).encode("utf-8")
        req = urllib_request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib_request.urlopen(req, timeout=3)
    except Exception:
        pass


def log_structured(
    request_id: str,
    level: str,
    route: str,
    message: str,
    **extra,
) -> None:
    entry = {
        "requestId": request_id,
        "level": level,
        "route": route,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        entry["data"] = {k: v for k, v in extra.items() if v is not None}
    print(json.dumps(entry, default=str))
    if level.lower() == "error":
        _notify_slack(entry)


def json_response(status_code: int, payload: dict, request_id: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if request_id:
        headers["X-Request-ID"] = request_id
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(payload, default=str),
    }
