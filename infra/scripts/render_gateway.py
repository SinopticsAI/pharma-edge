"""Fill infra/gateway/openapi.template.yaml placeholders from env or yc."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "infra" / "gateway" / "openapi.template.yaml"
OUTPUT = REPO / "infra" / "gateway" / "openapi.yaml"

PLACEHOLDERS = {
    "__CUSTOM_DOMAIN__": ("CUSTOM_DOMAIN", "pharma-edge.sinoptics.ru"),
    "__SA_API_GATEWAY_ID__": ("SA_API_GATEWAY_ID", ""),
    "__FN_CASES__": ("FN_CASES", "pharma-edge-cases"),
    "__FN_CASE_GET__": ("FN_CASE_GET", "pharma-edge-case-get"),
    "__FN_CASE_UPDATE__": ("FN_CASE_UPDATE", "pharma-edge-case-update"),
    "__FN_DOSSIER_ITEMS__": ("FN_DOSSIER_ITEMS", "pharma-edge-dossier-items"),
    "__FN_STATUS_INGEST__": ("FN_STATUS_INGEST", "pharma-edge-status-ingest"),
    "__FN_REGISTRY_SEARCH__": ("FN_REGISTRY_SEARCH", "pharma-edge-registry-search"),
}


def _read_account_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for name in ("account.env", "account.env.example"):
        path = REPO / "infra" / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, rest = line.split("=", 1)
            values.setdefault(key.strip(), rest.strip())
    return values


def _yc_function_id(name: str) -> str:
    try:
        raw = subprocess.check_output(
            ["yc", "serverless", "function", "get", "--name", name, "--format", "json"],
            text=True,
        )
        return json.loads(raw).get("id") or ""
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return ""


def resolve(token: str, env_key: str, fallback: str, account: dict[str, str]) -> str:
    value = os.getenv(env_key) or account.get(env_key) or ""
    if value:
        return value
    if fallback.startswith("pharma-edge-"):
        looked = _yc_function_id(fallback)
        if looked:
            return looked
    return fallback


def main() -> None:
    account = _read_account_env()
    text = TEMPLATE.read_text(encoding="utf-8")
    missing = []
    for token, (env_key, fallback) in PLACEHOLDERS.items():
        value = resolve(token, env_key, fallback, account)
        if token.startswith("__FN_") or token == "__SA_API_GATEWAY_ID__":
            if not value or value.startswith("pharma-edge-"):
                missing.append(env_key)
        text = text.replace(token, value)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    if missing:
        raise SystemExit(f"unresolved placeholders: {', '.join(missing)}")


if __name__ == "__main__":
    main()
