"""HTTP bridge Edge → Plane facade. Cutover is one env var, as in Logos.

Edge never calls YaWL directly; the workflow id is Plane's business.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

API_VERSION = "v2026-08"
TIMEOUT_SECONDS = 20

WORKFLOW_DOSSIER = "pharma-dossier"
WORKFLOW_QUALIFY = "pharma-qualify"
WORKFLOW_INTAKE = "pharma-intake"


class PlaneError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"plane {status}: {message}")
        self.status = status
        self.message = message


def base_url() -> str:
    return (os.getenv("PHARMA_PLANE_BASE_URL") or "").rstrip("/")


def is_configured() -> bool:
    return bool(base_url() and os.getenv("PHARMA_PLANE_API_KEY"))


def intake_case_id(session_id: str) -> str:
    """Plane's roster is case-keyed; an intake session borrows a technical id."""
    return f"intake-{session_id}"


def _post(path: str, payload: dict[str, Any], request_id: str = "") -> dict[str, Any]:
    root = base_url()
    if not root:
        raise PlaneError(503, "PHARMA_PLANE_BASE_URL is not set")
    api_key = os.getenv("PHARMA_PLANE_API_KEY") or ""
    if not api_key:
        raise PlaneError(503, "PHARMA_PLANE_API_KEY is not set")

    url = f"{root}{path}"
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-API-Key": api_key}
    if request_id:
        headers["X-Request-Id"] = request_id
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8") or "{}"
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            detail = exc.reason or ""
        raise PlaneError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise PlaneError(502, str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise PlaneError(502, f"plane returned non-JSON: {exc}") from exc


def start_case(
    case_id: str,
    workflow: str,
    items: Optional[list[dict[str, Any]]] = None,
    settings: Optional[dict[str, Any]] = None,
    title: str = "Case",
    request_id: str = "",
) -> dict[str, Any]:
    payload = {
        "case_id": case_id,
        "client_id": os.getenv("PHARMA_PLANE_CLIENT_ID") or "pharma-edge",
        "title": title,
        "settings": {**(settings or {}), "workflow": workflow},
        "items": items or [],
    }
    return _post(f"/api/{API_VERSION}/cases/{case_id}/actions/start", payload, request_id)


def update_items(
    case_id: str,
    items: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
    request_id: str = "",
) -> dict[str, Any]:
    payload = {
        "client_id": os.getenv("PHARMA_PLANE_CLIENT_ID") or "pharma-edge",
        "items": items,
    }
    if settings:
        payload["settings"] = settings
    return _post(f"/api/{API_VERSION}/cases/{case_id}/actions/update-items", payload, request_id)


def wants_plane(value: Any) -> bool:
    """True only when the cabinet sent usePlane on this confirm."""
    if value is True:
        return True
    if isinstance(value, (int, float)) and int(value) == 1:
        return True
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def already_started(result: dict[str, Any]) -> bool:
    return "already started" in str(result.get("message") or "").lower()


def hand_to_plane(
    *,
    case_id: str,
    workflow: str,
    items: list[dict[str, Any]],
    settings: Optional[dict[str, Any]] = None,
    title: str = "Case",
    request_id: str = "",
) -> dict[str, Any]:
    """Start a parent run, or append items when that case is already processing."""
    extras = {**(settings or {}), "workflow": workflow}
    try:
        result = start_case(
            case_id=case_id,
            workflow=workflow,
            items=items,
            settings=settings,
            title=title,
            request_id=request_id,
        )
    except PlaneError as exc:
        if exc.status != 409:
            raise
        return update_items(case_id, items, settings=extras, request_id=request_id)
    if already_started(result):
        return update_items(case_id, items, settings=extras, request_id=request_id)
    return result


def item_payload(item_id: str, item_type: str, object_key: str, bucket: str) -> dict[str, Any]:
    """S3 object key only. Plane reads SOURCE_BUCKET (pharma-dossier)."""
    key = (object_key or "").strip().lstrip("/")
    prefix = f"{(bucket or '').strip()}/"
    if bucket and key.startswith(prefix):
        key = key[len(prefix) :]
    return {
        "item_id": item_id,
        "item_type": item_type,
        "source_data": {"bucket_path": key},
        "item_settings": {"expected_type": item_type},
    }
