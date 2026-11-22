"""
The weekly report: what happened in a server's tickets in a week, compared with the week
before. Pure functions (no Discord): the bot sends the result to Discord and Telegram.
"""

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

WEEK = 7 * 86400
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def latest_report_time(now: float, timezone: str, day: str, hour: int) -> float:
    """When the latest weekly report was due (`day` at `hour`:00 in `timezone`), at or
    before `now`. Daylight saving time is handled by the time zone."""
    zone = ZoneInfo(timezone)
    local = datetime.fromtimestamp(now, zone)
    due = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    due -= timedelta(days=(local.weekday() - DAYS.index(day)) % 7)
    if due > local:                                  # today is the day, but too early
        due -= timedelta(days=7)
    # Rebuild from the date: the UTC offset may differ from today's (summer time)
    return datetime(due.year, due.month, due.day, hour, tzinfo=zone).timestamp()


def report_due(cfg: dict, now: float, timezone: str, day: str, hour: int) -> float | None:
    """The end of the week to report, if this server's report hasn't been sent for it."""
    if not cfg.get("weekly_report", True):
        return None
    due = latest_report_time(now, timezone, day, hour)
    last = cfg.get("last_report_at")
    return due if last is None or last < due else None


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _between(value: float | None, start: float, end: float) -> bool:
    return value is not None and start <= value < end


def week_stats(tickets: list[dict], start: float, end: float) -> dict:
    """One week: tickets opened, closed, escalated in it; first response of the ones
    opened in it, resolution and rating of the ones closed in it."""
    opened = [t for t in tickets if _between(t.get("opened_at"), start, end)]
    closed = [t for t in tickets if t.get("status") == config.STATUS_CLOSED
              and _between(t.get("closed_at"), start, end)]
    ratings = [t["rating"] for t in closed if t.get("rating")]

    staff: dict[int, dict] = {}
    for t in closed:
        if t.get("claimed_by"):
            s = staff.setdefault(t["claimed_by"], {"closed": 0, "ratings": []})
            s["closed"] += 1
            if t.get("rating"):
                s["ratings"].append(t["rating"])
    top_staff = sorted(({"staff_id": sid, "closed": s["closed"],
                         "avg_rating": _avg(s["ratings"])} for sid, s in staff.items()),
                       key=lambda s: (-s["closed"], -(s["avg_rating"] or 0), s["staff_id"]))
    return {
        "opened": len(opened),
        "closed": len(closed),
        "escalated": sum(1 for t in tickets if _between(t.get("escalated_at"), start, end)),
        "avg_first_response": _avg([max(0.0, t["first_response_at"] - t["opened_at"])
                                    for t in opened if t.get("first_response_at")]),
        "avg_resolution": _avg([max(0.0, t["closed_at"] - t["opened_at"]) for t in closed]),
        "avg_rating": _avg(ratings),
        "ratings": len(ratings),
        "top_staff": top_staff[:3],
        "top_types": Counter(f"{t['type_emoji']} {t['type_label']}"
                             for t in opened).most_common(3),
    }


def weekly_report(tickets: list[dict], end: float, open_now: int) -> dict:
    """The week before `end` and the one before it. `tickets`: the server's tickets
    opened, closed or escalated in the last two weeks."""
    start = end - WEEK
    return {"start": start, "end": end, "open_now": open_now,
            "week": week_stats(tickets, start, end),
            "previous": week_stats(tickets, start - WEEK, start)}


def change(current: float | None, previous: float | None) -> float | None:
    """How much a number changed since the week before (None: nothing to compare)."""
    if current is None or previous is None:
        return None
    return current - previous
