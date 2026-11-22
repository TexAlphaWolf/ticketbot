"""
Start the bot or the web dashboard, or manage the database:

    python -m ticketbot                    start the bot
    python -m ticketbot bot                start the bot (same as above)
    python -m ticketbot web                start the web dashboard and API
    python -m ticketbot backup             make a backup now
    python -m ticketbot backups            list the backups
    python -m ticketbot restore <file>     restore a backup (stop the bot first)
    python -m ticketbot settings           check the .env file (secrets hidden)
    python -m ticketbot db status          database in use and schema version
    python -m ticketbot db copy <url>      copy all the data to another (empty) database
    python -m ticketbot db encrypt         encrypt with the current key (after a key change)
    python -m ticketbot keygen             make a new ENCRYPTION_KEY
    python -m ticketbot keygen --metrics   make a METRICS_TOKEN (Prometheus)
    python -m ticketbot held [id]          hidden transcripts of deleted tickets
"""

import argparse
import asyncio
import sqlite3
import sys

from .core.settings import SettingsError, get_settings
from .db.backup import create_backup, list_backups, prune_backups, restore_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ticketbot", description="TicketBot")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("bot", help="start the Discord bot (default)")
    web = sub.add_parser("web", help="start the web dashboard and API")
    web.add_argument("--wait", type=float, default=0, metavar="SECONDS",
                     help="if the database isn't ready yet (e.g. the bot is updating it), "
                          "try again for up to this long (used by Docker)")
    sub.add_parser("backup", help="make a database backup now")
    sub.add_parser("backups", help="list the database backups")
    restore = sub.add_parser("restore", help="restore a backup (stop the bot first)")
    restore.add_argument("file", help="backup file, e.g. data/backups/ticketbot-...db.gz")
    restore.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    sub.add_parser("settings", help="check the .env file and show the settings in use")
    db_cmd = sub.add_parser("db", help="database tools")
    db_sub = db_cmd.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("status", help="show the database in use and its schema version")
    copy = db_sub.add_parser("copy", help="copy all the data to another, empty database "
                                          "(e.g. from SQLite to PostgreSQL)")
    copy.add_argument("target", help="e.g. postgresql://user:password@host:5432/ticketbot")
    copy.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    db_sub.add_parser("encrypt", help="encrypt everything with the current ENCRYPTION_KEY "
                                      "(after changing it; the bot also does it at start)")
    keygen = sub.add_parser("keygen", help="make a new random ENCRYPTION_KEY for the "
                                           ".env file (--metrics: a METRICS_TOKEN)")
    keygen.add_argument("--metrics", action="store_true",
                        help="a token for the Prometheus metrics instead")
    held = sub.add_parser("held", help="transcripts of deleted tickets kept for "
                                       "LEGAL_HOLD_DAYS: list them, or save one as HTML")
    held.add_argument("id", nargs="?", type=int, help="number of the transcript to save")
    held.add_argument("--out", help="file to write (default: held-<id>.html)")
    args = parser.parse_args(argv)

    if args.command == "keygen" and args.metrics:
        import secrets
        print(f"METRICS_TOKEN={secrets.token_urlsafe(32)}")
        print("Add this line to .env; Prometheus sends it as a bearer token.")
        return 0
    if args.command == "keygen":
        from .core.crypto import generate_key
        print(f"ENCRYPTION_KEY={generate_key()}")
        print("Add this line to .env and keep a copy somewhere safe (e.g. a password "
              "manager): without it the encrypted data can't be read.")
        return 0

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

    if args.command == "web":
        from .web.app import run as run_web
        try:
            run_web(settings, wait=args.wait)
        except SettingsError as e:
            print(e)
            return 2
        except KeyboardInterrupt:
            pass
        return 0

    if args.command == "held":
        try:
            return asyncio.run(held_command(args, settings))
        except SettingsError as e:
            print(e)
            return 2

    if args.command == "settings":
        width = max(len(name) for name, _ in settings.summary())
        for name, value in settings.summary():
            print(f"{name.ljust(width)}  {value}")
        return 0

    if args.command == "db":
        if args.db_command in ("copy", "encrypt"):
            from .core import crypto
            try:
                crypto.configure(settings.keyring())
            except SettingsError as e:
                print(e)
                return 2
        if args.db_command == "copy" and not confirm_copy(args, settings):
            return 1 if args.target_ok else 2
        try:
            return asyncio.run(database_command(args, settings))
        except KeyboardInterrupt:
            print("Cancelled.")
            return 1

    database = settings.sqlite_path
    if args.command in ("backup", "restore") and database is None:
        print("The database is PostgreSQL: back it up with pg_dump and restore it with "
              "pg_restore (see the PostgreSQL documentation).")
        return 1

    if args.command == "backup":
        if not database.exists():
            print(f"No database found at {database}")
            return 1
        source = sqlite3.connect(database)
        try:
            path = create_backup(source, settings.backups_path)
        finally:
            source.close()
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
        answer = input(f"Replace {database} with {args.file}? "
                       "The bot must be stopped. Type 'yes' to continue: ")
        if answer.strip().lower() != "yes":
            print("Restore cancelled.")
            return 1
    try:
        safety = restore_backup(args.file, database)
    except (OSError, RuntimeError) as e:
        print(f"Restore failed, the database was not changed: {e}")
        return 1
    print(f"Restored {args.file}")
    if safety:
        print(f"The previous database was saved as {safety}")
    return 0


