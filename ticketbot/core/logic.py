"""Pure functions (no Discord calls), easy to unit test."""

import re
import unicodedata
from collections import Counter

from . import config


def is_kept(priority: str | None) -> bool:
    """High priority transcripts are kept until an admin deletes them."""
    return priority in config.KEPT_PRIORITIES


def autoclose_action(ticket: dict, now: float,
                     hours: int = config.AUTO_CLOSE_HOURS,
                     warn_before: int = config.WARNING_HOURS_BEFORE) -> str | None:
    """
    Decide what to do with an idle ticket: "warn", "close" or None.

    The timer only runs while the ticket is waiting on the USER (the last
    message came from the staff). A ticket waiting on the staff is never
    closed automatically.
    """
    if ticket.get("status") == config.STATUS_CLOSED or ticket.get("last_actor") != "staff":
        return None
    idle = now - (ticket.get("last_activity") or now)
    if idle >= hours * 3600:
        return "close"
    if idle >= (hours - warn_before) * 3600 and not ticket.get("warned"):
        return "warn"
    return None


def expired_refs(refs: list[dict], now: float, days: int) -> list[dict]:
    """Transcript messages (Low/Medium/unset) older than the retention period."""
    cutoff = now - days * 86400
    return [r for r in refs
            if not is_kept(r.get("priority")) and r.get("closed_at", now) <= cutoff]


def slugify(text: str, max_len: int = 20) -> str:
    """'Bug Report!' -> 'bug-report' (used as ticket type key and channel prefix)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].strip("-")


def ticket_channel_name(type_key: str, username: str, user_id: int, user_number: int) -> str:
    """'bug', 'Mario.Rossi', 42, 2 -> 'bug-mario-rossi-2' (Discord limit: 100 characters)."""
    user = slugify(username, max_len=32) or str(user_id)[-6:]
    return f"{type_key}-{user}-{user_number}"[:100]


def answers_text(answers: list[tuple[str, str]]) -> str:
    """Custom form answers as the ticket description: **Question**\nAnswer."""
    return "\n\n".join(f"**{question}**\n{answer.strip() or '-'}"
                         for question, answer in answers)


def attachment_problem(filename: str, size: int, max_bytes: int) -> str | None:
    """Why a form attachment can't be forwarded ("blocked", "too_big"), or None if it's fine."""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension in config.BLOCKED_EXTENSIONS:
        return "blocked"
    if size > max_bytes:
        return "too_big"
    return None


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{max(minutes, 1)}m" if seconds >= 30 else "<1m"


def cooldown_left(last_ticket: dict | None, minutes: int, now: float) -> float:
    """Seconds a member still has to wait before opening a new ticket (0 = can open)."""
    if not last_ticket or minutes <= 0:
        return 0.0
    return max(0.0, last_ticket["opened_at"] + minutes * 60 - now)


def assignment_order(available: list[dict], open_counts: dict[int, int]) -> list[int]:
    """Staff in the order they should get the next ticket: fewest open tickets first,
    then whoever has waited longest since their last assignment (round-robin)."""
    ranked = sorted(available, key=lambda s: (open_counts.get(s["user_id"], 0),
                                              s.get("last_assigned_at") or 0, s["user_id"]))
    return [s["user_id"] for s in ranked]


def stars(n: int | None) -> str:
    return "⭐" * n if n else "-"


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compute_stats(tickets: list[dict], staff_id: int | None = None) -> dict:
    """
    Aggregate statistics for a list of ticket rows.
    If staff_id is given, only tickets claimed by that staff member are counted.
    """
    if staff_id is not None:
        tickets = [t for t in tickets if t.get("claimed_by") == staff_id]

    closed = [t for t in tickets if t.get("status") == config.STATUS_CLOSED]
    first_responses = [max(0.0, t["first_response_at"] - t["opened_at"])
                       for t in tickets if t.get("first_response_at")]
    resolutions = [max(0.0, t["closed_at"] - t["opened_at"])
                   for t in closed if t.get("closed_at")]
    ratings = [t["rating"] for t in tickets if t.get("rating")]

    staff: dict[int, dict] = {}
    for t in tickets:
        sid = t.get("claimed_by")
        if not sid:
            continue
        s = staff.setdefault(sid, {"handled": 0, "ratings": [], "first_responses": []})
        s["handled"] += 1
        if t.get("rating"):
            s["ratings"].append(t["rating"])
        if t.get("first_response_at"):
            s["first_responses"].append(max(0.0, t["first_response_at"] - t["opened_at"]))

    leaderboard = sorted(
        ({"staff_id": sid,
          "handled": s["handled"],
          "avg_rating": _avg(s["ratings"]),
          "ratings": len(s["ratings"]),
          "avg_first_response": _avg(s["first_responses"])}
         for sid, s in staff.items()),
        key=lambda x: (-x["handled"], -(x["avg_rating"] or 0)),
    )

    return {
        "opened": len(tickets),
        "closed": len(closed),
        "open": len(tickets) - len(closed),
        "by_type": Counter(f"{t['type_emoji']} {t['type_label']}" for t in tickets),
        "by_priority": Counter(t.get("priority") for t in tickets),
        "avg_first_response": _avg(first_responses),
        "avg_resolution": _avg(resolutions),
        "avg_rating": _avg(ratings),
        "ratings": len(ratings),
        "unclaimed": sum(1 for t in tickets if not t.get("claimed_by")),
        "leaderboard": leaderboard,
    }


def valid_emoji(text: str) -> bool:
    """Accept one unicode emoji or a custom Discord emoji like <:name:id>."""
    text = text.strip()
    if re.fullmatch(r"<a?:\w{2,32}:\d{15,25}>", text):
        return True
    if re.fullmatch("[0-9#*]️?⃣", text):  # keycaps like 1️⃣
        return True
    if not text or len(text) > 10 or any(c.isascii() and c.isalnum() for c in text):
        return False
    return any(unicodedata.category(c) == "So" for c in text)


PROFILE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
PROFILE_IMAGE_MAX_MB = 8


def valid_profile_image(content_type: str | None, size: int) -> bool:
    """Images accepted for the bot's server avatar and banner."""
    kind = (content_type or "").split(";")[0].strip().lower()
    return kind in PROFILE_IMAGE_TYPES and 0 < size <= PROFILE_IMAGE_MAX_MB * 1024 * 1024


