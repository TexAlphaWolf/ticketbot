"""/privacy: download or delete your own data (Beta4)."""

import asyncio
import json
import sqlite3

import pytest
from conftest import new_store
from test_transcripts_db import MESSAGES, META, NOTES
from test_web_api import GUILD, MEMBER, api, as_user, csrf  # noqa: F401

from ticketbot.core.privacy import PrivacyError, erase_personal_data, export_personal_data
from ticketbot.core.transcripts import dump_transcript

USER, STAFF_MEMBER = 11, 20


async def world(store):
    await store.save_guild(1)
    await store.save_guild(2)
    mine = await store.create_ticket(guild_id=1, channel_id=100, owner_id=USER,
                                     type_key="bug", type_label="Bug", type_emoji="🐞",
                                     opened_at=1000.0, last_activity=1000.0,
                                     subject="Crash", description="At start")
    await store.update_ticket(mine, status="closed", closed_at=2000.0, claimed_by=STAFF_MEMBER,
                              rating=4, channel_deleted=True)
    await store.save_transcript(guild_id=1, ticket_id=mine, channel_name="bug-1",
                                content=dump_transcript(META, MESSAGES, NOTES),
                                created_at=2000.0, archive_channel_id=60,
                                archive_message_id=61)
    await store.add_note(mine, STAFF_MEMBER, "Known bug", 2000.0)
    still_open = await store.create_ticket(guild_id=1, channel_id=101, owner_id=USER,
                                           type_key="bug", type_label="Bug", type_emoji="🐞",
                                           opened_at=3000.0, last_activity=3000.0)
    other = await store.create_ticket(guild_id=1, channel_id=102, owner_id=99,
                                      type_key="bug", type_label="Bug", type_emoji="🐞",
                                      opened_at=1000.0, last_activity=1000.0)
    await store.update_ticket(other, claimed_by=USER)          # USER is staff there
    await store.add_note(other, USER, "User 99 is nice", 1500.0)
    elsewhere = await store.create_ticket(guild_id=2, channel_id=200, owner_id=USER,
                                          type_key="bug", type_label="Bug", type_emoji="🐞",
                                          opened_at=1000.0, last_activity=1000.0)
    await store.track_telegram_message(-5, 70, 1, mine)
    await store.block_user(1, USER, "Spam", 30, 900.0, None)
    await store.set_available(1, USER, True)
    await store.audit(1, USER, "ticket.open", target=f"ticket:{mine}")
    await store.audit(2, USER, "ticket.open")                   # another server
    await store.link_telegram_account(555, USER)
    return mine, still_open, other, elsewhere


def test_export(tmp_path):
    async def go():
        store = await new_store(tmp_path / "ticketbot.db")
        mine, still_open, other, _ = await world(store)
        data = await export_personal_data(store, 1, USER, now=5000.0)
        json.dumps(data)                                         # a valid JSON file
        assert [t["id"] for t in data["tickets"]] == [mine, still_open]  # this server only
        first = data["tickets"][0]
        assert (first["subject"], first["form_answers"], first["rating"]) == \
            ("Crash", "At start", 4)
        assert first["opened_at"] == "1970-01-01T00:16:40+00:00"
        assert first["conversation"][0]["text"] == MESSAGES[0].content
        assert "Known bug" not in json.dumps(data)               # staff notes: not theirs
        assert data["tickets"][1]["conversation"] is None
        assert [t["id"] for t in data["tickets_handled_as_staff"]] == [other]
        assert [n["text"] for n in data["notes_written"]] == ["User 99 is nice"]
        assert data["block"]["reason"] == "Spam"
        assert data["available_for_new_tickets"] is True
        assert [a["action"] for a in data["actions"]] == ["ticket.open"]
        assert data["telegram_account"]["telegram_user_id"] == "555"
        await store.close()

    asyncio.run(go())


