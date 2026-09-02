"""Cloud Function: registry_search — GET /registry/search (cached, not truth).

The registry is the source of truth for numbers; this endpoint keeps a link and
a cached answer, never a private copy the cabinet would start believing.
"""

import hashlib
from datetime import datetime, timedelta, timezone

from common_log import get_request_id, json_response, log_structured
from edge_http import error_response, get_http_method, get_query, resolve_identity
from edge_pg import as_json, execute, query_one

ROUTE = "GET /registry/search"
TTL_HOURS = 24
SOURCES = frozenset({"elk", "grls"})

SELECT_HIT = "SELECT * FROM search_hits WHERE hit_key = %(hit_key)s"

UPSERT_HIT = """
INSERT INTO search_hits (hit_key, source, query, hits, expires_at)
VALUES (%(hit_key)s, %(source)s, %(query)s, %(hits)s, %(expires_at)s)
ON CONFLICT (hit_key) DO UPDATE
SET hits = EXCLUDED.hits, expires_at = EXCLUDED.expires_at, created_at = now()
"""


def _hit_key(source: str, query: str) -> str:
    raw = f"{source}|{query.strip().lower()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _lookup_public(source: str, query: str) -> list:
    """Wave 1: no scrape of ELK or GRLS. Empty hits, truth=false."""
    return []


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)

    if method != "GET":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    params = get_query(event)
    search = (params.get("q") or "").strip()
    source = (params.get("source") or "elk").strip().lower()
    if not search:
        return error_response(400, "missing_query", "query parameter q is required", request_id)
    if source not in SOURCES:
        return error_response(400, "invalid_source", "source must be elk or grls", request_id)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        key = _hit_key(source, search)
        row = query_one(SELECT_HIT, {"hit_key": key})
        now = datetime.now(timezone.utc)

        if row:
            expires = row.get("expires_at")
            fresh = True
            if isinstance(expires, datetime):
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                fresh = expires > now
            if fresh:
                log_structured(request_id, "info", ROUTE, "cache hit", source=source)
                return json_response(
                    200,
                    {
                        "data": {
                            "hits": row.get("hits") or [],
                            "source": source,
                            "query": search,
                            "cached": True,
                            "truth": False,
                        }
                    },
                    request_id,
                )

        hits = _lookup_public(source, search)
        execute(
            UPSERT_HIT,
            {
                "hit_key": key,
                "source": source,
                "query": search,
                "hits": as_json(hits),
                "expires_at": now + timedelta(hours=TTL_HOURS),
            },
        )
        log_structured(request_id, "info", ROUTE, "cache miss", source=source, count=len(hits))
        return json_response(
            200,
            {"data": {"hits": hits, "source": source, "query": search, "cached": False, "truth": False}},
            request_id,
        )
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
