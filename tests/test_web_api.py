"""Web API, read-only part (Beta3): servers, tickets and statistics, with the same
permissions as the bot on Discord."""

import asyncio
import sqlite3
import time

import pytest
from conftest import new_store
from fastapi.testclient import TestClient
from test_web import FakeDiscord, log_in, make_settings

from ticketbot.core.i18n import DEFAULT_TYPES
from ticketbot.web.app import create_app
from ticketbot.web.permissions import Access, is_admin

GUILD = 111111111111111111
OTHER = 222222222222222222          # the bot is not set up there
ADMIN, STAFF, DEV, MANAGER, MEMBER = 1, 2, 3, 4, 5          # user IDs
STAFF_ROLE, DEV_ROLE, MANAGER_ROLE = 50, 30, 40


async def seed(path):
    """A server: staff role 50, *bug* handled by role 30, escalation level 1 = role 40.
    Tickets: 1 bug, 2 support, 3 support escalated to 1, 4 support closed, 5 of a type
    that was deleted."""
    store = await new_store(path)
    await store.save_guild(GUILD, staff_role=STAFF_ROLE, language="en")
    await store.ensure_default_types(GUILD, DEFAULT_TYPES["en"])
    await store.add_type_role(GUILD, "bug", DEV_ROLE)
    await store.add_escalation_level(GUILD, MANAGER_ROLE, None)
    await store.save_guild(OTHER)
    now = time.time()
    for n, (key, extra) in enumerate([
            ("bug", {}), ("support", {}), ("support", {"escalation_level": 1}),
            ("support", {"status": "closed", "closed_at": now, "closed_by": STAFF,
                         "rating": 5, "claimed_by": STAFF, "first_response_at": now - 50}),
            ("gone", {})], start=1):
        tid = await store.create_ticket(
            guild_id=GUILD, channel_id=1000 + n, number=n, owner_id=MEMBER, type_key=key,
            type_label=key.title(), type_emoji="x", subject=f"Subject {n}",
            description=f"Answers {n}", opened_at=now - 100, last_activity=now - 100)
        if extra:
            await store.update_ticket(tid, **extra)
    await store.add_note(2, STAFF, "Called the user", now)
    await store.record_faq_result(GUILD, "support", True, now=now)
    await store.close()


@pytest.fixture
def api(tmp_path):
    asyncio.run(seed(tmp_path / "ticketbot.db"))
    settings = make_settings(tmp_path, discord_client_id="42", discord_client_secret="s",
                             discord_token="bot-token")
    with TestClient(create_app(settings), follow_redirects=False) as c:
        c.db_path = tmp_path / "ticketbot.db"
        c.discord = FakeDiscord()
        c.discord.members = {(GUILD, STAFF): [STAFF_ROLE], (GUILD, DEV): [DEV_ROLE],
                             (GUILD, MANAGER): [MANAGER_ROLE], (GUILD, MEMBER): [],
                             (GUILD, ADMIN): []}
        c.app.state.discord = c.discord
        yield c


def as_user(c, user_id, *, owner=False, permissions="0", guilds=None):
    """Log in as `user_id`, member of GUILD (and of the other server)."""
    c.cookies.clear()
    c.discord.user_id = str(user_id)
    c.discord.guilds = guilds if guilds is not None else [
        {"id": str(GUILD), "name": "The Tex Club", "icon": "abc", "owner": owner,
         "permissions": permissions},
        {"id": str(OTHER), "name": "Other", "icon": None, "owner": True,
         "permissions": "8"}]
    assert log_in(c).status_code == 302
    c.app.state.guilds_cache._data.clear()
    c.app.state.members_cache._data.clear()


def ticket_ids(c, **params):
    r = c.get(f"/api/v1/guilds/{GUILD}/tickets", params={"status": "all", **params})
    assert r.status_code == 200, r.text
    return [t["id"] for t in r.json()["tickets"]]


