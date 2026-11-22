"""Server management from the web (Beta3): settings, types, FAQ, escalation."""

import sqlite3

from test_web_api import ADMIN, DEV, GUILD, STAFF, api, as_user, csrf  # noqa: F401

BASE = f"/api/v1/guilds/{GUILD}"


def queued(c):
    conn = sqlite3.connect(c.db_path)
    try:
        return [r[0] for r in conn.execute("SELECT kind FROM bot_commands ORDER BY id")]
    finally:
        conn.close()


def audit_actions(c):
    conn = sqlite3.connect(c.db_path)
    try:
        return [r for r in conn.execute(
            "SELECT action, source FROM audit_log WHERE action NOT LIKE 'auth.%' "
            "ORDER BY id")]
    finally:
        conn.close()


def admin(c):
    as_user(c, ADMIN, owner=True)
    return csrf(c)


def test_only_admins(api):  # noqa: F811
    as_user(api, STAFF)
    for path in ("/settings", "/types", "/faq", "/escalation", "/roles"):
        assert api.get(BASE + path).status_code == 403, path
    assert api.patch(BASE + "/settings", json={"auto_assign": True},
                     headers=csrf(api)).status_code == 403


def test_roles(api):  # noqa: F811
    admin(api)
    roles = api.get(BASE + "/roles").json()
    assert [r["name"] for r in roles][:2] == ["Directors", "Managers"]   # highest first
    flags = {r["name"]: r["assignable"] for r in roles}
    assert not flags["@everyone"] and not flags["SomeBot"] and flags["Staff"]


def test_settings(api):  # noqa: F811
    h = admin(api)
    s = api.get(BASE + "/settings").json()
    assert s == {"language": "en", "retention_days": 30, "staff_reminders": True,
                 "auto_assign": False, "ticket_cooldown": 0, "telegram_messages": True,
                 "weekly_report": True, "ticket_mode": "channel", "staff_role": "50"}
    r = api.patch(BASE + "/settings", json={"language": "it", "ticket_cooldown": 15},
                  headers=h)
    assert r.json()["language"] == "it" and r.json()["ticket_cooldown"] == 15
    assert queued(api) == ["panel.refresh", "guidelines.refresh"]
    assert ("settings.language", "web") in audit_actions(api)
    assert ("settings.cooldown", "web") in audit_actions(api)
    r = api.patch(BASE + "/settings", json={"auto_assign": True, "telegram_messages": False,
                                            "weekly_report": False}, headers=h)
    assert r.json()["telegram_messages"] is False and r.json()["weekly_report"] is False
    assert ("settings.report", "web") in audit_actions(api)
    assert queued(api) == ["panel.refresh", "guidelines.refresh"]     # nothing to redo
    assert ("settings.telegram_messages", "web") in audit_actions(api)
    for bad in ({"language": "fr"}, {"ticket_cooldown": 99999}, {"retention_days": 0}):
        assert api.patch(BASE + "/settings", json=bad, headers=h).status_code == 422
    r = api.put(BASE + "/settings/mode", json={"mode": "thread"}, headers=h)
    assert r.status_code == 202 and queued(api)[-1] == "settings.mode"


