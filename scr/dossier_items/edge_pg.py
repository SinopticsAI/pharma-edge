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
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

_lock = threading.Lock()
_conn: Optional[psycopg.Connection] = None

# YC Functions zip lands under /function. sync_shared.py copies the MDB CA to
# certs/root.crt next to this module. The storage/ path is a leftover from an
# earlier mount that was never attached.
_MODULE_CERT = Path(__file__).resolve().parent / "certs" / "root.crt"
_CERT_CANDIDATES = (
    "/function/storage/certs/root.crt",
    "/function/certs/root.crt",
)


def _existing_cert() -> str:
    env_path = (os.getenv("PG_SSLROOTCERT") or "").strip()
    for path in (env_path, str(_MODULE_CERT), *_CERT_CANDIDATES):
        if path and os.path.isfile(path):
            return path
    return ""


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
    requested = (os.getenv("PG_SSLMODE") or "verify-full").strip() or "verify-full"
    cert = _existing_cert()
    # verify-full without sslrootcert makes libpq look at ~/.postgresql/root.crt
    # (/function/.postgresql/root.crt in Cloud Functions) and fail the request.
    sslmode = requested
    if requested.startswith("verify") and not cert:
        sslmode = "require"
    parts = [
        f"host={host}",
        f"port={port}",
        f"dbname={database}",
        f"user={user}",
        f"password={password}",
        f"sslmode={sslmode}",
        "connect_timeout=5",
    ]
    if cert and sslmode.startswith("verify"):
        parts.append(f"sslrootcert={cert}")
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


# One registration number per account. Expression matches sql/04_organization_uscc.sql.
_ORG_USCC_EXPR = """NULLIF(upper(trim(BOTH FROM COALESCE(
      NULLIF(draft #>> '{registrationNumber,value}', ''),
      CASE WHEN jsonb_typeof(draft -> 'registrationNumber') = 'string'
           THEN NULLIF(draft ->> 'registrationNumber', '') END,
      NULLIF(profile #>> '{registrationNumber,value}', ''),
      CASE WHEN jsonb_typeof(profile -> 'registrationNumber') = 'string'
           THEN NULLIF(profile ->> 'registrationNumber', '') END,
      ''
    ))), '')"""

SELECT_ORGS_BY_USCC = f"""
SELECT * FROM organizations
WHERE account_id = %(account_id)s
  AND {_ORG_USCC_EXPR} = %(uscc)s
ORDER BY created_at DESC
LIMIT 200
"""


def list_orgs_by_uscc(account_id: str, uscc: str) -> list[dict[str, Any]]:
    code = str(uscc or "").strip().upper()
    if not code:
        return []
    return query(SELECT_ORGS_BY_USCC, {"account_id": account_id, "uscc": code})


def find_org_by_uscc(
    account_id: str,
    uscc: str,
    exclude_organization_id: str = "",
) -> Optional[dict[str, Any]]:
    exclude = str(exclude_organization_id or "")
    for row in list_orgs_by_uscc(account_id, uscc):
        if str(row.get("organization_id") or "") != exclude:
            return row
    return None


def as_json(value: Any) -> Jsonb:
    """Explicit jsonb wrapper so dicts never land in a text column by accident."""
    return Jsonb(value if value is not None else {})


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