def test_admin_sees_everything(api):
    as_user(api, ADMIN, permissions=str(1 << 3))        # Administrator
    guilds = api.get("/api/v1/guilds").json()
    assert guilds == [{"id": str(GUILD), "name": "The Tex Club", "role": "admin",
                       "icon_url": f"https://cdn.discordapp.com/icons/{GUILD}/abc.png"
                                   "?size=128"}]                 # not the unset server
    detail = api.get(f"/api/v1/guilds/{GUILD}").json()
    assert detail["waiting"] == 4 and detail["ticket_mode"] == "channel"
    assert detail["can_see_stats"] and "bug" in [t["key"] for t in detail["types"]]
    assert ticket_ids(api) == [5, 4, 3, 2, 1]
    assert ticket_ids(api, status="closed") == [4]
    page = api.get(f"/api/v1/guilds/{GUILD}/tickets", params={"limit": 2}).json()
    assert [t["id"] for t in page["tickets"]] == [5, 3] and page["next_before"] == 3
    assert page["tickets"][0]["owner_id"] == str(MEMBER)
    assert page["people"][str(MEMBER)]["name"] == f"User {MEMBER}"
    assert ticket_ids(api, before=3) == [2, 1]
    assert ticket_ids(api, type="bug") == [1]


def test_owner_is_admin_too(api):
    as_user(api, ADMIN, owner=True)
    assert api.get("/api/v1/guilds").json()[0]["role"] == "admin"


def test_staff_see_only_the_tickets_they_handle_on_discord(api):
    as_user(api, STAFF)            # staff role: types without roles of their own
    assert api.get("/api/v1/guilds").json()[0]["role"] == "staff"
    assert ticket_ids(api) == [5, 4, 3, 2]
    as_user(api, DEV)              # role of the *bug* type
    assert ticket_ids(api) == [1]
    assert api.get(f"/api/v1/guilds/{GUILD}/tickets/2").status_code == 404
    as_user(api, MANAGER)          # escalation level 1
    assert ticket_ids(api) == [3]


def test_no_access_looks_like_no_server(api):
    as_user(api, MEMBER)           # in the server, but not staff
    assert api.get("/api/v1/guilds").json() == []
    for path in ("", "/tickets", "/tickets/1", "/stats"):
        assert api.get(f"/api/v1/guilds/{GUILD}{path}").status_code == 404
    as_user(api, STAFF, guilds=[])  # left the server
    assert api.get(f"/api/v1/guilds/{GUILD}").status_code == 404
    api.cookies.clear()
    assert api.get(f"/api/v1/guilds/{GUILD}").status_code == 401
    assert api.get("/api/v1/guilds").status_code == 401


def test_ticket_detail_and_audit(api):
    as_user(api, STAFF)
    t = api.get(f"/api/v1/guilds/{GUILD}/tickets/4").json()
    assert t["subject"] == "Subject 4" and t["description"] == "Answers 4"
    assert t["rating"] == 5 and t["closed_by"] == str(STAFF) and t["status"] == "closed"
    t = api.get(f"/api/v1/guilds/{GUILD}/tickets/2").json()
    assert t["notes"] == [{"author_id": str(STAFF), "text": "Called the user",
                           "created_at": t["notes"][0]["created_at"]}]
    assert set(t["people"]) == {str(MEMBER), str(STAFF)}
    assert api.get(f"/api/v1/guilds/{GUILD}/tickets/999").status_code == 404
    conn = sqlite3.connect(api.db_path)
    rows = conn.execute("SELECT action, source, target, ip FROM audit_log "
                        "WHERE action = 'ticket.view' ORDER BY id").fetchall()
    conn.close()
    assert [r[:3] for r in rows] == [("ticket.view", "web", "ticket:4"),
                                     ("ticket.view", "web", "ticket:2")]
    assert rows[0][3].startswith("enc:v1:")             # IP encrypted


