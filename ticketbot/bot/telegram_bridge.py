"""
Two-way Telegram: the staff answers the ticket notifications on Telegram and the answer
reaches the ticket on Discord, with the same permissions as on Discord and in the
dashboard.

- A member links their Telegram account once: `/telegram-account link` on Discord gives
  a one-time code, sent to the Telegram bot with `/link CODE` (or by opening the link).
- Answering (reply) a notification about a ticket with a text posts it in the ticket
  with the member's name; its buttons (or the answers `/claim priority` and
  `/close reason`) take the ticket, choosing the priority like on Discord, or close it.
- What users write in their tickets is sent to Telegram too (`/telegram messages`), and
  can be answered the same way.
"""

import html
import re
import secrets
import time

import discord

from ..core import config
from ..core.i18n import LANGUAGES, t
from ..integrations.telegram import TelegramError
from .common import (
    channel_url,
    is_ticket_staff,
    priority_label,
    telegram_notify,
    ticket_buttons,
    translator,
)
from .tickets import ticket_roles
from .web_commands import CommandError, run_web_command

CODE_TTL = 10 * 60              # seconds a link code works
TEXT_LIMIT = 1500               # characters of a user's message sent to Telegram


def priority_buttons(_) -> list[tuple[str, str]]:
    """Claim, like on Discord: first the priority."""
    return ([(priority_label(_, p), f"claim:{p}") for p in config.PRIORITIES]
            + [(_("tg.btn_back"), "keep")])


def buttons_for(ticket: dict | None, _) -> list[tuple[str, str]]:
    """What can still be done on a ticket: Claim (if nobody has it) and Close."""
    return [] if ticket is None else ticket_buttons(_, ticket)


def parse_priority(word: str) -> str | None:
    """`high`, `alta`, `hoch`... in any of the bot's languages."""
    word = word.strip().lower()
    for p in config.PRIORITIES:
        if word == p or any(word == t(lang, f"priority.{p}").lower() for lang in LANGUAGES):
            return p
    return None


def new_account_code(client, discord_user_id: int, language: str,
                     now: float | None = None) -> str:
    """A one-time code that links the Telegram account that sends it to this member.
    8 random characters: guessing one in its 10 minutes isn't realistic."""
    now = now or time.time()
    codes = client.telegram_codes
    for code, pending in list(codes.items()):          # one code per member, no old ones
        if pending["user_id"] == discord_user_id or pending["expires"] < now:
            del codes[code]
    code = secrets.token_hex(4).upper()
    codes[code] = {"user_id": discord_user_id, "expires": now + CODE_TTL,
                   "language": language}
    return code


async def handle_message(client, message: dict) -> None:
    """Everything the Telegram bot receives besides /start and /id."""
    try:
        await _handle(client, message)
    except Exception as e:                    # one bad message must not stop the others
        print(f"[telegram] could not handle a message: {e}")


async def _answer(client, message: dict, text: str) -> None:
    try:
        await client.telegram.send_message(str(message["chat"]["id"]), text,
                                           reply_to=message.get("message_id"))
    except TelegramError as e:
        print(f"[telegram] could not answer: {e}")


async def _handle(client, message: dict) -> None:
    sender = message.get("from") or {}
    if not sender.get("id") or sender.get("is_bot"):
        return
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    words = text.split(maxsplit=1)
    command = words[0].split("@")[0].lower() if text.startswith("/") else None
    argument = words[1].strip() if len(words) > 1 else ""

    if command in ("/link", "/start"):                   # /start CODE: the link
        await link_account(client, message, sender, argument)
        return
    if command == "/unlink":
        removed = await client.db.unlink_telegram_account(telegram_user_id=sender["id"])
        _ = translator(None)
        await _answer(client, message, _("tg.account_unlinked") if removed
                      else _("tg.account_needed"))
        return

    reply = message.get("reply_to_message")
    if not reply:
        if command in ("/claim", "/close"):         # which ticket? say how to choose it
            await _answer(client, message, translator(None)("tg.reply_needed"))
        return
    tracked = await client.db.telegram_message(chat_id, reply["message_id"])
    if tracked is None:
        return                                   # not an answer to a ticket notification
    cfg = await client.db.get_guild(tracked["guild_id"])
    if not cfg or str(cfg.get("telegram_chat_id")) != str(chat_id):
        return                                   # the chat was unlinked from the server
    _ = translator(cfg)
    account = await client.db.telegram_account(sender["id"])
    if account is None:
        await _answer(client, message, _("tg.account_needed"))
        return
    if not text:
        await _answer(client, message, _("tg.only_text"))
        return

    if command == "/claim":
        priority = parse_priority(argument)
        if priority is None:                      # like on Discord: choose it first
            sent = await client.telegram.send_message(
                str(chat_id), _("tg.choose_priority"), reply_to=message.get("message_id"),
                buttons=priority_buttons(_))
            await client.db.track_telegram_message(chat_id, sent["message_id"],
                                                   tracked["guild_id"], tracked["ticket_id"])
            return
        kind, payload = "ticket.claim", {"priority": priority}
    elif command == "/close":
        kind, payload = "ticket.close", {"reason": argument}
    elif command is not None:
        await _answer(client, message, _("tg.unknown_command"))
        return
    else:
        kind, payload = "ticket.message", {"text": text}
    try:
        await run_web_command(client, {
            "guild_id": tracked["guild_id"], "kind": kind, "source": "telegram",
            "requested_by": account["discord_user_id"],
            "payload": {"ticket_id": tracked["ticket_id"], **payload}})
    except CommandError as e:
        await _answer(client, message, _("tg.failed", reason=html.escape(str(e))))
        return
    try:
        await client.telegram.react(str(chat_id), message["message_id"])
    except TelegramError:                       # reactions not allowed in this chat
        await _answer(client, message, _("tg.done"))


