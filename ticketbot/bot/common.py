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
