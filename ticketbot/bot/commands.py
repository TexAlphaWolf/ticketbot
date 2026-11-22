"""Slash commands."""

import io
import re
import secrets
import time
from datetime import UTC, datetime

import discord
from discord import app_commands

from ..core import config, export
from ..core.i18n import DEFAULT_TYPES, LANGUAGES
from ..core.logic import (
    PROFILE_IMAGE_MAX_MB,
    activity_changes,
    compute_stats,
    fill_reply,
    format_duration,
    new_type_key,
    reply_name,
    stars,
    valid_emoji,
    valid_profile_image,
)
from ..integrations.telegram import TelegramError
from . import telegram_bridge
from .common import (
    COLOR,
    audit,
    esc,
    grant_thread_access,
    is_staff,
    lang_of,
    missing_thread_permissions,
    priority_label,
    respond,
    telegram_notify,
    translator,
)
from .tickets import (
    TicketPanel,
    apply_priority,
    escalate,
    get_context,
    guidelines_embed,
    panel_embed,
    refresh_guidelines,
    refresh_panel,
    reopen_ticket,
    request_close,
    ticket_label,
    transfer_ticket,
)

admin_only = app_commands.default_permissions(administrator=True)


def detect_language(guild: discord.Guild) -> str:
    locale = str(guild.preferred_locale or "")
    for lang in LANGUAGES:
        if locale.startswith(lang):
            return lang
    return config.DEFAULT_LANGUAGE


async def require_setup(interaction: discord.Interaction):
    cfg = await interaction.client.db.get_guild(interaction.guild.id)
    _ = translator(cfg)
    if cfg is None or not cfg.get("category"):
        await respond(interaction, _("error.not_setup"), ephemeral=True)
        return None
    return cfg, _


# ------------------------------------------------------------------ setup ---

@app_commands.command(name="setup", description="Set up the ticket system and post the panel")
@app_commands.guild_only()
@admin_only
@app_commands.describe(
    staff_role="Role of the moderators who handle tickets",
    category="Category where ticket channels are created",
    log_channel="Channel where transcripts are logged",
    panel_channel="Channel where the 'Open ticket' button is posted",
    archive_channel="(Optional) Archive channel that keeps every transcript",
)
async def setup(interaction: discord.Interaction, staff_role: discord.Role,
                category: discord.CategoryChannel, log_channel: discord.TextChannel,
                panel_channel: discord.TextChannel,
                archive_channel: discord.TextChannel | None = None):
    db = interaction.client.db
    guild = interaction.guild
    existing = await db.get_guild(guild.id)
    lang = existing["language"] if existing else detect_language(guild)
    fields = dict(staff_role=staff_role.id, category=category.id,
                  log_channel=log_channel.id, language=lang)
    if archive_channel is not None:
        fields["archive_channel"] = archive_channel.id
    cfg = await db.save_guild(guild.id, **fields)
    await db.ensure_default_types(guild.id, DEFAULT_TYPES[lang])
    _ = translator(cfg)

    try:
        message = await panel_channel.send(embed=panel_embed(await db.list_types(guild.id), _),
                                           view=TicketPanel(_))
    except discord.HTTPException:
        await interaction.response.send_message(
            _("setup.panel_failed", channel=panel_channel.mention), ephemeral=True
        )
        return
    await db.save_guild(guild.id, panel_channel=panel_channel.id, panel_message=message.id)
    await audit(interaction, "setup", staff_role=staff_role.id, category=category.id,
                log_channel=log_channel.id, panel_channel=panel_channel.id,
                archive_channel=archive_channel.id if archive_channel else None)
    await interaction.response.send_message(
        _("setup.done", channel=panel_channel.mention, language=LANGUAGES[lang]), ephemeral=True
    )


@app_commands.command(name="guidelines",
                      description="Post and pin the priority guidelines in the log channel")
@app_commands.guild_only()
@admin_only
async def guidelines(interaction: discord.Interaction):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    cfg, _ = ctx
    guild = interaction.guild
    channel = guild.get_channel(cfg.get("log_channel") or 0)
    if channel is None:
        await interaction.response.send_message(_("error.no_log_channel"), ephemeral=True)
        return

    old_channel = guild.get_channel(cfg.get("guidelines_channel") or 0)
    if old_channel is not None and cfg.get("guidelines_message"):
        try:
            await old_channel.get_partial_message(cfg["guidelines_message"]).delete()
        except discord.HTTPException:
            pass

    message = await channel.send(embed=guidelines_embed(cfg, _))
    await interaction.client.db.save_guild(guild.id, guidelines_channel=channel.id,
                                     guidelines_message=message.id)
    try:
        await message.pin(reason="Ticket priority guidelines")
        text = _("guidelines.posted", channel=channel.mention)
    except discord.HTTPException:
        text = _("guidelines.posted_not_pinned", channel=channel.mention)
    await interaction.response.send_message(text, ephemeral=True)


def ticket_history_embed(tickets: list[dict], title: str, _) -> discord.Embed:
    """Open tickets first, then the latest closed ones."""
    open_lines, closed_lines = [], []
    for t in tickets:
        kind = f"{t['type_emoji']} {t['type_label']}"
        if t["status"] != config.STATUS_CLOSED:
            status = _("mytickets.status." + t["status"])
            where = f"<#{t['channel_id']}>" if not t["channel_deleted"] else ticket_label(t)
            open_lines.append(f"{status} · {where} · {kind} · <t:{int(t['opened_at'])}:R>")
        else:
            line = (f"✅ **{ticket_label(t)}** · {kind} · <t:{int(t['opened_at'])}:d>"
                    f" → <t:{int(t['closed_at'] or t['opened_at'])}:d>")
            if t.get("rating"):
                line += f" · {stars(t['rating'])}"
            if t.get("close_reason"):
                line += f"\n-# {t['close_reason'][:90]}"
            closed_lines.append(line)

    embed = discord.Embed(title=title, color=COLOR)
    if open_lines:
        embed.add_field(name=_("mytickets.open", count=len(open_lines)),
                        value="\n".join(open_lines)[:1024], inline=False)
    if closed_lines:
        shown = closed_lines[:config.MYTICKETS_CLOSED_SHOWN]
        value = ""
        for line in shown:  # keep whole lines within Discord's 1024 characters
            if len(value) + len(line) + 1 > 1024:
                break
            value += line + "\n"
        embed.add_field(name=_("mytickets.closed", shown=len(shown), total=len(closed_lines)),
                        value=value.strip(), inline=False)
    if not tickets:
        embed.description = _("mytickets.none")
    return embed


@app_commands.command(name="mytickets", description="Show your tickets in this server")
@app_commands.guild_only()
@app_commands.describe(member="(Staff only) Show the tickets of another member")
async def mytickets(interaction: discord.Interaction, member: discord.Member | None = None):
    db = interaction.client.db
    cfg = await db.get_guild(interaction.guild.id)
    _ = translator(cfg)
    target = member or interaction.user
    if target.id != interaction.user.id and not is_staff(interaction.user, cfg):
        await interaction.response.send_message(_("mytickets.staff_only"), ephemeral=True)
        return
    tickets = await db.tickets_of_user(interaction.guild.id, target.id)
    if member is not None and target.id != interaction.user.id:
        await audit(interaction, "tickets.view_member", f"user:{target.id}")
    title = (_("mytickets.title_member", user=target.display_name) if member
             else _("mytickets.title"))
    await interaction.response.send_message(embed=ticket_history_embed(tickets, title, _),
                                            ephemeral=True)


@app_commands.command(name="available",
                      description="Choose whether you get automatically assigned tickets")
@app_commands.guild_only()
@app_commands.describe(enabled="True to join the rotation, False to leave it")
async def available(interaction: discord.Interaction, enabled: bool):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    cfg, _ = ctx
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(_("error.staff_only"), ephemeral=True)
        return
    db = interaction.client.db
    await db.set_available(interaction.guild.id, interaction.user.id, enabled)
    await audit(interaction, "staff.available", enabled=enabled)
    text = _("available.on") if enabled else _("available.off")
    if enabled and not cfg.get("auto_assign"):
        text += "\n" + _("available.feature_off")
    count = len(await db.available_staff(interaction.guild.id))
    await interaction.response.send_message(text + "\n" + _("available.count", count=count),
                                            ephemeral=True)


