import asyncio
import json
import re
import string
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from conftest import SyncStore, new_store, unused_store  # noqa: E402

from ticketbot.core import config, logic  # noqa: E402
from ticketbot.core.i18n import COMMAND_TEXT, DEFAULT_TYPES, LANGUAGES, STRINGS, t  # noqa: E402
from ticketbot.core.transcripts import (  # noqa: E402
    TMessage,
    markdown_to_html,
    render_html,
    render_txt,
)
from ticketbot.db.legacy import migrate_legacy_config  # noqa: E402

HOUR = 3600
DAY = 86400


def new_ticket(db, guild_id=1, owner_id=10, channel_id=100, now=1_000_000.0, **extra):
    db.save_guild(guild_id)
    fields = dict(guild_id=guild_id, channel_id=channel_id, owner_id=owner_id,
                  type_key="bug", type_label="Bug report", type_emoji="🐞",
                  subject="Crash", description="It crashes", opened_at=now,
                  last_activity=now)
    fields.update(extra)
    return db.create_ticket(**fields)


# ------------------------------------------------------------------ logic ---

def ticket_state(last_actor, idle_hours, warned=0, status="in_progress", now=1_000_000.0):
    return {"status": status, "last_actor": last_actor,
            "last_activity": now - idle_hours * HOUR, "warned": warned}, now


def test_waiting_on_staff_is_never_closed():
    ticket, now = ticket_state("user", 100)
    assert logic.autoclose_action(ticket, now) is None


def test_new_ticket_without_messages_is_never_closed():
    ticket, now = ticket_state(None, 100)
    assert logic.autoclose_action(ticket, now) is None


def test_closed_ticket_is_ignored():
    ticket, now = ticket_state("staff", 100, status="closed")
    assert logic.autoclose_action(ticket, now) is None


def test_warning_then_close():
    hours = config.AUTO_CLOSE_HOURS - config.WARNING_HOURS_BEFORE
    assert logic.autoclose_action(*ticket_state("staff", 2)) is None
    assert logic.autoclose_action(*ticket_state("staff", hours)) == "warn"
    assert logic.autoclose_action(*ticket_state("staff", hours + 1, warned=1)) is None
    assert logic.autoclose_action(*ticket_state("staff", config.AUTO_CLOSE_HOURS,
                                                warned=1)) == "close"


def test_expired_refs_respect_retention_and_priority():
    now = 10_000_000.0
    refs = [
        {"message_id": 1, "priority": "low", "closed_at": now - 31 * DAY},
        {"message_id": 2, "priority": "medium", "closed_at": now - 31 * DAY},
        {"message_id": 3, "priority": None, "closed_at": now - 31 * DAY},
        {"message_id": 4, "priority": "low", "closed_at": now - 5 * DAY},
        {"message_id": 5, "priority": "high", "closed_at": now - 400 * DAY},
    ]
    assert [r["message_id"] for r in logic.expired_refs(refs, now, 30)] == [1, 2, 3]


def test_slugify():
    assert logic.slugify("Bug Report!") == "bug-report"
    assert logic.slugify("Segnalazione è già") == "segnalazione-e-gia"
    assert logic.slugify("🐞") == ""
    assert len(logic.slugify("x" * 50)) == 20


def test_format_duration():
    assert logic.format_duration(None) == "-"
    assert logic.format_duration(10) == "<1m"
    assert logic.format_duration(5 * 60) == "5m"
    assert logic.format_duration(2 * HOUR + 15 * 60) == "2h 15m"
    assert logic.format_duration(3 * DAY + 4 * HOUR) == "3d 4h"


@pytest.mark.parametrize("emoji, ok", [
    ("🐞", True), ("🛠️", True), ("❤️", True), ("1️⃣", True), ("<:wolf:123456789012345678>", True),
    ("abc", False), ("", False), ("#", False), ("a🐞", False),
])
def test_valid_emoji(emoji, ok):
    assert logic.valid_emoji(emoji) is ok


def test_compute_stats():
    base = 1_000_000.0
    rows = [
        dict(status="closed", type_emoji="🐞", type_label="Bug", priority="high", claimed_by=7,
             opened_at=base, first_response_at=base + 600, closed_at=base + 3600, rating=5),
        dict(status="closed", type_emoji="🐞", type_label="Bug", priority="low", claimed_by=7,
             opened_at=base, first_response_at=base + 1200, closed_at=base + 7200, rating=3),
        dict(status="in_progress", type_emoji="🛠️", type_label="Support", priority=None,
             claimed_by=8, opened_at=base, first_response_at=base + 60, closed_at=None,
             rating=None),
        dict(status="waiting", type_emoji="🛠️", type_label="Support", priority=None,
             claimed_by=None, opened_at=base, first_response_at=None, closed_at=None,
             rating=None),
    ]
    s = logic.compute_stats(rows)
    assert (s["opened"], s["closed"], s["open"], s["unclaimed"]) == (4, 2, 2, 1)
    assert s["avg_rating"] == 4 and s["ratings"] == 2
    assert s["avg_first_response"] == pytest.approx((600 + 1200 + 60) / 3)
    assert s["avg_resolution"] == pytest.approx((3600 + 7200) / 2)
    assert s["by_type"]["🐞 Bug"] == 2
    assert s["leaderboard"][0]["staff_id"] == 7 and s["leaderboard"][0]["handled"] == 2
    mine = logic.compute_stats(rows, staff_id=8)
    assert mine["opened"] == 1 and mine["leaderboard"][0]["staff_id"] == 8


# --------------------------------------------------------------- database ---

def test_guild_settings_and_counter(db):
    cfg = db.save_guild(1, language="it", staff_role=5)
    assert cfg["language"] == "it" and cfg["retention_days"] == config.DEFAULT_RETENTION_DAYS
    assert db.next_ticket_number(1) == 1
    assert db.next_ticket_number(1) == 2
    with pytest.raises(ValueError):
        db.save_guild(1, unknown_field=1)


