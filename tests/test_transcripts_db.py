"""Transcripts kept in the database (Beta3): the dashboard shows them, deleting the
archive message deletes the ticket everywhere, LEGAL_HOLD_DAYS keeps a hidden copy."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

from conftest import new_store

from ticketbot.core.transcripts import TMessage, dump_transcript, load_transcript

DAY = 86400
META = {"guild": "Test", "channel": "bug-mario-1", "fields": [("Type", "🐞 Bug")]}
MESSAGES = [TMessage(author="Mario", author_id=11, avatar="https://cdn/a.png", color=None,
                     bot=False, created_at=datetime(2026, 11, 21, 12, tzinfo=UTC),
                     content="It **crashes**",
                     embeds=[{"author": "", "title": "T", "description": "D",
                              "fields": [("Game", "3.2")], "footer": "", "color": None}],
                     attachments=[{"filename": "log.txt", "url": "https://cdn/log.txt",
                                   "image": False}],
                     stickers=[{"name": "wave", "id": 99, "url": "u", "image": True}],
                     reactions=[{"emoji": "👍", "id": None, "url": None, "count": 1,
                                 "users": ["Tex"]}])]
NOTES = [{"author": "Tex", "author_id": 3, "text": "Known bug", "created_at": 5.0,
          "id": 1, "ticket_id": 1}]


def test_dump_and_load():
    meta, messages, notes = load_transcript(dump_transcript(META, MESSAGES, NOTES))
    assert meta == META and messages == MESSAGES
    assert notes == [{"author": "Tex", "author_id": "3", "text": "Known bug",
                      "created_at": 5.0}]


async def ticket_with_transcript(store, archive_message=500, now=1000.0):
    tid = await store.create_ticket(guild_id=1, channel_id=archive_message, owner_id=11,
                                    type_key="bug", type_label="Bug", type_emoji="x",
                                    opened_at=now, last_activity=now)
    await store.update_ticket(tid, status="closed", closed_at=now)
    await store.add_note(tid, 3, "note", now)
    await store.save_transcript(guild_id=1, ticket_id=tid, channel_name="bug-mario-1",
                                content=dump_transcript(META, MESSAGES, NOTES),
                                created_at=now, archive_channel_id=70,
                                archive_message_id=archive_message, log_channel_id=60,
                                log_message_id=archive_message + 1)
    return tid


def test_delete_ticket_with_and_without_hold(tmp_path):
    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        first = await ticket_with_transcript(store, 500)
        second = await ticket_with_transcript(store, 600)
        assert (await store.ticket_transcript(first))["channel_name"] == "bug-mario-1"
        assert (await store.transcript_by_archive_message(600))["ticket_id"] == second

        removed = await store.delete_ticket(first)                 # no hold: all gone
        assert removed[0]["archive_message_id"] == 500 and removed[0]["log_message_id"] == 501
        assert await store.get_ticket(first) is None
        assert await store.list_notes(first) == []
        assert await store.held_transcripts() == []

        await store.delete_ticket(second, hold_days=365, now=10 * DAY)
        assert await store.get_ticket(second) is None
        assert await store.ticket_transcript(second) is None       # hidden
        assert await store.transcript_by_archive_message(600) is None
        held = await store.held_transcripts()
        assert len(held) == 1 and held[0]["held_until"] == 375 * DAY
        assert (await store.get_transcript(held[0]["id"]))["content"].startswith('{"v": 1')
        assert await store.purge_held_transcripts(374 * DAY) == 0
        assert await store.purge_held_transcripts(376 * DAY) == 1
        await store.close()

    asyncio.run(scenario())


def test_old_tickets_and_removed_servers(tmp_path):
    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        tid = await ticket_with_transcript(store, 500, now=1000.0)
        await store.mark_channel_deleted(tid)
        assert await store.purge_closed_before(2000.0, hold_days=30, now=3000.0) == 1
        assert [h["held_until"] for h in await store.held_transcripts()] == [3000 + 30 * DAY]

        await ticket_with_transcript(store, 700)
        await store.delete_guild(1)                                # no hold: deleted
        assert len(await store.held_transcripts()) == 1            # the older copy stays
        await store.close()

    asyncio.run(scenario())
    conn = sqlite3.connect(tmp_path / "ticketbot.db")
    content = conn.execute("SELECT content FROM transcripts").fetchone()[0]
    conn.close()
    assert content.startswith("enc:v1:") and "crashes" not in content


def test_archive_deletion_deletes_everywhere(tmp_path):
    from ticketbot.bot.client import TicketBot
    from ticketbot.core.settings import Settings

    deleted = []

    class Channel:
        def __init__(self, cid):
            self.id = cid

        def get_partial_message(self, mid):
            async def delete():
                deleted.append((self.id, mid))
            return SimpleNamespace(delete=delete)

    class TicketChannel:                         # closed, waiting for the reopen window
        id = 500

        async def delete(self, reason=None):
            deleted.append(("channel", self.id))

    guild = SimpleNamespace(id=1, get_channel=lambda cid: Channel(cid) if cid in (60, 70)
                            else None,
                            get_channel_or_thread=lambda cid: TicketChannel()
                            if cid == 500 else None)

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1, archive_channel=70)
        tid = await ticket_with_transcript(store, 500)
        bot = TicketBot(store, Settings(_env_file=None, legal_hold_days=10))
        bot.get_guild = lambda gid: guild
        assert await bot.archive_messages_deleted(1, 60, [500]) == 0   # not the archive
        assert await bot.archive_messages_deleted(1, 70, [12345]) == 0
        assert await bot.archive_messages_deleted(1, 70, [500]) == 1
        assert await store.get_ticket(tid) is None
        # the ticket's channel and the log copy; the archive's message is already gone
        assert deleted == [("channel", 500), (60, 501)]
        assert len(await store.held_transcripts()) == 1  # LEGAL_HOLD_DAYS=10
        entries = await store.audit_entries(1)
        assert entries[0]["action"] == "ticket.delete" and entries[0]["source"] == "discord"
        assert await bot.archive_messages_deleted(1, 70, [500]) == 0   # nothing left
        await store.close()

    asyncio.run(scenario())


def test_held_command(tmp_path, monkeypatch, capsys):
    import base64

    from conftest import TEST_KEY

    from ticketbot import __main__ as cli

    async def prepare():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        tid = await ticket_with_transcript(store)
        await store.delete_ticket(tid, hold_days=30)
        await store.close()

    asyncio.run(prepare())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENCRYPTION_KEY", base64.urlsafe_b64encode(TEST_KEY).decode())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from ticketbot.core.settings import get_settings
    get_settings.cache_clear()
    try:
        assert cli.main(["held"]) == 0
        assert "#bug-mario-1" in capsys.readouterr().out
        assert cli.main(["held", "99"]) == 1
        assert cli.main(["held", "1", "--out", "copy.html"]) == 0
        page = (tmp_path / "copy.html").read_text(encoding="utf-8")
        assert "crashes" in page and "Known bug" in page
    finally:
        get_settings.cache_clear()


def test_saving_the_transcript_refreshes_the_dashboards(tmp_path):
    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        tid = await store.create_ticket(guild_id=1, channel_id=5, owner_id=11, type_key="bug",
                                        type_label="Bug", type_emoji="x", opened_at=1.0,
                                        last_activity=1.0)
        await store.update_ticket(tid, status="closed", closed_at=1.0)
        before = await store.tickets_version(1)
        await asyncio.sleep(0.01)
        await store.save_transcript(guild_id=1, ticket_id=tid, channel_name="bug-1",
                                    content=dump_transcript(META, MESSAGES, NOTES),
                                    created_at=2.0)
        assert await store.tickets_version(1) != before
        await store.close()

    asyncio.run(scenario())


def test_web_deletion_removes_the_channel_left_open(tmp_path):
    from ticketbot.bot.client import TicketBot

    deleted = []

    class TicketChannel:
        def __init__(self, cid):
            self.id = cid

        async def delete(self, reason=None):
            deleted.append(self.id)

    member = SimpleNamespace(id=9, guild_permissions=SimpleNamespace(administrator=True),
                             roles=[])
    guild = SimpleNamespace(id=1, owner_id=9, get_member=lambda uid: member,
                            get_channel=lambda cid: None,
                            get_channel_or_thread=lambda cid: TicketChannel(cid)
                            if cid == 800 else None)

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1, staff_role=5)
        bot = TicketBot(store)
        bot.get_guild = lambda gid: guild
        ok = await store.enqueue_command(1, "transcript.delete_messages", 9,
                                         {"channel_id": "800", "transcripts": []})
        gone = await store.enqueue_command(1, "transcript.delete_messages", 9,
                                           {"channel_id": "801", "transcripts": []})
        await bot.web_commands.coro(bot)
        assert [(await store.get_command(c))["status"] for c in (ok, gone)] == ["done"] * 2
        assert deleted == [800]
        await store.close()

    asyncio.run(scenario())


def test_embed_author_and_footer():
    from dataclasses import replace

    from ticketbot.core.transcripts import render_html

    # Saved before 3.0.0b3: no author and footer, loaded as empty
    before = replace(MESSAGES[0], embeds=[{"title": "T", "description": "D", "fields": [],
                                           "color": None}])
    _, old, _ = load_transcript(dump_transcript(META, [before], NOTES))
    assert (old[0].embeds[0]["author"], old[0].embeds[0]["footer"]) == ("", "")
    staff_answer = replace(MESSAGES[0], embeds=[{
        "author": "WerewolfTex", "title": "", "description": "We are on it", "fields": [],
        "footer": "Sent from the web dashboard", "color": None}])
    _, new, _ = load_transcript(dump_transcript(META, [staff_answer], []))
    assert new[0].embeds[0]["author"] == "WerewolfTex"
    html = render_html(META, new, [], lambda key, **kw: key).decode()
    assert "<div class='ea'>WerewolfTex</div>" in html
    assert "<div class='efoot'>Sent from the web dashboard</div>" in html