def plain(text: str) -> str:
    """A text without HTML, for the notices of the buttons."""
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def handle_button(client, query: dict) -> None:
    """A button under a ticket notification: Claim, Close (then Yes / Keep it open)."""
    try:
        await _button(client, query)
    except Exception as e:
        print(f"[telegram] could not handle a button: {e}")


async def _button(client, query: dict) -> None:
    tg = client.telegram
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    data = query.get("data")
    tracked = (await client.db.telegram_message(chat_id, message_id)
               if chat_id is not None and message_id is not None else None)
    cfg = await client.db.get_guild(tracked["guild_id"]) if tracked else None
    if tracked is None or not cfg or str(cfg.get("telegram_chat_id")) != str(chat_id):
        await tg.answer_button(query["id"], plain(translator(cfg)("tg.button_old")), True)
        return
    _ = translator(cfg)
    account = await client.db.telegram_account((query.get("from") or {}).get("id") or 0)
    if account is None:
        await tg.answer_button(query["id"], plain(_("tg.account_needed")), True)
        return

    async def buttons(new):
        try:
            await tg.set_buttons(str(chat_id), message_id, new)
        except TelegramError:
            pass                                  # e.g. too old to be changed

    if data == "close":                           # ask first: a tap can be a mistake
        await buttons([(_("tg.btn_confirm_close"), "close!"), (_("tg.btn_keep"), "keep")])
        await tg.answer_button(query["id"])
        return
    if data == "claim":                           # like on Discord: the priority first
        await buttons(priority_buttons(_))
        await tg.answer_button(query["id"], plain(_("tg.choose_priority")))
        return
    if data == "keep":
        await buttons(buttons_for(await client.db.get_ticket(tracked["ticket_id"]), _))
        await tg.answer_button(query["id"])
        return
    if data.startswith("claim:") and data[6:] in config.PRIORITIES:
        kind, payload = "ticket.claim", {"priority": data[6:]}
    elif data == "close!":
        kind, payload = "ticket.close", {"reason": ""}
    else:
        await tg.answer_button(query["id"])
        return
    try:
        await run_web_command(client, {
            "guild_id": tracked["guild_id"], "kind": kind, "source": "telegram",
            "requested_by": account["discord_user_id"],
            "payload": {"ticket_id": tracked["ticket_id"], **payload}})
    except CommandError as e:
        await buttons(buttons_for(await client.db.get_ticket(tracked["ticket_id"]), _))
        await tg.answer_button(query["id"], plain(_("tg.failed", reason=str(e))), True)
        return
    # What is left to do: Close after a claim, nothing after closing
    await buttons(buttons_for(await client.db.get_ticket(tracked["ticket_id"]), _))
    await tg.answer_button(query["id"], plain(_("tg.done")))


async def link_account(client, message: dict, sender: dict, code: str) -> None:
    code = code.strip().upper()
    pending = client.telegram_codes.get(code)
    if pending is None or pending["expires"] < time.time():
        client.telegram_codes.pop(code, None)
        await _answer(client, message, translator(None)("tg.account_bad_code"))
        return
    del client.telegram_codes[code]                    # one use only
    await client.db.link_telegram_account(sender["id"], pending["user_id"])
    _ = translator({"language": pending["language"]})
    user = client.get_user(pending["user_id"])
    await _answer(client, message, _("tg.account_linked", user=html.escape(
        user.display_name if user else str(pending["user_id"]))))


async def forward_user_message(client, message: discord.Message, ticket: dict,
                               cfg: dict) -> None:
    """What a user writes in a ticket, to the server's Telegram chat (answerable)."""
    if client.telegram is None or not cfg.get("telegram_chat_id") \
            or not cfg.get("telegram_messages", True):
        return
    if message.author.id != ticket["owner_id"] and is_ticket_staff(
            message.author, cfg, *await ticket_roles(client.db, ticket)):
        return                     # the staff's own answers (the owner counts as a user)
    _ = translator(cfg)
    text = message.clean_content.strip()
    if len(text) > TEXT_LIMIT:
        text = text[:TEXT_LIMIT] + "…"
    if not text and not message.attachments:
        return                                            # e.g. only a sticker
    files = _("tg.attachments", count=len(message.attachments)) if message.attachments else ""
    await telegram_notify(client, cfg, _(
        "tg.user_message", guild=html.escape(message.guild.name),
        channel=html.escape(getattr(message.channel, "name", "?")),
        user=html.escape(message.author.display_name), text=html.escape(text),
        attachments=files, url=channel_url(message.guild.id, message.channel.id),
    ), ticket_id=ticket["id"])


def purge_before(now: float) -> float:
    return now - config.TELEGRAM_MESSAGE_DAYS * 86400
