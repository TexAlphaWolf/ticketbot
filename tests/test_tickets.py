import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ticketbot as tb  # noqa: E402

HOUR = 3600


def make_ticket(last_actor, idle_hours, warned=False, now=1_000_000.0):
    ticket = tb.new_ticket_state(1, "bug", "test", now - 48 * HOUR)
    ticket["last_actor"] = last_actor
    ticket["last_activity"] = now - idle_hours * HOUR
    ticket["warned"] = warned
    return ticket, now


def test_waiting_on_staff_is_never_closed():
    ticket, now = make_ticket("user", 100)
    assert tb.autoclose_action(ticket, now) is None


def test_new_ticket_without_messages_is_never_closed():
    ticket, now = make_ticket(None, 100)
    assert tb.autoclose_action(ticket, now) is None


def test_recent_staff_reply_does_nothing():
    ticket, now = make_ticket("staff", 2)
    assert tb.autoclose_action(ticket, now) is None


def test_warning_before_closing():
    hours = tb.AUTO_CLOSE_HOURS - tb.WARNING_HOURS_BEFORE
    ticket, now = make_ticket("staff", hours)
    assert tb.autoclose_action(ticket, now) == "warn"


def test_warning_is_sent_only_once():
    hours = tb.AUTO_CLOSE_HOURS - tb.WARNING_HOURS_BEFORE + 1
    ticket, now = make_ticket("staff", hours, warned=True)
    assert tb.autoclose_action(ticket, now) is None


def test_closes_after_timeout_without_user_reply():
    ticket, now = make_ticket("staff", tb.AUTO_CLOSE_HOURS, warned=True)
    assert tb.autoclose_action(ticket, now) == "close"


def test_queue_counts():
    cfg = {"tickets": {
        "1": {"status": tb.STATUS_WAITING},
        "2": {"status": tb.STATUS_WAITING},
        "3": {"status": tb.STATUS_IN_PROGRESS},
    }}
    assert tb.queue_counts(cfg) == (2, 1)
    assert tb.queue_counts({}) == (0, 0)


DAY = 86400


def test_high_priority_is_kept():
    assert tb.is_kept("high")
    assert not tb.is_kept("medium")
    assert not tb.is_kept("low")
    assert not tb.is_kept(None)


def test_expired_transcripts_respect_retention_and_priority():
    now = 10_000_000.0
    entries = [
        {"message": 1, "priority": "low", "closed_at": now - 31 * DAY},
        {"message": 2, "priority": "medium", "closed_at": now - 31 * DAY},
        {"message": 3, "priority": None, "closed_at": now - 31 * DAY},
        {"message": 4, "priority": "low", "closed_at": now - 5 * DAY},
        {"message": 5, "priority": "high", "closed_at": now - 400 * DAY},
    ]
    expired = [e["message"] for e in tb.expired_transcripts(entries, now, 30)]
    assert expired == [1, 2, 3]


def test_priority_label():
    assert tb.priority_label("high") == "🔴 High"
    assert tb.priority_label(None) == "⚪ Not set"