def test_ticket_types(db):
    db.save_guild(1)
    db.ensure_default_types(1, DEFAULT_TYPES["de"])
    db.ensure_default_types(1, DEFAULT_TYPES["en"])  # no duplicates
    types = db.list_types(1)
    assert [t["key"] for t in types] == ["support", "bug", "report", "other"]
    assert types[1]["label"] == "Fehlermeldung"
    db.add_type(1, "billing", "Billing", "💳", "Payments")
    db.update_type(1, "billing", label="Payments")
    assert db.list_types(1)[-1]["label"] == "Payments"
    assert db.remove_type(1, "billing") and not db.remove_type(1, "billing")


def test_ticket_lifecycle_and_queue(db):
    a = new_ticket(db, owner_id=10, channel_id=100)
    new_ticket(db, owner_id=11, channel_id=101, status="in_progress")
    assert db.queue_counts(1) == (1, 1)
    assert db.open_ticket_of_owner(1, 10)["id"] == a
    db.add_note(a, 7, "secret", 1.0)
    db.update_ticket(a, status="closed", closed_at=2_000_000.0)
    assert db.queue_counts(1) == (0, 1)
    assert db.open_ticket_of_owner(1, 10) is None
    assert [t["id"] for t in db.closed_channels_due(2_000_000.0)] == [a]
    db.mark_channel_deleted(a)
    row = db.get_ticket(a)
    assert row["channel_deleted"] == 1 and row["subject"] is None and row["description"] is None
    assert db.list_notes(a) == []
    assert db.ticket_by_channel(100) is None
    assert db.purge_closed_before(2_000_001.0) == 1


def test_delete_guild_removes_everything(db):
    tid = new_ticket(db)
    db.add_note(tid, 7, "x", 1.0)
    db.add_transcript_ref(1, 50, 60, "low", 1.0)
    db.ensure_default_types(1, DEFAULT_TYPES["en"])
    assert db.delete_guild(1)
    for table in ("guilds", "tickets", "notes", "transcript_refs", "ticket_types"):
        assert db.count(table) == 0


def test_migration_from_v1_config(db, tmp_path):
    legacy = {
        "42": {
            "staff_role": 5, "category": 6, "log_channel": 7, "archive_channel": 8,
            "counter": 12, "retention_days": 14,
            "telegram": {"chat_id": "-100123", "verified": True},
            "guidelines_message": {"channel": 7, "message": 99},
            "tickets": {
                "300": {"owner": 10, "type": "bug", "subject": "Crash", "status": "waiting",
                        "claimed_by": None, "priority": None, "control_message": 77,
                        "opened_at": 1.0, "last_actor": "user", "last_activity": 2.0,
                        "warned": False},
                "301": {"owner": 11, "type": "unknown", "subject": "", "status": "in_progress",
                        "claimed_by": 9, "priority": "high", "opened_at": 1.0,
                        "last_activity": 2.0},
            },
            "transcripts": [{"channel": 7, "message": 500, "priority": "low", "closed_at": 3.0}],
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert db.run(migrate_legacy_config(db.store, path)) == 1
    assert not path.exists() and (tmp_path / "config.json.migrated").exists()
    cfg = db.get_guild(42)
    assert (cfg["counter"], cfg["retention_days"], cfg["telegram_chat_id"]) == (12, 14, "-100123")
    assert (cfg["guidelines_channel"], cfg["guidelines_message"]) == (7, 99)
    assert db.ticket_by_channel(300)["type_label"] == "Bug report"
    other = db.ticket_by_channel(301)
    assert (other["type_key"], other["status"], other["priority"]) == ("other", "in_progress",
                                                                       "high")
    assert db.transcript_refs(42)[0]["message_id"] == 500
    assert db.run(migrate_legacy_config(db.store, path)) == 0  # nothing left to migrate


# ------------------------------------------------------------ translations ---

def _placeholders(text):
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_translations_complete_and_consistent():
    en = STRINGS["en"]
    for lang in LANGUAGES:
        assert set(STRINGS[lang]) == set(en), lang
        for key, text in en.items():
            assert _placeholders(STRINGS[lang][key]) == _placeholders(text), (lang, key)


def test_all_keys_used_in_code_exist():
    used = set()
    for f in (ROOT / "ticketbot").rglob("*.py"):
        source = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"""_\(\s*["']([a-z_.]+)["']\s*[,)]""", source))
    assert used - set(STRINGS["en"]) == set()


def test_translation_fallback():
    assert t("de", "btn.close") == "Schließen"
    assert t("fr", "btn.close") == "Close"
    assert t("en", "missing.key") == "missing.key"


def test_default_types_have_same_keys():
    keys = [k for k, *_ in DEFAULT_TYPES["en"]]
    for lang in LANGUAGES:
        assert [k for k, *_ in DEFAULT_TYPES[lang]] == keys


def test_command_texts_translated():
    from discord import app_commands

    from ticketbot.bot.client import TicketBot
    from ticketbot.bot.commands import all_commands

    client = TicketBot(unused_store())
    for command in all_commands():
        client.tree.add_command(command)
    texts = set()

    def walk(cmd):
        texts.add(cmd.description)
        if isinstance(cmd, app_commands.Group):
            for sub in cmd.commands:
                walk(sub)
        else:
            for p in cmd.parameters:
                texts.add(p.description)
                texts.update(c.name for c in p.choices)

    for command in client.tree.get_commands():
        walk(command)
    texts -= set(LANGUAGES.values())
    for lang, table in COMMAND_TEXT.items():
        assert texts - set(table) == set(), lang
        assert all(len(v) <= 100 for v in table.values()), lang
    asyncio.run(client.close())


# ------------------------------------------------------------- transcripts ---

def _msg(author_id, content, minutes=0, **extra):
    return TMessage(author=f"user{author_id}", author_id=author_id, avatar="https://a/b.png",
                    color=None, bot=False,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC)
                    + timedelta(minutes=minutes),
                    content=content, **extra)


