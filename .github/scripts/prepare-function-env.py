#!/usr/bin/env python3
"""Build yc-sls-function environment and Lockbox secret blocks.

Yandex Cloud rejects empty environment values (INVALID_ARGUMENT on
PG_HOST / PG_PASSWORD). Blank keys are omitted. Host and VPC have
defaults for the shared orders-panel cluster; the password must come
from Lockbox or PG_CABINET_PASSWORD.
"""

from __future__ import annotations

import os
import sys

DEFAULT_PG_HOST = "c-c9qbferg3hcqjnqkghcp.rw.mdb.yandexcloud.net"
DEFAULT_VPC_NETWORK_ID = "enpp5oe8dlepbkjm52rl"
PG_LOCKBOX_KEY = "pharma_cabinet_password"
HTTP_LOCKBOX_KEY = "PHARMA_EDGE_API_KEY"
S3_UPLOAD_IDS = frozenset({"dossier_items", "organization_items"})


def _clean(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _error(message: str) -> None:
    # Surface the reason in Actions annotations, not only the job log.
    print(f"::error::{message}", file=sys.stderr)


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        print(f"{name}=\n{value}\n", file=sys.stderr)
        return
    with open(path, "a", encoding="utf-8") as fh:
        if "\n" in value:
            fh.write(f"{name}<<EOF\n{value}\nEOF\n")
        else:
            fh.write(f"{name}={value}\n")


def main() -> int:
    deploy_env = _clean("DEPLOY_ENV") or "prod"
    function_name = _clean("YC_FUNCTION_NAME")
    matrix_id = _clean("MATRIX_ID")
    pg_host = _clean("PG_HOST") or DEFAULT_PG_HOST
    network_id = _clean("VPC_NETWORK_ID") or DEFAULT_VPC_NETWORK_ID
    lockbox_pg = _clean("LOCKBOX_PG_ID")
    lockbox_http = _clean("LOCKBOX_HTTP_ID")
    lockbox_s3 = _clean("LOCKBOX_S3_ID")
    pg_password = _clean("PG_CABINET_PASSWORD")
    api_key = _clean("PHARMA_EDGE_API_KEY")
    aws_key = _clean("AWS_ACCESS_KEY_ID")
    aws_secret = _clean("AWS_SECRET_ACCESS_KEY")
    plane_base = _clean("PHARMA_PLANE_BASE_URL")

    if not function_name:
        _error("YC_FUNCTION_NAME is empty")
        return 1
    if not lockbox_pg and not pg_password:
        _error(
            "Missing PostgreSQL password: set GitHub secret LOCKBOX_PG_ID "
            "(preferred, after pharma-postgracesql ensure-postgres.ps1) "
            "or PG_CABINET_PASSWORD. Empty PG_PASSWORD is rejected by "
            "Yandex Cloud as INVALID_ARGUMENT."
        )
        return 1

    env_pairs: list[tuple[str, str]] = [
        ("DEPLOY_ENV", deploy_env),
        ("YC_FUNCTION_NAME", function_name),
        ("PG_HOST", pg_host),
        ("PG_PORT", "6432"),
        ("PG_DATABASE", "pharma_cabinet"),
        ("PG_USER", "pharma_cabinet"),
        ("PG_SSLMODE", "verify-full"),
        ("DOSSIER_BUCKET", "pharma-dossier"),
        ("S3_ENDPOINT", "https://storage.yandexcloud.net"),
    ]
    if plane_base:
        env_pairs.append(("PHARMA_PLANE_BASE_URL", plane_base))
    if pg_password and not lockbox_pg:
        env_pairs.append(("PG_PASSWORD", pg_password))
    if api_key and not lockbox_http:
        env_pairs.append(("PHARMA_EDGE_API_KEY", api_key))
    attach_aws = bool(aws_key and aws_secret) and not lockbox_s3
    if attach_aws:
        env_pairs.append(("AWS_ACCESS_KEY_ID", aws_key))
        env_pairs.append(("AWS_SECRET_ACCESS_KEY", aws_secret))

    # yc-sls-function@v3 sent "latest" to the API as a version id and YC
    # answered NOT_FOUND. v5 resolves latest to current_version.id at deploy.
    secret_lines: list[str] = []
    if lockbox_pg:
        secret_lines.append(f"PG_PASSWORD={lockbox_pg}/latest/{PG_LOCKBOX_KEY}")
    if lockbox_http:
        secret_lines.append(f"PHARMA_EDGE_API_KEY={lockbox_http}/latest/{HTTP_LOCKBOX_KEY}")
    if lockbox_s3 and (matrix_id in S3_UPLOAD_IDS or not (aws_key and aws_secret)):
        secret_lines.append(f"AWS_ACCESS_KEY_ID={lockbox_s3}/latest/AWS_ACCESS_KEY_ID")
        secret_lines.append(
            f"AWS_SECRET_ACCESS_KEY={lockbox_s3}/latest/AWS_SECRET_ACCESS_KEY"
        )

    env_block = "\n".join(f"{key}={value}" for key, value in env_pairs if value)
    secrets_block = "\n".join(secret_lines)
    _write_output("environment", env_block)
    _write_output("secrets", secrets_block)
    _write_output("network_id", network_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
