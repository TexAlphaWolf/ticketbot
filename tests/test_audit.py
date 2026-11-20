"""Audit log and the queue of actions asked from the web dashboard."""

import asyncio
from types import SimpleNamespace

import pytest
from conftest import new_store, unused_store

from ticketbot.core.i18n import t


def test_audit_log_storage(db):
    db.save_guild(1)
    db.audit(1, 10, "settings.language", details={"value": "it"}, now=100.0)
    db.audit(1, None, "ticket.close", source="system", target="ticket:5",
             details={"reason": "No reply"}, now=200.0)
    db.audit(2, 11, "type.add", now=300.0)
    entries = db.audit_entries(1)
    assert [e["action"] for e in entries] == ["ticket.close", "settings.language"]
    assert entries[0]["details"] == {"reason": "No reply"} and entries[0]["source"] == "system"
    assert entries[1]["details"] == {"value": "it"}
    assert [e["action"] for e in db.audit_entries(1, limit=1, before_id=entries[0]["id"])] \
        == ["settings.language"]
    # Details are personal data: encrypted on disk
    stored = db.count("audit_log")
    assert stored == 3
    import sqlite3
    conn = sqlite3.connect(db.path)
    raw = conn.execute("SELECT details FROM audit_log WHERE action = 'ticket.close'").fetchone()
    conn.close()
    assert raw[0].startswith("enc:v1:") and "No reply" not in raw[0]

    assert db.purge_audit_before(150.0) == 1
    db.delete_guild(1)                                   # a server's data goes with it
    assert db.audit_entries(1) == [] and len(db.audit_entries(2)) == 1


def test_command_queue(db):
    db.save_guild(1)
    first = db.enqueue_command(1, "ticket.close", 10, {"ticket_id": 5, "reason": "done"})
    second = db.enqueue_command(1, "panel.refresh", 10)
    taken = db.take_commands()
    assert [c["id"] for c in taken] == [first, second]
    assert taken[0]["payload"] == {"ticket_id": 5, "reason": "done"}
    assert db.take_commands() == []                      # nobody takes them twice
    db.finish_command(first, True, "ok")
    assert db.reset_running_commands() == 1              # the second one, after a crash
    assert [c["id"] for c in db.take_commands()] == [second]
    db.finish_command(second, False, "boom")
    assert db.get_command(first)["status"] == "done"
    assert db.get_command(second)["status"] == "failed"
    assert db.purge_finished_commands(10**12) == 2


class FakeGuild:
    def __init__(self, members):
        self.id = 1
        self._members = members
        self.channels = {}

    def get_channel(self, cid):
        return self.channels.get(cid)

    get_channel_or_thread = get_channel

    def get_member(self, uid):
        return self._members.get(uid)

    async def fetch_member(self, uid):
        raise LookupError(f"member {uid} not found")


def test_web_commands_run_on_discord(tmp_path, monkeypatch):
    import discord

    from ticketbot.bot import client as client_module
    from ticketbot.bot.client import TicketBot

    class Member(SimpleNamespace):
        pass

    monkeypatch.setattr(discord, "Member", Member)
    staff = Member(id=10, roles=[SimpleNamespace(id=5)],
                   guild_permissions=SimpleNamespace(administrator=False))
    user = Member(id=11, roles=[], guild_permissions=SimpleNamespace(administrator=False))
    guild = FakeGuild({10: staff, 11: user})
    guild.channels[100] = SimpleNamespace(id=100)
    closed, refreshed = [], []

    async def fake_close(bot, channel, ticket, member, reason, source=None):
        closed.append((ticket["id"], member.id, reason, source))

    async def fake_refresh(bot, g, cfg):
        refreshed.append(g.id)

    monkeypatch.setattr(client_module, "close_ticket", fake_close)
    monkeypatch.setattr(client_module, "refresh_panel", fake_refresh)

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1, staff_role=5)
        tid = await store.create_ticket(guild_id=1, channel_id=100, owner_id=11, type_key="b",
                                        type_label="B", type_emoji="x", opened_at=1.0,
                                        last_activity=1.0)
        bot = TicketBot(store)
        bot.get_guild = lambda gid: guild if gid == 1 else None
        ids = [
            await store.enqueue_command(1, "ticket.close", 10, {"ticket_id": tid,
                                                                "reason": "Solved"}),
            await store.enqueue_command(1, "ticket.close", 11, {"ticket_id": tid}),
            await store.enqueue_command(1, "panel.refresh", 10),
            await store.enqueue_command(1, "launch.rockets", 10),
        ]
        await bot.web_commands.coro(bot)
        results = [await store.get_command(i) for i in ids]
        assert [r["status"] for r in results] == ["done", "failed", "done", "failed"]
        assert "only staff" in results[1]["result"]
        assert "unknown command" in results[3]["result"]
        assert closed == [(tid, 10, "Solved", "web")]
        assert refreshed == [1]
        await store.close()

    asyncio.run(scenario())


def test_audit_command_lines():
    from ticketbot.bot.commands import audit_lines

    _ = lambda key, /, **kw: t("en", key, **kw)  # noqa: E731
    lines = audit_lines([
        {"actor_id": 10, "source": "discord", "action": "block.add", "target": "user:7",
         "created_at": 1000.0},
        {"actor_id": None, "source": "system", "action": "ticket.close",
         "target": "ticket:3", "created_at": 2000.0},
        {"actor_id": 12, "source": "web", "action": "settings.language", "target": None,
         "created_at": 3000.0},
    ], _)
    assert lines[0] == "<t:1000:R> · <@10> · **block.add** · `user:7`"
    assert lines[1] == "<t:2000:R> · TicketBot (system) · **ticket.close** · `ticket:3`"
    assert lines[2] == "<t:3000:R> · <@12> (web) · **settings.language**"


def test_bot_builds_with_audit_command():
    from ticketbot.bot.client import TicketBot
    from ticketbot.bot.commands import all_commands

    bot = TicketBot(unused_store())
    for command in all_commands():
        bot.tree.add_command(command)
    assert bot.tree.get_command("audit") is not None


@pytest.mark.parametrize("lang", ["en", "it", "de"])
def test_audit_texts(lang):
    assert "{days}" not in t(lang, "audit.footer", days=365)