def _tr(key, **kw):
    return t("en", key, **kw)


META = {"guild": "Server", "channel": "bug-0001", "fields": [("Type", "🐞 Bug")]}


def test_markdown_is_escaped_and_formatted():
    out = markdown_to_html("<script>alert(1)</script> **bold** `x<y` https://e.com/a?b=1&c=2")
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "<strong>bold</strong>" in out
    assert "<code>x&lt;y</code>" in out
    assert 'href="https://e.com/a?b=1&amp;c=2"' in out
    assert "snake_case_name" in markdown_to_html("snake_case_name")


def test_html_transcript_groups_messages_and_hides_notes_for_users():
    msgs = [_msg(1, "hello"), _msg(1, "again", minutes=1), _msg(2, "hi", minutes=2),
            _msg(1, "img", minutes=3,
                 attachments=[{"filename": "a.png", "url": "https://cdn/a.png", "image": True}])]
    notes = [{"author": "mod", "text": "check <logs>", "created_at": 1.0}]
    staff = render_html(META, msgs, notes, _tr).decode()
    user = render_html(META, msgs, [], _tr).decode()
    assert staff.count("class='msg first'") == 3
    assert "Staff notes" in staff and "check &lt;logs&gt;" in staff
    assert "Staff notes" not in user
    assert "<img src='https://cdn/a.png'" in staff


def test_txt_transcript():
    msgs = [_msg(1, "hello", embeds=[{"title": "T", "description": "D", "fields": [("F", "V")],
                                      "color": None}])]
    txt = render_txt(META, msgs, [{"author": "mod", "text": "n", "created_at": 1.0}],
                     _tr).decode()
    assert "Transcript of #bug-0001" in txt
    assert "user1: hello [embed: T | D | F: V]" in txt
    assert "Staff notes" in txt and "mod: n" in txt


def test_translator_accepts_any_placeholder_name():
    from ticketbot.bot.common import translator
    _ = translator({"language": "en"})
    assert "`bug`" in _("types.added", type="🐞 Bug", key="bug")
    assert "bug" in t("en", "types.added", type="x", key="bug")


def test_startup_deletes_servers_the_bot_left(tmp_path):
    from types import SimpleNamespace

    from ticketbot.bot.client import TicketBot

    async def scenario():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(1)
        await store.save_guild(2)
        client = TicketBot(store)
        client._connection._guilds = {1: SimpleNamespace(id=1)}
        await client.on_ready()
        assert await store.guild_ids() == [1]
        await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("content_type, size, ok", [
    ("image/png", 1000, True), ("image/gif", 5 * 1024 * 1024, True),
    ("image/jpeg; charset=binary", 10, True), ("image/webp", 8 * 1024 * 1024, True),
    ("image/png", 8 * 1024 * 1024 + 1, False), ("image/svg+xml", 10, False),
    ("application/pdf", 10, False), (None, 10, False), ("image/png", 0, False),
])
def test_valid_profile_image(content_type, size, ok):
    assert logic.valid_profile_image(content_type, size) is ok


def test_command_payloads_build_for_discord():
    """Builds exactly what tree.sync() sends to Discord, translations included."""
    import json as _json

    from ticketbot.bot.client import TicketBot
    from ticketbot.bot.commands import all_commands
    from ticketbot.bot.translator import CommandTranslator

    async def build():
        client = TicketBot(unused_store())
        for command in all_commands():
            client.tree.add_command(command)
        translator = CommandTranslator()
        payloads = [await c.get_translated_payload(client.tree, translator)
                    for c in client.tree.get_commands()]
        await client.close()
        return payloads

    payloads = asyncio.run(build())
    _json.dumps(payloads)  # must be serializable, like in tree.sync()
    names = [p["name"] for p in payloads]
    assert len(names) == len(set(names))
    assert {"setup", "stats", "profile", "types", "settings", "telegram", "note"} <= set(names)
    profile = next(p for p in payloads if p["name"] == "profile")
    assert [o["name"] for o in profile["options"]] == ["name", "avatar", "banner", "bio", "reset"]


def _rich_message():
    return _msg(
        1, "ciao <:wolf:123456789012345678> e <a:dance:223456789012345678>",
        stickers=[{"name": "Wave", "id": 816087792291282944,
                   "url": "https://media.discordapp.net/stickers/816087792291282944.png",
                   "image": True},
                  {"name": "Lottie", "id": 749054660769218631, "url": "https://x/l.json",
                   "image": False}],
        reactions=[{"emoji": "👍", "id": None, "url": None, "count": 2,
                    "users": ["Tex", "User"]},
                   {"emoji": ":wolf:", "id": 123456789012345678,
                    "url": "https://cdn.discordapp.com/emojis/123456789012345678.png",
                    "count": 1, "users": ["Mod"]}],
    )


def test_txt_transcript_shows_stickers_reactions_and_custom_emoji():
    txt = render_txt(META, [_rich_message()], [], _tr).decode()
    assert ":wolf: (123456789012345678)" in txt and ":dance: (223456789012345678)" in txt
    assert "[Sticker: Wave (ID 816087792291282944)]" in txt
    assert "[Sticker: Lottie (ID 749054660769218631)]" in txt
    assert "Reactions: 👍 2 (Tex, User) · :wolf: (123456789012345678) 1 (Mod)" in txt


def test_html_transcript_shows_stickers_reactions_and_custom_emoji():
    out = render_html(META, [_rich_message()], [], _tr).decode()
    assert "cdn.discordapp.com/emojis/123456789012345678.png" in out
    assert "cdn.discordapp.com/emojis/223456789012345678.gif" in out
    assert "Wave · ID 816087792291282944" in out
    assert "stickers/816087792291282944.png" in out
    assert "Sticker: Lottie · ID 749054660769218631" in out
    assert "<b>2</b><small>Tex, User</small>" in out


