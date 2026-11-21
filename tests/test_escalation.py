"""Escalation levels above the normal staff (Beta2)."""

import asyncio
from types import SimpleNamespace

import discord
from conftest import new_store

from ticketbot.bot.common import is_ticket_staff
from ticketbot.bot.tickets import escalate, ticket_roles
from ticketbot.core.logic import auto_escalation_level

HOUR = 3600
T0 = 1_000_000.0


def test_escalation_levels_storage(db):
    db.save_guild(1, staff_role=5)
    assert db.escalation_levels(1) == []
    assert db.add_escalation_level(1, 30, None) == 1
    assert db.add_escalation_level(1, 40, 24) == 2
    assert db.add_escalation_level(1, 50, 48) == 3
    assert [(lv["level"], lv["role_id"], lv["after_hours"])
            for lv in db.escalation_levels(1)] == [(1, 30, None), (2, 40, 24), (3, 50, 48)]
    assert db.remove_escalation_level(1, 2) and not db.remove_escalation_level(1, 7)
    assert [(lv["level"], lv["role_id"]) for lv in db.escalation_levels(1)] == \
        [(1, 30), (2, 50)]                              # level 3 moved down
    assert db.add_escalation_level(1, 60, None) == 3
    db.delete_guild(1)
    assert db.count("escalation_levels") == 0


def test_ticket_starts_at_level_zero(db):
    db.save_guild(1)
    tid = db.create_ticket(guild_id=1, channel_id=5, owner_id=2, type_key="b", type_label="B",
                           type_emoji="x", opened_at=1.0, last_activity=1.0)
    ticket = db.get_ticket(tid)
    assert ticket["escalation_level"] == 0 and ticket["escalated_at"] is None


def test_auto_escalation_level():
    levels = [{"level": 1, "after_hours": None}, {"level": 2, "after_hours": 24},
              {"level": 3, "after_hours": 48}]
    waiting = {"status": "waiting", "last_actor": "user", "awaiting_staff_since": T0,
               "escalation_level": 0}
    assert auto_escalation_level(waiting, levels, T0 + 23 * HOUR) is None
    assert auto_escalation_level(waiting, levels, T0 + 24 * HOUR) == 2      # level 1 is manual
    assert auto_escalation_level(waiting, levels, T0 + 50 * HOUR) == 3      # skips to the top
    assert auto_escalation_level({**waiting, "escalation_level": 3}, levels,
                                 T0 + 99 * HOUR) is None                    # never goes down
    assert auto_escalation_level({**waiting, "last_actor": "staff"}, levels,
                                 T0 + 99 * HOUR) is None                    # staff answered
    assert auto_escalation_level({**waiting, "status": "closed"}, levels, T0 + 99 * HOUR) is None
    assert auto_escalation_level(waiting, [], T0 + 99 * HOUR) is None


def test_escalation_roles_count_as_staff_of_the_ticket(tmp_path, monkeypatch):
    class Member(SimpleNamespace):
        pass

    monkeypatch.setattr(discord, "Member", Member)
    manager = Member(roles=[SimpleNamespace(id=40)],
                     guild_permissions=SimpleNamespace(administrator=False))
    cfg = {"staff_role": 5}

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1, staff_role=5)
        await store.add_escalation_level(1, 30, None)
        await store.add_escalation_level(1, 40, None)
        ticket = {"guild_id": 1, "type_key": "bug", "escalation_level": 1}
        assert await ticket_roles(store, ticket) == ([], [30])
        assert not is_ticket_staff(manager, cfg, *await ticket_roles(store, ticket))
        ticket["escalation_level"] = 2
        assert await ticket_roles(store, ticket) == ([], [30, 40])
        assert is_ticket_staff(manager, cfg, *await ticket_roles(store, ticket))
        await store.close()

    asyncio.run(scenario())


class Sink:
    """A channel or thread that records what the bot does with it."""

    def __init__(self, cid):
        self.id, self.mention, self.sent, self.perms = cid, f"<#{cid}>", [], []

    async def send(self, text, **kwargs):
        self.sent.append(text)

    async def set_permissions(self, target, **kwargs):
        self.perms.append((target.id, kwargs))

    def overwrites_for(self, role):
        return discord.PermissionOverwrite()


def test_escalate_in_a_channel_and_in_a_thread(tmp_path, monkeypatch):
    class Thread(Sink):
        pass

    monkeypatch.setattr(discord, "Thread", Thread)
    role = SimpleNamespace(id=40, name="Managers", mention="<@&40>")
    panel, log = Sink(200), Sink(300)
    guild = SimpleNamespace(id=1, name="Test",
                            get_role=lambda rid: role if rid == 40 else None,
                            get_channel=lambda cid: {200: panel, 300: log}.get(cid))
    actor = SimpleNamespace(id=10, mention="<@10>")
    cfg = {"language": "en", "panel_channel": 200, "log_channel": 300}

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1, staff_role=5)
        await store.add_escalation_level(1, 40, 24)
        await store.add_escalation_level(1, 99, None)        # role deleted on Discord
        bot = SimpleNamespace(db=store, telegram=None)

        tid = await store.create_ticket(guild_id=1, channel_id=100, owner_id=11, type_key="b",
                                        type_label="B", type_emoji="x", opened_at=1.0,
                                        last_activity=1.0)
        channel = Sink(100)
        ticket = await store.get_ticket(tid)
        assert await escalate(bot, guild, channel, ticket, cfg, 1, actor, "Refund over 100€")
        assert channel.perms[0][0] == 40 and channel.perms[0][1]["view_channel"]
        assert "level 1" in channel.sent[0] and "<@&40>" in channel.sent[0]
        assert "Refund over 100€" in channel.sent[0]
        stored = await store.get_ticket(tid)
        assert stored["escalation_level"] == 1 and stored["escalated_at"]
        assert not await escalate(bot, guild, channel, stored, cfg, 2, actor, None)
        assert (await store.get_ticket(tid))["escalation_level"] == 1

        tid2 = await store.create_ticket(guild_id=1, channel_id=101, owner_id=11,
                                         type_key="b", type_label="B", type_emoji="x",
                                         opened_at=1.0, last_activity=1.0, is_thread=True)
        thread = Thread(101)
        assert await escalate(bot, guild, thread, await store.get_ticket(tid2), cfg, 1,
                              None, None)                   # automatic
        assert panel.perms[0][0] == 40                      # Manage Threads in the panel
        assert "automatically" in thread.sent[0]
        assert "<#101>" in log.sent[0] and "<@&40>" in log.sent[0]   # pings reach the log

        entries = await store.audit_entries(1)
        assert [(e["action"], e["source"], e["actor_id"]) for e in entries] == [
            ("ticket.escalate", "system", None), ("ticket.escalate", "discord", 10)]
        await store.close()

    asyncio.run(scenario())
