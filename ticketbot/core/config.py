"""Fixed constants of the ticket system (settings from .env are in settings.py)."""

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
MAX_TYPE_QUESTIONS = 3         # modal: subject + 3 questions + 1 attachment = 5 (Discord max)
SHORT_ANSWER_LENGTH = 200
LONG_ANSWER_LENGTH = 1000
MYTICKETS_CLOSED_SHOWN = 10    # closed tickets listed by /mytickets
MAX_FORM_ATTACHMENTS = 5       # files a user can attach in the ticket form (Discord max: 10)
# File types that can run code: never forwarded into a ticket
BLOCKED_EXTENSIONS = {
    "apk", "app", "bat", "cmd", "com", "cpl", "dll", "exe", "hta", "iso", "img", "jar",
    "js", "jse", "lnk", "msc", "msi", "msp", "pif", "ps1", "psm1", "reg", "scr", "sh",
    "sys", "vb", "vbe", "vbs", "vhd", "vhdx", "wsf", "wsh",
}
MAX_TICKET_COOLDOWN_MINUTES = 1440  # /settings cooldown: up to one day between two tickets
BLOCK_REASON_LENGTH = 200
# /block add durations (seconds, None = permanent)
BLOCK_DURATIONS = {"1h": 3600, "1d": 86400, "7d": 7 * 86400, "30d": 30 * 86400,
                   "permanent": None}
MAX_REPLIES = 100              # quick replies per server
MAX_REPLY_LENGTH = 1800        # leaves room for the signature (Discord: 2000)

PRIORITIES = ("low", "medium", "high")
PRIORITY_EMOJI = {"low": "🟢", "medium": "🟡", "high": "🔴"}
KEPT_PRIORITIES = {"high"}     # transcripts of these priorities are never auto-deleted

# Hours a ticket can wait for a staff reply before the staff is reminded (None = no priority)
STAFF_REPLY_HOURS = {"high": 2, "medium": 24, "low": 48, None: 12}

STATUS_WAITING = "waiting"          # nobody from the staff has picked it up yet
STATUS_IN_PROGRESS = "in_progress"  # claimed or answered by the staff
STATUS_CLOSED = "closed"