def test_erase(tmp_path):
    async def go():
        store = await new_store(tmp_path / "ticketbot.db")
        mine, still_open, other, elsewhere = await world(store)
        with pytest.raises(PrivacyError):
            await erase_personal_data(store, 1, USER)            # an open ticket
        assert await store.get_ticket(mine) is not None          # nothing deleted
        await store.update_ticket(still_open, status="closed", closed_at=4000.0)

        result = await erase_personal_data(store, 1, USER)
        assert result["tickets"] == 2 and result["telegram_account"]
        second, first = result["leftovers"]                     # newest first
        assert first["channel_id"] is None and first["telegram"] == [[-5, 70]]
        assert first["transcripts"][0]["archive_message_id"] == "61"
        assert second["channel_id"] == "101"                    # closed, channel still there
        assert await store.get_ticket(mine) is None and await store.get_ticket(still_open) is None
        assert await store.ticket_transcript(mine) is None
        assert await store.telegram_account_of(USER) is None
        assert not await store.is_available(1, USER)
        # Kept on purpose: the block, the audit log, the ticket handled as staff and its
        # note, and the tickets in other servers
        assert await store.get_block(1, USER, 5000.0) is not None
        assert len(await store.audit_of_actor(1, USER)) == 1
        assert (await store.get_ticket(other))["claimed_by"] == USER
        assert len(await store.notes_by_author(1, USER)) == 1
        assert await store.get_ticket(elsewhere) is not None
        await store.close()

    asyncio.run(go())


def test_dashboard_export_and_delete(api):  # noqa: F811
    base = f"/api/v1/me/guilds/{GUILD}/privacy"
    as_user(api, MEMBER)
    r = api.get(base)
    assert r.status_code == 200
    assert r.headers["content-disposition"] == \
        f'attachment; filename="ticketbot-data-{GUILD}.json"'
    assert r.headers["cache-control"] == "no-store"
    assert [t["number"] for t in r.json()["tickets"]] == [1, 2, 3, 4, 5]

    assert api.delete(base).status_code == 403                    # CSRF
    h = csrf(api)
    assert api.delete(base, headers=h).status_code == 409         # open tickets
    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("UPDATE tickets SET status = 'closed', closed_at = 1 "
                     "WHERE owner_id = ?", (MEMBER,))
    r = api.delete(base, headers=h)
    assert r.status_code == 200 and r.json() == {"tickets": 5}
    assert "tb_session" in r.headers["set-cookie"]                 # cookie cleared
    try:
        kinds = [k for (k,) in conn.execute("SELECT kind FROM bot_commands")]
        actions = [a for (a,) in conn.execute("SELECT action FROM audit_log")]
    finally:
        conn.close()
    assert kinds == ["privacy.cleanup"]                           # the bot cleans Discord
    assert {"privacy.export", "privacy.delete"} <= set(actions)
    assert api.get("/api/v1/auth/me").status_code == 401         # logged out everywhere


def test_bot_cleans_up_after_a_web_delete(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import ticketbot.bot.web_commands as wc
    from ticketbot.bot.client import TicketBot

    done = []

    async def fake_delete(client, guild_id, transcripts, keep=None, channel_id=None,
                          telegram=None):
        done.append((guild_id, channel_id, telegram, len(transcripts)))

    monkeypatch.setattr(wc, "delete_transcript_messages", fake_delete)

    async def go():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        bot = TicketBot(store)
        bot.get_guild = lambda gid: SimpleNamespace(id=gid)
        cid = await store.enqueue_command(1, "privacy.cleanup", USER, {"leftovers": [
            {"channel_id": "101", "telegram": [[-5, 70]], "transcripts": [{}]},
            {"channel_id": None, "telegram": [], "transcripts": []}]})
        await bot.web_commands.coro(bot)
        assert (await store.get_command(cid))["status"] == "done"
        assert done == [(1, 101, [[-5, 70]], 1), (1, None, [], 0)]
        await store.close()

    asyncio.run(go())
