"""Reads the messages of a ticket channel for the transcripts."""

import discord

from ..core.transcripts import REACTION_USERS_LIMIT, TMessage, emoji_url


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
                    "url": emoji_url(emoji.id, emoji.animated)}
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
