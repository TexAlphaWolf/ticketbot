"""The bot carries out the actions queued by the web dashboard (Beta3)."""

import asyncio
from types import SimpleNamespace

import discord
import pytest
from conftest import new_store

from ticketbot.bot.client import TicketBot

GUILD = 1


class Member(SimpleNamespace):
    @property
    def mention(self):
        return f"<@{self.id}>"

    @property
    def display_avatar(self):
        return SimpleNamespace(url=f"https://cdn.example/{self.id}.png")

    def __str__(self):
        return self.display_name


class Channel:
    def __init__(self, guild, cid):
        self.guild, self.id, self.name, self.mention = guild, cid, f"t-{cid}", f"<#{cid}>"
        self.sent = []
        self.perms = []

    async def send(self, content=None, **kwargs):
        self.sent.append(content if content is not None else kwargs.get("embed"))

    async def set_permissions(self, target, **kwargs):
        self.perms.append(target.id)


class Guild:
    def __init__(self, members, roles):
        self.id, self.name = GUILD, "Test"
        self.members, self.roles, self.channels = members, roles, {}

    def get_member(self, uid):
        return self.members.get(uid)

    async def fetch_member(self, uid):
        raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "unknown member")

    def get_channel(self, cid):
        return self.channels.get(cid)

    get_channel_or_thread = get_channel

    def get_role(self, rid):
        return self.roles.get(rid)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(discord, "Member", Member)

    def member(uid, *roles):
        return Member(id=uid, display_name=f"Staff{uid}", bot=False,
                      roles=[SimpleNamespace(id=r) for r in roles],
                      guild_permissions=SimpleNamespace(administrator=False))

    members = {10: member(10, 5), 12: member(12, 5), 13: member(13), 14: member(14, 40)}
    roles = {40: SimpleNamespace(id=40, name="Managers", mention="<@&40>")}
    guild = Guild(members, roles)
    guild.channels[100] = Channel(guild, 100)
    return guild


def run(tmp_path, guild, commands, check):
    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD, staff_role=5, language="en")
        await store.add_escalation_level(GUILD, 40, None)
        tid = await store.create_ticket(guild_id=GUILD, channel_id=100, owner_id=11,
                                        type_key="b", type_label="B", type_emoji="x",
                                        opened_at=1.0, last_activity=1.0,
                                        awaiting_staff_since=1.0)
        bot = TicketBot(store)
        bot.get_guild = lambda gid: guild if gid == GUILD else None
        ids = [await store.enqueue_command(GUILD, kind, by, {"ticket_id": tid, **payload})
               for kind, by, payload in commands]
        await bot.web_commands.coro(bot)
        results = [await store.get_command(i) for i in ids]
        await check(store, tid, [(r["status"], r["result"]) for r in results])
        await store.close()

    asyncio.run(scenario())


def test_claim_priority_transfer(tmp_path, world):
    channel = world.channels[100]

    async def check(store, tid, results):
        assert results == [
            ("done", "ok"),
            ("failed", "the ticket was already claimed"),
            ("done", "ok"),
            ("failed", "that member is not staff for this ticket"),
            ("failed", "you are not staff for this ticket anymore"),
            ("done", "ok"),
            ("failed", "the ticket is already theirs")]
        t = await store.get_ticket(tid)
        assert (t["claimed_by"], t["priority"], t["status"]) == (12, "low", "in_progress")
        assert t["first_response_at"]
        assert "<@10>" in channel.sent[0] and "High" in channel.sent[0]   # claim
        assert "Low" in channel.sent[1]                                   # priority
        assert "<@12>" in channel.sent[2] and "<@10>" in channel.sent[2]  # transfer
        actions = [(e["action"], e["source"]) for e in await store.audit_entries(GUILD)]
        assert actions[::-1] == [("ticket.claim", "web"), ("ticket.priority", "web"),
                                 ("ticket.transfer", "web")]

    run(tmp_path, world, [
        ("ticket.claim", 10, {"priority": "high"}),
        ("ticket.claim", 12, {"priority": "low"}),
        ("ticket.priority", 10, {"priority": "low"}),
        ("ticket.transfer", 10, {"member_id": "13"}),      # not staff
        ("ticket.transfer", 13, {"member_id": "12"}),      # asked by a non-staff member
        ("ticket.transfer", 10, {"member_id": "12"}),
        ("ticket.transfer", 10, {"member_id": "12"}),
    ], check)


def test_message_and_escalation(tmp_path, world):
    channel = world.channels[100]

    async def check(store, tid, results):
        assert results == [("done", "ok"), ("done", "ok"),
                           ("failed", "there is no such escalation level")]
        embed = channel.sent[0]
        assert embed.description == "We are on it" and embed.author.name == "Staff10"
        assert embed.footer.text == "Sent from the web dashboard"
        t = await store.get_ticket(tid)
        assert t["last_actor"] == "staff" and t["first_response_at"]
        assert t["status"] == "in_progress" and t["awaiting_staff_since"] is None
        assert t["escalation_level"] == 1 and channel.perms == [40]
        assert "Refund" in channel.sent[1]

    run(tmp_path, world, [
        ("ticket.message", 10, {"text": "We are on it"}),
        ("ticket.escalate", 10, {"level": 1, "reason": "Refund"}),
        ("ticket.escalate", 10, {}),                        # already at the top
    ], check)


def test_gone_members_and_closed_tickets(tmp_path, world):
    async def check(store, tid, results):
        assert results == [("failed", "you are not staff for this ticket anymore"),
                           ("done", "ok"),
                           ("failed", "the ticket is closed"),
                           ("done", "already closed")]

    async def fake_close(client, channel, ticket, member, reason, source=None):
        await client.db.update_ticket(ticket["id"], status="closed")

    import ticketbot.bot.web_commands as wc
    original = wc.close_ticket
    wc.close_ticket = fake_close
    try:
        run(tmp_path, world, [
            ("ticket.message", 99, {"text": "hi"}),         # left the server
            ("ticket.close", 10, {}),
            ("ticket.message", 10, {"text": "late"}),
            ("ticket.close", 10, {}),
        ], check)
    finally:
        wc.close_ticket = original