@app_commands.command(name="queue", description="Show how many tickets are open right now")
@app_commands.guild_only()
async def queue(interaction: discord.Interaction):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    _ = ctx[1]
    waiting, in_progress = await interaction.client.db.queue_counts(interaction.guild.id)
    await interaction.response.send_message(
        "📊 " + _("queue.line", waiting=waiting, in_progress=in_progress), ephemeral=True
    )


# ------------------------------------------------------ inside a ticket ---

@app_commands.command(name="add", description="Add a member to this ticket")
@app_commands.guild_only()
@app_commands.describe(user="Member to add")
async def add(interaction: discord.Interaction, user: discord.Member):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    _, ticket = ctx[1], ctx[2]
    if isinstance(interaction.channel, discord.Thread):
        await interaction.channel.add_user(user)
    else:
        await interaction.channel.set_permissions(
            user, view_channel=True, send_messages=True, attach_files=True,
            read_message_history=True,
        )
    await audit(interaction, "ticket.add_member", f"ticket:{ticket['id']}", user=user.id)
    await interaction.response.send_message(_("member.added", user=user.mention))


@app_commands.command(name="remove", description="Remove a member from this ticket")
@app_commands.guild_only()
@app_commands.describe(user="Member to remove")
async def remove(interaction: discord.Interaction, user: discord.Member):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    _, ticket = ctx[1], ctx[2]
    if user.id == ticket["owner_id"]:
        await interaction.response.send_message(_("member.cant_remove_owner"), ephemeral=True)
        return
    if isinstance(interaction.channel, discord.Thread):
        await interaction.channel.remove_user(user)
    else:
        await interaction.channel.set_permissions(user, overwrite=None)
    await audit(interaction, "ticket.remove_member", f"ticket:{ticket['id']}", user=user.id)
    await interaction.response.send_message(_("member.removed", user=user.mention))


@app_commands.command(name="close", description="Close this ticket")
@app_commands.guild_only()
@app_commands.describe(reason="(Optional) Reason for closing the ticket")
async def close(interaction: discord.Interaction,
                reason: app_commands.Range[str, 1, 500] | None = None):
    await request_close(interaction, reason)


@app_commands.command(name="reopen", description="Reopen this closed ticket")
@app_commands.guild_only()
async def reopen(interaction: discord.Interaction):
    await reopen_ticket(interaction)


@app_commands.command(name="priority", description="Change the priority of this ticket")
@app_commands.guild_only()
@app_commands.describe(level="New priority")
@app_commands.choices(level=[
    app_commands.Choice(name="Low", value="low"),
    app_commands.Choice(name="Medium", value="medium"),
    app_commands.Choice(name="High", value="high"),
])
async def priority(interaction: discord.Interaction, level: app_commands.Choice[str]):
    await apply_priority(interaction, level.value, claim=False)


@app_commands.command(name="transfer", description="Assign this ticket to another staff member")
@app_commands.guild_only()
@app_commands.describe(member="Staff member who will handle the ticket")
async def transfer(interaction: discord.Interaction, member: discord.Member):
    await transfer_ticket(interaction, member)


@app_commands.command(name="escalate",
                      description="Bring this ticket to the next escalation level")
@app_commands.guild_only()
@app_commands.describe(level="(Optional) Level to reach (default: the next one)",
                       reason="(Optional) Why the ticket needs a higher level")
