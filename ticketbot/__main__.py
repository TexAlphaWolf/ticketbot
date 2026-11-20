"""
Start the bot, or manage the database backups:

    python -m ticketbot                    start the bot
    python -m ticketbot bot                start the bot (same as above)
    python -m ticketbot backup             make a backup now
    python -m ticketbot backups            list the backups
    python -m ticketbot restore <file>     restore a backup (stop the bot first)
    python -m ticketbot settings           check the .env file (secrets hidden)
"""

import argparse
import sys

from .core.settings import SettingsError, get_settings
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
    sub.add_parser("settings", help="check the .env file and show the settings in use")
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except SettingsError as e:
        print(e)
        return 2

    if args.command in (None, "bot"):
        from .bot.client import main as run_bot
        try:
            run_bot(settings)
        except SettingsError as e:
            print(e)
            return 2
        return 0

    if args.command == "settings":
        width = max(len(name) for name, _ in settings.summary())
        for name, value in settings.summary():
            print(f"{name.ljust(width)}  {value}")
        return 0

    if args.command == "backup":
        from .db import Database
        if not settings.db_path.exists():
            print(f"No database found at {settings.db_path}")
            return 1
        db = Database(settings.db_path)
        path = create_backup(db.conn, settings.backups_path)
        db.close()
        removed = prune_backups(settings.backups_path, max(settings.backup_keep, 1))
        print(f"Backup saved: {path}" + (f" ({len(removed)} old removed)" if removed else ""))
        return 0

    if args.command == "backups":
        backups = list_backups(settings.backups_path)
        if not backups:
            print(f"No backups in {settings.backups_path}")
        for path in reversed(backups):
            print(f"{path}  ({path.stat().st_size / 1024:.1f} KB)")
        return 0

    if not args.yes:
        answer = input(f"Replace {settings.db_path} with {args.file}? "
                       "The bot must be stopped. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Restore cancelled.")
            return 1
    try:
        safety = restore_backup(args.file, settings.db_path)
    except (OSError, RuntimeError) as e:
        print(f"Restore failed, the database was not changed: {e}")
        return 1
    print(f"Restored {args.file}")
    if safety:
        print(f"The previous database was saved as {safety}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
