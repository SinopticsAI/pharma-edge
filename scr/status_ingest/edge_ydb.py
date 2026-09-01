"""YDB session pool and typed execute — same pattern as Logos Edge."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, Optional

import ydb
import ydb.iam

_ydb_driver = None
_ydb_pool = None


def request_settings():
    return (
        ydb.BaseRequestSettings()
        .with_timeout(20)
        .with_operation_timeout(15)
        .with_cancel_after(15)
    )


def get_ydb_pool():
    global _ydb_driver, _ydb_pool
    if _ydb_pool is not None:
        return _ydb_pool
    endpoint = os.getenv("YDB_ENDPOINT")
    database = os.getenv("YDB_DATABASE")
    if not endpoint or not database:
        raise RuntimeError("YDB_ENDPOINT and YDB_DATABASE must be set")
    _ydb_driver = ydb.Driver(
        endpoint=endpoint,
        database=database,
        credentials=ydb.iam.MetadataUrlCredentials(),
    )
    _ydb_driver.wait(fail_fast=True, timeout=10)
    _ydb_pool = ydb.SessionPool(_ydb_driver)
    return _ydb_pool


def ydb_value_to_python(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return str(uuid.UUID(bytes=value))
        except (ValueError, TypeError):
            try:
                return value.decode("utf-8")
            except Exception:
                return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def result_set_to_dicts(result_set) -> list[dict[str, Any]]:
    rows_out = []
    for row in result_set.rows:
        item = {}
        for column in result_set.columns:
            item[column.name] = ydb_value_to_python(getattr(row, column.name, None))
        rows_out.append(item)
    return rows_out


def execute(pool, query: str, params: Optional[dict] = None) -> list[dict[str, Any]]:
    settings = request_settings()

    def _run(session):
        prepared = session.prepare(query, settings=settings)
        result = session.transaction().execute(
            prepared,
            params or {},
            commit_tx=True,
            settings=settings,
        )
        if not result:
            return []
        return result_set_to_dicts(result[0])

    return pool.retry_operation_sync(
        _run,
        ydb.RetrySettings(idempotent=True, max_retries=3),
    )


def now_ts() -> datetime:
    return datetime.utcnow()
