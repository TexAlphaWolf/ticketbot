"""One-time import of the v1 config.json into the database."""

import json
import time
from pathlib import Path

from ..core import config
from ..core.i18n import DEFAULT_TYPES
from .store import Store


async def migrate_legacy_config(db: Store, path: Path) -> int:
    """Import v1 settings, open tickets and transcript references. Returns the server count."""
    path = Path(path)
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = {key: (label, emoji) for key, label, emoji, _ in DEFAULT_TYPES["en"]}
    now = time.time()
    count = 0

    for guild_key, cfg in data.items():
        guild_id = int(guild_key)
        if await db.get_guild(guild_id) is not None:
            continue  # already in the database
        guidelines = cfg.get("guidelines_message") or {}
        telegram = cfg.get("telegram") or {}
        await db.save_guild(
            guild_id,
            language="en",
            staff_role=cfg.get("staff_role"),
            category=cfg.get("category"),
            log_channel=cfg.get("log_channel"),
            archive_channel=cfg.get("archive_channel"),
            counter=cfg.get("counter", 0),
            retention_days=cfg.get("retention_days", config.DEFAULT_RETENTION_DAYS),
            guidelines_channel=guidelines.get("channel"),
            guidelines_message=guidelines.get("message"),
            telegram_chat_id=telegram.get("chat_id") if telegram.get("verified") else None,
        )
        await db.ensure_default_types(guild_id, DEFAULT_TYPES["en"])

        for channel_id, t in (cfg.get("tickets") or {}).items():
            key = t.get("type") if t.get("type") in defaults else "other"
            label, emoji = defaults[key]
            claimed = t.get("claimed_by")
            status = (config.STATUS_IN_PROGRESS
                      if claimed or t.get("status") == "in_progress" else config.STATUS_WAITING)
            await db.create_ticket(
                guild_id=guild_id, channel_id=int(channel_id), owner_id=t["owner"],
                type_key=key, type_label=label, type_emoji=emoji,
                subject=t.get("subject") or None, status=status,
                priority=t.get("priority"), claimed_by=claimed,
                control_message=t.get("control_message"),
                opened_at=t.get("opened_at", now),
                last_actor=t.get("last_actor"),
                last_activity=t.get("last_activity", now),
                warned=bool(t.get("warned")),
            )

        for ref in cfg.get("transcripts") or []:
            await db.add_transcript_ref(guild_id, ref["channel"], ref["message"],
                                  ref.get("priority"), ref.get("closed_at", now))
        count += 1

    path.rename(path.with_name(path.name + ".migrated"))
    return count