def test_stats(api):
    as_user(api, STAFF)
    s = api.get(f"/api/v1/guilds/{GUILD}/stats", params={"period": "7"}).json()
    assert (s["opened"], s["closed"], s["open"]) == (5, 1, 4)
    assert s["avg_rating"] == 5 and s["faq_solved"] == 1 and s["faq_opened"] == 0
    assert s["by_priority"]["none"] == 5
    assert s["leaderboard"][0]["staff_id"] == str(STAFF)
    assert s["people"][str(STAFF)]["name"] == f"User {STAFF}"
    assert api.get(f"/api/v1/guilds/{GUILD}/stats", params={"period": "5"}).status_code \
        == 422
    as_user(api, DEV)              # only a type role: like /stats on Discord, no
    assert api.get(f"/api/v1/guilds/{GUILD}/stats").status_code == 403


def test_discord_answers_are_cached_and_token_renewed(api):
    as_user(api, ADMIN, owner=True)
    for _ in range(3):
        api.get("/api/v1/guilds")
    assert api.discord.calls == 1                        # one call per minute

    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("UPDATE web_sessions SET token_expires_at = ?", (time.time() + 10,))
    conn.close()
    api.app.state.guilds_cache._data.clear()
    assert api.get("/api/v1/guilds").status_code == 200
    assert api.discord.refreshed == ["r"]                # renewed before using it

    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("UPDATE web_sessions SET token_expires_at = ?", (time.time() + 10,))
    conn.close()
    api.app.state.guilds_cache._data.clear()
    api.discord.refresh_fails = True
    assert api.get("/api/v1/guilds").status_code == 401  # Discord said no: logged out
    assert api.get("/api/v1/auth/me").status_code == 401


def test_login_answer_must_come_from_discord(api):
    r = api.get("/api/v1/auth/login")
    state = r.headers["location"].split("state=")[1].split("&")[0]
    r = api.get("/api/v1/auth/callback", params={"code": "a", "state": state,
                                                 "iss": "https://evil.example"})
    assert r.headers["location"] == "/?login_error=invalid"


# ---------------------------------------------------- permissions alone ---

def access(roles=(), admin=False):
    return Access(guild_id=GUILD, admin=admin, roles=frozenset(roles),
                  cfg={"staff_role": STAFF_ROLE}, type_roles={"bug": [DEV_ROLE]},
                  levels=[{"level": 1, "role_id": MANAGER_ROLE},
                          {"level": 2, "role_id": 41}])


@pytest.mark.parametrize("roles, level, key, visible", [
    ((), 0, "support", False),
    ((STAFF_ROLE,), 0, "support", True),
    ((STAFF_ROLE,), 0, "bug", False),          # the type has its own roles
    ((DEV_ROLE,), 0, "bug", True),
    ((DEV_ROLE,), 0, "support", False),
    ((MANAGER_ROLE,), 0, "support", False),
    ((MANAGER_ROLE,), 1, "bug", True),
    ((MANAGER_ROLE,), 2, "support", True),     # a higher level includes the lower ones
    ((41,), 1, "support", False),
])
def test_can_see_matches_the_query(tmp_path, roles, level, key, visible):
    a = access(roles)
    assert a.can_see({"type_key": key, "escalation_level": level}) is visible

    async def scenario():                      # the database query agrees
        store = await new_store(tmp_path / "t.db")
        await store.save_guild(GUILD)
        tid = await store.create_ticket(guild_id=GUILD, owner_id=1, type_key=key,
                                        type_label="x", type_emoji="x", opened_at=1.0,
                                        last_activity=1.0, escalation_level=level)
        found, _next = await store.list_tickets(GUILD, status="all", scope=a.scope())
        await store.close()
        return [t["id"] for t in found] == [tid]

    assert asyncio.run(scenario()) is visible


def test_roles_and_admin():
    assert access(admin=True).role == "admin" and access(admin=True).scope() is None
    assert access((STAFF_ROLE,)).role == "staff" and access((STAFF_ROLE,)).can_see_stats
    assert access((DEV_ROLE,)).role == "staff" and not access((DEV_ROLE,)).can_see_stats
    assert access((41,)).role == "staff"
    assert access((99,)).role is None
    assert is_admin({"owner": True, "permissions": "0"})
    assert is_admin({"owner": False, "permissions": str(1 << 3 | 1 << 5)})
    assert not is_admin({"owner": False, "permissions": str(1 << 5)})   # Manage Server


