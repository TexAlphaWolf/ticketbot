import asyncio
import json
import re
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ticketbot import config, logic  # noqa: E402
from ticketbot.db import Database  # noqa: E402
from ticketbot.i18n import COMMAND_TEXT, DEFAULT_TYPES, LANGUAGES, STRINGS, t  # noqa: E402
from ticketbot.migrate import migrate_legacy_config  # noqa: E402
from ticketbot.transcripts import TMessage, markdown_to_html, render_html, render_txt  # noqa: E402

HOUR = 3600
DAY = 86400


@pytest.fixture
def db():
    database = Database(":memory:")
    yield database
    database.close()


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
        assert db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


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
    assert migrate_legacy_config(db, path) == 1
    assert not path.exists() and (tmp_path / "config.json.migrated").exists()
    cfg = db.get_guild(42)
    assert (cfg["counter"], cfg["retention_days"], cfg["telegram_chat_id"]) == (12, 14, "-100123")
    assert (cfg["guidelines_channel"], cfg["guidelines_message"]) == (7, 99)
    assert db.ticket_by_channel(300)["type_label"] == "Bug report"
    other = db.ticket_by_channel(301)
    assert (other["type_key"], other["status"], other["priority"]) == ("other", "in_progress",
                                                                       "high")
    assert db.transcript_refs(42)[0]["message_id"] == 500
    assert migrate_legacy_config(db, path) == 0  # nothing left to migrate


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
    for f in (ROOT / "ticketbot").glob("*.py"):
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

    from ticketbot.bot import TicketBot
    from ticketbot.commands import all_commands

    client = TicketBot(Database(":memory:"))
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
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
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
    from ticketbot.common import translator
    _ = translator({"language": "en"})
    assert "`bug`" in _("types.added", type="🐞 Bug", key="bug")
    assert "bug" in t("en", "types.added", type="x", key="bug")


def test_startup_deletes_servers_the_bot_left():
    from types import SimpleNamespace

    from ticketbot.bot import TicketBot

    database = Database(":memory:")
    database.save_guild(1)
    database.save_guild(2)
    client = TicketBot(database)
    client._connection._guilds = {1: SimpleNamespace(id=1)}
    asyncio.run(client.on_ready())
    assert database.guild_ids() == [1]
    asyncio.run(client.close())


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

    from ticketbot.bot import TicketBot
    from ticketbot.commands import all_commands
    from ticketbot.i18n import CommandTranslator

    async def build():
        client = TicketBot(Database(":memory:"))
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

    from ticketbot.transcripts import collect_messages

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
    msg = SimpleNamespace(author=author, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
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

    database = Database(path)
    old = database.ticket_by_channel(100)
    assert old["user_number"] is None and old["name"] is None
    assert old["awaiting_staff_since"] is None and old["staff_reminded_at"] is None
    assert database.get_guild(1)["staff_reminders"] == 1
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
    assert db.conn.execute("SELECT COUNT(*) FROM replies").fetchone()[0] == 0


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
    database = Database(path)
    database.save_guild(1, language="it")
    new_ticket(database, guild_id=1)
    return database


def test_backup_is_valid_and_compressed(tmp_path):
    import gzip
    import sqlite3

    from ticketbot.backup import create_backup, list_backups

    database = _filled_db(tmp_path / "data" / "ticketbot.db")
    path = create_backup(database.conn, tmp_path / "backups",
                         now=datetime(2026, 11, 20, 3, 0, tzinfo=timezone.utc))
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

    from ticketbot.backup import backup_due, list_backups, prune_backups

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
    from ticketbot.backup import create_backup, restore_backup

    db_path = tmp_path / "data" / "ticketbot.db"
    database = _filled_db(db_path)
    backup = create_backup(database.conn, tmp_path / "backups")
    database.save_guild(2)  # change after the backup
    database.close()

    safety = restore_backup(backup, db_path)
    restored = Database(db_path)
    assert restored.guild_ids() == [1]
    restored.close()
    before = Database(safety)
    assert sorted(before.guild_ids()) == [1, 2]
    before.close()


def test_restore_refuses_damaged_backup(tmp_path):
    import gzip

    from ticketbot.backup import restore_backup

    db_path = tmp_path / "ticketbot.db"
    _filled_db(db_path).close()
    damaged = tmp_path / "ticketbot-20260101-000000.db.gz"
    damaged.write_bytes(gzip.compress(b"this is not a database" * 100))
    with pytest.raises(Exception):  # noqa: B017
        restore_backup(damaged, db_path)
    check = Database(db_path)
    assert check.guild_ids() == [1]  # untouched
    check.close()


def test_command_line(tmp_path, monkeypatch, capsys):
    from ticketbot import __main__ as cli
    from ticketbot import config as cfg

    db_path = tmp_path / "ticketbot.db"
    _filled_db(db_path).close()
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "BACKUP_DIR", tmp_path / "backups")
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
    assert db.conn.execute("SELECT COUNT(*) FROM type_questions").fetchone()[0] == 0


def test_answers_text():
    text = logic.answers_text([("Version", "1.4.2"), ("Steps", "  open\nclick  "),
                               ("Link", "")])
    assert text == "**Version**\n1.4.2\n\n**Steps**\nopen\nclick\n\n**Link**\n-"


def test_ticket_modal_uses_type_questions():
    from ticketbot.tickets import TicketModal

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

    from ticketbot.tickets import forward_attachments

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