def test_collect_messages_reads_stickers_and_reactions():
    from types import SimpleNamespace

    import discord

    from ticketbot.bot.collect import collect_messages

    class Users:
        def __init__(self, names):
            self.names = names

        def __aiter__(self):
            self.i = iter(self.names)
            return self

        async def __anext__(self):
            try:
                return SimpleNamespace(display_name=next(self.i))
            except StopIteration:
                raise StopAsyncIteration from None

    custom = discord.PartialEmoji(name="wolf", id=123456789012345678, animated=False)
    reactions = [SimpleNamespace(emoji="👍", count=2, users=lambda limit: Users(["Tex", "User"])),
                 SimpleNamespace(emoji=custom, count=1, users=lambda limit: Users(["Mod"]))]
    sticker = SimpleNamespace(name="Wave", id=816087792291282944, url="https://s/w.png",
                              format=discord.StickerFormatType.png)
    author = SimpleNamespace(display_name="User", id=4, bot=False,
                             display_avatar=SimpleNamespace(url="https://a"))
    msg = SimpleNamespace(author=author, created_at=datetime(2026, 1, 1, tzinfo=UTC),
                          clean_content="hi", embeds=[], attachments=[], stickers=[sticker],
                          reactions=reactions)

    class Channel:
        def history(self, **kwargs):
            async def gen():
                yield msg
            return gen()

    [m] = asyncio.run(collect_messages(Channel()))
    assert m.stickers == [{"name": "Wave", "id": 816087792291282944, "url": "https://s/w.png",
                           "image": True}]
    assert m.reactions[0] == {"emoji": "👍", "id": None, "url": None, "count": 2,
                              "users": ["Tex", "User"]}
    assert m.reactions[1]["emoji"] == ":wolf:" and m.reactions[1]["users"] == ["Mod"]
    assert m.reactions[1]["url"].endswith("123456789012345678.png")


def test_ticket_channel_name():
    assert logic.ticket_channel_name("bug", "mario", 42, 1) == "bug-mario-1"
    assert logic.ticket_channel_name("support", "Mario.Rossi_99", 42, 12) == \
        "support-mario-rossi-99-12"
    assert logic.ticket_channel_name("bug", "...", 123456789012345678, 3) == "bug-345678-3"
    assert len(logic.ticket_channel_name("x" * 20, "y" * 40, 1, 99999)) <= 100


def test_user_numbers_are_per_user_and_per_server(db):
    def open_for(guild_id, owner_id, channel_id):
        n = db.next_user_number(guild_id, owner_id)
        new_ticket(db, guild_id=guild_id, owner_id=owner_id, channel_id=channel_id,
                   user_number=n)
        return n

    assert open_for(1, 10, 100) == 1   # Mario, first ticket
    assert open_for(1, 11, 101) == 1   # Luca, first ticket
    assert open_for(1, 10, 102) == 2   # Mario, second ticket
    assert open_for(2, 10, 103) == 1   # Mario in another server
    db.update_ticket(db.ticket_by_channel(100)["id"], status="closed")
    db.mark_channel_deleted(db.ticket_by_channel(100)["id"])
    assert open_for(1, 10, 104) == 3   # closed tickets still count


