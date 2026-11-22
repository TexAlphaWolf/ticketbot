"""The weekly report on Discord (log channel, or the one chosen with /settings report)
and on Telegram. The numbers come from core/report.py."""

import time

import discord

from ..core.logic import format_duration
from ..core.report import WEEK, change, report_due, weekly_report
from .common import COLOR, esc, telegram_notify, translator


async def build_report(client, guild_id: int, end: float) -> dict:
    tickets = await client.db.report_tickets(guild_id, end - 2 * WEEK)
    report = weekly_report(tickets, end, await client.db.open_ticket_count(guild_id))
    report["faq"] = await client.db.faq_results_since(guild_id, end - WEEK)
    return report


def is_empty(report: dict) -> bool:
    """Nothing happened in two weeks and nothing is open: no report to send."""
    week, previous = report["week"], report["previous"]
    return not (report["open_now"] or week["opened"] or week["closed"]
                or previous["opened"] or previous["closed"])


def _count_change(current: int, previous: int) -> str:
    diff = current - previous
    return "=" if diff == 0 else f"{diff:+d}".replace("-", "−")


def _time_change(current: float | None, previous: float | None) -> str:
    diff = change(current, previous)
    if diff is None:
        return ""
    if abs(diff) < 60:
        return " (=)"
    sign = "+" if diff > 0 else "−"
    return f" ({sign}{format_duration(abs(diff))})"


def _rating(week: dict) -> str:
    return f"{week['avg_rating']:.1f} ⭐ ({week['ratings']})" if week["ratings"] else "-"


def _lines(report: dict, _, name) -> dict[str, str]:
    """The report's texts, shared by Discord and Telegram. `name(staff_id)` writes a
    staff member: a mention on Discord, the name on Telegram."""
    week, previous = report["week"], report["previous"]
    staff = [_("report.staff_line", rank=i, user=name(s["staff_id"]), closed=s["closed"],
               rating=f"{s['avg_rating']:.1f}⭐" if s["avg_rating"] else "-")
             for i, s in enumerate(week["top_staff"], 1)]
    types = [f"{label}: {n}" for label, n in week["top_types"]]
    faq = report.get("faq") or {}
    return {
        "tickets": _("report.tickets_value",
                     opened=week["opened"], opened_change=_count_change(week["opened"],
                                                                       previous["opened"]),
                     closed=week["closed"], closed_change=_count_change(week["closed"],
                                                                       previous["closed"]),
                     open=report["open_now"]),
        "first_response": format_duration(week["avg_first_response"]) + _time_change(
            week["avg_first_response"], previous["avg_first_response"]),
        "resolution": format_duration(week["avg_resolution"]) + _time_change(
            week["avg_resolution"], previous["avg_resolution"]),
        "rating": _rating(week),
        "escalated": str(week["escalated"]),
        "staff": "\n".join(staff),
        "types": "\n".join(types),
        "faq": _("stats.faq_value", **faq) if faq.get("solved") or faq.get("opened") else "",
    }


def report_embed(report: dict, guild: discord.Guild, _) -> discord.Embed:
    text = _lines(report, _, lambda uid: f"<@{uid}>")
    embed = discord.Embed(
        title="📊 " + _("report.title", guild=guild.name), color=COLOR,
        description=_("report.period", start=f"<t:{int(report['start'])}:D>",
                      end=f"<t:{int(report['end']) - 1}:D>"))
    embed.add_field(name=_("stats.tickets"), value=text["tickets"], inline=False)
    embed.add_field(name=_("stats.first_response"), value=text["first_response"])
    embed.add_field(name=_("stats.resolution"), value=text["resolution"])
    embed.add_field(name=_("stats.rating"), value=text["rating"])
    if report["week"]["escalated"]:
        embed.add_field(name=_("report.escalated"), value=text["escalated"])
    if text["staff"]:
        embed.add_field(name=_("report.top_staff"), value=text["staff"][:1024], inline=False)
    if text["types"]:
        embed.add_field(name=_("report.top_types"), value=text["types"][:1024], inline=False)
    if text["faq"]:
        embed.add_field(name=_("stats.faq"), value=text["faq"], inline=False)
    embed.set_footer(text=_("report.footer"))
    return embed


def _member_name(guild: discord.Guild, client, uid: int) -> str:
    member = guild.get_member(uid) or client.get_user(uid)
    return member.display_name if member else str(uid)


def report_telegram(report: dict, guild: discord.Guild, client, _) -> str:
    """The same report as Telegram HTML (names instead of mentions, no Markdown)."""
    text = _lines(report, _, lambda uid: esc(_member_name(guild, client, uid)))

    def plain(value: str) -> str:                     # **bold** → <b>bold</b>
        parts = value.split("**")
        return "".join(f"<b>{p}</b>" if i % 2 else p for i, p in enumerate(parts))

    days = time.strftime("%d/%m", time.gmtime(report["start"])) + " – " + \
        time.strftime("%d/%m", time.gmtime(report["end"] - 1))
    lines = [f"📊 <b>{esc(_('report.title', guild=guild.name))}</b> · {days}", "",
             plain(text["tickets"]),
             f"{_('stats.first_response')}: {text['first_response']}",
             f"{_('stats.resolution')}: {text['resolution']}",
             f"{_('stats.rating')}: {text['rating']}"]
    if report["week"]["escalated"]:
        lines.append(f"{_('report.escalated')}: {text['escalated']}")
    for key, title in (("staff", "report.top_staff"), ("types", "report.top_types")):
        if text[key]:
            lines += ["", f"<b>{_(title)}</b>", esc(text[key]) if key == "types"
                      else text[key]]
    if text["faq"]:
        lines += ["", plain(text["faq"])]
    return "\n".join(lines)


async def send_weekly_reports(client, now: float | None = None) -> int:
    """Send the reports that are due (checked every few minutes). Each server gets one
    per week, also after a restart; an empty one (no tickets at all) is skipped."""
    now = now or time.time()
    settings = client.settings
    sent = 0
    for guild_id in await client.db.guild_ids():
        cfg = await client.db.get_guild(guild_id)
        due = report_due(cfg or {}, now, settings.report_timezone, settings.report_day,
                         settings.report_hour)
        guild = client.get_guild(guild_id)
        if due is None or guild is None:
            continue
        await client.db.save_guild(guild_id, last_report_at=now)   # once, even if it fails
        report = await build_report(client, guild_id, due)
        if is_empty(report):
            continue
        _ = translator(cfg)
        channel = guild.get_channel(cfg.get("report_channel") or cfg.get("log_channel") or 0)
        if channel is not None:
            try:
                await channel.send(embed=report_embed(report, guild, _),
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as e:
                print(f"[report] could not send the weekly report of {guild.name}: {e}")
        await telegram_notify(client, cfg, report_telegram(report, guild, client, _))
        sent += 1
    return sent