async def escalate_command(interaction: discord.Interaction,
                           level: app_commands.Range[int, 1, config.MAX_ESCALATION_LEVELS]
                           | None = None,
                           reason: app_commands.Range[str, 1, 300] | None = None):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    levels = await interaction.client.db.escalation_levels(interaction.guild.id)
    if not levels:
        await interaction.response.send_message(_("escalation.none"), ephemeral=True)
        return
    current = ticket.get("escalation_level") or 0
    target = level or current + 1
    if target > levels[-1]["level"]:
        key = "escalation.top" if level is None else "escalation.no_level"
        await interaction.response.send_message(
            _(key, level=target, top=levels[-1]["level"]), ephemeral=True)
        return
    if target <= current:
        await interaction.response.send_message(
            _("escalation.already", level=current), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    done = await escalate(interaction.client, interaction.guild, interaction.channel, ticket,
                          cfg, target, interaction.user, reason)
    await interaction.followup.send(
        _("escalation.sent", level=target) if done else _("escalation.role_gone", level=target),
        ephemeral=True)


class EscalationGroup(app_commands.Group):
    """/escalation ...: the levels above the normal staff."""

    def __init__(self):
        super().__init__(name="escalation", description="Escalation levels above the staff",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="list", description="Show the escalation levels")
    async def list_levels(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        levels = await interaction.client.db.escalation_levels(interaction.guild.id)
        lines = [_("escalation.line", level=lv["level"], role=f"<@&{lv['role_id']}>")
                 + (" · " + _("escalation.after", hours=f"{lv['after_hours']:g}")
                    if lv["after_hours"] else "")
                 for lv in levels]
        embed = discord.Embed(title=_("escalation.title", count=len(levels),
                                      max=config.MAX_ESCALATION_LEVELS),
                              description="\n".join(lines) or _("escalation.empty"),
                              color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add the next escalation level")
    @app_commands.describe(
        role="Role that takes over at this level",
        after_hours="(Optional) Escalate by itself after these hours without a staff reply")
    async def add_level(self, interaction: discord.Interaction, role: discord.Role,
                        after_hours: app_commands.Range[float, 0.5,
                                                        config.MAX_ESCALATION_HOURS]
                        | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        levels = await db.escalation_levels(interaction.guild.id)
        if role.is_default() or role.managed:
            await interaction.response.send_message(_("roles.invalid"), ephemeral=True)
            return
        if len(levels) >= config.MAX_ESCALATION_LEVELS:
            await interaction.response.send_message(
                _("escalation.too_many", max=config.MAX_ESCALATION_LEVELS), ephemeral=True)
            return
        if any(lv["role_id"] == role.id for lv in levels):
            await interaction.response.send_message(
                _("escalation.role_used", role=role.mention), ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        timed = [lv["after_hours"] for lv in levels if lv["after_hours"]]
        if after_hours is not None and timed and after_hours <= max(timed):
            await interaction.response.send_message(
                _("escalation.hours_order", hours=f"{max(timed):g}"), ephemeral=True)
            return
        level = await db.add_escalation_level(interaction.guild.id, role.id, after_hours)
        await audit(interaction, "escalation.add", f"level:{level}", role=role.id,
                    after_hours=after_hours)
        text = _("escalation.added", level=level, role=role.mention)
        if after_hours is not None:
            text += "\n" + _("escalation.added_auto", hours=f"{after_hours:g}")
        if cfg.get("ticket_mode") == "thread":
            text += "\n" + _("roles.thread_note")
        await interaction.response.send_message(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="remove", description="Remove an escalation level")
    @app_commands.describe(level="Number of the level (see /escalation list)")
    async def remove_level(self, interaction: discord.Interaction,
                           level: app_commands.Range[int, 1, config.MAX_ESCALATION_LEVELS]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        if not await interaction.client.db.remove_escalation_level(interaction.guild.id, level):
            await interaction.response.send_message(
                _("escalation.not_there", level=level), ephemeral=True)
            return
        await audit(interaction, "escalation.remove", f"level:{level}")
        await interaction.response.send_message(_("escalation.removed", level=level),
                                                ephemeral=True)


class NoteGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="note", description="Private staff notes on this ticket",
                         guild_only=True)

    @app_commands.command(name="add", description="Add a private note visible only to the staff")
    @app_commands.describe(text="Text of the note")
    async def note_add(self, interaction: discord.Interaction,
                       text: app_commands.Range[str, 1, 1000]):
        ctx = await get_context(interaction, staff=True)
        if ctx is None:
            return
        _, ticket = ctx[1], ctx[2]
        await interaction.client.db.add_note(ticket["id"], interaction.user.id, text, time.time())
        await audit(interaction, "ticket.note", f"ticket:{ticket['id']}")
        await interaction.response.send_message(_("note.added"), ephemeral=True)

    @app_commands.command(name="list", description="Show the private notes of this ticket")
    async def note_list(self, interaction: discord.Interaction):
        ctx = await get_context(interaction, staff=True, allow_closed=True)
        if ctx is None:
            return
        _, ticket = ctx[1], ctx[2]
        notes = await interaction.client.db.list_notes(ticket["id"])
        if not notes:
            await interaction.response.send_message(_("note.none"), ephemeral=True)
            return
        embed = discord.Embed(title=_("note.title"), color=discord.Color.gold())
        for n in notes[-25:]:
            embed.add_field(name=f"<t:{int(n['created_at'])}:f>",
                            value=f"<@{n['author_id']}>: {n['text']}"[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ------------------------------------------------------------------ stats ---

PERIODS = {"7": 7, "30": 30, "90": 90, "all": None}


PERIOD_CHOICES = [
    app_commands.Choice(name="Last 7 days", value="7"),
    app_commands.Choice(name="Last 30 days", value="30"),
    app_commands.Choice(name="Last 90 days", value="90"),
    app_commands.Choice(name="All time", value="all"),
]


def audit_lines(entries: list[dict], _) -> list[str]:
    lines = []
    for e in entries:
        who = f"<@{e['actor_id']}>" if e["actor_id"] else _("audit.system")
        source = "" if e["source"] == "discord" else f" ({e['source']})"
        target = f" · `{e['target']}`" if e["target"] else ""
        lines.append(f"<t:{int(e['created_at'])}:R> · {who}{source} · **{e['action']}**{target}")
    return lines


@app_commands.command(name="audit", description="Show the latest actions done in this server")
@app_commands.guild_only()
@admin_only
@app_commands.describe(member="Only the actions of this member")
async def audit_log(interaction: discord.Interaction, member: discord.Member | None = None):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    _ = ctx[1]
    entries = await interaction.client.db.audit_entries(interaction.guild.id, limit=200)
    if member is not None:
        entries = [e for e in entries if e["actor_id"] == member.id]
    embed = discord.Embed(title=_("audit.title"), color=COLOR)
    description = ""
    for line in audit_lines(entries[:config.AUDIT_SHOWN], _):
        if len(description) + len(line) + 1 > 4000:     # Discord: 4096 characters
            break
        description += line + "\n"
    embed.description = description.strip() or _("audit.none")
    embed.set_footer(text=_("audit.footer", days=config.AUDIT_KEEP_DAYS))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app_commands.command(name="stats", description="Show ticket statistics")
@app_commands.guild_only()
@app_commands.describe(period="Time period", member="Show the statistics of one staff member")
@app_commands.choices(period=PERIOD_CHOICES)
async def stats(interaction: discord.Interaction,
                period: app_commands.Choice[str] | None = None,
                member: discord.Member | None = None):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    cfg, _ = ctx
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(_("error.staff_only"), ephemeral=True)
        return

    key = period.value if period else "30"
    days = PERIODS[key]
    since = time.time() - days * 86400 if days else 0
    rows = await interaction.client.db.tickets_since(interaction.guild.id, since)
    s = compute_stats(rows, member.id if member else None)

    period_label = _("stats.period." + key)
    title = (_("stats.title_member", member=member.display_name, period=period_label)
             if member else _("stats.title", period=period_label))
    embed = discord.Embed(title=title, color=COLOR)
    embed.add_field(name=_("stats.tickets"),
                    value=_("stats.tickets_value", opened=s["opened"], closed=s["closed"],
                            open=s["open"]), inline=False)
    embed.add_field(name=_("stats.first_response"), value=format_duration(s["avg_first_response"]))
    embed.add_field(name=_("stats.resolution"), value=format_duration(s["avg_resolution"]))
    embed.add_field(
        name=_("stats.rating"),
        value=f"{s['avg_rating']:.1f} ⭐ ({s['ratings']})" if s["ratings"] else "-",
    )
    if s["by_type"]:
        embed.add_field(name=_("stats.by_type"), value="\n".join(
            f"{label}: **{n}**" for label, n in s["by_type"].most_common(10)))
    if s["opened"]:
        embed.add_field(name=_("stats.by_priority"), value="\n".join(
            f"{priority_label(_, p)}: **{s['by_priority'].get(p, 0)}**"
            for p in (*config.PRIORITIES, None)))
    if not member and s["leaderboard"]:
        lines = []
        for i, row in enumerate(s["leaderboard"][:10], 1):
            rating = f"{row['avg_rating']:.1f}⭐" if row["avg_rating"] else "-"
            lines.append(_("stats.staff_line", rank=i, user=f"<@{row['staff_id']}>",
                           handled=row["handled"], rating=rating,
                           response=format_duration(row["avg_first_response"])))
        embed.add_field(name=_("stats.staff"), value="\n".join(lines)[:1024], inline=False)
    faq = None if member else await interaction.client.db.faq_results_since(
        interaction.guild.id, since)
    if faq and (faq["solved"] or faq["opened"]):
        embed.add_field(name=_("stats.faq"), value=_("stats.faq_value", **faq), inline=False)
    if not s["opened"]:
        embed.description = _("stats.empty")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@app_commands.command(name="export", description="Download the ticket statistics as a file")
@app_commands.guild_only()
@app_commands.describe(period="Time period", file_format="File type")
@app_commands.rename(file_format="format")
@app_commands.choices(period=PERIOD_CHOICES, file_format=[
    app_commands.Choice(name="Excel (.xlsx)", value="xlsx"),
    app_commands.Choice(name="CSV (.csv)", value="csv"),
])
async def export_stats(interaction: discord.Interaction,
                       period: app_commands.Choice[str] | None = None,
                       file_format: app_commands.Choice[str] | None = None):
    ctx = await require_setup(interaction)
    if ctx is None:
        return
    cfg, _ = ctx
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(_("error.staff_only"), ephemeral=True)
        return

    key = period.value if period else "30"
    kind = file_format.value if file_format else "xlsx"
    days = PERIODS[key]
    guild = interaction.guild
    tickets = await interaction.client.db.tickets_since(guild.id, time.time() - days * 86400
                                                  if days else 0)
    if not tickets:
        await interaction.response.send_message(_("stats.empty"), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)

    ids = {t[k] for t in tickets for k in ("owner_id", "claimed_by", "assigned_to", "closed_by")
           if t.get(k)}
    names = {i: m.name for i in ids if (m := guild.get_member(i)) is not None}
    rows = export.ticket_rows(tickets, names, _)
    period_label = _("stats.period." + key)
    data = (export.to_xlsx(rows, tickets, names, period_label, _) if kind == "xlsx"
            else export.to_csv(rows, _))
    if len(data) > guild.filesize_limit:
        await interaction.followup.send(_("export.too_big"), ephemeral=True)
        return
    await audit(interaction, "data.export", period=key, format=kind, tickets=len(rows))
    day = datetime.now(UTC).strftime("%Y%m%d")
    filename = f"tickets-{key}-{day}.{kind}"
    await interaction.followup.send(
        _("export.done", count=len(rows), period=period_label),
        file=discord.File(io.BytesIO(data), filename=filename), ephemeral=True,
    )


# --------------------------------------------------------------- settings ---

class SettingsGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="settings", description="Ticket system settings",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="show", description="Show the current settings")
    async def show(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx

        def ch(cid):
            return f"<#{cid}>" if cid else "-"

        embed = discord.Embed(title=_("settings.title"), color=COLOR)
        embed.add_field(name=_("settings.language"), value=LANGUAGES[cfg["language"]])
        embed.add_field(name=_("settings.staff_role"),
                        value=f"<@&{cfg['staff_role']}>" if cfg.get("staff_role") else "-")
        embed.add_field(name=_("settings.category"), value=ch(cfg.get("category")))
        embed.add_field(name=_("settings.log"), value=ch(cfg.get("log_channel")))
        embed.add_field(name=_("settings.archive"), value=ch(cfg.get("archive_channel")))
        embed.add_field(name=_("settings.panel"), value=ch(cfg.get("panel_channel")))
        embed.add_field(name=_("settings.retention"),
                        value=_("settings.days", days=cfg["retention_days"]))
        embed.add_field(name=_("settings.telegram"),
                        value=f"`{cfg['telegram_chat_id']}`" if cfg.get("telegram_chat_id")
                        else "-")
        embed.add_field(name=_("settings.reminders"),
                        value=_("settings.on") if cfg.get("staff_reminders", 1)
                        else _("settings.off"))
        available = len(await interaction.client.db.available_staff(interaction.guild.id))
        embed.add_field(name=_("settings.autoassign"),
                        value=_("settings.autoassign_on", count=available)
                        if cfg.get("auto_assign") else _("settings.off"))
        embed.add_field(name=_("settings.mode"),
                        value=_("settings.mode_" + (cfg.get("ticket_mode") or "channel")))
        cooldown = cfg.get("ticket_cooldown") or 0
        embed.add_field(name=_("settings.cooldown"),
                        value=format_duration(cooldown * 60) if cooldown else _("settings.off"))
        types = await interaction.client.db.list_types(interaction.guild.id)
        embed.add_field(name=_("settings.types"), value=str(len(types)))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="language", description="Change the language of the bot")
    @app_commands.describe(language="Language used by the bot in this server")
    @app_commands.choices(language=[
        app_commands.Choice(name=name, value=code) for code, name in LANGUAGES.items()
    ])
    async def language(self, interaction: discord.Interaction,
                       language: app_commands.Choice[str]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg = await interaction.client.db.save_guild(interaction.guild.id, language=language.value)
        await audit(interaction, "settings.language", value=language.value)
        _ = translator(cfg)
        await interaction.response.send_message(
            _("settings.language_set", language=language.name), ephemeral=True
        )
        await refresh_panel(interaction.client, interaction.guild, cfg)
        await refresh_guidelines(interaction.guild, cfg)

    @app_commands.command(
        name="retention",
        description="Days after which Low/Medium transcripts are deleted from the log",
    )
    @app_commands.describe(days="Number of days (1-365)")
    async def retention(self, interaction: discord.Interaction,
                        days: app_commands.Range[int, 1, 365]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg = await interaction.client.db.save_guild(interaction.guild.id, retention_days=days)
        await audit(interaction, "settings.retention", value=days)
        _ = translator(cfg)
        await interaction.response.send_message(_("settings.retention_set", days=days),
                                                ephemeral=True)
        await refresh_guidelines(interaction.guild, cfg)

    @app_commands.command(name="reminders", description="Turn the staff reminders on or off")
    @app_commands.describe(
        enabled="Remind the staff when a ticket waits too long for a reply")
    async def reminders(self, interaction: discord.Interaction, enabled: bool):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg = await interaction.client.db.save_guild(interaction.guild.id,
                                               staff_reminders=enabled)
        await audit(interaction, "settings.reminders", value=enabled)
        _ = translator(cfg)
        await interaction.response.send_message(
            _("settings.reminders_on") if enabled else _("settings.reminders_off"),
            ephemeral=True)
        await refresh_guidelines(interaction.guild, cfg)

    @app_commands.command(name="autoassign",
                          description="Assign new tickets automatically to the available staff")
    @app_commands.describe(enabled="Staff members join the rotation with /available")
    async def autoassign(self, interaction: discord.Interaction, enabled: bool):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        await interaction.client.db.save_guild(interaction.guild.id, auto_assign=enabled)
        await audit(interaction, "settings.autoassign", value=enabled)
        await interaction.response.send_message(
            _("settings.autoassign_set_on") if enabled else _("settings.autoassign_set_off"),
            ephemeral=True)

    @app_commands.command(name="mode",
                          description="Open new tickets as channels or as private threads")
    @app_commands.describe(mode="Where new tickets are opened")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Channels (one per ticket)", value="channel"),
        app_commands.Choice(name="Private threads in the panel channel", value="thread"),
    ])
    async def mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        guild = interaction.guild
        text = _("settings.mode_set_channel")
        if mode.value == "thread":
            panel = guild.get_channel(cfg.get("panel_channel") or 0)
            if panel is None:
                await interaction.response.send_message(_("error.bad_setup"), ephemeral=True)
                return
            missing = missing_thread_permissions(panel, guild.me)
            if missing:
                await interaction.response.send_message(
                    _("settings.mode_missing", channel=panel.mention,
                      permissions=", ".join(missing)), ephemeral=True)
                return
            roles = {cfg["staff_role"]} | {
                r for ids in (await interaction.client.db.all_type_roles(guild.id)).values()
                for r in ids}
            failed = await grant_thread_access(panel, [guild.get_role(r) for r in roles])
            text = _("settings.mode_set_thread", channel=panel.mention)
            if failed:
                text += "\n" + _("settings.mode_roles_failed", roles=" ".join(failed))
        await interaction.client.db.save_guild(guild.id, ticket_mode=mode.value)
        await audit(interaction, "settings.mode", value=mode.value)
        await interaction.response.send_message(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="cooldown",
                          description="Minimum time between two tickets of the same member")
    @app_commands.describe(minutes="Minutes (0 = off, max 1440)")
    async def cooldown(self, interaction: discord.Interaction,
                       minutes: app_commands.Range[int, 0, config.MAX_TICKET_COOLDOWN_MINUTES]):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        await interaction.client.db.save_guild(interaction.guild.id, ticket_cooldown=minutes)
        await audit(interaction, "settings.cooldown", value=minutes)
        await interaction.response.send_message(
            _("settings.cooldown_set", time=format_duration(minutes * 60)) if minutes
            else _("settings.cooldown_off"), ephemeral=True)

    @app_commands.command(name="archive", description="Set or remove the archive channel")
    @app_commands.describe(channel="Archive channel (leave empty to disable it)")
    async def archive(self, interaction: discord.Interaction,
                      channel: discord.TextChannel | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        await interaction.client.db.save_guild(interaction.guild.id,
                                         archive_channel=channel.id if channel else None)
        await audit(interaction, "settings.archive", value=channel.id if channel else None)
        await interaction.response.send_message(
            _("settings.archive_set", channel=channel.mention) if channel
            else _("settings.archive_off"), ephemeral=True
        )


# ---------------------------------------------------------- blocked users ---

BLOCK_CHOICES = [
    app_commands.Choice(name="1 hour", value="1h"),
    app_commands.Choice(name="1 day", value="1d"),
    app_commands.Choice(name="7 days", value="7d"),
    app_commands.Choice(name="30 days", value="30d"),
    app_commands.Choice(name="Permanent", value="permanent"),
]


async def log_event(guild: discord.Guild, cfg: dict, text: str) -> None:
    """Post a short moderation note in the log channel, if there is one."""
    channel = guild.get_channel(cfg.get("log_channel") or 0)
    if channel is None:
        return
    try:
        await channel.send(embed=discord.Embed(description=text, color=COLOR),
                           allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        pass


class BlockGroup(app_commands.Group):
    """/block ...: members who can't open tickets."""

    def __init__(self):
        super().__init__(name="block", description="Block members from opening tickets",
                         guild_only=True)

    async def _staff(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return None
        cfg, _ = ctx
        if not is_staff(interaction.user, cfg):
            await interaction.response.send_message(_("error.staff_only"), ephemeral=True)
            return None
        return ctx

    @app_commands.command(name="add", description="Block a member from opening tickets")
    @app_commands.describe(member="Member to block", duration="How long the block lasts",
                           reason="Reason (shown to the member)")
    @app_commands.choices(duration=BLOCK_CHOICES)
    async def block_add(self, interaction: discord.Interaction, member: discord.Member,
                        duration: app_commands.Choice[str] | None = None,
                        reason: app_commands.Range[str, 1, config.BLOCK_REASON_LENGTH]
                        | None = None):
        ctx = await self._staff(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        if member.bot or member.id == interaction.user.id or is_staff(member, cfg):
            await interaction.response.send_message(_("block.cannot"), ephemeral=True)
            return
        db = interaction.client.db
        now = time.time()
        seconds = config.BLOCK_DURATIONS[duration.value if duration else "permanent"]
        until = now + seconds if seconds else None
        await db.block_user(interaction.guild.id, member.id, reason, interaction.user.id, now,
                            until)
        await audit(interaction, "block.add", f"user:{member.id}", until=until, reason=reason)

        when = _("block.until", time=f"<t:{int(until)}:f>") if until else _("block.permanent")
        text = _("block.added", user=member.mention, when=when)
        existing = await db.open_ticket_of_owner(interaction.guild.id, member.id)
        if existing:
            text += "\n" + _("block.has_open", channel=f"<#{existing['channel_id']}>")
        await interaction.response.send_message(text, ephemeral=True)
        log = _("block.log_added", staff=interaction.user.mention, user=member.mention,
                when=when)
        if reason:
            log += "\n" + _("open.blocked_reason", reason=reason)
        await log_event(interaction.guild, cfg, log)

    @app_commands.command(name="remove", description="Allow a member to open tickets again")
    @app_commands.describe(member="Member to unblock")
    async def block_remove(self, interaction: discord.Interaction, member: discord.Member):
        ctx = await self._staff(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        active = await db.get_block(interaction.guild.id, member.id, time.time())
        await db.unblock_user(interaction.guild.id, member.id)
        if not active:
            await interaction.response.send_message(_("block.not_blocked", user=member.mention),
                                                    ephemeral=True)
            return
        await audit(interaction, "block.remove", f"user:{member.id}")
        await interaction.response.send_message(_("block.removed", user=member.mention),
                                                ephemeral=True)
        await log_event(interaction.guild, cfg, _("block.log_removed",
                                                  staff=interaction.user.mention,
                                                  user=member.mention))

    @app_commands.command(name="list", description="Show the blocked members")
    async def block_list(self, interaction: discord.Interaction):
        ctx = await self._staff(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        blocks = await interaction.client.db.list_blocks(interaction.guild.id, time.time())
        embed = discord.Embed(title=_("block.list_title", count=len(blocks)), color=COLOR)
        description = ""
        for b in blocks:
            when = (_("block.until", time=f"<t:{int(b['until'])}:R>") if b["until"]
                    else _("block.permanent"))
            line = f"<@{b['user_id']}> · {when} · <@{b['blocked_by']}>"
            if b.get("reason"):
                line += f"\n-# {b['reason'][:100]}"
            if len(description) + len(line) + 1 > 4000:  # Discord: 4096 characters
                description += "…"
                break
            description += line + "\n"
        embed.description = description.strip() or _("block.none")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ------------------------------------------------------------ ticket types ---

async def type_autocomplete(interaction: discord.Interaction, current: str):
    types = await interaction.client.db.list_types(interaction.guild.id)
    current = current.lower()
    return [
        app_commands.Choice(name=f"{t['emoji']} {t['label']}"[:100], value=t["key"])
        for t in types if current in t["label"].lower() or current in t["key"]
    ][:25]


class QuestionsGroup(app_commands.Group):
    """/types questions ...: the custom form of each ticket type."""

    def __init__(self):
        super().__init__(name="questions", description="Custom questions of the ticket form")

    async def _type(self, interaction: discord.Interaction, key: str):
        db = interaction.client.db
        _ = translator(await db.get_guild(interaction.guild.id))
        ticket_type = await db.get_type(interaction.guild.id, key)
        if ticket_type is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
        return ticket_type, _

    @app_commands.command(name="list", description="Show the questions of a ticket type")
    @app_commands.describe(type="Ticket type")
    @app_commands.autocomplete(type=type_autocomplete)
    async def list_questions(self, interaction: discord.Interaction, type: str):
        ticket_type, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        questions = await interaction.client.db.list_questions(interaction.guild.id, type)
        name = f"{ticket_type['emoji']} {ticket_type['label']}"
        if not questions:
            text = _("questions.none")
        else:
            lines = []
            for q in questions:
                kind = _("questions.long") if q["long"] else _("questions.short")
                need = _("questions.required") if q["required"] else _("questions.optional")
                example = f"\n   -# {q['placeholder']}" if q["placeholder"] else ""
                lines.append(f"**{q['position']}.** {q['label']} ({kind}, {need}){example}")
            text = "\n".join(lines)
        embed = discord.Embed(title=_("questions.title", type=name,
                                      count=len(questions), max=config.MAX_TYPE_QUESTIONS),
                              description=text, color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a question to the form of a ticket type")
    @app_commands.describe(
        type="Ticket type",
        question="Question shown to the user (max 45 characters)",
        length="Answer length",
        required="Whether the answer is required",
        example="(Optional) Example shown inside the field",
    )
    @app_commands.autocomplete(type=type_autocomplete)
    @app_commands.choices(length=[
        app_commands.Choice(name="Short", value="short"),
        app_commands.Choice(name="Long", value="long"),
    ])
    async def add_question(self, interaction: discord.Interaction, type: str,
                           question: app_commands.Range[str, 1, 45],
                           length: app_commands.Choice[str] | None = None,
                           required: bool = True,
                           example: app_commands.Range[str, 1, 100] | None = None):
        ticket_type, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        db = interaction.client.db
        if len(await db.list_questions(interaction.guild.id, type)) >= config.MAX_TYPE_QUESTIONS:
            await interaction.response.send_message(
                _("questions.too_many", max=config.MAX_TYPE_QUESTIONS), ephemeral=True)
            return
        position = await db.add_question(interaction.guild.id, type, question.strip(),
                                   (example or "").strip(),
                                   long=bool(length and length.value == "long"),
                                   required=required)
        await audit(interaction, "type.question_add", f"type:{type}", position=position)
        await interaction.response.send_message(
            _("questions.added", number=position, question=question.strip(),
              type=f"{ticket_type['emoji']} {ticket_type['label']}"), ephemeral=True)

    @app_commands.command(name="remove", description="Remove a question from the form")
    @app_commands.describe(type="Ticket type",
                           number="Number of the question (see /types questions list)")
    @app_commands.autocomplete(type=type_autocomplete)
    async def remove_question(self, interaction: discord.Interaction, type: str,
                              number: app_commands.Range[int, 1, 10]):
        ticket_type, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        if await interaction.client.db.remove_question(interaction.guild.id, type, number):
            await audit(interaction, "type.question_remove", f"type:{type}", position=number)
            text = _("questions.removed", number=number,
                     type=f"{ticket_type['emoji']} {ticket_type['label']}")
        else:
            text = _("questions.bad_number", number=number)
        await interaction.response.send_message(text, ephemeral=True)


class TypeRolesGroup(app_commands.Group):
    """/types roles ...: which roles handle the tickets of a type."""

    def __init__(self):
        super().__init__(name="roles", description="Roles that handle the tickets of a type")

    async def _type(self, interaction: discord.Interaction, key: str):
        db = interaction.client.db
        cfg = await db.get_guild(interaction.guild.id)
        _ = translator(cfg)
        ticket_type = await db.get_type(interaction.guild.id, key)
        if ticket_type is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
        return ticket_type, cfg, _

    @app_commands.command(name="add",
                          description="Let a role see and handle the tickets of a type")
    @app_commands.describe(type="Ticket type", role="Role that handles these tickets")
    @app_commands.autocomplete(type=type_autocomplete)
    async def add_role(self, interaction: discord.Interaction, type: str, role: discord.Role):
        ticket_type, cfg, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        name = f"{ticket_type['emoji']} {ticket_type['label']}"
        if role.is_default() or role.managed:
            await interaction.response.send_message(_("roles.invalid"), ephemeral=True)
            return
        if not await interaction.client.db.add_type_role(interaction.guild.id, type, role.id):
            await interaction.response.send_message(
                _("roles.exists", role=role.mention, type=name), ephemeral=True)
            return
        await audit(interaction, "type.role_add", f"type:{type}", role=role.id)
        text = _("roles.added", role=role.mention, type=name)
        if cfg.get("ticket_mode") == "thread":
            panel = interaction.guild.get_channel(cfg.get("panel_channel") or 0)
            if panel is not None and await grant_thread_access(panel, [role]):
                text += "\n" + _("settings.mode_roles_failed", roles=role.mention)
            text += "\n" + _("roles.thread_note")
        await interaction.response.send_message(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(name="remove", description="Remove a role from a ticket type")
    @app_commands.describe(type="Ticket type", role="Role to remove")
    @app_commands.autocomplete(type=type_autocomplete)
    async def remove_role(self, interaction: discord.Interaction, type: str,
                          role: discord.Role):
        ticket_type, cfg, _ = await self._type(interaction, type)
        if ticket_type is None:
            return
        name = f"{ticket_type['emoji']} {ticket_type['label']}"
        db = interaction.client.db
        if not await db.remove_type_role(interaction.guild.id, type, role.id):
            await interaction.response.send_message(
                _("roles.not_there", role=role.mention, type=name), ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
            return
        await audit(interaction, "type.role_remove", f"type:{type}", role=role.id)
        text = _("roles.removed", role=role.mention, type=name)
        if not await db.type_roles(interaction.guild.id, type):
            text += "\n" + _("roles.back_to_staff", staff=f"<@&{cfg['staff_role']}>")
        await interaction.response.send_message(
            text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())


class TypesGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="types", description="Manage the ticket types of this server",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))
        self.add_command(QuestionsGroup())
        self.add_command(TypeRolesGroup())

    @app_commands.command(name="list", description="Show the ticket types")
    async def list_types(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        types = await interaction.client.db.list_types(interaction.guild.id)
        roles = await interaction.client.db.all_type_roles(interaction.guild.id)
        lines = [f"{t['emoji']} **{t['label']}** (`{t['key']}`)"
                 + (f" – {t['description']}" if t["description"] else "")
                 + ("\n-# " + _("roles.handled_by",
                                roles=" ".join(f"<@&{r}>" for r in roles[t["key"]]))
                    if t["key"] in roles else "")
                 for t in types]
        embed = discord.Embed(title=_("types.title", count=len(types),
                                      max=config.MAX_TICKET_TYPES),
                              description="\n".join(lines) or "-", color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a ticket type")
    @app_commands.describe(name="Name of the type", emoji="Emoji shown next to the name",
                           description="(Optional) Short description shown in the menu")
    async def add_type(self, interaction: discord.Interaction,
                       name: app_commands.Range[str, 1, 80], emoji: str,
                       description: app_commands.Range[str, 1, 100] | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        types = await db.list_types(interaction.guild.id)
        if len(types) >= config.MAX_TICKET_TYPES:
            await interaction.response.send_message(
                _("types.too_many", max=config.MAX_TICKET_TYPES), ephemeral=True)
            return
        if not valid_emoji(emoji):
            await interaction.response.send_message(_("types.bad_emoji"), ephemeral=True)
            return
        key = new_type_key(name, {t["key"] for t in types})
        await db.add_type(interaction.guild.id, key, name.strip(), emoji.strip(),
                    (description or "").strip())
        await audit(interaction, "type.add", f"type:{key}", label=name.strip())
        await interaction.response.send_message(
            _("types.added", type=f"{emoji} {name}", key=key), ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, cfg)

    @app_commands.command(name="edit", description="Edit a ticket type")
    @app_commands.describe(type="Type to edit", name="New name", emoji="New emoji",
                           description="New description")
    @app_commands.autocomplete(type=type_autocomplete)
    async def edit_type(self, interaction: discord.Interaction, type: str,
                        name: app_commands.Range[str, 1, 80] | None = None,
                        emoji: str | None = None,
                        description: app_commands.Range[str, 1, 100] | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        current = await db.get_type(interaction.guild.id, type)
        if current is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        changes = {}
        if name:
            changes["label"] = name.strip()
        if emoji:
            if not valid_emoji(emoji):
                await interaction.response.send_message(_("types.bad_emoji"), ephemeral=True)
                return
            changes["emoji"] = emoji.strip()
        if description:
            changes["description"] = description.strip()
        if not changes:
            await interaction.response.send_message(_("types.nothing"), ephemeral=True)
            return
        await db.update_type(interaction.guild.id, type, **changes)
        await audit(interaction, "type.edit", f"type:{type}", **changes)
        updated = await db.get_type(interaction.guild.id, type)
        await interaction.response.send_message(
            _("types.edited", type=f"{updated['emoji']} {updated['label']}"), ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, cfg)

    @app_commands.command(name="remove", description="Remove a ticket type")
    @app_commands.describe(type="Type to remove")
    @app_commands.autocomplete(type=type_autocomplete)
    async def remove_type(self, interaction: discord.Interaction, type: str):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        db = interaction.client.db
        types = await db.list_types(interaction.guild.id)
        target = next((t for t in types if t["key"] == type), None)
        if target is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        if len(types) <= 1:
            await interaction.response.send_message(_("types.last"), ephemeral=True)
            return
        await db.remove_type(interaction.guild.id, type)
        await audit(interaction, "type.remove", f"type:{type}")
        await interaction.response.send_message(
            _("types.removed", type=f"{target['emoji']} {target['label']}"), ephemeral=True)
        await refresh_panel(interaction.client, interaction.guild, cfg)


# --------------------------------------------------------------- telegram ---

class TelegramGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="telegram", description="Ticket notifications on Telegram",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    async def ready(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return None
        cfg, _ = ctx
        if interaction.client.telegram is None:
            await interaction.response.send_message(_("tg.disabled"), ephemeral=True)
            return None
        return cfg, _

    @app_commands.command(name="link", description="Link a Telegram chat to this server")
    @app_commands.describe(chat_id="Telegram chat ID (send /start to the Telegram bot to get it)")
    async def link(self, interaction: discord.Interaction, chat_id: str):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        client = interaction.client
        chat_id = chat_id.strip()
        if not re.fullmatch(r"-?\d{1,20}", chat_id):
            await interaction.response.send_message(_("tg.bad_id"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        code = f"{secrets.randbelow(1_000_000):06d}"
        try:
            await client.telegram.send_message(chat_id, _(
                "tg.code", guild=esc(interaction.guild.name), code=code,
                minutes=config.VERIFY_CODE_TTL // 60,
            ))
        except TelegramError:
            await interaction.followup.send(
                _("tg.unreachable", bot=client.telegram.username), ephemeral=True)
            return
        client.pending_links[interaction.guild.id] = {
            "chat_id": chat_id, "code": code,
            "expires": time.time() + config.VERIFY_CODE_TTL, "attempts": 0,
        }
        await interaction.followup.send(_("tg.code_sent"), ephemeral=True)

    @app_commands.command(name="verify", description="Confirm the Telegram link with the code")
    @app_commands.describe(code="The 6-digit code you received on Telegram")
    async def verify(self, interaction: discord.Interaction, code: str):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        client = interaction.client
        pending = client.pending_links.get(interaction.guild.id)
        if pending is None or time.time() > pending["expires"]:
            client.pending_links.pop(interaction.guild.id, None)
            await interaction.response.send_message(_("tg.no_code"), ephemeral=True)
            return
        pending["attempts"] += 1
        if not secrets.compare_digest(code.strip(), pending["code"]):
            left = config.VERIFY_MAX_ATTEMPTS - pending["attempts"]
            if left <= 0:
                client.pending_links.pop(interaction.guild.id, None)
                await interaction.response.send_message(_("tg.too_many"), ephemeral=True)
            else:
                await interaction.response.send_message(_("tg.wrong_code", left=left),
                                                        ephemeral=True)
            return
        cfg = await client.db.save_guild(interaction.guild.id, telegram_chat_id=pending["chat_id"])
        await audit(interaction, "telegram.link", chat=pending["chat_id"])
        client.pending_links.pop(interaction.guild.id, None)
        await interaction.response.send_message(_("tg.linked"), ephemeral=True)
        await telegram_notify(client, cfg, _("tg.linked_chat",
                                             guild=esc(interaction.guild.name)))

    @app_commands.command(name="status", description="Show the Telegram link of this server")
    async def status(self, interaction: discord.Interaction):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        if cfg.get("telegram_chat_id"):
            text = _("tg.status_linked", chat=cfg["telegram_chat_id"])
        else:
            text = _("tg.status_none", bot=interaction.client.telegram.username)
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="test", description="Send a test notification to Telegram")
    async def test(self, interaction: discord.Interaction):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        if not cfg.get("telegram_chat_id"):
            await interaction.response.send_message(_("tg.not_linked"), ephemeral=True)
            return
        await telegram_notify(interaction.client, cfg,
                              _("tg.test", guild=esc(interaction.guild.name)))
        await interaction.response.send_message(_("tg.test_sent"), ephemeral=True)

    @app_commands.command(name="unlink", description="Stop sending notifications to Telegram")
    async def unlink(self, interaction: discord.Interaction):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        await interaction.client.db.save_guild(interaction.guild.id, telegram_chat_id=None)
        await audit(interaction, "telegram.unlink")
        interaction.client.pending_links.pop(interaction.guild.id, None)
        await interaction.response.send_message(_("tg.unlinked"), ephemeral=True)

    @app_commands.command(name="messages",
                          description="Also send to Telegram what users write in their tickets")
    @app_commands.describe(enabled="On: every message of a user in a ticket reaches the chat")
    async def messages(self, interaction: discord.Interaction, enabled: bool):
        ctx = await self.ready(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        await interaction.client.db.save_guild(interaction.guild.id, telegram_messages=enabled)
        await audit(interaction, "settings.telegram_messages", enabled=enabled)
        await interaction.response.send_message(
            _("tg.messages_on" if enabled else "tg.messages_off"), ephemeral=True)


class TelegramAccountGroup(app_commands.Group):
    """Two-way Telegram: each staff member links their own Telegram account, then
    answers the ticket notifications there."""

    def __init__(self):
        super().__init__(name="telegram-account",
                         description="Answer tickets from Telegram with your account",
                         guild_only=True)

    async def _ready(self, interaction: discord.Interaction):
        cfg = await interaction.client.db.get_guild(interaction.guild.id)
        _ = translator(cfg)
        if interaction.client.telegram is None:
            await interaction.response.send_message(_("tg.disabled"), ephemeral=True)
            return None
        return cfg, _

    @app_commands.command(name="link", description="Link your Telegram account")
    async def link(self, interaction: discord.Interaction):
        ctx = await self._ready(interaction)
        if ctx is None:
            return
        cfg, _ = ctx
        client = interaction.client
        code = telegram_bridge.new_account_code(client, interaction.user.id, lang_of(cfg))
        bot = client.telegram.username
        await interaction.response.send_message(_(
            "tg.account_code", bot=bot, code=code, link=f"https://t.me/{bot}?start={code}",
            minutes=telegram_bridge.CODE_TTL // 60), ephemeral=True)

    @app_commands.command(name="status", description="Show whether your Telegram account is linked")
    async def status(self, interaction: discord.Interaction):
        ctx = await self._ready(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        account = await interaction.client.db.telegram_account_of(interaction.user.id)
        await interaction.response.send_message(
            _("tg.account_status", since=f"<t:{int(account['linked_at'])}:D>") if account
            else _("tg.account_status_none"), ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink your Telegram account")
    async def unlink(self, interaction: discord.Interaction):
        ctx = await self._ready(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        removed = await interaction.client.db.unlink_telegram_account(
            discord_user_id=interaction.user.id)
        await interaction.response.send_message(
            _("tg.account_unlinked_discord" if removed else "tg.account_status_none"),
            ephemeral=True)


# ---------------------------------------------------------- quick replies ---

async def reply_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    return [
        app_commands.Choice(name=f"{r['name']} – {r['content']}".replace("\n", " ")[:100],
                            value=r["name"])
        for r in await interaction.client.db.list_replies(interaction.guild.id)
        if current in r["name"]
    ][:25]


@app_commands.command(name="reply", description="Send a quick reply in this ticket")
@app_commands.guild_only()
@app_commands.describe(name="Quick reply to send")
@app_commands.autocomplete(name=reply_autocomplete)
async def reply(interaction: discord.Interaction, name: str):
    ctx = await get_context(interaction, staff=True)
    if ctx is None:
        return
    cfg, _, ticket = ctx
    db = interaction.client.db
    saved = await db.get_reply(interaction.guild.id, name)
    if saved is None:
        await interaction.response.send_message(_("replies.unknown", name=name), ephemeral=True)
        return
    text = fill_reply(saved["content"], user=f"<@{ticket['owner_id']}>",
                      staff=interaction.user.mention, server=interaction.guild.name)
    await interaction.response.send_message(
        text + "\n-# " + _("replies.signature", staff=interaction.user.display_name),
        allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
    )
    # A quick reply is a staff answer: it counts for stats and the auto-close timer
    await db.update_ticket(ticket["id"], **activity_changes(ticket, time.time(), from_staff=True))


class ReplyModal(discord.ui.Modal):
    def __init__(self, name: str, _, content: str | None = None):
        super().__init__(title=_("replies.modal_title", name=name)[:45])
        self.name = name
        self._ = _
        self.content = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, max_length=config.MAX_REPLY_LENGTH,
            default=content,
        )
        self.add_item(discord.ui.Label(text=_("replies.modal_label"),
                                       description=_("replies.modal_hint"),
                                       component=self.content))

    async def on_submit(self, interaction: discord.Interaction):
        _ = self._
        db = interaction.client.db
        is_new = await db.get_reply(interaction.guild.id, self.name) is None
        if is_new and len(await db.list_replies(interaction.guild.id)) >= config.MAX_REPLIES:
            await interaction.response.send_message(
                _("replies.too_many", max=config.MAX_REPLIES), ephemeral=True)
            return
        await db.save_reply(interaction.guild.id, self.name, self.content.value)
        await audit(interaction, "reply.save", f"reply:{self.name}")
        preview = fill_reply(self.content.value, user="@User", staff="@Staff",
                             server=interaction.guild.name)
        await interaction.response.send_message(
            _("replies.saved", name=self.name, preview=preview)[:2000], ephemeral=True)


class RepliesGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="replies", description="Manage the quick replies of this server",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="list", description="Show the quick replies")
    async def list_replies(self, interaction: discord.Interaction):
        _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
        replies = await interaction.client.db.list_replies(interaction.guild.id)
        if not replies:
            await interaction.response.send_message(_("replies.none"), ephemeral=True)
            return
        lines = []
        for r in replies:
            preview = r["content"].replace("\n", " ")
            preview = preview[:80] + ("…" if len(preview) > 80 else "")
            lines.append(f"**`{r['name']}`** – {preview}")
        embed = discord.Embed(
            title=_("replies.title", count=len(replies), max=config.MAX_REPLIES),
            description="\n".join(lines)[:4096], color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a quick reply")
    @app_commands.describe(name="Name of the quick reply (e.g. logs)")
    async def add_reply(self, interaction: discord.Interaction,
                        name: app_commands.Range[str, 1, 32]):
        db = interaction.client.db
        _ = translator(await db.get_guild(interaction.guild.id))
        key = reply_name(name)
        if not key:
            await interaction.response.send_message(_("replies.bad_name"), ephemeral=True)
            return
        if await db.get_reply(interaction.guild.id, key):
            await interaction.response.send_message(_("replies.exists", name=key),
                                                    ephemeral=True)
            return
        if len(await db.list_replies(interaction.guild.id)) >= config.MAX_REPLIES:
            await interaction.response.send_message(
                _("replies.too_many", max=config.MAX_REPLIES), ephemeral=True)
            return
        await db.save_guild(interaction.guild.id)  # make sure the server row exists
        await interaction.response.send_modal(ReplyModal(key, _))

    @app_commands.command(name="edit", description="Edit a quick reply")
    @app_commands.describe(name="Quick reply to edit")
    @app_commands.autocomplete(name=reply_autocomplete)
    async def edit_reply(self, interaction: discord.Interaction, name: str):
        db = interaction.client.db
        _ = translator(await db.get_guild(interaction.guild.id))
        saved = await db.get_reply(interaction.guild.id, name)
        if saved is None:
            await interaction.response.send_message(_("replies.unknown", name=name),
                                                    ephemeral=True)
            return
        await interaction.response.send_modal(ReplyModal(saved["name"], _, saved["content"]))

    @app_commands.command(name="remove", description="Remove a quick reply")
    @app_commands.describe(name="Quick reply to remove")
    @app_commands.autocomplete(name=reply_autocomplete)
    async def remove_reply(self, interaction: discord.Interaction, name: str):
        db = interaction.client.db
        _ = translator(await db.get_guild(interaction.guild.id))
        if await db.remove_reply(interaction.guild.id, name):
            await audit(interaction, "reply.remove", f"reply:{name.lower()}")
            await interaction.response.send_message(_("replies.removed", name=name.lower()),
                                                    ephemeral=True)
        else:
            await interaction.response.send_message(_("replies.unknown", name=name),
                                                    ephemeral=True)


# -------------------------------------------------------------------- FAQ ---

async def faq_autocomplete(interaction: discord.Interaction, current: str):
    current = current.lower()
    return [
        app_commands.Choice(name=f"#{e['id']} {e['question']}"[:100], value=e["id"])
        for e in await interaction.client.db.list_faq(interaction.guild.id)
        if current in e["question"].lower() or current.lstrip("#") == str(e["id"])
    ][:25]


class FaqModal(discord.ui.Modal):
    """Question and answer of a FAQ entry (new when entry is None)."""

    def __init__(self, _, type_key: str | None = None, entry: dict | None = None):
        title = _("faq.modal_edit", id=entry["id"]) if entry else _("faq.modal_add")
        super().__init__(title=title[:45])
        self._, self.type_key, self.entry = _, type_key, entry
        self.question = discord.ui.TextInput(
            max_length=config.FAQ_QUESTION_LENGTH,
            default=entry["question"] if entry else None)
        self.answer = discord.ui.TextInput(
            style=discord.TextStyle.paragraph, max_length=config.FAQ_ANSWER_LENGTH,
            default=entry["answer"] if entry else None)
        self.add_item(discord.ui.Label(text=_("faq.q_label"), description=_("faq.q_hint"),
                                       component=self.question))
        self.add_item(discord.ui.Label(text=_("faq.a_label"), description=_("faq.a_hint"),
                                       component=self.answer))

    async def on_submit(self, interaction: discord.Interaction):
        _ = self._
        db = interaction.client.db
        guild_id = interaction.guild.id
        question, answer = self.question.value.strip(), self.answer.value.strip()
        if self.entry:
            if not await db.update_faq(guild_id, self.entry["id"], question, answer):
                await interaction.response.send_message(
                    _("faq.unknown", id=self.entry["id"]), ephemeral=True)
                return
            entry_id = self.entry["id"]
            await audit(interaction, "faq.edit", f"faq:{entry_id}")
            text = _("faq.saved", id=entry_id)
        else:
            if len(await db.list_faq(guild_id)) >= config.MAX_FAQ_ENTRIES:
                await interaction.response.send_message(
                    _("faq.too_many", max=config.MAX_FAQ_ENTRIES), ephemeral=True)
                return
            if self.type_key and await db.get_type(guild_id, self.type_key) is None:
                await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
                return
            entry_id = await db.add_faq(guild_id, self.type_key, question, answer)
            await audit(interaction, "faq.add", f"faq:{entry_id}", type=self.type_key)
            text = _("faq.added", id=entry_id)
        preview = discord.Embed(color=COLOR)
        preview.add_field(name=question, value=answer, inline=False)
        await interaction.response.send_message(text, embed=preview, ephemeral=True)


class FaqGroup(app_commands.Group):
    """/faq ...: answers shown before the ticket form, to solve requests without a ticket."""

    def __init__(self):
        super().__init__(name="faq", description="Questions and answers shown before the "
                                                 "ticket form",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    @app_commands.command(name="list", description="Show the FAQ")
    async def list_faq(self, interaction: discord.Interaction):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        db = interaction.client.db
        entries = await db.list_faq(interaction.guild.id)
        if not entries:
            await interaction.response.send_message(_("faq.none"), ephemeral=True)
            return
        types = {t["key"]: f"{t['emoji']} {t['label']}"
                 for t in await db.list_types(interaction.guild.id)}
        lines = [f"`#{e['id']}` **{e['question']}** · "
                 + (types.get(e["type_key"], e["type_key"]) if e["type_key"]
                    else _("faq.all_types"))
                 for e in entries]
        embed = discord.Embed(title=_("faq.list_title", count=len(entries),
                                      max=config.MAX_FAQ_ENTRIES),
                              description="\n".join(lines)[:4096], color=COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add", description="Add a question and its answer")
    @app_commands.describe(type="(Optional) Ticket type (default: all types)")
    @app_commands.autocomplete(type=type_autocomplete)
    async def add_faq(self, interaction: discord.Interaction, type: str | None = None):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        db = interaction.client.db
        if type is not None and await db.get_type(interaction.guild.id, type) is None:
            await interaction.response.send_message(_("error.type_gone"), ephemeral=True)
            return
        if len(await db.list_faq(interaction.guild.id)) >= config.MAX_FAQ_ENTRIES:
            await interaction.response.send_message(
                _("faq.too_many", max=config.MAX_FAQ_ENTRIES), ephemeral=True)
            return
        await interaction.response.send_modal(FaqModal(_, type_key=type))

    @app_commands.command(name="edit", description="Edit a FAQ entry")
    @app_commands.describe(entry="FAQ entry")
    @app_commands.autocomplete(entry=faq_autocomplete)
    async def edit_faq(self, interaction: discord.Interaction, entry: int):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        saved = await interaction.client.db.get_faq(interaction.guild.id, entry)
        if saved is None:
            await interaction.response.send_message(_("faq.unknown", id=entry), ephemeral=True)
            return
        await interaction.response.send_modal(FaqModal(_, entry=saved))

    @app_commands.command(name="remove", description="Remove a FAQ entry")
    @app_commands.describe(entry="FAQ entry")
    @app_commands.autocomplete(entry=faq_autocomplete)
    async def remove_faq(self, interaction: discord.Interaction, entry: int):
        ctx = await require_setup(interaction)
        if ctx is None:
            return
        _ = ctx[1]
        if not await interaction.client.db.remove_faq(interaction.guild.id, entry):
            await interaction.response.send_message(_("faq.unknown", id=entry), ephemeral=True)
            return
        await audit(interaction, "faq.remove", f"faq:{entry}")
        await interaction.response.send_message(_("faq.removed", id=entry), ephemeral=True)


# ---------------------------------------------------------------- profile ---

class ProfileGroup(app_commands.Group):
    """The bot's name, avatar, banner and bio in this server only."""

    def __init__(self):
        super().__init__(name="profile", description="Customize the bot's profile in this server",
                         guild_only=True,
                         default_permissions=discord.Permissions(administrator=True))

    async def _apply(self, interaction: discord.Interaction, done: str, **changes) -> None:
        _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await interaction.guild.me.edit(**changes,
                                            reason=f"Profile changed by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send(_("profile.forbidden"), ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(_("profile.failed", error=(e.text or str(e))[:300]),
                                            ephemeral=True)
        else:
            await audit(interaction, "profile.change", fields=sorted(changes))
            await interaction.followup.send(done, ephemeral=True)

    async def _image(self, interaction: discord.Interaction, image: discord.Attachment):
        _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
        if not valid_profile_image(image.content_type, image.size):
            await interaction.response.send_message(
                _("profile.bad_image", mb=PROFILE_IMAGE_MAX_MB), ephemeral=True)
            return None
        await interaction.response.defer(ephemeral=True, thinking=True)
        return await image.read()

    @app_commands.command(name="name", description="Change the bot's name in this server")
    @app_commands.describe(name="New name (up to 32 characters)")
    async def set_name(self, interaction: discord.Interaction,
                   name: app_commands.Range[str, 1, 32]):
        _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
        await self._apply(interaction, _("profile.name_set", name=name.strip()),
                          nick=name.strip())

    @app_commands.command(name="avatar", description="Change the bot's avatar in this server")
    @app_commands.describe(image="Image (PNG, JPG, GIF or WEBP, max 8 MB)")
    async def set_avatar(self, interaction: discord.Interaction, image: discord.Attachment):
        data = await self._image(interaction, image)
        if data is not None:
            _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
            await self._apply(interaction, _("profile.avatar_set"), avatar=data)

    @app_commands.command(name="banner", description="Change the bot's banner in this server")
    @app_commands.describe(image="Image (PNG, JPG, GIF or WEBP, max 8 MB)")
    async def set_banner(self, interaction: discord.Interaction, image: discord.Attachment):
        data = await self._image(interaction, image)
        if data is not None:
            _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
            await self._apply(interaction, _("profile.banner_set"), banner=data)

    @app_commands.command(name="bio", description="Change the bot's bio in this server")
    @app_commands.describe(text="New bio (up to 190 characters)")
    async def set_bio(self, interaction: discord.Interaction,
                  text: app_commands.Range[str, 1, 190]):
        _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
        await self._apply(interaction, _("profile.bio_set"), bio=text.strip())

    @app_commands.command(name="reset",
                          description="Restore the bot's original profile in this server")
    async def reset_profile(self, interaction: discord.Interaction):
        _ = translator(await interaction.client.db.get_guild(interaction.guild.id))
        await self._apply(interaction, _("profile.reset"),
                          nick=None, avatar=None, banner=None, bio=None)


def all_commands() -> list:
    return [setup, guidelines, audit_log, queue, mytickets, available, add, remove, close, reopen,
            priority, transfer, escalate_command, stats, export_stats, reply, NoteGroup(),
            SettingsGroup(), TypesGroup(), TelegramGroup(), TelegramAccountGroup(),
            ProfileGroup(), RepliesGroup(), BlockGroup(), EscalationGroup(), FaqGroup()]