def test_existing_database_is_upgraded(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE guilds (guild_id INTEGER PRIMARY KEY, language TEXT NOT NULL DEFAULT 'en',
            staff_role INTEGER, category INTEGER, log_channel INTEGER, archive_channel INTEGER,
            panel_channel INTEGER, panel_message INTEGER, guidelines_channel INTEGER,
            guidelines_message INTEGER, counter INTEGER NOT NULL DEFAULT 0,
            retention_days INTEGER NOT NULL DEFAULT 30, telegram_chat_id TEXT);
        CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            channel_id INTEGER UNIQUE, number INTEGER, owner_id INTEGER NOT NULL,
            type_key TEXT NOT NULL, type_label TEXT NOT NULL, type_emoji TEXT NOT NULL,
            subject TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'waiting',
            priority TEXT, claimed_by INTEGER, control_message INTEGER, opened_at REAL NOT NULL,
            first_response_at REAL, last_actor TEXT, last_activity REAL NOT NULL,
            warned INTEGER NOT NULL DEFAULT 0, closed_at REAL, closed_by INTEGER,
            close_reason TEXT, channel_deleted INTEGER NOT NULL DEFAULT 0, rating INTEGER,
            rating_comment TEXT, rated_at REAL);
        INSERT INTO guilds (guild_id) VALUES (1);
        INSERT INTO tickets (guild_id, channel_id, owner_id, type_key, type_label, type_emoji,
            opened_at, last_activity) VALUES (1, 100, 10, 'bug', 'Bug', '🐞', 1, 1);
    """)
    conn.commit()
    conn.close()

    database = SyncStore(path)  # adopts the v2.0 file: missing columns are added
    old = database.ticket_by_channel(100)
    assert old["user_number"] is None and old["name"] is None
    assert old["awaiting_staff_since"] is None and old["staff_reminded_at"] is None
    assert database.get_guild(1)["staff_reminders"] is True
    assert database.next_user_number(1, 10) == 1
    database.close()


def test_quick_replies_storage(db):
    db.save_guild(1)
    db.save_reply(1, "Logs", "Send me the logs, {user}")
    assert db.get_reply(1, "logs")["content"] == "Send me the logs, {user}"
    db.save_reply(1, "logs", "Updated")  # same name: replaces
    assert [r["content"] for r in db.list_replies(1)] == ["Updated"]
    assert db.remove_reply(1, "LOGS") and db.list_replies(1) == []
    db.save_reply(1, "x", "y")
    db.delete_guild(1)
    assert db.list_replies(1) == []


def test_reply_name_and_placeholders():
    assert logic.reply_name("Send Logs!") == "send-logs"
    assert logic.reply_name("🙂") == ""
    text = logic.fill_reply("Hi {user}, I'm {staff} from {server}. {other} {", "@U", "@S", "Club")
    assert text == "Hi @U, I'm @S from Club. {other} {"


def test_activity_changes():
    new = {"status": "waiting", "first_response_at": None, "last_actor": None,
           "awaiting_staff_since": 10.0}
    staff = logic.activity_changes(new, 50.0, from_staff=True)
    assert staff == {"last_actor": "staff", "last_activity": 50.0, "warned": 0,
                     "status": "in_progress", "first_response_at": 50.0,
                     "awaiting_staff_since": None, "staff_reminded_at": None}
    answered = {"status": "in_progress", "first_response_at": 10.0, "last_actor": "staff",
                "awaiting_staff_since": None}
    assert "first_response_at" not in logic.activity_changes(answered, 60.0, from_staff=True)
    # user writes after the staff: a new wait starts
    assert logic.activity_changes(answered, 70.0, from_staff=False) == {
        "last_actor": "user", "last_activity": 70.0, "warned": 0,
        "awaiting_staff_since": 70.0}
    # user writes again before the staff answers: the start of the wait is kept
    assert logic.activity_changes(new, 80.0, from_staff=False) == {
        "last_actor": "user", "last_activity": 80.0, "warned": 0}


def test_modal_hint_shows_placeholders():
    for lang in LANGUAGES:
        hint = t(lang, "replies.modal_hint")
        assert "{user}" in hint and "{staff}" in hint and "{server}" in hint



def _waiting(priority, waited_hours, reminded_hours_ago=None, last_actor="user",
             status="in_progress", now=1_000_000.0):
    return {"status": status, "priority": priority, "last_actor": last_actor,
            "awaiting_staff_since": now - waited_hours * HOUR, "last_activity": now,
            "opened_at": now - 100 * HOUR,
            "staff_reminded_at": (now - reminded_hours_ago * HOUR
                                  if reminded_hours_ago is not None else None)}, now


@pytest.mark.parametrize("priority, hours", [("high", 2), ("medium", 24), ("low", 48),
                                             (None, 12)])
def test_staff_reminder_after_priority_limit(priority, hours):
    assert not logic.staff_reminder_due(*_waiting(priority, hours - 0.1))
    assert logic.staff_reminder_due(*_waiting(priority, hours))


def test_staff_reminder_repeats_every_interval():
    assert not logic.staff_reminder_due(*_waiting("high", 3, reminded_hours_ago=1))
    assert logic.staff_reminder_due(*_waiting("high", 5, reminded_hours_ago=2))


def test_no_staff_reminder_when_waiting_for_user_or_closed():
    assert not logic.staff_reminder_due(*_waiting("high", 50, last_actor="staff"))
    assert not logic.staff_reminder_due(*_waiting("high", 50, status="closed"))


def test_waiting_since_falls_back_for_old_tickets():
    ticket = {"status": "waiting", "last_actor": None, "awaiting_staff_since": None,
              "last_activity": None, "opened_at": 5.0}
    assert logic.waiting_for_staff_since(ticket) == 5.0
    ticket.update(last_actor="user", last_activity=9.0)
    assert logic.waiting_for_staff_since(ticket) == 9.0


def test_guild_reminder_setting_and_upgrade(db):
    assert db.save_guild(1)["staff_reminders"] == 1
    assert db.save_guild(1, staff_reminders=0)["staff_reminders"] == 0


# ----------------------------------------------------------------- backups ---

def _filled_db(path):
    database = SyncStore(path)
    database.save_guild(1, language="it")
    new_ticket(database, guild_id=1)
    return database


def _backup(path, folder, **kwargs):
    import sqlite3

    from ticketbot.db.backup import create_backup

    source = sqlite3.connect(path)
    try:
        return create_backup(source, folder, **kwargs)
    finally:
        source.close()


def _guild_ids(path):
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return sorted(r[0] for r in conn.execute("SELECT guild_id FROM guilds"))
    finally:
        conn.close()


def test_backup_is_valid_and_compressed(tmp_path):
    import gzip
    import sqlite3

    from ticketbot.db.backup import list_backups

    database = _filled_db(tmp_path / "data" / "ticketbot.db")
    path = _backup(database.path, tmp_path / "backups",
                   now=datetime(2026, 11, 20, 3, 0, tzinfo=UTC))
    assert path.name == "ticketbot-20261120-030000.db.gz"
    assert list_backups(tmp_path / "backups") == [path]
    restored = tmp_path / "check.db"
    restored.write_bytes(gzip.decompress(path.read_bytes()))
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT language FROM guilds").fetchone()[0] == "it"
    assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 1
    conn.close()
    database.close()


def test_prune_keeps_newest_and_backup_due(tmp_path):
    import os

    from ticketbot.db.backup import backup_due, list_backups, prune_backups

    folder = tmp_path / "backups"
    assert backup_due(folder, 24)  # no backups yet
    folder.mkdir()
    for day in range(1, 11):
        (folder / f"ticketbot-202611{day:02d}-030000.db.gz").write_bytes(b"x")
    (folder / "notes.txt").write_text("not a backup")
    removed = prune_backups(folder, keep=7)
    assert [p.name[10:18] for p in removed] == ["20261101", "20261102", "20261103"]
    assert len(list_backups(folder)) == 7 and (folder / "notes.txt").exists()
    newest = list_backups(folder)[-1]
    os.utime(newest, (1_000_000, 1_000_000))
    assert not backup_due(folder, 24, now=1_000_000 + 23 * HOUR)
    assert backup_due(folder, 24, now=1_000_000 + 24 * HOUR)


def test_restore_replaces_db_and_keeps_safety_copy(tmp_path):
    from ticketbot.db.backup import restore_backup

    db_path = tmp_path / "data" / "ticketbot.db"
    database = _filled_db(db_path)
    backup = _backup(db_path, tmp_path / "backups")
    database.save_guild(2)  # change after the backup
    database.close()

    safety = restore_backup(backup, db_path)
    assert _guild_ids(db_path) == [1]
    assert _guild_ids(safety) == [1, 2]


def test_restore_refuses_damaged_backup(tmp_path):
    import gzip

    from ticketbot.db.backup import restore_backup

    db_path = tmp_path / "ticketbot.db"
    _filled_db(db_path).close()
    damaged = tmp_path / "ticketbot-20260101-000000.db.gz"
    damaged.write_bytes(gzip.compress(b"this is not a database" * 100))
    with pytest.raises(Exception):  # noqa: B017
        restore_backup(damaged, db_path)
    assert _guild_ids(db_path) == [1]  # untouched


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Settings from environment variables only, in an empty folder (no .env)."""
    from ticketbot.core.settings import get_settings

    monkeypatch.chdir(tmp_path)
    for name in ("DISCORD_TOKEN", "TELEGRAM_BOT_TOKEN", "DATABASE_URL", "DATA_DIR",
                 "LEGACY_CONFIG", "BACKUP_DIR", "BACKUP_KEEP", "BACKUP_INTERVAL_HOURS"):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_command_line(tmp_path, env, capsys):
    from ticketbot import __main__ as cli

    db_path = tmp_path / "data" / "ticketbot.db"
    _filled_db(db_path).close()
    env.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    assert cli.main(["backup"]) == 0
    assert "Backup saved" in capsys.readouterr().out
    assert cli.main(["backups"]) == 0
    listed = capsys.readouterr().out.split()[0]
    assert cli.main(["restore", listed, "--yes"]) == 0
    assert "Restored" in capsys.readouterr().out
    assert cli.main(["restore", str(tmp_path / "missing.db.gz"), "--yes"]) == 1
    assert "Restore failed" in capsys.readouterr().out


