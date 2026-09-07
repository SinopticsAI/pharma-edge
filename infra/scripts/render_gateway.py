"""Fill infra/gateway/openapi.template.yaml placeholders from env or yc.

Canon: SinopticsAI/pharma_env. Keep this copy in sync: CD here re-renders the
spec of an existing gateway, but the gateway itself is created from that repo.
"""

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
    "__FN_IDENTITY__": ("FN_IDENTITY", "pharma-edge-identity"),
    "__FN_ORGANIZATIONS__": ("FN_ORGANIZATIONS", "pharma-edge-organizations"),
    "__FN_ORGANIZATION_ITEMS__": ("FN_ORGANIZATION_ITEMS", "pharma-edge-organization-items"),
    "__FN_PRODUCTS__": ("FN_PRODUCTS", "pharma-edge-products"),
    "__FN_INTAKE__": ("FN_INTAKE", "pharma-edge-intake"),
    "__FN_CASES__": ("FN_CASES", "pharma-edge-cases"),
    "__FN_CASE_GET__": ("FN_CASE_GET", "pharma-edge-case-get"),
    "__FN_CASE_UPDATE__": ("FN_CASE_UPDATE", "pharma-edge-case-update"),
    "__FN_CASE_START__": ("FN_CASE_START", "pharma-edge-case-start"),
    "__FN_DOSSIER_ITEMS__": ("FN_DOSSIER_ITEMS", "pharma-edge-dossier-items"),
    "__FN_STATUS_INGEST__": ("FN_STATUS_INGEST", "pharma-edge-status-ingest"),
    "__FN_REGISTRY_SEARCH__": ("FN_REGISTRY_SEARCH", "pharma-edge-registry-search"),
    "__FN_WEBHOOKS__": ("FN_WEBHOOKS", "pharma-edge-webhooks"),
    # First container integration in this gateway: the Mastra agent.
    "__CONTAINER_AGENT__": ("CONTAINER_AGENT_ID", "pharma-agent"),
}

# The gateway goes up before the agent container exists (step 4 of the first
# rollout, agent is step 7). An unresolved container id would be rejected by
# yc, so /chat/* answers 503 until the id is known and the gateway is redeployed.
AGENT_CONTAINER_BLOCK = """    agent:
      type: serverless_containers
      container_id: __CONTAINER_AGENT__
      service_account_id: __SA_API_GATEWAY_ID__
"""

AGENT_STUB_BLOCK = """    agent:
      type: dummy
      content:
        "*": '{"error":"agent_container_not_deployed"}'
      http_code: 503
      http_headers:
        Content-Type: application/json
        Access-Control-Allow-Origin: "*"
"""


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


def _yc_resource_id(kind: str, name: str) -> str:
    try:
        raw = subprocess.check_output(
            ["yc", "serverless", kind, "get", "--name", name, "--format", "json"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(raw).get("id") or ""
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, OSError):
        return ""


def _is_container_id(value: str) -> bool:
    return value.startswith("bba") and len(value) > 8


def resolve(token: str, env_key: str, fallback: str, account: dict[str, str]) -> str:
    value = (os.getenv(env_key) or account.get(env_key) or "").strip()
    if token == "__CONTAINER_AGENT__":
        if _is_container_id(value):
            return value
        looked = _yc_resource_id("container", fallback)
        if _is_container_id(looked):
            return looked
        # PermissionDenied or a missing container must not fail CD:
        # /chat/* stays a 503 stub until the id is known.
        return ""
    if value:
        return value
    if fallback.startswith("pharma-edge-"):
        looked = _yc_resource_id("function", fallback)
        if looked:
            return looked
    return fallback


def main() -> None:
    account = _read_account_env()
    text = TEMPLATE.read_text(encoding="utf-8")

    agent = resolve("__CONTAINER_AGENT__", "CONTAINER_AGENT_ID", "pharma-agent", account)
    if not _is_container_id(agent):
        if AGENT_CONTAINER_BLOCK not in text:
            raise SystemExit("agent integration block not found in the template")
        text = text.replace(AGENT_CONTAINER_BLOCK, AGENT_STUB_BLOCK)
        print("WARNING: CONTAINER_AGENT_ID is empty; /chat/* will answer 503")
        agent = ""

    missing = []
    for token, (env_key, fallback) in PLACEHOLDERS.items():
        if token == "__CONTAINER_AGENT__":
            continue
        value = resolve(token, env_key, fallback, account)
        if token.startswith("__FN_") or token == "__SA_API_GATEWAY_ID__":
            if not value or value.startswith("pharma-edge-"):
                missing.append(env_key)
        text = text.replace(token, value)
    text = text.replace("__CONTAINER_AGENT__", agent)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    if missing:
        raise SystemExit(f"unresolved placeholders: {', '.join(missing)}")


if __name__ == "__main__":
    main()
