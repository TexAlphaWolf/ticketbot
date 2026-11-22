"""Weekly report (Beta4)."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import new_store

from ticketbot.core.report import WEEK, latest_report_time, report_due, week_stats


def ts(*args) -> float:
    return datetime(*args, tzinfo=UTC).timestamp()


def test_when_the_report_is_due():
    rome = "Europe/Rome"
    # Wednesday 2026-11-18: the report of Monday 16 at 9:00 in Rome (8:00 UTC, winter)
    assert latest_report_time(ts(2026, 11, 18, 12), rome, "monday", 9) == ts(2026, 11, 16, 8)
    # Monday 23 at 7:59 UTC is 8:59 in Rome: still the one of the week before
    assert latest_report_time(ts(2026, 11, 23, 7, 59), rome, "monday", 9) == \
        ts(2026, 11, 16, 8)
    assert latest_report_time(ts(2026, 11, 23, 8), rome, "monday", 9) == ts(2026, 11, 23, 8)
    # Summer time ended on Sunday 25 October: the Monday before was 9:00 CEST (7:00 UTC)
    assert latest_report_time(ts(2026, 10, 25, 12), rome, "monday", 9) == \
        ts(2026, 10, 19, 7)
    assert latest_report_time(ts(2026, 10, 25, 12), rome, "sunday", 9) == \
        ts(2026, 10, 25, 8)
    assert latest_report_time(ts(2026, 11, 20, 23), "UTC", "friday", 23) == \
        ts(2026, 11, 20, 23)

    now = ts(2026, 11, 18, 12)
    due = ts(2026, 11, 16, 8)
    assert report_due({}, now, rome, "monday", 9) == due                 # never sent
    assert report_due({"last_report_at": due - 1}, now, rome, "monday", 9) == due
    assert report_due({"last_report_at": due + 60}, now, rome, "monday", 9) is None
    assert report_due({"weekly_report": False}, now, rome, "monday", 9) is None


def ticket(opened, **values):
    return {"opened_at": opened, "status": values.pop("status", "waiting"),
            "type_label": values.pop("label", "Bug"), "type_emoji": "🐞", **values}


def test_week_numbers():
    end = ts(2026, 11, 23, 8)
    start = end - WEEK
    day = 86400
    tickets = [
        ticket(start + day, first_response_at=start + day + 600, status="closed",
               closed_at=start + 2 * day, claimed_by=1, rating=5),
        ticket(start + day, first_response_at=start + day + 1800, claimed_by=2,
               escalated_at=start + 3 * day, label="Billing"),
        ticket(start - 2 * day, status="closed", closed_at=start + day, claimed_by=1,
               rating=3),                         # opened the week before, closed in this
        ticket(start - 3 * day, first_response_at=start - 3 * day + 60,
               status="closed", closed_at=start - day, claimed_by=2),
        ticket(end + 10),                         # after the week: not counted
    ]
    week = week_stats(tickets, start, end)
    assert (week["opened"], week["closed"], week["escalated"]) == (2, 2, 1)
    assert week["avg_first_response"] == 1200
    assert week["avg_resolution"] == (day + 3 * day) / 2
    assert (week["avg_rating"], week["ratings"]) == (4, 2)
    assert week["top_staff"] == [{"staff_id": 1, "closed": 2, "avg_rating": 4}]
    assert week["top_types"] == [("🐞 Bug", 1), ("🐞 Billing", 1)]
    previous = week_stats(tickets, start - WEEK, start)
    assert (previous["opened"], previous["closed"], previous["avg_first_response"]) == \
        (2, 1, 60)


class Channel:
    def __init__(self, cid):
        self.id, self.mention, self.embeds = cid, f"<#{cid}>", []

    async def send(self, embed=None, **kwargs):
        self.embeds.append(embed)


class FakeTelegram:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_to=None, buttons=None):
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}


def test_reports_are_sent_once_a_week(tmp_path):
    from ticketbot.bot.client import TicketBot
    from ticketbot.bot.report import send_weekly_reports
    from ticketbot.core.settings import Settings

    log, chosen = Channel(70), Channel(80)
    guild = SimpleNamespace(id=1, name="Test & Co", get_member=lambda uid: None,
                            get_channel=lambda cid: {70: log, 80: chosen}.get(cid))
    quiet = SimpleNamespace(id=2, name="Quiet", get_member=lambda uid: None,
                            get_channel=lambda cid: log)
    now = ts(2026, 11, 23, 9)                      # Monday, an hour after 9:00 in Rome

    async def go():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1, log_channel=70, language="it", telegram_chat_id="-5")
        await store.save_guild(2, log_channel=70)                  # no tickets at all
        await store.save_guild(3, log_channel=70, weekly_report=False)
        await store.create_ticket(guild_id=1, channel_id=100, owner_id=11, type_key="b",
                                  type_label="Bug", type_emoji="🐞", opened_at=now - 86400,
                                  last_activity=now)
        bot = TicketBot(store, Settings(_env_file=None, report_timezone="Europe/Rome"))
        bot.telegram = FakeTelegram()
        bot.get_guild = {1: guild, 2: quiet}.get
        bot.get_user = lambda uid: None

        assert await send_weekly_reports(bot, now) == 1
        embed = log.embeds[0]
        assert embed.title == "📊 Report settimanale · Test & Co"
        assert "Aperti: **1** (+1)" in embed.fields[0].value
        assert "Ancora aperti: **1**" in embed.fields[0].value
        chat, text = bot.telegram.sent[0]
        assert chat == "-5" and "<b>Report settimanale · Test &amp; Co</b>" in text
        assert "Aperti: <b>1</b> (+1)" in text
        assert (await store.get_guild(2))["last_report_at"] == now   # empty: skipped
        assert (await store.get_guild(3))["last_report_at"] is None  # turned off

        assert await send_weekly_reports(bot, now + 3600) == 0       # once a week
        await store.save_guild(1, report_channel=80)
        assert await send_weekly_reports(bot, now + WEEK) == 1       # the next Monday
        assert len(chosen.embeds) == 1 and len(log.embeds) == 1
        await store.close()

    asyncio.run(go())


def test_report_settings():
    from ticketbot.core.settings import Settings

    s = Settings(_env_file=None, report_timezone=" Europe/Rome ", report_day="Friday")
    assert (s.report_timezone, s.report_day, s.report_hour) == ("Europe/Rome", "friday", 9)
    for bad in ({"report_timezone": "Mars/Olympus"}, {"report_day": "lunedì"},
                {"report_hour": 24}):
        with pytest.raises(ValueError):
            Settings(_env_file=None, **bad)
