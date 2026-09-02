"""Cloud Function: identity — GET /accounts/me.

The SPA calls this right after login to learn which account it is in and what
the user may do. Roles come from the realm, the account from account_users.
"""

from common_log import get_request_id, json_response, log_structured
from edge_http import error_response, get_http_method, resolve_identity
from edge_pg import query_one

ROUTE = "GET /accounts/me"

SELECT_ACCOUNT = """
SELECT account_id, name, status
FROM accounts
WHERE account_id = %(account_id)s
"""


def handler(event, context):
    request_id = get_request_id(event)
    method = get_http_method(event)
    log_structured(request_id, "info", ROUTE, "handler entry", method=method)

    if method != "GET":
        return error_response(405, "method_not_allowed", f"{method} is not allowed", request_id)

    try:
        identity, denied = resolve_identity(event, request_id)
        if denied:
            return denied

        account = query_one(SELECT_ACCOUNT, {"account_id": identity.account_id})
        payload = {
            "accountId": identity.account_id,
            "subject": identity.subject,
            "role": identity.role,
            "displayName": identity.display_name,
            "account": {
                "id": identity.account_id,
                "name": (account or {}).get("name") or {},
                "status": (account or {}).get("status") or "unknown",
            },
            "can": {
                "approveAsSpecialist": identity.can_approve_as_specialist,
                "operate": identity.can_operate,
            },
        }
        return json_response(200, {"data": payload}, request_id)
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return error_response(500, "internal_error", str(exc), request_id)