def confirm_copy(args, settings) -> bool:
    """Show what will be copied where and ask, before any database is opened."""
    from .db.engine import safe_url

    args.target_ok = False
    try:
        target = safe_url(args.target)
    except Exception as e:  # noqa: BLE001 - a wrong URL, shown to the user
        print(str(e).splitlines()[0])
        return False
    args.target_ok = True
    print(f"From: {safe_url(settings.db_url)}\nTo:   {target}")
    if args.yes:
        return True
    answer = input("Stop the bot first. Type 'yes' to copy all the data: ")
    if answer.strip().lower() == "yes":
        return True
    print("Copy cancelled.")
    return False


async def held_command(args, settings) -> int:
    """Hidden copies of deleted tickets' transcripts: only here, never in the dashboard.
    Every copy saved to a file is recorded in the audit log."""
    from datetime import UTC, datetime
    from pathlib import Path

    from .core.i18n import t
    from .core.transcripts import load_transcript, render_html
    from .web.database import open_web_store

    store = await open_web_store(settings)
    try:
        if args.id is None:
            rows = await store.held_transcripts()
            if not rows:
                print("No hidden transcripts.")
            for r in rows:
                until = datetime.fromtimestamp(r["held_until"], UTC).strftime("%Y-%m-%d")
                made = datetime.fromtimestamp(r["created_at"], UTC).strftime("%Y-%m-%d")
                print(f"{r['id']:>6}  server {r['guild_id']}  #{r['channel_name']}  "
                      f"closed {made}  kept until {until}")
            return 0
        found = await store.get_transcript(args.id)
        if found is None or found["held_until"] is None:
            print(f"No hidden transcript number {args.id}.")
            return 1
        meta, messages, notes = load_transcript(found["content"])
        page = render_html(meta, messages, notes, lambda key, /, **kw: t("en", key, **kw))
        out = Path(args.out or f"held-{args.id}.html")
        out.write_bytes(page)
        await store.audit(found["guild_id"], None, "transcript.held_export", source="cli",
                          target=f"transcript:{args.id}")
        print(f"Saved to {out} (recorded in the audit log). It holds personal data: "
              "delete the file when you don't need it anymore.")
        return 0
    finally:
        await store.close()


async def database_command(args, settings) -> int:
    from .db import migrate
    from .db.engine import create_engine, safe_url
    from .db.transfer import TransferError, copy_database

    source = create_engine(settings.db_url)
    try:
        if args.db_command == "status":
            revision = await migrate.current_revision(source)
            head = migrate.head_revision()
            print(f"database  {safe_url(source.url)}")
            print(f"schema    {revision or 'none'}"
                  + ("  (latest)" if revision == head else f"  (latest is {head})"))
            return 0

        if args.db_command == "encrypt":
            from .core.crypto import CryptoError
            from .db.encryption import encrypt_pending
            if await migrate.current_revision(source) != migrate.head_revision():
                print("Start the bot once first, so that the database has the latest schema.")
                return 1
            try:
                changed = await encrypt_pending(source)
            except CryptoError as e:
                print(f"Encryption failed, nothing was changed: {e}")
                return 1
            print(f"Encrypted {changed} row(s) with key {settings.keyring().current_id}."
                  if changed else "Everything is already encrypted with the current key.")
            return 0

        target = create_engine(args.target)
        try:
            copied = await copy_database(source, target)
        except TransferError as e:
            print(f"Copy failed: {e}")
            return 1
        finally:
            await target.dispose()
        for table, rows in copied.items():
            print(f"  {table:<20} {rows} row(s)")
        print("Done, the row counts match. To use the new database, set in .env:\n"
              "  DATABASE_URL=<the same URL>\nand start the bot.")
        return 0
    finally:
        await source.dispose()


if __name__ == "__main__":
    sys.exit(main())
