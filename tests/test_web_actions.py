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


def test_admin_commands(tmp_path, world, monkeypatch):
    import ticketbot.bot.web_commands as wc

    world.members[20] = Member(id=20, display_name="Admin", bot=False, roles=[],
                               guild_permissions=SimpleNamespace(administrator=True))
    panel = SimpleNamespace(id=7, name="tickets")
    world.channels[7] = panel
    world.me = SimpleNamespace(id=999)
    granted = []

    async def fake_grant(channel, roles):
        granted.append([r.id for r in roles if r is not None])
        return []

    monkeypatch.setattr(wc, "grant_thread_access", fake_grant)
    missing = {"value": ["Manage Threads"]}
    monkeypatch.setattr(wc, "missing_thread_permissions", lambda p, me: missing["value"])

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD, staff_role=5, panel_channel=7)
        bot = TicketBot(store)
        bot.get_guild = lambda gid: world

        async def run_one(kind, by, payload):
            cid = await store.enqueue_command(GUILD, kind, by, payload)
            await bot.web_commands.coro(bot)
            c = await store.get_command(cid)
            return c["status"], c["result"]

        assert await run_one("settings.mode", 10, {"mode": "thread"}) == \
            ("failed", "only admins can change this")
        assert await run_one("settings.mode", 20, {"mode": "thread"}) == \
            ("failed", "the bot needs these permissions in #tickets: Manage Threads")
        missing["value"] = []
        assert await run_one("settings.mode", 20, {"mode": "thread"}) == ("done", "ok")
        assert (await store.get_guild(GUILD))["ticket_mode"] == "thread"
        assert granted == [[]]               # staff role 5 isn't a role of this fake guild
        assert await run_one("thread.access", 20, {"role_ids": ["40"]}) == ("done", "ok")
        assert granted[-1] == [40]
        assert await run_one("settings.mode", 20, {"mode": "channel"}) == ("done", "ok")
        assert (await store.get_guild(GUILD))["ticket_mode"] == "channel"
        await store.close()

    asyncio.run(scenario())


def test_panel_refresh_needs_a_known_panel(tmp_path, world):
    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD, staff_role=5)            # set up by TicketBot 1
        bot = TicketBot(store)
        bot.get_guild = lambda gid: world
        cid = await store.enqueue_command(GUILD, "panel.refresh", 10)
        await bot.web_commands.coro(bot)
        c = await store.get_command(cid)
        assert c["status"] == "failed" and "press 'Open ticket'" in c["result"]
        await store.close()

    asyncio.run(scenario())


def test_open_button_teaches_the_bot_its_panel(tmp_path, world):
    from ticketbot.bot.tickets import TicketPanel

    edited = []
    panel_channel = SimpleNamespace(
        id=7, get_partial_message=lambda mid: SimpleNamespace(
            edit=lambda **kw: _record(edited, mid)))
    world.channels[7] = panel_channel

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD, staff_role=5, category=6)
        bot = TicketBot(store)
        sent = []

        async def send_message(*a, **kw):
            sent.append(a)

        interaction = SimpleNamespace(
            client=bot, guild=world, channel=panel_channel, message=SimpleNamespace(id=555),
            user=Member(id=11, display_name="User", bot=False, roles=[],
                        guild_permissions=SimpleNamespace(administrator=False)),
            response=SimpleNamespace(send_message=send_message))
        await TicketPanel().open_btn.callback(interaction)
        cfg = await store.get_guild(GUILD)
        assert (cfg["panel_channel"], cfg["panel_message"]) == (7, 555)
        assert edited == [555]                                  # and updated it at once
        interaction.message = SimpleNamespace(id=777)           # an older panel: ignored
        await TicketPanel().open_btn.callback(interaction)
        assert (await store.get_guild(GUILD))["panel_message"] == 555
        await store.close()

    asyncio.run(scenario())


async def _record(where, value):
    where.append(value)


def test_open_from_the_web(tmp_path, world, monkeypatch):
    import ticketbot.bot.web_commands as wc
    from ticketbot.bot.tickets import OpenError

    opened = []

    async def fake_create(client, guild, member, ticket_type, subject, description, *,
                          source="discord", attachments=None):
        if subject == "blocked":
            raise OpenError("⏳ Wait until <t:1795300000:R> in <#100>, **please**")
        opened.append((member.id, ticket_type["key"], subject, description, source))
        return SimpleNamespace(id=4242), "queue"

    monkeypatch.setattr(wc, "create_ticket", fake_create)

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD, staff_role=5)
        await store.add_type(GUILD, "bug", "Bug", "🐞", "")
        bot = TicketBot(store)
        bot.get_guild = lambda gid: world

        async def run_one(by, payload):
            cid = await store.enqueue_command(GUILD, "ticket.open", by, payload)
            await bot.web_commands.coro(bot)
            c = await store.get_command(cid)
            return c["status"], c["result"]

        ok = {"type_key": "bug", "subject": "Crash", "description": "At start"}
        assert await run_one(13, ok) == ("done", "channel:4242")
        assert opened == [(13, "bug", "Crash", "At start", "web")]
        assert await run_one(99, ok) == ("failed", "you are not a member of this server")
        assert await run_one(13, {**ok, "type_key": "gone"}) == \
            ("failed", "this ticket type doesn't exist anymore")
        status, result = await run_one(13, {**ok, "subject": "blocked"})
        assert status == "failed"
        assert result == "⏳ Wait until 2026-11-21 22:26 UTC in #t-100, please"
        await store.close()

    asyncio.run(scenario())
