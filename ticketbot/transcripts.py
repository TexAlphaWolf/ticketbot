"""Ticket transcripts: collected from Discord, rendered as plain text and HTML."""

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord


@dataclass
class TMessage:
    author: str
    author_id: int
    avatar: str
    color: str | None
    bot: bool
    created_at: datetime
    content: str
    embeds: list[dict] = field(default_factory=list)       # {title, description, fields, color}
    attachments: list[dict] = field(default_factory=list)  # {filename, url, image}
    stickers: list[dict] = field(default_factory=list)     # {name, id, url, image}
    reactions: list[dict] = field(default_factory=list)    # {emoji, id, url, count, users}


REACTION_USERS_LIMIT = 25  # names shown for each reaction
CUSTOM_EMOJI = re.compile(r"<(a?):(\w{2,32}):(\d{15,25})>")


def _emoji_url(emoji_id: int | str, animated: bool) -> str:
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if animated else 'png'}"


async def _reactions(msg: discord.Message) -> list[dict]:
    reactions = []
    for reaction in msg.reactions:
        users = []
        try:
            async for user in reaction.users(limit=REACTION_USERS_LIMIT):
                users.append(user.display_name)
        except discord.HTTPException:
            pass
        emoji = reaction.emoji
        if isinstance(emoji, (discord.Emoji, discord.PartialEmoji)) and emoji.id:
            item = {"emoji": f":{emoji.name}:", "id": emoji.id,
                    "url": _emoji_url(emoji.id, emoji.animated)}
        else:
            item = {"emoji": str(emoji), "id": None, "url": None}
        item.update(count=reaction.count, users=users)
        reactions.append(item)
    return reactions


async def collect_messages(channel: discord.TextChannel) -> list[TMessage]:
    messages = []
    async for msg in channel.history(limit=None, oldest_first=True):
        author = msg.author
        color = None
        if isinstance(author, discord.Member) and author.color.value:
            color = str(author.color)
        messages.append(TMessage(
            author=author.display_name,
            author_id=author.id,
            avatar=str(author.display_avatar.url),
            color=color,
            bot=author.bot,
            created_at=msg.created_at,
            content=msg.clean_content,
            embeds=[{
                "title": e.title or "",
                "description": e.description or "",
                "fields": [(f.name, f.value) for f in e.fields],
                "color": str(e.color) if e.color else None,
            } for e in msg.embeds],
            attachments=[{
                "filename": a.filename,
                "url": a.url,
                "image": (a.content_type or "").startswith("image/"),
            } for a in msg.attachments],
            stickers=[{
                "name": st.name,
                "id": st.id,
                "url": str(st.url),
                "image": st.format != discord.StickerFormatType.lottie,
            } for st in msg.stickers],
            reactions=await _reactions(msg),
        ))
    return messages


