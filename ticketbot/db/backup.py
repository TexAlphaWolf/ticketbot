"""Database backups: consistent copies made while the bot is running, checked and compressed."""

import gzip
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

PREFIX = "ticketbot-"
SUFFIX = ".db.gz"


def _check(conn: sqlite3.Connection) -> bool:
    return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def create_backup(source: sqlite3.Connection, backup_dir: Path,
                  now: datetime | None = None) -> Path:
    """Copy the database with SQLite's backup API, verify it and save it gzip-compressed."""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{PREFIX}{stamp}{SUFFIX}"
    tmp = backup_dir / f".{PREFIX}{stamp}.tmp"
    try:
        copy = sqlite3.connect(tmp)
        with copy:
            source.backup(copy)
        ok = _check(copy)
        copy.close()
        if not ok:
            raise RuntimeError("the backup copy failed the integrity check")
        with open(tmp, "rb") as raw, gzip.open(target, "wb") as packed:
            shutil.copyfileobj(raw, packed)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def list_backups(backup_dir: Path) -> list[Path]:
    """Backups from the oldest to the newest (the timestamp is in the file name)."""
    backup_dir = Path(backup_dir)
    if not backup_dir.is_dir():
        return []
    return sorted(p for p in backup_dir.glob(f"{PREFIX}*{SUFFIX}") if p.is_file())


def prune_backups(backup_dir: Path, keep: int) -> list[Path]:
    """Delete the oldest backups so that only the newest `keep` remain."""
    backups = list_backups(backup_dir)
    removed = backups[:-keep] if keep > 0 else []
    for path in removed:
        path.unlink(missing_ok=True)
    return removed


def backup_due(backup_dir: Path, interval_hours: float, now: float | None = None) -> bool:
    backups = list_backups(backup_dir)
    if not backups:
        return True
    age = (now or time.time()) - backups[-1].stat().st_mtime
    return age >= interval_hours * 3600


def restore_backup(backup_file: Path, db_path: Path) -> Path | None:
    """
    Replace the database with a backup. The bot must be stopped.
    The current database is kept as <name>.before-restore; returns its path (or None).
    """
    backup_file, db_path = Path(backup_file), Path(db_path)
    tmp = db_path.with_name(db_path.name + ".restore-tmp")
    try:
        with gzip.open(backup_file, "rb") as packed, open(tmp, "wb") as raw:
            shutil.copyfileobj(packed, raw)
        conn = sqlite3.connect(tmp)
        ok = _check(conn)
        conn.close()
        if not ok:
            raise RuntimeError(f"{backup_file.name} is damaged: restore cancelled")

        safety = None
        if db_path.exists():
            # Copy through SQLite so that changes still in the -wal file are included
            safety = db_path.with_name(db_path.name + ".before-restore")
            safety.unlink(missing_ok=True)
            current, copy = sqlite3.connect(db_path), sqlite3.connect(safety)
            with copy:
                current.backup(copy)
            current.close()
            copy.close()
        for extra in ("-wal", "-shm"):
            db_path.with_name(db_path.name + extra).unlink(missing_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(db_path)
        return safety
    finally:
        tmp.unlink(missing_ok=True)
