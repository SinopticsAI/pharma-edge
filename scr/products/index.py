"""Cloud Function: products — product cards, classification options, approvals.

Two rules shape this file.

Variants are offered only at full completeness: until the agent has enough
facts it asks for documents instead of guessing a class. And a variant marked
`forbidden` exists to be explained, never to be chosen — the platform refuses
to file a class it knows is wrong.

Approval runs specialist first, client second. The case and its node map are
built only when both are in.
"""

from common_log import get_request_id, json_response, log_structured
from edge_domain import (
    PRODUCT_STATUSES,
    as_l10n,
    new_case_code,
    new_id,
    row_to_org_item,
    row_to_product,
    row_to_variant,
)
from edge_http import (
    error_response,
    get_http_method,
    get_path,
    get_path_params,
    parse_body,
    resolve_identity,
)
from edge_intake import (
    default_node_map,
    guess_kind,
    missing_product_fields,
    product_completeness,
    product_intake_blocked,
)
from edge_pg import as_json, execute, query, query_one

SELECT_ORG = """
SELECT organization_id, status, name FROM organizations
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
"""

SELECT_PRODUCTS = """
SELECT * FROM products
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
ORDER BY created_at DESC
"""

SELECT_PRODUCT = """
SELECT * FROM products
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
"""

INSERT_PRODUCT = """
INSERT INTO products (product_id, account_id, organization_id, name, kind, status, draft)
VALUES (%(product_id)s, %(account_id)s, %(organization_id)s, %(name)s, %(kind)s, 'collecting', %(draft)s)
"""

UPDATE_PRODUCT = """
UPDATE products
SET name = %(name)s, kind = %(kind)s, status = %(status)s, draft = %(draft)s,
    completeness = %(completeness)s, updated_at = now()
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
"""

SELECT_VARIANTS = """
SELECT * FROM classification_variants
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
ORDER BY
  CASE variant_type WHEN 'recommended' THEN 0 WHEN 'alternative' THEN 1 ELSE 2 END,
  created_at
"""

DELETE_VARIANTS = """
DELETE FROM classification_variants
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
"""

INSERT_VARIANT = """
INSERT INTO classification_variants
(variant_id, product_id, account_id, variant_type, kind, track, risk_class,
 title, summary, pros, cons, reason, budget, distribution, cycle_months)
VALUES
(%(variant_id)s, %(product_id)s, %(account_id)s, %(variant_type)s, %(kind)s,
 %(track)s, %(risk_class)s, %(title)s, %(summary)s, %(pros)s, %(cons)s,
 %(reason)s, %(budget)s, %(distribution)s, %(cycle_months)s)
"""

SELECT_INHERITED = """
SELECT * FROM organization_items
WHERE organization_id = %(organization_id)s AND account_id = %(account_id)s
  AND (level = 'company' OR product_id = %(product_id)s)
ORDER BY created_at
"""

MARK_SPECIALIST = """
UPDATE products
SET specialist_approved_by = %(actor)s, specialist_approved_at = now(),
    selected_variant_id = %(variant_id)s, status = 'variant_selected', updated_at = now()
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
"""

MARK_CLIENT = """
UPDATE products
SET client_approved_by = %(actor)s, client_approved_at = now(),
    status = 'ru_confirmed', case_id = %(case_id)s, updated_at = now()
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
"""

SELECT_VARIANT = """
SELECT * FROM classification_variants
WHERE variant_id = %(variant_id)s AND product_id = %(product_id)s AND account_id = %(account_id)s
"""

MARK_VARIANT_SELECTED = """
UPDATE classification_variants
SET selected = (variant_id = %(variant_id)s)
WHERE product_id = %(product_id)s AND account_id = %(account_id)s
"""

INSERT_CASE = """
INSERT INTO cases
(case_id, account_id, code, organization_id, product_id, product, manufacturer,
 kind, track, risk_class, track_confirmed, current_stage, next_actor,
 waiting_for, due_working_days, started_on, cycle_months)
VALUES
(%(case_id)s, %(account_id)s, %(code)s, %(organization_id)s, %(product_id)s,
 %(product)s, %(manufacturer)s, %(kind)s, %(track)s, %(risk_class)s, true,
 'roadmap', 'ru', %(waiting_for)s, 30, current_date, %(cycle_months)s)
"""

INSERT_MANDATE = """
INSERT INTO mandates (case_id, complete, role, steps)
VALUES (%(case_id)s, false, 'upp', %(steps)s)
ON CONFLICT (case_id) DO NOTHING
"""