def _ts(value: datetime | float | None) -> str:
    if value is None:
        return "-"
    if not isinstance(value, datetime):
        value = datetime.fromtimestamp(value, timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ------------------------------------------------------------- plain text ---

def render_txt(meta: dict, messages: list[TMessage], notes: list[dict],
               _: Callable[..., str]) -> bytes:
    lines = [_("transcript.title", channel=meta["channel"]), ""]
    for label, value in meta["fields"]:
        lines.append(f"{label}: {value}")
    lines += ["=" * 50, ""]
    for m in messages:
        text = m.content
        for e in m.embeds:
            parts = [e["title"], e["description"]] + [f"{n}: {v}" for n, v in e["fields"]]
            text += f" [embed: {' | '.join(p for p in parts if p)}]"
        text = CUSTOM_EMOJI.sub(lambda e: f":{e.group(2)}: ({e.group(3)})", text)
        for a in m.attachments:
            text += f" [{a['filename']}: {a['url']}]"
        for st in m.stickers:
            text += f" [{_('transcript.sticker')}: {st['name']} (ID {st['id']})]"
        lines.append(f"[{_ts(m.created_at)}] {m.author}: {text}")
        if m.reactions:
            lines.append(f"    {_('transcript.reactions')}: " + " · ".join(_txt_reaction(r)
                                                                      for r in m.reactions))
    if notes:
        lines += ["", "=" * 50, _("transcript.notes"), ""]
        for n in notes:
            lines.append(f"[{_ts(n['created_at'])}] {n['author']}: {n['text']}")
    return "\n".join(lines).encode("utf-8")


def _txt_reaction(r: dict) -> str:
    emoji = f"{r['emoji']} ({r['id']})" if r["id"] else r["emoji"]
    who = f" ({', '.join(r['users'])})" if r["users"] else ""
    return f"{emoji} {r['count']}{who}"


# ------------------------------------------------------------------- HTML ---

def markdown_to_html(text: str) -> str:
    """Escape the text, then apply a safe subset of Discord markdown."""
    text = html.escape(text)
    keep: list[str] = []

    def protect(fragment: str) -> str:
        keep.append(fragment)
        return f"\x00{len(keep) - 1}\x00"

    text = re.sub(r"```(?:[\w+-]*\n)?(.*?)```",
                  lambda m: protect(f"<pre>{m.group(1).strip(chr(10))}</pre>"), text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`", lambda m: protect(f"<code>{m.group(1)}</code>"), text)
    text = re.sub(r"&lt;(a?):(\w{2,32}):(\d{15,25})&gt;",
                  lambda m: protect(
                      f"<img class='emoji' src='{_emoji_url(m.group(3), bool(m.group(1)))}' "
                      f"alt=':{m.group(2)}:' title=':{m.group(2)}: ({m.group(3)})' "
                      "onerror=\"this.replaceWith(this.alt)\">"), text)
    text = re.sub(r"https?://[^\s<>\"']+",
                  lambda m: protect(f'<a href="{m.group(0)}" target="_blank" '
                                    f'rel="noopener noreferrer">{m.group(0)}</a>'), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"<u>\1</u>", text, flags=re.S)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text, flags=re.S)
    text = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", text, flags=re.S)
    text = text.replace("\n", "<br>")
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)


CSS = """
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#313338;color:#dbdee1;
font:15px/1.4 "gg sans","Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:24px 16px}
.head{background:#2b2d31;border-radius:8px;padding:20px;margin-bottom:24px}
.head h1{margin:0 0 4px;font-size:22px;color:#f2f3f5}
.head .sub{color:#949ba4;margin-bottom:12px}
.head table{border-collapse:collapse;width:100%}
.head td{padding:4px 8px;vertical-align:top;border-top:1px solid #3f4147}
.head td:first-child{color:#949ba4;white-space:nowrap;width:1%}
.msg{display:flex;gap:16px;padding:2px 0}
.msg.first{margin-top:16px}
.av{width:40px;height:40px;border-radius:50%;flex:none;background:#1e1f22}
.gap{width:40px;flex:none}
.body{min-width:0;flex:1}
.name{font-weight:600;color:#f2f3f5}
.bot{background:#5865f2;color:#fff;font-size:10px;font-weight:700;padding:1px 4px;border-radius:3px;
margin-left:4px;vertical-align:middle}
.time{color:#949ba4;font-size:12px;margin-left:6px}
.text{word-wrap:break-word;overflow-wrap:anywhere}
.text a{color:#00a8fc}
code{background:#1e1f22;padding:1px 4px;border-radius:4px;font-size:13px}
pre{background:#1e1f22;padding:8px;border-radius:4px;white-space:pre-wrap;margin:4px 0}
.embed{background:#2b2d31;border-left:4px solid #5865f2;border-radius:4px;padding:8px 12px;
margin:4px 0;max-width:520px}
.embed .et{font-weight:600;color:#f2f3f5;margin-bottom:4px}
.embed .ef{margin-top:6px}
.embed .ef b{display:block;color:#f2f3f5}
.att img{max-width:400px;max-height:300px;border-radius:4px;margin-top:4px;display:block}
.att a{color:#00a8fc}
.emoji{width:22px;height:22px;vertical-align:-5px;object-fit:contain}
.sticker{margin-top:4px}
.sticker img{width:160px;height:160px;object-fit:contain;display:block}
.sticker span{color:#949ba4;font-size:12px}
.reactions{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.reaction{background:#2b2d31;border:1px solid #3f4147;border-radius:8px;padding:2px 8px;
font-size:14px}
.reaction .emoji{width:18px;height:18px;vertical-align:-3px}
.reaction b{color:#f2f3f5;margin-left:4px}
.reaction small{color:#949ba4;margin-left:6px}
.notes{background:#2b2d31;border-left:4px solid #f0b232;border-radius:8px;padding:16px 20px;
margin-top:32px}
.notes h2{margin:0 0 8px;font-size:16px;color:#f0b232}
.note{padding:6px 0;border-top:1px solid #3f4147}
.foot{color:#949ba4;font-size:12px;text-align:center;margin-top:32px}
"""


def render_html(meta: dict, messages: list[TMessage], notes: list[dict],
                _: Callable[..., str]) -> bytes:
    esc = html.escape
    rows = "".join(f"<tr><td>{esc(str(k))}</td><td>{esc(str(v))}</td></tr>"
                   for k, v in meta["fields"])
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{esc(_('transcript.title', channel=meta['channel']))}</title>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        "<div class='head'>",
        f"<h1>#{esc(meta['channel'])}</h1>",
        f"<div class='sub'>{esc(meta['guild'])}</div>",
        f"<table>{rows}</table></div>",
    ]

    previous = None
    for m in messages:
        grouped = (previous is not None and previous.author_id == m.author_id
                   and (m.created_at - previous.created_at).total_seconds() < 420)
        if grouped:
            left = "<div class='gap'></div>"
            header = ""
        else:
            left = (f"<img class='av' src='{esc(m.avatar, quote=True)}' alt='' "
                    "onerror=\"this.style.visibility='hidden'\">")
            style = f" style='color:{esc(m.color, quote=True)}'" if m.color else ""
            badge = "<span class='bot'>BOT</span>" if m.bot else ""
            header = (f"<div><span class='name'{style}>{esc(m.author)}</span>{badge}"
                      f"<span class='time'>{esc(_ts(m.created_at))}</span></div>")
        body = [header]
        if m.content:
            body.append(f"<div class='text'>{markdown_to_html(m.content)}</div>")
        for e in m.embeds:
            border = f" style='border-color:{esc(e['color'], quote=True)}'" if e["color"] else ""
            inner = ""
            if e["title"]:
                inner += f"<div class='et'>{markdown_to_html(e['title'])}</div>"
            if e["description"]:
                inner += f"<div class='text'>{markdown_to_html(e['description'])}</div>"
            for name, value in e["fields"]:
                inner += (f"<div class='ef'><b>{markdown_to_html(name)}</b>"
                          f"{markdown_to_html(value)}</div>")
            body.append(f"<div class='embed'{border}>{inner}</div>")
        for a in m.attachments:
            url = esc(a["url"], quote=True)
            if a["image"]:
                body.append(f"<div class='att'><a href='{url}' target='_blank' rel='noopener'>"
                            f"<img src='{url}' alt='{esc(a['filename'], quote=True)}' "
                            "onerror=\"this.replaceWith(this.alt)\"></a></div>")
            else:
                body.append(f"<div class='att'>📎 <a href='{url}' target='_blank' "
                            f"rel='noopener'>{esc(a['filename'])}</a></div>")
        for st in m.stickers:
            caption = f"{esc(st['name'])} · ID {st['id']}"
            if st["image"]:
                body.append(f"<div class='sticker'><img src='{esc(st['url'], quote=True)}' "
                            f"alt='{esc(st['name'], quote=True)}' "
                            "onerror=\"this.remove()\">"
                            f"<span>🏷️ {caption}</span></div>")
            else:
                body.append(f"<div class='sticker'><span>🏷️ {esc(_('transcript.sticker'))}: "
                            f"{caption}</span></div>")
        if m.reactions:
            chips = []
            for r in m.reactions:
                if r["url"]:
                    icon = (f"<img class='emoji' src='{esc(r['url'], quote=True)}' "
                            f"alt='{esc(r['emoji'], quote=True)}' "
                            "onerror=\"this.replaceWith(this.alt)\">")
                else:
                    icon = esc(r["emoji"])
                title = f"{r['emoji']} ({r['id']})" if r["id"] else r["emoji"]
                who = f"<small>{esc(', '.join(r['users']))}</small>" if r["users"] else ""
                chips.append(f"<span class='reaction' title='{esc(title, quote=True)}'>"
                             f"{icon}<b>{r['count']}</b>{who}</span>")
            body.append(f"<div class='reactions'>{''.join(chips)}</div>")
        cls = "msg" if grouped else "msg first"
        parts.append(f"<div class='{cls}'>{left}<div class='body'>{''.join(body)}</div></div>")
        previous = m

    if notes:
        parts.append(f"<div class='notes'><h2>🔒 {esc(_('transcript.notes'))}</h2>")
        for n in notes:
            parts.append(f"<div class='note'><span class='name'>{esc(n['author'])}</span>"
                         f"<span class='time'>{esc(_ts(n['created_at']))}</span>"
                         f"<div class='text'>{markdown_to_html(n['text'])}</div></div>")
        parts.append("</div>")

    parts.append(f"<div class='foot'>{esc(_('transcript.footer', count=len(messages)))}"
                 "</div></div></body></html>")
    return "".join(parts).encode("utf-8")