# --------------------------------------------------------- form questions ---

def test_type_questions_storage(db):
    db.save_guild(1)
    db.ensure_default_types(1, DEFAULT_TYPES["en"])
    assert db.add_question(1, "bug", "Version", "e.g. 1.4.2") == 1
    assert db.add_question(1, "bug", "Steps to reproduce", long=True) == 2
    assert db.add_question(1, "bug", "Screenshot link", required=False) == 3
    assert db.list_questions(1, "support") == []
    assert db.remove_question(1, "bug", 1)
    assert [(q["position"], q["label"]) for q in db.list_questions(1, "bug")] == [
        (1, "Steps to reproduce"), (2, "Screenshot link")]
    assert not db.remove_question(1, "bug", 9)
    db.remove_type(1, "bug")  # questions go with the type
    assert db.count("type_questions") == 0


def test_answers_text():
    text = logic.answers_text([("Version", "1.4.2"), ("Steps", "  open\nclick  "),
                               ("Link", "")])
    assert text == "**Version**\n1.4.2\n\n**Steps**\nopen\nclick\n\n**Link**\n-"


def test_ticket_modal_uses_type_questions():
    from ticketbot.bot.tickets import TicketModal

    _ = lambda key, /, **kw: t("en", key, **kw)  # noqa: E731
    bug = {"key": "bug", "label": "Bug report", "emoji": "🐞"}
    default = TicketModal(bug, _)
    assert [c.text for c in default.children] == ["Subject", "Describe your issue",
                                                  "Attachments (optional)"]
    assert default.upload.required is False and default.upload.max_values == 5

    questions = [
        {"label": "Version", "placeholder": "e.g. 1.4.2", "long": 0, "required": 1},
        {"label": "Steps to reproduce", "placeholder": "", "long": 1, "required": 1},
        {"label": "Link", "placeholder": "", "long": 0, "required": 0},
    ]
    custom = TicketModal(bug, _, questions)
    assert [c.text for c in custom.children] == ["Subject", "Version", "Steps to reproduce",
                                                 "Link", "Attachments (optional)"]
    assert len(custom.children) <= 5  # Discord's limit for a modal
    version, steps, link = (field for _label, field in custom.answers)
    assert version.placeholder == "e.g. 1.4.2" and version.max_length == 200
    assert steps.style.name == "paragraph" and steps.max_length == 1000
    assert link.required is False
    version._value, steps._value, link._value = "1.4.2", "open the app", ""
    assert custom.description_text() == ("**Version**\n1.4.2\n\n**Steps to reproduce**\n"
                                         "open the app\n\n**Link**\n-")



# ------------------------------------------------------------- attachments ---

@pytest.mark.parametrize("name, size, problem", [
    ("screenshot.png", 1000, None), ("log.txt", 10, None), ("LOGS.ZIP", 10, None),
    ("setup.exe", 10, "blocked"), ("photo.jpg.exe", 10, "blocked"), ("run.PS1", 10, "blocked"),
    ("README", 10, None), ("video.mp4", 11 * 1024 * 1024, "too_big"),
])
def test_attachment_problem(name, size, problem):
    assert logic.attachment_problem(name, size, 10 * 1024 * 1024) == problem


def test_forward_attachments_resends_safe_files_only():
    from types import SimpleNamespace

    import discord

    from ticketbot.bot.tickets import forward_attachments

    sent = []

    class Channel:
        guild = SimpleNamespace(filesize_limit=10 * 1024 * 1024)

        async def send(self, content=None, files=None, **kwargs):
            sent.append((content, [f.filename for f in files or []]))

    class Attachment:
        def __init__(self, filename, size, fail=False):
            self.filename, self.size, self.fail = filename, size, fail

        async def read(self):
            if self.fail:
                raise discord.HTTPException(SimpleNamespace(status=404, reason="gone"), "gone")
            return b"data"

    files = [Attachment("screen.png", 100), Attachment("virus.exe", 100),
             Attachment("huge.zip", 50 * 1024 * 1024), Attachment("expired.txt", 10, fail=True)]
    _ = lambda key, /, **kw: t("en", key, **kw)  # noqa: E731
    user = SimpleNamespace(mention="<@4>")
    asyncio.run(forward_attachments(Channel(), user, files, _))
    assert sent[0] == ("📎 Attachments from <@4>", ["screen.png"])
    assert sent[1][0].startswith("⚠️ Some files were not added:")
    for part in ("`virus.exe` (file type not allowed)", "`huge.zip` (larger than 10 MB)",
                 "`expired.txt` (upload failed)"):
        assert part in sent[1][0]


