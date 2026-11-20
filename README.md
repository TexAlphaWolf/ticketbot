# TicketBot 🎫

[![Tests](https://github.com/TexAlphaWolf/ticketbot/actions/workflows/tests.yml/badge.svg)](https://github.com/TexAlphaWolf/ticketbot/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A Discord ticket bot written in Python with [discord.py](https://discordpy.readthedocs.io/).
Users pick a ticket type and open a private channel with the staff team. Staff members
claim tickets with a priority, leave private notes, transfer and close them; every ticket
is saved as a Discord-style HTML transcript, rated by the user and counted in the statistics.

Available in **English**, **Italian** and **German**.

## Features

**Tickets**
- Panel with an **Open ticket** button, a menu of **custom ticket types** and a form
- **Custom questions per type**: up to 3 questions for each ticket type (e.g. *Version*
  and *Steps to reproduce* for bug reports), with short or long answers, required or
  optional, and an example inside the field
- **Attachments in the form**: up to 5 files (screenshots, logs...) uploaded together with
  the ticket and posted in the ticket channel; files that can run code (`.exe`, `.bat`,
  `.ps1`, `.jar`...) and files over the server's upload limit are skipped
- A private channel for every ticket, visible only to the user and the staff role,
  named after the type, the username and the user's ticket number (e.g. `bug-mario-2`)
- One open ticket per user, with queue info (*waiting* / *in progress*)
- **Ticket history** with `/mytickets`: open tickets with their status and the latest
  closed ones with dates and ratings; staff members can see the history of any member
- Auto-close after **24 hours without a reply from the user** (with a reminder 4 hours
  before); tickets waiting for the staff are never closed automatically

**Staff tools**
- **Claim with priority** (🟢 Low, 🟡 Medium, 🔴 High) following guidelines pinned in the
  log channel with `/guidelines`
- **Quick replies**: saved answers sent with `/reply` (with `{user}`, `{staff}` and
  `{server}` placeholders), managed by admins with `/replies`
- **Staff reminders**: if a ticket waits too long for a staff reply (🔴 2h, 🟡 24h,
  🟢 48h, ⚪ 12h without a priority), the bot pings the staff member who claimed it, or
  the staff role, and sends a Telegram notification; it can be turned off per server
- **Auto-assign**: new tickets are assigned in turn to the staff members who joined the
  rotation with `/available` (whoever has the fewest open tickets first, then whoever
  has waited longest), and only the assigned member is pinged; turn it on with
  `/settings autoassign`
- **Transfer** a ticket to another staff member
- **Abuse protection**: block members from opening tickets with `/block` (for 1 hour,
  1 day, 7 days, 30 days or permanently, with a reason shown to them and a note in the log
  channel), and set a minimum time between two tickets of the same member with
  `/settings cooldown`; staff members are never blocked
- **Private notes** visible only to the staff and included in the staff transcript
- **Reopen**: closed tickets stay available for 12 hours before the channel is deleted
- **Statistics** with `/stats`: tickets per type and priority, average first response and
  resolution time, ratings and a staff leaderboard, per period or per staff member
- **Export** with `/export`: download the tickets of a period as an **Excel** file (with a
  summary sheet and the staff leaderboard) or as **CSV**; text written by users is
  protected against spreadsheet formula injection

**Transcripts and feedback**
- **HTML transcripts** that look like Discord (avatars, colors, embeds, images, code,
  stickers, reactions and custom emoji) plus
  a plain `.txt` version, sent to the log channel, the archive channel and the user
- Low and Medium transcripts are deleted from the log channel after 30 days
  (configurable); High priority transcripts and the archive channel are kept
- **Ratings**: the user rates the support from 1 to 5 stars, with an optional comment
- **Telegram notifications** for new, high priority, closed and rated tickets

**Setup**
- Data stored in **SQLite** (default, no setup) or **PostgreSQL**, with versioned schema
  migrations; databases from TicketBot 2 and v1 `config.json` files are imported
  automatically
- **Automatic daily backups** of the database, checked and compressed, with commands
  to list and restore them
- **Multilingual** bot messages and slash command descriptions (EN / IT / DE)
- **Per-server profile**: each server can give the bot its own name, avatar, banner
  and bio with `/profile`
- Runs with Python, as a **systemd** service or with **Docker**

## Installation

### Requirements
- Python 3.11+ (or Docker)
- A bot created in the [Discord Developer Portal](https://discord.com/developers/applications)
  with **Message Content Intent** enabled (under **Bot**), required for transcripts

Permissions required by the bot: Manage Channels, Manage Roles, View Channels,
Send Messages, Manage Messages, Pin Messages, Embed Links, Attach Files,
Read Message History, Change Nickname.

### With Python

```bash
git clone https://github.com/TexAlphaWolf/ticketbot.git
cd ticketbot
python -m pip install -r requirements.txt
cp .env.example .env   # then add your tokens
python -m ticketbot settings   # checks the .env file (tokens are never printed)
python -m ticketbot
```

If a value in `.env` is missing or wrong, the bot doesn't start and says which one.

### With Docker

```bash
git clone https://github.com/TexAlphaWolf/ticketbot.git
cd ticketbot
cp .env.example .env   # then add your tokens
docker compose up -d --build
docker compose logs -f
```

The database is saved in the `data/` folder next to `docker-compose.yml`.

### Upgrading from TicketBot 2

Make a backup (`python -m ticketbot backup`), update the files, run
`python -m pip install -r requirements.txt` and start the bot. On the first start the
database is adopted by the new migration system: the bot makes another backup, adds the
migration history and prints `[database] adopted the TicketBot 2 database`. Nothing is
copied: your data stays in the same file.

### Using PostgreSQL

SQLite needs no setup and is the default. To use PostgreSQL, create an empty database and
set `DATABASE_URL=postgresql://user:password@host:5432/ticketbot` in `.env`: the tables are
created at the first start. Back it up with `pg_dump`; the automatic backups and
`python -m ticketbot backup` are for SQLite only.

### Upgrading from v1

Stop the bot, update the files and start it with `python -m ticketbot`. On the first
start, `config.json` is imported into the database and renamed to `config.json.migrated`:
settings, open tickets, Telegram links and transcript references are kept.
With Docker, copy `config.json` into the `data/` folder before the first start.
If you use the systemd service, update `ExecStart` to `python -m ticketbot`.

## Configuration

As an admin, in your server:

```
/setup staff_role:@Moderators category:Tickets log_channel:#ticket-log panel_channel:#support archive_channel:#ticket-archive
```

The language is detected from the server's locale and can be changed with
`/settings language`. Then:

- `/guidelines` posts and pins the priority guidelines in the log channel
- `/types add` / `edit` / `remove` customize the ticket types (up to 25)
- `/settings show` shows all the settings
- `/profile` changes the bot's name, avatar, banner and bio in this server only
  (other servers keep the original profile)

## Telegram notifications

1. Create a bot with [@BotFather](https://t.me/BotFather) and put its token in `.env`
   as `TELEGRAM_BOT_TOKEN` (optional: without it, Telegram features are disabled).
2. Open your Telegram bot and send `/start`: it replies with your **chat ID**.
   For a group, add the bot to the group and send `/id` there.
3. In Discord, run `/telegram link chat_id:<your chat ID>`.
4. The bot sends a 6-digit code to that Telegram chat: confirm it with
   `/telegram verify code:<code>`.

The verification step makes sure nobody can link a chat they don't own.

### Multiple people or devices

- **Same Telegram account on several devices**: nothing to do, Telegram syncs
  the notifications on every phone, tablet and PC where you are logged in.
- **Several admins or moderators**: create a Telegram group with everyone who
  should receive the tickets, add the Telegram bot to the group and send `/id`
  there. Link the group's chat ID (a negative number, e.g. `-1001234567890`) with
  `/telegram link` and confirm the code that arrives in the group.

### Multiple servers in the same chat

A Telegram chat can be linked to more than one Discord server: run
`/telegram link` and `/telegram verify` with the same chat ID in each server.
Every notification shows the server name, and each server only sends its own tickets.

> Whoever hosts the bot technically has access to the data of every server it is in.
> If you want full control over your tickets, host your own instance.

## Running 24/7 (Linux)

```bash
cd ~/ticketbot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
nano .env                                        # DISCORD_TOKEN=... TELEGRAM_BOT_TOKEN=...
sudo cp ticketbot.service /etc/systemd/system/   # after adjusting User and paths
sudo systemctl daemon-reload
sudo systemctl enable --now ticketbot
journalctl -u ticketbot -f                       # logs
```

systemd starts the bot at boot and automatically restarts it if it crashes.
With Docker, `restart: unless-stopped` in `docker-compose.yml` does the same.

## Backups

The bot backs up its database every 24 hours in `data/backups/` and keeps the last 7
copies. Each backup is made while the bot is running, checked for integrity and
compressed. You can change this in `.env` with `BACKUP_KEEP` (0 disables backups),
`BACKUP_INTERVAL_HOURS` and `BACKUP_DIR`.

```bash
python -m ticketbot backup                 # make a backup now
python -m ticketbot backups                # list the backups, newest first
python -m ticketbot restore data/backups/ticketbot-20261120-030000.db.gz
```

Stop the bot before restoring. The restore checks the backup first and keeps the
current database as `data/ticketbot.db.before-restore`. With Docker, run the same
commands with `docker compose exec ticketbot python -m ticketbot backup` (and
`docker compose run --rm ticketbot python -m ticketbot restore ...` with the bot stopped).

> Backups protect against mistakes and damaged files, not against losing the whole disk:
> copy the `data/backups/` folder to another device from time to time.

## Commands

| Command | Who | What it does |
|---|---|---|
| `/setup` | Admin | Sets up the ticket system and posts the panel |
| `/guidelines` | Admin | Posts and pins the priority guidelines in the log channel |
| `/settings show` / `language` / `retention` / `archive` / `reminders` / `cooldown` / `autoassign` | Admin | Shows or changes the settings |
| `/types list` / `add` / `edit` / `remove` | Admin | Manages the ticket types |
| `/types questions list` / `add` / `remove` | Admin | Manages the custom questions of a ticket type |
| `/telegram link` / `verify` / `status` / `test` / `unlink` | Admin | Manages Telegram notifications |
| `/profile name` / `avatar` / `banner` / `bio` / `reset` | Admin | Changes the bot's profile in this server only |
| `/available enabled` | Staff | Joins or leaves the auto-assign rotation |
| `/block add` / `remove` / `list` | Staff | Blocks members from opening tickets |
| `/stats period member` | Staff | Shows ticket statistics |
| `/export period format` | Staff | Downloads the tickets of a period as Excel or CSV |
| `/replies list` / `add` / `edit` / `remove` | Admin | Manages the quick replies |
| `/reply name` | Staff | Sends a quick reply in the ticket |
| `/priority level` | Staff | Changes the priority of the ticket |
| `/transfer member` | Staff | Assigns the ticket to another staff member |
| `/note add` / `list` | Staff | Adds or shows private staff notes |
| `/add user` / `/remove user` | Staff | Adds or removes a member from the ticket |
| `/reopen` | Staff | Reopens a closed ticket |
| `/close reason` | Staff or ticket owner | Closes the ticket |
| `/queue` | Everyone | Shows how many tickets are waiting / in progress |
| `/mytickets member` | Everyone (`member`: staff only) | Shows your open and closed tickets |

## Project structure

```
ticketbot/
├── core/                # shared by the bot and (from V3) the web API, no Discord code
│   ├── settings.py      # settings from .env, validated at startup
│   ├── config.py        # constants
│   ├── i18n.py          # translations (EN / IT / DE)
│   ├── logic.py         # pure functions (auto-close, stats, retention...)
│   ├── export.py        # Excel and CSV export of the statistics
│   └── transcripts.py   # HTML and text transcripts
├── db/
│   ├── models.py        # V3 tables (SQLAlchemy 2)
│   ├── engine.py        # async engine: SQLite or PostgreSQL
│   ├── migrate.py       # runs the Alembic migrations
│   ├── migrations/      # numbered schema changes
│   ├── store.py         # async queries used by the bot
│   ├── v2.py            # recognises and adopts TicketBot 2 databases
│   ├── backup.py        # backups and restore
│   └── legacy.py        # v1 config.json import
├── bot/
│   ├── client.py        # Discord client, events and background tasks
│   ├── commands.py      # slash commands
│   ├── tickets.py       # panel, opening, claiming, closing, reopening, ratings
│   ├── collect.py       # reads a ticket's messages for the transcripts
│   ├── translator.py    # slash command translations
│   └── common.py        # helpers shared by the bot modules
├── integrations/
│   └── telegram.py      # Telegram Bot API client
└── __main__.py          # command line: bot, settings, backup, backups, restore
```

## Tests

```bash
python -m pip install pytest ruff
python -m pytest     # unit tests
ruff check .         # code style and common mistakes
```

Both run automatically on GitHub Actions at every push, on Python 3.11 to 3.14, and the
storage tests also run on PostgreSQL.

## Terms and privacy

- [Terms of Service](TERMS.md)
- [Privacy Policy](PRIVACY.md)

## License

[MIT](LICENSE)