def reply_name(text: str) -> str:
    """Normalize a quick reply name: lowercase, letters/numbers/dashes, max 32 chars."""
    return slugify(text, max_len=32)


def fill_reply(content: str, user: str, staff: str, server: str) -> str:
    """Replace {user}, {staff} and {server}; any other brace is left untouched."""
    for key, value in (("{user}", user), ("{staff}", staff), ("{server}", server)):
        content = content.replace(key, value)
    return content


def activity_changes(ticket: dict, now: float, from_staff: bool) -> dict:
    """Fields to update when someone writes in a ticket."""
    changes = {"last_actor": "staff" if from_staff else "user",
               "last_activity": now, "warned": False}
    if from_staff:
        if ticket.get("status") == config.STATUS_WAITING:
            changes["status"] = config.STATUS_IN_PROGRESS
        if not ticket.get("first_response_at"):
            changes["first_response_at"] = now
        # The staff answered: stop waiting and reset the reminders
        changes["awaiting_staff_since"] = None
        changes["staff_reminded_at"] = None
    elif ticket.get("last_actor") == "staff" or not ticket.get("awaiting_staff_since"):
        # The user wrote after a staff answer: a new wait for the staff starts now.
        # If the user writes again before the staff answers, the start is kept.
        changes["awaiting_staff_since"] = now
    return changes


def waiting_for_staff_since(ticket: dict) -> float | None:
    """When the ticket started waiting for a staff reply, or None if it isn't waiting."""
    if ticket.get("status") == config.STATUS_CLOSED or ticket.get("last_actor") == "staff":
        return None
    return (ticket.get("awaiting_staff_since") or ticket.get("last_activity")
            or ticket.get("opened_at"))


def auto_escalation_level(ticket: dict, levels: list[dict], now: float) -> int | None:
    """The highest level whose waiting time has passed without a staff reply, when it is
    above the ticket's current level (None = nothing to do). Levels never go down."""
    since = waiting_for_staff_since(ticket)
    if since is None:
        return None
    due = [lv["level"] for lv in levels
           if lv.get("after_hours") and now - since >= lv["after_hours"] * 3600]
    target = max(due, default=0)
    return target if target > (ticket.get("escalation_level") or 0) else None


def staff_reply_hours(priority: str | None) -> int:
    hours = config.STAFF_REPLY_HOURS
    return hours.get(priority, hours[None])


def staff_reminder_due(ticket: dict, now: float) -> bool:
    """
    True when the ticket has waited longer than its priority allows for a staff reply.
    The reminder repeats every same interval until someone from the staff answers.
    """
    since = waiting_for_staff_since(ticket)
    if since is None:
        return False
    interval = staff_reply_hours(ticket.get("priority")) * 3600
    if now - since < interval:
        return False
    last = ticket.get("staff_reminded_at")
    return last is None or now - last >= interval