def test_tickets_of_user_newest_first_and_per_server(db):
    first = new_ticket(db, owner_id=10, channel_id=1, now=1_000.0)
    second = new_ticket(db, owner_id=10, channel_id=2, now=2_000.0)
    new_ticket(db, owner_id=11, channel_id=3, now=3_000.0)
    new_ticket(db, guild_id=2, owner_id=10, channel_id=4, now=4_000.0)
    assert [t["id"] for t in db.tickets_of_user(1, 10)] == [second, first]
    assert db.tickets_of_user(1, 99) == []


def test_ticket_history_embed():
    from ticketbot.bot.commands import ticket_history_embed

    _ = lambda key, /, **kw: t("en", key, **kw)  # noqa: E731
    base = {"type_emoji": "🐞", "type_label": "Bug", "channel_deleted": 0, "rating": None,
            "close_reason": None, "closed_at": None, "number": 1}
    tickets = [dict(base, status="waiting", channel_id=5, name="bug-mario-3", opened_at=300)]
    tickets += [dict(base, status="closed", channel_id=i, name=f"bug-mario-{i}", opened_at=i,
                     closed_at=i + 10, rating=5, close_reason="Solved")
                for i in range(1, 15)]
    embed = ticket_history_embed(tickets, "Your tickets", _)
    assert "<#5>" in embed.fields[0].value
    assert embed.fields[1].name == "Closed (latest 10 of 14)"
    assert "⭐" in embed.fields[1].value and len(embed.fields[1].value) <= 1024
    assert ticket_history_embed([], "x", _).description == t("en", "mytickets.none")


def test_blocks_expire_and_are_per_server(db):
    db.save_guild(1)
    db.save_guild(2)
    db.block_user(1, 10, "spam", 99, 1_000.0, None)
    db.block_user(1, 11, None, 99, 1_000.0, 2_000.0)
    assert db.get_block(1, 10, 5_000.0)["reason"] == "spam"
    assert db.get_block(2, 10, 5_000.0) is None
    assert db.get_block(1, 11, 1_500.0) is not None
    assert db.get_block(1, 11, 2_000.0) is None
    assert [b["user_id"] for b in db.list_blocks(1, 1_500.0)] == [10, 11]
    assert db.purge_expired_blocks(5_000.0) == 1
    assert db.unblock_user(1, 10) and not db.unblock_user(1, 10)
    db.block_user(2, 10, None, 99, 1_000.0, None)
    db.delete_guild(2)
    assert db.get_block(2, 10, 5_000.0) is None


def test_cooldown_left():
    last = {"opened_at": 1_000.0, "closed_at": 1_060.0}
    assert logic.cooldown_left(None, 10, 1_000.0) == 0
    assert logic.cooldown_left(last, 0, 1_000.0) == 0
    assert logic.cooldown_left(last, 10, 1_300.0) == 300
    assert logic.cooldown_left(last, 10, 1_600.0) == 0


def test_last_ticket_of_owner(db):
    new_ticket(db, owner_id=10, channel_id=1, now=1_000.0)
    second = new_ticket(db, owner_id=10, channel_id=2, now=2_000.0)
    assert db.last_ticket_of_owner(1, 10)["id"] == second
    assert db.last_ticket_of_owner(1, 11) is None


def test_assignment_order_balances_then_rotates():
    available = [{"user_id": 1, "last_assigned_at": 300.0},
                 {"user_id": 2, "last_assigned_at": 100.0},
                 {"user_id": 3, "last_assigned_at": None}]
    assert logic.assignment_order(available, {}) == [3, 2, 1]
    assert logic.assignment_order(available, {3: 2, 2: 1}) == [1, 2, 3]
    assert logic.assignment_order([], {}) == []


def test_staff_rotation_in_db(db):
    db.save_guild(1)
    db.set_available(1, 5, True)
    db.set_available(1, 5, True)  # no duplicates
    db.set_available(1, 6, True)
    db.mark_assigned(1, 5, 1_000.0)
    assert [(s["user_id"], s["last_assigned_at"]) for s in db.available_staff(1)] == \
        [(5, 1_000.0), (6, None)]
    db.set_available(1, 6, False)
    assert [s["user_id"] for s in db.available_staff(1)] == [5]

    new_ticket(db, channel_id=1, assigned_to=5)
    new_ticket(db, channel_id=2, assigned_to=5, claimed_by=6)  # the claim counts
    closed = new_ticket(db, channel_id=3, assigned_to=5)
    db.update_ticket(closed, status="closed")
    new_ticket(db, channel_id=4)
    assert db.open_tickets_per_staff(1) == {5: 1, 6: 1}


def _export_tickets():
    base = {"type_label": "Bug", "type_emoji": "🐞", "number": 1, "assigned_to": None,
            "closed_by": None, "rating_comment": None}
    return [
        dict(base, id=1, name="bug-mario-1", owner_id=10, status="closed", priority="high",
             claimed_by=20, opened_at=1_000_000.0, first_response_at=1_000_600.0,
             closed_at=1_003_600.0, close_reason="=HYPERLINK(\"http://x\")", rating=5,
             rating_comment="+great"),
        dict(base, id=2, name="bug-luigi-1", owner_id=11, status="waiting", priority=None,
             claimed_by=None, assigned_to=20, opened_at=1_100_000.0, first_response_at=None,
             closed_at=None, close_reason=None, rating=None),
    ]


def test_safe_text_blocks_formulas():
    from ticketbot.core.export import safe_text

    assert safe_text("=1+1") == "'=1+1"
    assert safe_text("@SUM(A1)") == "'@SUM(A1)"
    assert safe_text("-2") == "'-2"
    assert safe_text("normal text") == "normal text"
    assert safe_text(5) == 5 and safe_text(None) is None


