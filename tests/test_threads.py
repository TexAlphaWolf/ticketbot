"""Tickets as private threads (Beta2)."""

import asyncio
import sqlite3
from types import SimpleNamespace

import discord

from ticketbot.bot.commands import missing_thread_permissions
from ticketbot.bot.common import ticket_channel


class Guild:
    def __init__(self, cached=None, archived=None):
        self.cached, self.archived, self.fetched = cached or {}, archived or {}, []

    def get_channel_or_thread(self, cid):
        return self.cached.get(cid)

    async def fetch_channel(self, cid):
        self.fetched.append(cid)
        if cid in self.archived:
            return self.archived[cid]
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "gone")


def test_ticket_channel_finds_archived_threads_only_for_threads():
    guild = Guild(cached={1: "channel"}, archived={2: "archived thread"})

    async def scenario():
        assert await ticket_channel(guild, {"channel_id": 1, "is_thread": False}) == "channel"
        assert await ticket_channel(guild, {"channel_id": 2, "is_thread": True}) == \
            "archived thread"
        assert await ticket_channel(guild, {"channel_id": 3, "is_thread": True}) is None
        assert await ticket_channel(guild, {"channel_id": 4, "is_thread": False}) is None

    asyncio.run(scenario())
    assert guild.fetched == [2, 3]       # channels are never fetched: no API call


def test_thread_mode_setting_and_ticket_flag(db):
    assert db.save_guild(1)["ticket_mode"] == "channel"
    assert db.save_guild(1, ticket_mode="thread")["ticket_mode"] == "thread"
    tid = db.create_ticket(guild_id=1, channel_id=5, owner_id=2, type_key="b", type_label="B",
                           type_emoji="x", opened_at=1.0, last_activity=1.0, is_thread=True)
    assert db.get_ticket(tid)["is_thread"] is True


def test_tickets_keep_autoincrement_after_all_migrations(db):
    conn = sqlite3.connect(db.path)
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'tickets'").fetchone()[0]
    conn.close()
    assert "AUTOINCREMENT" in sql


def test_missing_thread_permissions():
    perms = SimpleNamespace(create_private_threads=True, send_messages_in_threads=False,
                            manage_threads=False)
    panel = SimpleNamespace(permissions_for=lambda me: perms)
    assert missing_thread_permissions(panel, None) == ["Send Messages in Threads",
                                                       "Manage Threads"]
    perms.send_messages_in_threads = perms.manage_threads = True
    assert missing_thread_permissions(panel, None) == []