def test_types_questions_and_roles(api):  # noqa: F811
    h = admin(api)
    r = api.post(BASE + "/types", json={"label": " Payments ", "emoji": "💳",
                                        "description": "Invoices"}, headers=h)
    assert r.status_code == 201 and r.json()["key"] == "payments"
    assert r.json()["label"] == "Payments" and queued(api) == ["panel.refresh"]
    assert api.post(BASE + "/types", json={"label": "X", "emoji": "abc"},
                    headers=h).status_code == 422
    r = api.patch(BASE + "/types/payments", json={"emoji": "💰"}, headers=h)
    assert r.json()["emoji"] == "💰" and r.json()["label"] == "Payments"
    assert api.patch(BASE + "/types/nope", json={"label": "x"}, headers=h).status_code \
        == 404

    for n in range(3):
        r = api.post(BASE + "/types/payments/questions",
                     json={"label": f"Question {n}", "long": n == 1}, headers=h)
        assert r.status_code == 201
    assert [q["long"] for q in r.json()["questions"]] == [False, True, False]
    assert api.post(BASE + "/types/payments/questions", json={"label": "4th"},
                    headers=h).status_code == 409
    assert api.delete(BASE + "/types/payments/questions/1", headers=h).status_code == 204
    labels = [q["label"] for q in api.get(BASE + "/types").json()[-1]["questions"]]
    assert labels == ["Question 1", "Question 2"]
    assert api.delete(BASE + "/types/payments/questions/9", headers=h).status_code == 404

    for bad in (str(GUILD), "60", "999999999999999999"):      # @everyone, a bot's, unknown
        assert api.post(BASE + "/types/payments/roles", json={"role_id": bad},
                        headers=h).status_code == 422, bad
    r = api.post(BASE + "/types/payments/roles", json={"role_id": "30"}, headers=h)
    assert r.status_code == 201 and r.json()["roles"] == ["30"]
    assert api.post(BASE + "/types/payments/roles", json={"role_id": "30"},
                    headers=h).status_code == 409
    assert "thread.access" not in queued(api)                  # channel mode
    assert api.delete(BASE + "/types/payments/roles/30", headers=h).status_code == 204
    assert api.delete(BASE + "/types/payments/roles/30", headers=h).status_code == 404

    assert api.delete(BASE + "/types/payments", headers=h).status_code == 204
    keys = [t["key"] for t in api.get(BASE + "/types").json()]
    for key in keys[1:]:
        assert api.delete(BASE + f"/types/{key}", headers=h).status_code == 204
    assert api.delete(BASE + f"/types/{keys[0]}", headers=h).status_code == 409  # the last
    actions = {a for a, _ in audit_actions(api)}
    assert {"type.add", "type.edit", "type.remove", "type.question_add",
            "type.question_remove", "type.role_add", "type.role_remove"} <= actions


def test_role_in_thread_mode_gets_access(api):  # noqa: F811
    h = admin(api)
    conn = sqlite3.connect(api.db_path)
    with conn:
        conn.execute("UPDATE guilds SET ticket_mode = 'thread'")
    conn.close()
    api.post(BASE + "/types/support/roles", json={"role_id": "40"}, headers=h)
    assert queued(api) == ["thread.access"]


def test_faq(api):  # noqa: F811
    h = admin(api)
    assert api.post(BASE + "/faq", json={"type_key": "nope", "question": "Q", "answer": "A"},
                    headers=h).status_code == 404
    assert api.post(BASE + "/faq", json={"question": "  ", "answer": "A"},
                    headers=h).status_code == 422
    r = api.post(BASE + "/faq", json={"type_key": "bug", "question": "Crash?",
                                      "answer": "Update the drivers.\nThen retry."},
                 headers=h)
    assert r.status_code == 201
    entry = r.json()
    assert entry["type_key"] == "bug" and "\n" in entry["answer"]
    r = api.put(BASE + f"/faq/{entry['id']}", json={"question": "Crash at start?",
                                                    "answer": "Update."}, headers=h)
    assert r.json()["question"] == "Crash at start?"
    assert [e["id"] for e in api.get(BASE + "/faq").json()] == [entry["id"]]
    assert api.delete(BASE + f"/faq/{entry['id']}", headers=h).status_code == 204
    assert api.delete(BASE + f"/faq/{entry['id']}", headers=h).status_code == 404
    assert api.put(BASE + "/faq/99", json={"question": "a", "answer": "b"},
                   headers=h).status_code == 404


def test_escalation(api):  # noqa: F811
    h = admin(api)
    assert [lv["role_id"] for lv in api.get(BASE + "/escalation").json()] == ["40"]
    assert api.post(BASE + "/escalation", json={"role_id": "40"}, headers=h).status_code \
        == 409                                                       # already a level
    r = api.post(BASE + "/escalation", json={"role_id": "41", "after_hours": 24},
                 headers=h)
    assert r.status_code == 201 and r.json()[-1] == {"level": 2, "role_id": "41",
                                                     "after_hours": 24.0}
    assert api.post(BASE + "/escalation", json={"role_id": "30", "after_hours": 12},
                    headers=h).status_code == 409                    # must wait longer
    assert api.post(BASE + "/escalation", json={"role_id": "30", "after_hours": 0.1},
                    headers=h).status_code == 422
    r = api.delete(BASE + "/escalation/1", headers=h)
    assert r.json() == [{"level": 1, "role_id": "41", "after_hours": 24.0}]
    assert api.delete(BASE + "/escalation/5", headers=h).status_code == 404


def test_dev_cannot_manage_even_with_csrf(api):  # noqa: F811
    as_user(api, DEV)
    assert api.post(BASE + "/faq", json={"question": "Q", "answer": "A"},
                    headers=csrf(api)).status_code == 403
