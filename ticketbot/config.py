"""Settings read from the environment (.env) and fixed constants."""

import os
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "ticketbot.db"
LEGACY_CONFIG = Path(os.getenv("LEGACY_CONFIG", "config.json"))  # v1 config, migrated once

COLOR = discord.Color.blurple()
TOPIC_PREFIX = "ticket-owner:"
DEFAULT_LANGUAGE = "en"

AUTO_CLOSE_HOURS = 24          # close after this many hours without a user reply
WARNING_HOURS_BEFORE = 4       # warn the user this many hours before closing
CLOSED_CHANNEL_HOURS = 12      # closed tickets can be reopened for this long
DEFAULT_RETENTION_DAYS = 30    # Low/Medium transcripts are deleted from the log after this
STATS_KEEP_DAYS = 365          # closed ticket metadata (for /stats) is kept this long
VERIFY_CODE_TTL = 10 * 60      # Telegram verification code lifetime (seconds)
VERIFY_MAX_ATTEMPTS = 5
MAX_TICKET_TYPES = 25          # Discord select menus allow up to 25 options
MAX_REPLIES = 100              # quick replies per server
MAX_REPLY_LENGTH = 1800        # leaves room for the signature (Discord: 2000)

PRIORITIES = ("low", "medium", "high")
PRIORITY_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}
KEPT_PRIORITIES = {"high"}     # transcripts of these priorities are never auto-deleted

STATUS_WAITING = "waiting"          # nobody from the staff has picked it up yet
STATUS_IN_PROGRESS = "in_progress"  # claimed or answered by the staff
STATUS_CLOSED = "closed"
