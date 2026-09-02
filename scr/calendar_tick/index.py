"""Cloud Function: calendar_tick — daily timer, working-day anchors.

Writes proposals, never facts. A deadline the machine computed is a suggestion
until an operator confirms it with an artifact.
"""

import json
from datetime import date, timedelta

from common_log import get_request_id, json_response, log_structured
from edge_domain import CALENDAR_ANCHORS, new_id
from edge_http import is_http_event
from edge_pg import as_json, execute, query

ROUTE = "TIMER calendar_tick"
WATCH_STAGES = frozenset({"samples", "filing", "expertise", "registry"})

# Official RF holidays 2026; weekends are handled separately.
RF_HOLIDAYS_2026 = frozenset(
    {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 2, 23),
        date(2026, 3, 8),
        date(2026, 5, 1),
        date(2026, 5, 9),
        date(2026, 6, 12),
        date(2026, 11, 4),
    }
)

SELECT_CASES = """
SELECT case_id, account_id, current_stage, started_on, due_working_days
FROM cases
WHERE current_stage = ANY(%(stages)s)
"""

SELECT_PROPOSAL = """
SELECT 1 FROM status_proposals
WHERE case_id = %(case_id)s AND kind = %(kind)s AND status = 'proposed'
LIMIT 1
"""

INSERT_PROPOSAL = """
INSERT INTO status_proposals (proposal_id, account_id, case_id, kind, stage, text, status)
VALUES (%(proposal_id)s, %(account_id)s, %(case_id)s, %(kind)s, %(stage)s, %(text)s, 'proposed')
"""

UPDATE_DUE = """
UPDATE cases SET due_working_days = %(due_working_days)s, updated_at = now()
WHERE case_id = %(case_id)s
"""


def is_working_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    return day not in RF_HOLIDAYS_2026


def working_days_between(start: date, end: date) -> int:
    if end <= start:
        return 0
    count = 0
    cursor = start + timedelta(days=1)
    while cursor <= end:
        if is_working_day(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count


def handler(event, context):
    request_id = get_request_id(event if isinstance(event, dict) else {})
    if is_http_event(event if isinstance(event, dict) else {}):
        return json_response(405, {"error": "timer_only"}, request_id)

    log_structured(request_id, "info", ROUTE, "tick start")
    created = 0
    scanned = 0
    try:
        rows = query(SELECT_CASES, {"stages": list(WATCH_STAGES)})
        today = date.today()
        for row in rows:
            scanned += 1
            stage = str(row.get("current_stage") or "")
            started = row.get("started_on")
            if row.get("due_working_days") is None and isinstance(started, date):
                remaining = max(0, 50 - working_days_between(started, today))
            else:
                remaining = max(0, int(row.get("due_working_days") or 0))

            case_id = str(row["case_id"])
            execute(UPDATE_DUE, {"case_id": case_id, "due_working_days": remaining})

            if remaining not in CALENDAR_ANCHORS:
                continue
            kind = f"anchor-{remaining}"
            if query(SELECT_PROPOSAL, {"case_id": case_id, "kind": kind}):
                continue

            execute(
                INSERT_PROPOSAL,
                {
                    "proposal_id": new_id("pr"),
                    "account_id": str(row["account_id"]),
                    "case_id": case_id,
                    "kind": kind,
                    "stage": stage,
                    "text": as_json(
                        {
                            "ru": f"Нормативный якорь {remaining} р.д. по стадии {stage}",
                            "en": f"Normative anchor {remaining} working days at {stage}",
                            "zh": f"{stage} 阶段的法定节点：{remaining} 个工作日",
                        }
                    ),
                },
            )
            created += 1

        log_structured(request_id, "info", ROUTE, "tick done", scanned=scanned, created=created)
        return {"statusCode": 200, "body": json.dumps({"scanned": scanned, "proposals": created})}
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}
