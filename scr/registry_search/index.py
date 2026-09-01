"""Cloud Function: registry_search — GET /registry/search (cached, not truth)."""

import hashlib
from datetime import datetime, timedelta, timezone

from common_log import get_request_id, json_response, log_structured
from edge_domain import dumps_json, loads_json
from edge_http import error_response, get_http_method, get_query, require_api_key
from edge_ydb import execute, get_ydb_pool

ROUTE = "GET /registry/search"
TTL_HOURS = 24
SOURCES = frozenset({"elk", "grls"})

SELECT_HIT = """
DECLARE $hit_key AS Utf8;
SELECT * FROM search_hits WHERE hit_key = $hit_key;
"""

UPSERT_HIT = """
DECLARE $hit_key AS Utf8;
DECLARE $source AS Utf8;
DECLARE $query AS Utf8;
DECLARE $hits_json AS Utf8;
DECLARE $expires_at AS Timestamp;
UPSERT INTO search_hits
(hit_key, source, query, hits_json, expires_at, created_at)
VALUES
($hit_key, $source, $query, $hits_json, $expires_at, CurrentUtcTimestamp());
"""


def _hit_key(source: str, query: str) -> str:
    raw = f"{source}|{query.strip().lower()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _lookup_public(source: str, query: str) -> list:
    """Wave 1: no scrape of ELK/GRLS. Empty hits, truth=false."""
    return []


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)
    denied = require_api_key(event, request_id, ROUTE)
    if denied:
        return denied
    if method != "GET":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    query = (get_query(event).get("q") or "").strip()
    source = (get_query(event).get("source") or "elk").strip().lower()
    if not query:
        return error_response(400, "missing_query", "query parameter q is required", request_id)
    if source not in SOURCES:
        return error_response(400, "invalid_source", "source must be elk or grls", request_id)

    key = _hit_key(source, query)
    try:
        pool = get_ydb_pool()
        rows = execute(pool, SELECT_HIT, {"$hit_key": key})
        now = datetime.now(timezone.utc)
        if rows:
            expires = rows[0].get("expires_at")
            fresh = True
            if isinstance(expires, str):
                try:
                    parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    fresh = parsed > now
                except ValueError:
                    fresh = True
            if fresh:
                hits = loads_json(rows[0].get("hits_json"), [])
                log_structured(request_id, "info", ROUTE, "cache hit", source=source)
                return json_response(
                    200,
                    {"data": {"hits": hits, "source": source, "query": query, "cached": True, "truth": False}},
                    request_id,
                )

        hits = _lookup_public(source, query)
        expires_at = (now + timedelta(hours=TTL_HOURS)).replace(tzinfo=None)
        execute(
            pool,
            UPSERT_HIT,
            {
                "$hit_key": key,
                "$source": source,
                "$query": query,
                "$hits_json": dumps_json(hits),
                "$expires_at": expires_at,
            },
        )
        log_structured(request_id, "info", ROUTE, "cache miss", source=source, count=len(hits))
        return json_response(
            200,
            {"data": {"hits": hits, "source": source, "query": query, "cached": False, "truth": False}},
            request_id,
        )
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
