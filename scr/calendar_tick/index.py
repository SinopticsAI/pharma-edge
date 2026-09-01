"""Cloud Function: calendar_tick — daily timer, working-day anchors, proposals only."""

from datetime import date, timedelta

from common_log import get_request_id, json_response, log_structured
from edge_domain import CALENDAR_ANCHORS, dumps_json, new_id
from edge_http import is_http_event
from edge_ydb import execute, get_ydb_pool

ROUTE = "TIMER calendar_tick"
WATCH_STAGES = frozenset({"samples", "filing", "expertise", "registry"})

# Official RF holidays 2026 (weekends handled separately).
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
SELECT case_id, current_stage, started_on, due_working_days
FROM cases;
"""

SELECT_PROPOSALS = """
DECLARE $case_id AS Utf8;
SELECT kind, status FROM status_proposals VIEW idx_status_proposals_case
WHERE case_id = $case_id;
"""

INSERT_PROPOSAL = """
DECLARE $proposal_id AS Utf8;
DECLARE $case_id AS Utf8;
DECLARE $kind AS Utf8;
DECLARE $stage AS Utf8;
DECLARE $text_json AS Utf8;
UPSERT INTO status_proposals
(proposal_id, case_id, kind, stage, text_json, status, created_at)
VALUES
($proposal_id, $case_id, $kind, $stage, $text_json, "proposed", CurrentUtcTimestamp());
"""

UPDATE_DUE = """
DECLARE $case_id AS Utf8;
DECLARE $due_working_days AS Int32;
UPDATE cases SET due_working_days = $due_working_days, updated_at = CurrentUtcTimestamp()
WHERE case_id = $case_id;
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


def _parse_started(value) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def handler(event, context):
    request_id = get_request_id(event if isinstance(event, dict) else {})
    if is_http_event(event if isinstance(event, dict) else {}):
        return json_response(405, {"error": "timer_only"}, request_id)

    log_structured(request_id, "info", ROUTE, "tick start")
    created = 0
    scanned = 0
    try:
        pool = get_ydb_pool()
        rows = execute(pool, SELECT_CASES, {})
        today = date.today()
        for row in rows:
            stage = row.get("current_stage") or ""
            if stage not in WATCH_STAGES:
                continue
            scanned += 1
            started = _parse_started(row.get("started_on"))
            if row.get("due_working_days") is None and started is not None:
                remaining = max(0, 50 - working_days_between(started, today))
            else:
                remaining = max(0, int(row.get("due_working_days") or 0))
            case_id = row.get("case_id")
            execute(pool, UPDATE_DUE, {"$case_id": case_id, "$due_working_days": remaining})
            if remaining not in CALENDAR_ANCHORS:
                continue
            kind = f"anchor-{remaining}"
            existing = execute(pool, SELECT_PROPOSALS, {"$case_id": case_id})
            if any(item.get("kind") == kind and item.get("status") == "proposed" for item in existing):
                continue
            text = {
                "ru": f"Нормативный якорь {remaining} р.д. по стадии {stage}",
                "en": f"Normative anchor {remaining} working days at {stage}",
            }
            execute(
                pool,
                INSERT_PROPOSAL,
                {
                    "$proposal_id": new_id("pr"),
                    "$case_id": case_id,
                    "$kind": kind,
                    "$stage": stage,
                    "$text_json": dumps_json(text),
                },
            )
            created += 1
        log_structured(request_id, "info", ROUTE, "tick done", scanned=scanned, created=created)
        return {"statusCode": 200, "body": dumps_json({"scanned": scanned, "proposals": created})}
    except Exception as exc:
        log_structured(request_id, "error", ROUTE, "unhandled", error=str(exc))
        return {"statusCode": 500, "body": dumps_json({"error": str(exc)})}
