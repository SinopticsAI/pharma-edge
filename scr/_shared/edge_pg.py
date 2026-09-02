"""PostgreSQL access for Cloud Functions.

The connection lives outside the handler and is reused across invocations: a
suspended instance loses its socket, so every query re-checks liveness and
reconnects once instead of failing the request.

Port 6432 is the Odyssey pooler in transaction mode. That is what makes a
serverless caller safe here; do not switch to 5432.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_lock = threading.Lock()
_conn: Optional[psycopg.Connection] = None

SSL_ROOT_CERT = "/function/storage/certs/root.crt"


def _dsn() -> str:
    dsn = os.getenv("PG_DSN")
    if dsn:
        return dsn
    host = os.getenv("PG_HOST") or ""
    port = os.getenv("PG_PORT") or "6432"
    database = os.getenv("PG_DATABASE") or "pharma_cabinet"
    user = os.getenv("PG_USER") or "pharma_cabinet"
    password = os.getenv("PG_PASSWORD") or ""
    if not host:
        raise RuntimeError("PG_HOST or PG_DSN must be set")
    # Inside the cloud network the pooler is reachable without TLS, but we keep
    # verify-full when a root certificate is shipped with the function.
    sslmode = os.getenv("PG_SSLMODE") or "verify-full"
    parts = [
        f"host={host}",
        f"port={port}",
        f"dbname={database}",
        f"user={user}",
        f"password={password}",
        f"sslmode={sslmode}",
        "connect_timeout=5",
    ]
    root_cert = os.getenv("PG_SSLROOTCERT") or (
        SSL_ROOT_CERT if os.path.exists(SSL_ROOT_CERT) else ""
    )
    if root_cert and sslmode.startswith("verify"):
        parts.append(f"sslrootcert={root_cert}")
    return " ".join(parts)


def _connect() -> psycopg.Connection:
    conn = psycopg.connect(_dsn(), row_factory=dict_row, autocommit=True)
    conn.prepare_threshold = None  # transaction pooling cannot keep prepared statements
    return conn


def get_connection() -> psycopg.Connection:
    global _conn
    with _lock:
        if _conn is not None and not _conn.closed:
            try:
                _conn.execute("SELECT 1")
                return _conn
            except psycopg.Error:
                try:
                    _conn.close()
                except psycopg.Error:
                    pass
                _conn = None
        _conn = _connect()
        return _conn


def query(sql: str, params: Optional[dict | tuple] = None) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            return list(cur.fetchall())
    except psycopg.OperationalError:
        # The pooler dropped an idle socket between invocations; one retry.
        global _conn
        with _lock:
            _conn = None
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description is None:
                return []
            return list(cur.fetchall())


def query_one(sql: str, params: Optional[dict | tuple] = None) -> Optional[dict[str, Any]]:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Optional[dict | tuple] = None) -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount
    except psycopg.OperationalError:
        global _conn
        with _lock:
            _conn = None
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def as_json(value: Any) -> Jsonb:
    """Explicit jsonb wrapper so dicts never land in a text column by accident."""
    return Jsonb(value if value is not None else {})


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
