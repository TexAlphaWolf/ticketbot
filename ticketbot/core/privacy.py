"""
/privacy: what the bot stores about one person in a server, as a file (export), and
deleting it (erase). Shared by the Discord command and the web dashboard; what is left
on Discord and Telegram after an erase (channels, transcript messages, notifications)
is deleted by the bot with the list `erase_personal_data` returns.

Kept on purpose, and written in PRIVACY.md: blocks (they stop abuse), the audit log
(security; deleted after 365 days) and what a staff member did in other people's
tickets (it is part of those tickets).
"""

import time
from datetime import UTC, datetime

from .transcripts import load_transcript


class PrivacyError(Exception):
    """The data can't be deleted yet (e.g. an open ticket)."""


def _when(value: float | None) -> str | None:
    return datetime.fromtimestamp(value, UTC).isoformat() if value else None


def _conversation(content: str) -> list[dict]:
    """A transcript's messages, without the staff notes (they are about the person, but
    the staff's internal work; the person's own messages and the answers are here)."""
    _, messages, _ = load_transcript(content)
    return [{"author": m.author, "author_id": str(m.author_id), "bot": m.bot,
             "sent_at": m.created_at.isoformat(), "text": m.content,
             "attachments": [a["filename"] for a in m.attachments],
             "embeds": [{k: e.get(k) for k in ("author", "title", "description")}
                        | {"fields": [list(f) for f in e.get("fields", [])]}
                        for e in m.embeds],
             "stickers": [s["name"] for s in m.stickers]}
            for m in messages]


async def export_personal_data(store, guild_id: int, user_id: int,
                               now: float | None = None) -> dict:
    """Everything about a person in a server (and their dashboard and Telegram links,
    which are not about one server), readable: JSON with dates in UTC."""
    now = now or time.time()
    tickets = []
    for t in reversed(await store.tickets_of_user(guild_id, user_id)):
        transcript = await store.ticket_transcript(t["id"])
        tickets.append({
            "id": t["id"], "number": t["number"], "channel": t["name"],
            "type": t["type_label"], "subject": t["subject"],
            "form_answers": t["description"], "status": t["status"],
            "priority": t["priority"], "opened_at": _when(t["opened_at"]),
            "handled_by": str(t["claimed_by"]) if t["claimed_by"] else None,
            "closed_at": _when(t["closed_at"]), "close_reason": t["close_reason"],
            "rating": t["rating"], "rating_comment": t["rating_comment"],
            "conversation": _conversation(transcript["content"]) if transcript else None,
        })
    block = await store.get_block(guild_id, user_id, now)
    account = await store.telegram_account_of(user_id)
    return {
        "about": "The data TicketBot stores about you in this server. Times are in UTC.",
        "exported_at": _when(now),
        "server_id": str(guild_id),
        "user_id": str(user_id),
        "tickets": tickets,
        "tickets_handled_as_staff": [
            {"id": t["id"], "number": t["number"], "type": t["type_label"],
             "status": t["status"], "opened_at": _when(t["opened_at"]),
             "closed_at": _when(t["closed_at"]), "rating": t["rating"]}
            for t in await store.handled_tickets(guild_id, user_id)],
        "notes_written": [
            {"ticket_id": n["ticket_id"], "text": n["text"],
             "written_at": _when(n["created_at"])}
            for n in await store.notes_by_author(guild_id, user_id)],
        "block": {"reason": block["reason"], "since": _when(block["blocked_at"]),
                  "until": _when(block["until"])} if block else None,
        "available_for_new_tickets": await store.is_available(guild_id, user_id),
        "actions": [
            {"action": a["action"], "source": a["source"], "target": a["target"],
             "details": a["details"], "at": _when(a["created_at"])}
            for a in await store.audit_of_actor(guild_id, user_id)],
        "dashboard_logins": [
            {"started_at": _when(s["created_at"]), "last_seen_at": _when(s["last_seen_at"]),
             "expires_at": _when(s["expires_at"]), "ip": s["ip"],
             "browser": s["user_agent"]}
            for s in await store.web_sessions_of(user_id)],
        "telegram_account": {"telegram_user_id": str(account["telegram_user_id"]),
                             "linked_at": _when(account["linked_at"])} if account else None,
    }


async def erase_personal_data(store, guild_id: int, user_id: int, hold_days: float = 0,
                              *, keep_sessions: bool = False) -> dict:
    """Delete a person's tickets (closed ones: open ones must be closed first), their
    Telegram link, dashboard logins and availability. Returns what the bot still has to
    delete on Discord and Telegram, ticket by ticket. `keep_sessions`: the dashboard
    deletes the current login itself, after answering."""
    tickets = await store.tickets_of_user(guild_id, user_id)
    if any(t["status"] != "closed" for t in tickets):
        raise PrivacyError("close your open tickets first")
    leftovers = []
    for t in tickets:
        telegram = await store.telegram_messages_of(t["id"])
        removed = await store.delete_ticket(t["id"], hold_days)
        leftovers.append({
            "channel_id": None if t["channel_deleted"] else str(t["channel_id"]),
            "telegram": telegram,
            "transcripts": [{k: str(v) if v else None for k, v in r.items() if k != "id"}
                            for r in removed]})
    await store.set_available(guild_id, user_id, False)
    telegram_account = await store.unlink_telegram_account(discord_user_id=user_id)
    sessions = 0 if keep_sessions else await store.delete_web_sessions_of(user_id)
    return {"tickets": len(tickets), "leftovers": leftovers, "sessions": sessions,
            "telegram_account": telegram_account}
