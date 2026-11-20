"""
Start the bot, or manage the database backups:

    python -m ticketbot                    start the bot
    python -m ticketbot bot                start the bot (same as above)
    python -m ticketbot backup             make a backup now
    python -m ticketbot backups            list the backups
    python -m ticketbot restore <file>     restore a backup (stop the bot first)
"""

import argparse
import sys

from .core import config
from .db.backup import create_backup, list_backups, prune_backups, restore_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ticketbot", description="TicketBot")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("bot", help="start the Discord bot (default)")
    sub.add_parser("backup", help="make a database backup now")
    sub.add_parser("backups", help="list the database backups")
    restore = sub.add_parser("restore", help="restore a backup (stop the bot first)")
    restore.add_argument("file", help="backup file, e.g. data/backups/ticketbot-...db.gz")
    restore.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args(argv)

    if args.command in (None, "bot"):
        from .bot.client import main as run_bot
        run_bot()
        return 0

    if args.command == "backup":
        from .db import Database
        if not config.DB_PATH.exists():
            print(f"No database found at {config.DB_PATH}")
            return 1
        db = Database(config.DB_PATH)
        path = create_backup(db.conn, config.BACKUP_DIR)
        db.close()
        removed = prune_backups(config.BACKUP_DIR, max(config.BACKUP_KEEP, 1))
        print(f"Backup saved: {path}" + (f" ({len(removed)} old removed)" if removed else ""))
        return 0

    if args.command == "backups":
        backups = list_backups(config.BACKUP_DIR)
        if not backups:
            print(f"No backups in {config.BACKUP_DIR}")
        for path in reversed(backups):
            print(f"{path}  ({path.stat().st_size / 1024:.1f} KB)")
        return 0

    if not args.yes:
        answer = input(f"Replace {config.DB_PATH} with {args.file}? "
                       "The bot must be stopped. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Restore cancelled.")
            return 1
    try:
        safety = restore_backup(args.file, config.DB_PATH)
    except (OSError, RuntimeError) as e:
        print(f"Restore failed, the database was not changed: {e}")
        return 1
    print(f"Restored {args.file}")
    if safety:
        print(f"The previous database was saved as {safety}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
