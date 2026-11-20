"""Helpers shared by tickets, commands and the bot."""

import html
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord

from ..core import config
from ..core.i18n import t

if TYPE_CHECKING:
    from .client import TicketBot

Translate = Callable[..., str]

COLOR = discord.Color.blurple()  # embeds


def lang_of(cfg: dict | None) -> str:
    return (cfg or {}).get("language") or config.DEFAULT_LANGUAGE


def translator(cfg: dict | None) -> Translate:
    lang = lang_of(cfg)
    return lambda key, /, **kw: t(lang, key, **kw)


def is_staff(member: discord.abc.User, cfg: dict | None) -> bool:
    if cfg is None or not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(role.id == cfg.get("staff_role") for role in member.roles)


def priority_label(_: Translate, priority: str | None) -> str:
    if priority not in config.PRIORITY_EMOJI:
        return f"⚪ {_('priority.none')}"
    return f"{config.PRIORITY_EMOJI[priority]} {_('priority.' + priority)}"


def type_label(ticket: dict) -> str:
    return f"{ticket['type_emoji']} {ticket['type_label']}"


async def ticket_channel(guild: discord.Guild, ticket: dict):
    """The channel or private thread of a ticket, or None if it doesn't exist anymore.
    Archived threads are not in the cache, so they are fetched (an API call)."""
    found = guild.get_channel_or_thread(ticket["channel_id"])
    if found is not None or not ticket.get("is_thread"):
        return found
    try:
        return await guild.fetch_channel(ticket["channel_id"])
    except (discord.NotFound, discord.Forbidden):
        return None


def channel_url(guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


def esc(text) -> str:
    return html.escape(str(text))


def user_name(guild: discord.Guild | None, user_id: int | None, client=None) -> str:
    if not user_id:
        return "-"
    member = guild.get_member(user_id) if guild else None
    if member is not None:
        return str(member)
    user = client.get_user(user_id) if client else None
    return str(user) if user else str(user_id)


async def telegram_notify(client: "TicketBot", cfg: dict | None, text: str,
                          document: bytes | None = None, filename: str | None = None) -> None:
    """Send a notification to the Telegram chat linked to this server only."""
    tg = client.telegram
    chat_id = (cfg or {}).get("telegram_chat_id")
    if tg is None or not chat_id:
        return
    from ..integrations.telegram import TelegramError
    try:
        if document is not None:
            await tg.send_document(chat_id, document, filename or "transcript.html", caption=text)
        else:
            await tg.send_message(chat_id, text)
    except TelegramError as e:
        print(f"[telegram] could not notify guild {cfg.get('guild_id')}: {e}")


def is_ticket_staff(member: discord.abc.User, cfg: dict | None,
                    type_roles: list[int]) -> bool:
    """Staff for one ticket: the type's roles when the type has some, else the staff
    role; admins always."""
    if not type_roles:
        return is_staff(member, cfg)
    if cfg is None or not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    return any(role.id in type_roles for role in member.roles)


def staff_mentions(cfg: dict, type_roles: list[int]) -> str:
    """Who to ping for a ticket: the type's roles, or the staff role."""
    roles = type_roles or ([cfg["staff_role"]] if cfg.get("staff_role") else [])
    return " ".join(f"<@&{r}>" for r in roles)


async def audit(interaction: discord.Interaction, action: str, target: str | None = None,
                **details) -> None:
    """Record an action done by a member from Discord in the audit log."""
    await interaction.client.db.audit(
        interaction.guild.id if interaction.guild else None, interaction.user.id, action,
        target=target, details={k: v for k, v in details.items() if v is not None} or None)


async def respond(interaction: discord.Interaction, content: str | None = None, **kwargs) -> None:
    """Reply to an interaction whether or not it was already answered/deferred."""
    if interaction.response.is_done():
        await interaction.followup.send(content, **kwargs)
    else:
        await interaction.response.send_message(content, **kwargs)