# ------------------------------------------------------------ actions ----

def csrf(c):
    return {"X-CSRF-Token": c.get("/api/v1/auth/me").json()["csrf_token"]}


def commands(c):
    conn = sqlite3.connect(c.db_path)
    try:
        return conn.execute("SELECT kind, requested_by, status FROM bot_commands "
                            "ORDER BY id").fetchall()
    finally:
        conn.close()


def test_actions_are_queued_for_the_bot(api):
    as_user(api, STAFF)
    h = csrf(api)
    base = f"/api/v1/guilds/{GUILD}/tickets/2"
    assert api.post(base + "/close", json={"reason": "Solved"}).status_code == 403  # no CSRF
    r = api.post(base + "/close", json={"reason": "Solved"}, headers=h)
    assert r.status_code == 202 and r.json()["status"] == "pending"
    command_id = r.json()["command_id"]
    for path, body in (("/claim", {"priority": "high"}), ("/priority", {"priority": "low"}),
                       ("/transfer", {"member_id": "123456789012345678"}),
                       ("/escalate", {"reason": "Refund"}), ("/messages", {"text": " Hi "})):
        assert api.post(base + path, json=body, headers=h).status_code == 202, path
    assert commands(api) == [(k, STAFF, "pending") for k in (
        "ticket.close", "ticket.claim", "ticket.priority", "ticket.transfer",
        "ticket.escalate", "ticket.message")]
    conn = sqlite3.connect(api.db_path)
    payloads = conn.execute("SELECT payload FROM bot_commands").fetchall()
    conn.close()
    assert all(p[0].startswith("enc:v1:") for p in payloads)       # encrypted

    s = api.get(f"/api/v1/guilds/{GUILD}/commands/{command_id}").json()
    assert s["kind"] == "ticket.close" and s["status"] == "pending" and s["result"] is None
    as_user(api, DEV)                       # someone else's command: not shown
    assert api.get(f"/api/v1/guilds/{GUILD}/commands/{command_id}").status_code == 404
    as_user(api, ADMIN, owner=True)         # admins see every command of the server
    assert api.get(f"/api/v1/guilds/{GUILD}/commands/{command_id}").status_code == 200


def test_actions_are_checked_before_queueing(api):
    as_user(api, STAFF)
    h = csrf(api)
    t = f"/api/v1/guilds/{GUILD}/tickets"
    assert api.post(f"{t}/1/close", json={}, headers=h).status_code == 404   # bug: not theirs
    assert api.post(f"{t}/4/close", json={}, headers=h).status_code == 409   # closed
    assert api.post(f"{t}/2/priority", json={"priority": "urgent"},
                    headers=h).status_code == 422
    assert api.post(f"{t}/2/messages", json={"text": "   "}, headers=h).status_code == 422
    assert api.post(f"{t}/2/transfer", json={"member_id": "abc"}, headers=h).status_code \
        == 422
    assert api.post(f"{t}/2/escalate", json={"level": 2}, headers=h).status_code == 409
    assert api.post(f"{t}/3/escalate", json={}, headers=h).status_code == 409  # at the top
    as_user(api, ADMIN, owner=True)
    h = csrf(api)
    assert api.post(f"{t}/2/claim", json={"priority": "low"}, headers=h).status_code == 202
    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("UPDATE tickets SET claimed_by = 9 WHERE id = 2")
    conn.close()
    assert api.post(f"{t}/2/claim", json={"priority": "low"}, headers=h).status_code == 409
    assert [c[0] for c in commands(api)] == ["ticket.claim"]