INSERT_NODE = """
INSERT INTO node_map_items
(case_id, code, position, title, note, status, owner, due_hint, blocked_by, critical)
VALUES
(%(case_id)s, %(code)s, %(position)s, %(title)s, %(note)s, %(status)s,
 %(owner)s, %(due_hint)s, %(blocked_by)s, %(critical)s)
ON CONFLICT (case_id, code) DO NOTHING
"""

INSERT_AUDIT = """
INSERT INTO audit_entries
(entry_id, account_id, subject_type, subject_id, action, actor, actor_role, detail, model, prompt_version)
VALUES
(%(entry_id)s, %(account_id)s, 'product', %(subject_id)s, %(action)s, %(actor)s,
 %(actor_role)s, %(detail)s, %(model)s, %(prompt_version)s)
"""


def _audit(identity, product_id, action, detail=None, model=None, prompt_version=None):
    execute(
        INSERT_AUDIT,
        {
            "entry_id": new_id("aud"),
            "account_id": identity.account_id,
            "subject_id": product_id,
            "action": action,
            "actor": identity.display_name or identity.subject,
            "actor_role": identity.role,
            "detail": as_json(detail or {}),
            "model": model,
            "prompt_version": prompt_version,
        },
    )


def _sub_route(event) -> str:
    path = get_path(event).rstrip("/")
    if path.endswith("/variants"):
        return "variants"
    if path.endswith("/approve"):
        return "approve"
    if "/products" in path and path.split("/products")[-1].strip("/") == "":
        return "collection"
    return "product"


def _list(organization_id, identity, request_id):
    rows = query(SELECT_PRODUCTS, {"organization_id": organization_id, "account_id": identity.account_id})
    return json_response(200, {"data": [row_to_product(row) for row in rows]}, request_id)


def _create(event, organization_id, identity, request_id):
    org = query_one(SELECT_ORG, {"organization_id": organization_id, "account_id": identity.account_id})
    if not org:
        return error_response(404, "not_found", f"organization {organization_id} not found", request_id)
    if product_intake_blocked(str(org.get("status"))):
        # Partial company data is fine; an unapproved profile is not.
        return error_response(
            409,
            "profile_not_approved",
            "approve the company profile before adding a product",
            request_id,
            organizationStatus=org.get("status"),
        )

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    product_id = new_id("prd")
    draft = body.get("draft") or {}
    execute(
        INSERT_PRODUCT,
        {
            "product_id": product_id,
            "account_id": identity.account_id,
            "organization_id": organization_id,
            "name": as_json(as_l10n(body.get("name") or "")),
            "kind": str(body.get("kind") or "") or None,
            "draft": as_json(draft),
        },
    )
    _audit(identity, product_id, "product.created")
    row = query_one(SELECT_PRODUCT, {"product_id": product_id, "account_id": identity.account_id})
    log_structured(request_id, "info", "POST /organizations/{id}/products", "created", product_id=product_id)
    return json_response(201, {"data": row_to_product(row)}, request_id)