def test_export_csv():
    import csv as _csv

    from ticketbot.core import export

    _ = lambda key, /, **kw: t("en", key, **kw)  # noqa: E731
    rows = export.ticket_rows(_export_tickets(), {10: "mario", 20: "mod"}, _)
    data = export.to_csv(rows, _)
    assert data.startswith(b"\xef\xbb\xbf")
    lines = list(_csv.reader(data.decode("utf-8-sig").splitlines()))
    assert lines[0][:4] == ["Ticket", "Type", "Priority", "Status"]
    first = dict(zip(lines[0], lines[1], strict=True))
    assert first["Opened by"] == "mario" and first["Claimed by"] == "mod"
    assert first["First response (min)"] == "10.0" and first["Resolution (min)"] == "60.0"
    assert first["Close reason"].startswith("'=") and first["Rating comment"] == "'+great"
    second = dict(zip(lines[0], lines[2], strict=True))
    assert second["Opened by"] == "11" and second["Assigned to"] == "mod"
    assert second["Status"] == "Waiting" and second["Priority"] == "Not set"
    assert second["Resolution (min)"] == ""


def test_export_xlsx():
    import io as _io

    openpyxl = pytest.importorskip("openpyxl")
    from ticketbot.core import export

    _ = lambda key, /, **kw: t("it", key, **kw)  # noqa: E731
    tickets = _export_tickets()
    rows = export.ticket_rows(tickets, {20: "mod"}, _)
    wb = openpyxl.load_workbook(_io.BytesIO(export.to_xlsx(rows, tickets, {20: "mod"},
                                                           "ultimi 30 giorni", _)))
    assert wb.sheetnames == ["Ticket", "Riepilogo"]
    ws = wb["Ticket"]
    assert ws.max_row == 3 and ws["A2"].value == "bug-mario-1"
    assert ws["J2"].value.year == 1970  # real dates, not text
    assert ws["O2"].value.startswith("'=")
    summary = {r[0]: r[1] for r in wb["Riepilogo"].iter_rows(values_only=True) if r and r[0]}
    assert summary["Aperti"] == 2 and summary["Chiusi"] == 1 and summary["mod"] == 1


def test_core_and_storage_do_not_depend_on_discord():
    """The core, the storage and the integrations are shared with the web API (V3)."""
    for package in ("core", "db", "integrations"):
        for f in (ROOT / "ticketbot" / package).glob("*.py"):
            source = f.read_text(encoding="utf-8")
            assert not re.search(r"^\s*(import discord|from discord)", source, re.M), f.name


def test_settings_defaults_and_secrets(env, tmp_path):
    from ticketbot.core.settings import Settings, SettingsError

    settings = Settings()
    assert settings.discord_token is None and settings.backup_keep == 7
    assert settings.db_path == Path("data") / "ticketbot.db"
    assert settings.backups_path == Path("data") / "backups"
    with pytest.raises(SettingsError, match="DISCORD_TOKEN is missing"):
        settings.require_discord_token()

    (tmp_path / ".env").write_text(
        "DISCORD_TOKEN=abc.def.ghi\nTELEGRAM_BOT_TOKEN=\nDATA_DIR=/srv/tb\nOTHER=1\n",
        encoding="utf-8")
    settings = Settings()
    assert settings.require_discord_token() == "abc.def.ghi"
    assert settings.telegram_bot_token is None          # empty = not set
    assert settings.db_path == Path("/srv/tb") / "ticketbot.db"
    assert "abc.def.ghi" not in repr(settings)           # secrets never printed
    assert ("DISCORD_TOKEN", "set") in settings.summary()


def test_settings_placeholder_and_invalid_values(env):
    from ticketbot.core.settings import Settings, SettingsError, get_settings

    env.setenv("DISCORD_TOKEN", "paste_your_bot_token_here")
    assert Settings().discord_token is None
    env.setenv("BACKUP_KEEP", "-1")
    env.setenv("BACKUP_INTERVAL_HOURS", "soon")
    with pytest.raises(SettingsError) as error:
        get_settings()
    message = str(error.value)
    assert "BACKUP_KEEP" in message and "BACKUP_INTERVAL_HOURS" in message


def test_settings_command_hides_secrets(env, capsys):
    from ticketbot import __main__ as cli

    env.setenv("DISCORD_TOKEN", "very.secret.token")
    assert cli.main(["settings"]) == 0
    out = capsys.readouterr().out
    assert "very.secret.token" not in out and "DISCORD_TOKEN" in out and "set" in out
    env.setenv("BACKUP_KEEP", "many")
    from ticketbot.core.settings import get_settings
    get_settings.cache_clear()
    assert cli.main(["settings"]) == 2
    assert "BACKUP_KEEP" in capsys.readouterr().out


def test_settings_database_url(env):
    from ticketbot.core.settings import Settings, SettingsError, get_settings

    assert Settings().db_url == "sqlite+aiosqlite:///data/ticketbot.db"
    env.setenv("DATABASE_URL", "postgresql://tb:very-secret@db:5432/tickets")
    settings = Settings()
    assert settings.db_url == "postgresql+asyncpg://tb:very-secret@db:5432/tickets"
    assert ("DATABASE_URL", "postgresql+asyncpg://tb:***@db:5432/tickets") in settings.summary()
    assert "very-secret" not in repr(settings)
    env.setenv("DATABASE_URL", "mysql://tb:very-secret@db/tickets")
    with pytest.raises(SettingsError) as error:
        get_settings()
    assert "unsupported database" in str(error.value)
    assert "very-secret" not in str(error.value)


def test_startup_logging_is_quiet(caplog):
    import logging

    from ticketbot.bot.client import setup_logging

    setup_logging()
    with caplog.at_level(logging.INFO):
        logging.getLogger("alembic.runtime.migration").info("Context impl SQLiteImpl.")
        logging.getLogger("discord.client").warning(
            "PyNaCl is not installed, voice will NOT be supported")
        logging.getLogger("discord.client").warning("something else")
    messages = [r.getMessage() for r in caplog.records]
    assert messages == ["something else"]
