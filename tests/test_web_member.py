"""Members open tickets from the browser and see their own (Beta3)."""

import sqlite3

from test_web_api import GUILD, MEMBER, STAFF, add_transcript, api, as_user, csrf  # noqa: F401

BASE = f"/api/v1/me/guilds/{GUILD}"


def queued(c):
    conn = sqlite3.connect(c.db_path)
    try:
        return conn.execute("SELECT kind, requested_by, status FROM bot_commands").fetchall()
    finally:
        conn.close()


def test_form_and_my_tickets(api):  # noqa: F811
    as_user(api, MEMBER)                   # no staff role at all
    assert [g["name"] for g in api.get("/api/v1/me/guilds").json()] == ["The Tex Club"]
    assert api.get("/api/v1/guilds").json() == []          # not in the staff dashboard
    form = api.get(BASE).json()
    assert {t["key"] for t in form["types"]} >= {"bug", "support"}
    assert [t["number"] for t in form["tickets"]] == [5, 4, 3, 2, 1]
    assert "notes" not in form["tickets"][0]
    assert api.get("/api/v1/me/guilds/222222222222222222").status_code == 404  # not set up


def test_open_a_ticket(api):  # noqa: F811
    as_user(api, MEMBER)
    h = csrf(api)
    assert api.post(BASE + "/tickets", json={"type_key": "bug", "subject": "x",
                                             "description": "y"}).status_code == 403
    assert api.post(BASE + "/tickets", json={"type_key": "nope", "subject": "x",
                                             "description": "y"}, headers=h).status_code == 404
    assert api.post(BASE + "/tickets", json={"type_key": "bug", "subject": "  ",
                                             "description": "y"}, headers=h).status_code == 422
    assert api.post(BASE + "/tickets", json={"type_key": "bug", "subject": "Crash",
                                             "description": " "}, headers=h).status_code == 422
    r = api.post(BASE + "/tickets", json={"type_key": "bug", "subject": "Crash",
                                          "description": "At start"}, headers=h)
    assert r.status_code == 202
    assert queued(api) == [("ticket.open", MEMBER, "pending")]
    assert api.post(BASE + "/tickets", json={"type_key": "bug", "subject": "Again",
                                             "description": "z"}, headers=h).status_code == 409
    cid = r.json()["command_id"]
    assert api.get(f"{BASE}/commands/{cid}").json() == {"status": "pending", "result": None,
                                                       "channel_id": None}
    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("UPDATE bot_commands SET status = 'done', result = 'channel:777'")
    conn.close()
    assert api.get(f"{BASE}/commands/{cid}").json()["channel_id"] == "777"
    as_user(api, STAFF)                    # someone else's command
    assert api.get(f"{BASE}/commands/{cid}").status_code == 404


def test_form_questions_are_checked(api):  # noqa: F811
    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("INSERT INTO type_questions (guild_id, type_key, position, label, "
                     "placeholder, long, required) VALUES (?, 'support', 1, 'Order', '', 0, 1)",
                     (GUILD,))
    conn.close()
    as_user(api, MEMBER)
    h = csrf(api)
    form = {t["key"]: t for t in api.get(BASE).json()["types"]}
    assert form["support"]["questions"][0]["label"] == "Order"
    body = {"type_key": "support", "subject": "Refund"}
    assert api.post(BASE + "/tickets", json={**body, "answers": []}, headers=h).status_code \
        == 422
    assert api.post(BASE + "/tickets", json={**body, "answers": [" "]},
                    headers=h).status_code == 422
    assert api.post(BASE + "/tickets", json={**body, "answers": ["x" * 201]},
                    headers=h).status_code == 422
    assert api.post(BASE + "/tickets", json={**body, "answers": ["#4711"]},
                    headers=h).status_code == 202


def test_faq_and_own_transcript(api):  # noqa: F811
    add_transcript(api.db_path, 4)
    as_user(api, MEMBER)
    h = csrf(api)
    assert api.post(BASE + "/faq", json={"type_key": "bug", "solved": True},
                    headers=h).status_code == 204
    tr = api.get(f"{BASE}/tickets/4/transcript").json()
    assert tr["messages"][0]["content"] == "It **crashes**" and tr["notes"] == []
    as_user(api, STAFF)                    # not their ticket
    assert api.get(f"{BASE}/tickets/4/transcript").status_code == 404