def _get(product_id, identity, request_id):
    row = query_one(SELECT_PRODUCT, {"product_id": product_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"product {product_id} not found", request_id)
    payload = row_to_product(row)
    inherited = query(
        SELECT_INHERITED,
        {
            "organization_id": row["organization_id"],
            "account_id": identity.account_id,
            "product_id": product_id,
        },
    )
    payload["documents"] = [row_to_org_item(item) for item in inherited]
    payload["missing"] = missing_product_fields(payload["draft"])
    payload["variants"] = [
        row_to_variant(item)
        for item in query(SELECT_VARIANTS, {"product_id": product_id, "account_id": identity.account_id})
    ]
    return json_response(200, {"data": payload}, request_id)


def _patch(event, product_id, identity, request_id):
    row = query_one(SELECT_PRODUCT, {"product_id": product_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"product {product_id} not found", request_id)
    current = row_to_product(row)

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    draft = dict(current["draft"])
    if isinstance(body.get("draft"), dict):
        draft.update(body["draft"])

    status = str(body.get("status") or current["status"])
    if status not in PRODUCT_STATUSES:
        return error_response(400, "invalid_status", f"status must be one of {PRODUCT_STATUSES}", request_id)

    completeness = product_completeness(draft)
    if status == "data_approved":
        missing = missing_product_fields(draft)
        if missing:
            return error_response(
                409, "product_incomplete", "cannot approve while fields are missing", request_id, missing=missing
            )

    kind = str(body.get("kind") or current["kind"] or "") or guess_kind(draft)
    name = as_l10n(body["name"]) if body.get("name") else current["name"]

    execute(
        UPDATE_PRODUCT,
        {
            "product_id": product_id,
            "account_id": identity.account_id,
            "name": as_json(name),
            "kind": kind,
            "status": status,
            "draft": as_json(draft),
            "completeness": completeness,
        },
    )
    if status != current["status"]:
        _audit(identity, product_id, f"product.{status}")
    return _get(product_id, identity, request_id)


def _get_variants(product_id, identity, request_id):
    rows = query(SELECT_VARIANTS, {"product_id": product_id, "account_id": identity.account_id})
    return json_response(200, {"data": [row_to_variant(row) for row in rows]}, request_id)


def _post_variants(event, product_id, identity, request_id):
    row = query_one(SELECT_PRODUCT, {"product_id": product_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"product {product_id} not found", request_id)
    product = row_to_product(row)

    if product["completeness"] < 100 and missing_product_fields(product["draft"]):
        return error_response(
            409,
            "not_complete",
            "classification options are proposed at full completeness only",
            request_id,
            completeness=product["completeness"],
            missing=missing_product_fields(product["draft"]),
        )

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    variants = body.get("variants")
    if not isinstance(variants, list) or not variants:
        return error_response(400, "invalid_body", "variants must be a non-empty list", request_id)

    execute(DELETE_VARIANTS, {"product_id": product_id, "account_id": identity.account_id})
    for entry in variants:
        if not isinstance(entry, dict):
            continue
        variant_type = str(entry.get("variantType") or entry.get("variant_type") or "alternative")
        if variant_type not in ("recommended", "alternative", "forbidden"):
            variant_type = "alternative"
        execute(
            INSERT_VARIANT,
            {
                "variant_id": new_id("var"),
                "product_id": product_id,
                "account_id": identity.account_id,
                "variant_type": variant_type,
                "kind": str(entry.get("kind") or product["kind"] or "device"),
                "track": str(entry.get("track") or "pp1684"),
                "risk_class": str(entry.get("riskClass") or entry.get("risk_class") or "1"),
                "title": as_json(entry.get("title") or {}),
                "summary": as_json(entry.get("summary") or {}),
                "pros": as_json(entry.get("pros") or []),
                "cons": as_json(entry.get("cons") or []),
                "reason": as_json(entry.get("reason")) if entry.get("reason") else None,
                "budget": as_json(entry.get("budget") or {}),
                "distribution": as_json(entry.get("distribution") or {}),
                "cycle_months": as_json(entry.get("cycleMonths") or entry.get("cycle_months") or [12, 18]),
            },
        )

    execute(
        UPDATE_PRODUCT,
        {
            "product_id": product_id,
            "account_id": identity.account_id,
            "name": as_json(product["name"]),
            "kind": product["kind"] or "device",
            "status": "variants_pending",
            "draft": as_json(product["draft"]),
            "completeness": product["completeness"],
        },
    )
    _audit(
        identity,
        product_id,
        "variants.proposed",
        {"count": len(variants)},
        model=str(body.get("model") or "") or None,
        prompt_version=str(body.get("promptVersion") or "") or None,
    )
    return _get_variants(product_id, identity, request_id)


def _build_case(product, org, variant, identity, request_id):
    case_id = new_id("case")
    code = new_case_code(case_id)
    execute(
        INSERT_CASE,
        {
            "case_id": case_id,
            "account_id": identity.account_id,
            "code": code,
            "organization_id": product["organizationId"],
            "product_id": product["id"],
            "product": as_json(product["name"]),
            "manufacturer": as_json(org.get("name") or {}),
            "kind": variant["kind"],
            "track": variant["track"],
            "risk_class": variant["riskClass"],
            "waiting_for": as_json(as_l10n("Дорожная карта", "Roadmap", "路线图")),
            "cycle_months": as_json(variant["cycleMonths"]),
        },
    )
    from edge_domain import default_mandate_steps

    execute(INSERT_MANDATE, {"case_id": case_id, "steps": as_json(default_mandate_steps())})

    nodes = default_node_map(
        kind=variant["kind"],
        track=variant["track"],
        risk_class=variant["riskClass"],
        measuring_instrument=bool(product["draft"].get("measuring")),
    )
    from edge_intake import critical_node

    critical = critical_node(nodes)
    for node in nodes:
        execute(
            INSERT_NODE,
            {
                "case_id": case_id,
                "code": node["code"],
                "position": node["position"],
                "title": as_json(node["title"]),
                "note": as_json(node["note"]) if node.get("note") else None,
                "status": node["status"],
                "owner": node["owner"],
                "due_hint": as_json(node.get("due_hint")) if node.get("due_hint") else None,
                "blocked_by": node.get("blocked_by") or [],
                "critical": bool(critical and critical["code"] == node["code"]),
            },
        )
    log_structured(request_id, "info", "products.approve", "case built", case_id=case_id, nodes=len(nodes))
    return case_id


def _approve(event, product_id, identity, request_id):
    row = query_one(SELECT_PRODUCT, {"product_id": product_id, "account_id": identity.account_id})
    if not row:
        return error_response(404, "not_found", f"product {product_id} not found", request_id)
    product = row_to_product(row)

    try:
        body = parse_body(event)
    except (ValueError, TypeError) as exc:
        return error_response(400, "invalid_json", str(exc), request_id)

    stage = str(body.get("as") or "").strip()
    if stage not in ("specialist", "client"):
        return error_response(400, "invalid_body", "as must be specialist or client", request_id)

    if stage == "specialist":
        if not identity.can_approve_as_specialist:
            return error_response(403, "forbidden", "only a specialist confirms the classification", request_id)
        variant_id = str(body.get("variantId") or "")
        variant_row = query_one(
            SELECT_VARIANT,
            {"variant_id": variant_id, "product_id": product_id, "account_id": identity.account_id},
        )
        if not variant_row:
            return error_response(400, "invalid_variant", "variantId is unknown for this product", request_id)
        if variant_row.get("variant_type") == "forbidden":
            # The card exists to be explained, not chosen.
            return error_response(
                409,
                "variant_forbidden",
                "this option is shown as a warning and cannot be selected",
                request_id,
            )
        execute(MARK_VARIANT_SELECTED, {"variant_id": variant_id, "product_id": product_id, "account_id": identity.account_id})
        execute(
            MARK_SPECIALIST,
            {
                "product_id": product_id,
                "account_id": identity.account_id,
                "actor": identity.display_name or identity.subject,
                "variant_id": variant_id,
            },
        )
        _audit(
            identity,
            product_id,
            "classification.specialist_approved",
            {"variantId": variant_id, "checkedAgainst": body.get("checkedAgainst") or ""},
        )
        return _get(product_id, identity, request_id)

    # stage == "client"
    if not product["specialistApprovedAt"]:
        return error_response(
            409,
            "specialist_first",
            "the specialist confirms the classification before the client",
            request_id,
        )
    variant_row = query_one(
        SELECT_VARIANT,
        {
            "variant_id": product["selectedVariantId"],
            "product_id": product_id,
            "account_id": identity.account_id,
        },
    )
    if not variant_row:
        return error_response(409, "no_variant", "no classification option is selected", request_id)

    org = query_one(SELECT_ORG, {"organization_id": product["organizationId"], "account_id": identity.account_id})
    case_id = _build_case(product, org or {}, row_to_variant(variant_row), identity, request_id)
    execute(
        MARK_CLIENT,
        {
            "product_id": product_id,
            "account_id": identity.account_id,
            "actor": identity.display_name or identity.subject,
            "case_id": case_id,
        },
    )
    _audit(identity, product_id, "classification.client_approved", {"caseId": case_id})
    return _get(product_id, identity, request_id)


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    params = get_path_params(event)
    path_id = params.get("id") or ""
    sub = _sub_route(event)
    route = f"{method} /products/{sub}"
    log_structured(request_id, "info", route, "handler entry", method=method, path=get_path(event))

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        if sub == "collection":
            if method == "GET":
                return _list(path_id, identity, request_id)
            if method == "POST":
                return _create(event, path_id, identity, request_id)
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        if not path_id:
            return error_response(400, "missing_id", "path parameter id is required", request_id)

        if sub == "variants":
            if method == "GET":
                return _get_variants(path_id, identity, request_id)
            if method == "POST":
                return _post_variants(event, path_id, identity, request_id)
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        if sub == "approve":
            if method == "POST":
                return _approve(event, path_id, identity, request_id)
            return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

        if method == "GET":
            return _get(path_id, identity, request_id)
        if method == "PATCH":
            return _patch(event, path_id, identity, request_id)
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)
    except Exception as exc:
        log_structured(request_id, "error", route, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
