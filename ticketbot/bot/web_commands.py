"""Actions asked from the web dashboard (the bot_commands queue), carried out on Discord.

The web checks the permissions before queueing an action; the bot checks them again
here with the member's current roles, since they may have changed in the meantime.
"""

import time

import discord

from ..core import config
from ..core.logic import activity_changes
from .common import (
    COLOR,
    grant_thread_access,
    is_ticket_staff,
    missing_thread_permissions,
    ticket_channel,
    translator,
)
from .tickets import (
    change_priority,
    claim_ticket,
    close_ticket,
    escalate,
    move_ticket,
    refresh_guidelines,
    refresh_panel,
    ticket_roles,
)

ADMIN_KINDS = {"settings.mode", "thread.access"}
TICKET_KINDS = {"ticket.close", "ticket.claim", "ticket.priority", "ticket.transfer",
                "ticket.escalate", "ticket.message"}


class CommandError(Exception):
    """The action can't be done; the message is shown in the dashboard."""


async def get_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return None
    return member


async def run_web_command(client, command: dict) -> str:
    """Carry out one queued action. Returns a short result; raises CommandError."""
    guild = client.get_guild(command["guild_id"])
    cfg = await client.db.get_guild(command["guild_id"])
    if guild is None or cfg is None:
        raise CommandError("the bot is not in this server anymore")
    payload, kind = command["payload"], command["kind"]
    if kind == "panel.refresh":
        problem = await refresh_panel(client, guild, cfg)
        if problem == "unknown panel":
            raise CommandError("the bot doesn't know the panel message yet: press "
                               "'Open ticket' on the panel once, or run /setup again")
        if problem:
            raise CommandError(f"the panel couldn't be updated ({problem})")
        return "ok"
    if kind == "guidelines.refresh":
        await refresh_guidelines(guild, cfg)
        return "ok"
    if kind in ADMIN_KINDS:
        member = await get_member(guild, command["requested_by"])
        if member is None or not member.guild_permissions.administrator:
            raise CommandError("only admins can change this")
        if kind == "settings.mode":
            return await set_ticket_mode(client, guild, cfg, payload["mode"], member)
        failed = await thread_access(client, guild, cfg,
                                     [int(r) for r in payload["role_ids"]])
        return f"could not change: {', '.join(failed)}" if failed else "ok"
    if kind not in TICKET_KINDS:
        raise CommandError(f"unknown command {kind!r}")

    ticket = await client.db.get_ticket(int(payload["ticket_id"]))
    if ticket is None or ticket["guild_id"] != guild.id:
        raise CommandError("ticket not found")
    if ticket["status"] == config.STATUS_CLOSED or ticket["channel_deleted"]:
        if kind == "ticket.close":
            return "already closed"
        raise CommandError("the ticket is closed")
    channel = await ticket_channel(guild, ticket)
    if channel is None:
        raise CommandError("the ticket channel doesn't exist anymore")
    member = await get_member(guild, command["requested_by"])
    if member is None or not is_ticket_staff(member, cfg,
                                             *await ticket_roles(client.db, ticket)):
        raise CommandError("you are not staff for this ticket anymore")
    _ = translator(cfg)

    if kind == "ticket.close":
        reason = (payload.get("reason") or "").strip() or _("close.reason_staff")
        await close_ticket(client, channel, ticket, member, reason[:500], source="web")
    elif kind == "ticket.claim":
        if ticket.get("claimed_by"):
            raise CommandError("the ticket was already claimed")
        await claim_ticket(client, channel, ticket, cfg, member, payload["priority"],
                           source="web")
    elif kind == "ticket.priority":
        await change_priority(client, channel, ticket, cfg, member, payload["priority"],
                              source="web")
    elif kind == "ticket.transfer":
        target = await get_member(guild, int(payload["member_id"]))
        if target is None or target.bot or not is_ticket_staff(
                target, cfg, *await ticket_roles(client.db, ticket)):
            raise CommandError("that member is not staff for this ticket")
        if ticket.get("claimed_by") == target.id:
            raise CommandError("the ticket is already theirs")
        await move_ticket(client, channel, ticket, cfg, target, member, source="web")
    elif kind == "ticket.escalate":
        levels = await client.db.escalation_levels(guild.id)
        current = ticket.get("escalation_level") or 0
        target = payload.get("level") or current + 1
        if not levels or target > levels[-1]["level"]:
            raise CommandError("there is no such escalation level")
        if target <= current:
            raise CommandError(f"the ticket is already at level {current}")
        if not await escalate(client, guild, channel, ticket, cfg, target, member,
                              payload.get("reason"), source="web"):
            raise CommandError(f"the role of level {target} doesn't exist anymore")
    elif kind == "ticket.message":
        await post_staff_message(client, channel, ticket, member, payload["text"], _)
    return "ok"


async def set_ticket_mode(client, guild: discord.Guild, cfg: dict, mode: str,
                          member: discord.Member) -> str:
    """Channels or private threads for new tickets (like /settings mode)."""
    if mode == "thread":
        panel = guild.get_channel(cfg.get("panel_channel") or 0)
        if panel is None:
            raise CommandError("the panel channel doesn't exist anymore: run /setup again")
        missing = missing_thread_permissions(panel, guild.me)
        if missing:
            raise CommandError(f"the bot needs these permissions in #{panel.name}: "
                               + ", ".join(missing))
        roles = {cfg["staff_role"]} | {
            r for ids in (await client.db.all_type_roles(guild.id)).values() for r in ids}
        failed = await grant_thread_access(panel, [guild.get_role(r) for r in roles])
    else:
        failed = []
    await client.db.save_guild(guild.id, ticket_mode=mode)
    await client.db.audit(guild.id, member.id, "settings.mode", source="web",
                          details={"value": mode})
    return f"ok; could not give access to: {', '.join(failed)}" if failed else "ok"


async def thread_access(client, guild: discord.Guild, cfg: dict,
                        role_ids: list[int]) -> list[str]:
    """In thread mode, roles that handle tickets need Manage Threads in the panel."""
    if cfg.get("ticket_mode") != "thread":
        return []
    panel = guild.get_channel(cfg.get("panel_channel") or 0)
    if panel is None:
        return []
    failed = await grant_thread_access(panel, [guild.get_role(r) for r in role_ids])
    return [f.strip("<@&>") for f in failed]


async def post_staff_message(client, channel, ticket: dict, member: discord.Member,
                             text: str, _) -> None:
    """A staff reply written in the dashboard, posted by the bot with the author's name.
    It counts as a staff answer (first response, reminders, auto-close)."""
    embed = discord.Embed(description=text[:4000], color=COLOR)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_footer(text=_("web.message_footer"))
    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    now = time.time()
    changes = activity_changes(ticket, now, from_staff=True)
    await client.db.update_ticket(ticket["id"], **changes)
    await client.db.audit(channel.guild.id, member.id, "ticket.message", source="web",
                          target=f"ticket:{ticket['id']}")