def test_notes_are_saved_at_once(api):
    as_user(api, STAFF)
    r = api.post(f"/api/v1/guilds/{GUILD}/tickets/3/notes",
                 json={"text": "Waiting for the bank"}, headers=csrf(api))
    assert r.status_code == 201 and r.json()["author_id"] == str(STAFF)
    notes = api.get(f"/api/v1/guilds/{GUILD}/tickets/3").json()["notes"]
    assert [n["text"] for n in notes] == ["Waiting for the bank"]
    assert commands(api) == []


def test_names_of_former_members(api):
    api.discord.former_members = {MEMBER}
    del api.discord.members[(GUILD, MEMBER)]           # left the server
    as_user(api, STAFF)
    people = api.get(f"/api/v1/guilds/{GUILD}/tickets").json()["people"]
    assert people[str(MEMBER)] == {
        "name": f"gone{MEMBER}",
        "avatar_url": f"https://cdn.discordapp.com/avatars/{MEMBER}/a1.png?size=128"}


def test_staff_candidates(api):
    as_user(api, STAFF)
    staff = api.get(f"/api/v1/guilds/{GUILD}/staff").json()
    assert [s["id"] for s in staff] == [str(STAFF)]          # handled ticket 4
    assert api.get(f"/api/v1/guilds/{GUILD}").json()["escalation_levels"] == 1


def add_transcript(path, ticket_id):
    from test_transcripts_db import MESSAGES, META, NOTES

    from ticketbot.core.transcripts import dump_transcript

    async def go():
        store = await new_store(path)
        await store.save_transcript(guild_id=GUILD, ticket_id=ticket_id, channel_name="t-4",
                                    content=dump_transcript(META, MESSAGES, NOTES),
                                    created_at=1.0, archive_channel_id=70,
                                    archive_message_id=500)
        await store.close()

    asyncio.run(go())


def test_transcript_in_the_dashboard(api):
    add_transcript(api.db_path, 4)
    as_user(api, STAFF)
    assert api.get(f"/api/v1/guilds/{GUILD}/tickets/4").json()["has_transcript"]
    assert not api.get(f"/api/v1/guilds/{GUILD}/tickets/2").json()["has_transcript"]
    tr = api.get(f"/api/v1/guilds/{GUILD}/tickets/4/transcript").json()
    assert tr["channel_name"] == "t-4" and tr["messages"][0]["content"] == "It **crashes**"
    assert tr["messages"][0]["attachments"][0]["filename"] == "log.txt"
    assert tr["notes"][0]["text"] == "Known bug"
    r = api.get(f"/api/v1/guilds/{GUILD}/tickets/4/transcript.html")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.headers["content-security-policy"].startswith("sandbox")
    assert "crashes" in r.text
    assert api.get(f"/api/v1/guilds/{GUILD}/tickets/2/transcript").status_code == 404
    as_user(api, DEV)                       # can't see ticket 4 (support)
    assert api.get(f"/api/v1/guilds/{GUILD}/tickets/4/transcript").status_code == 404
    conn = sqlite3.connect(api.db_path)
    views = conn.execute("SELECT COUNT(*) FROM audit_log "
                         "WHERE action = 'ticket.transcript_view'").fetchone()[0]
    conn.close()
    assert views == 2


def test_admin_deletes_a_ticket(api):
    add_transcript(api.db_path, 4)
    as_user(api, STAFF)
    assert api.delete(f"/api/v1/guilds/{GUILD}/tickets/4", headers=csrf(api)).status_code \
        == 403
    as_user(api, ADMIN, owner=True)
    h = csrf(api)
    assert api.delete(f"/api/v1/guilds/{GUILD}/tickets/2", headers=h).status_code == 409
    assert api.delete(f"/api/v1/guilds/{GUILD}/tickets/4", headers=h).status_code == 204
    assert api.get(f"/api/v1/guilds/{GUILD}/tickets/4").status_code == 404
    assert api.delete(f"/api/v1/guilds/{GUILD}/tickets/4", headers=h).status_code == 404
    assert [c[0] for c in commands(api)] == ["transcript.delete_messages"]
