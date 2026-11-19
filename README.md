# TicketBot 🎫

A Discord ticket bot written in Python with [discord.py](https://discordpy.readthedocs.io/).
Users pick a ticket type and open a private channel with the staff team. Staff members
claim tickets with a priority, leave private notes, transfer and close them; every ticket
is saved as a Discord-style HTML transcript, rated by the user and counted in the statistics.

Available in **English**, **Italian** and **German**.

## Features

**Tickets**
- Panel with an **Open ticket** button, a menu of **custom ticket types** and a form
- A private channel for every ticket, visible only to the user and the staff role,
  named after the type, the username and the user's ticket number (e.g. `bug-mario-2`)
- One open ticket per user, with queue info (*waiting* / *in progress*)
- Auto-close after **24 hours without a reply from the user** (with a reminder 4 hours
  before); tickets waiting for the staff are never closed automatically

**Staff tools**
- **Claim with priority** (🟢 Low, 🟡 Medium, 🔴 High) following guidelines pinned in the
  log channel with `/guidelines`
- **Transfer** a ticket to another staff member
- **Private notes** visible only to the staff and included in the staff transcript
- **Reopen**: closed tickets stay available for 12 hours before the channel is deleted
- **Statistics** with `/stats`: tickets per type and priority, average first response and
  resolution time, ratings and a staff leaderboard, per period or per staff member

**Transcripts and feedback**
- **HTML transcripts** that look like Discord (avatars, colors, embeds, images, code,
  stickers, reactions and custom emoji) plus
  a plain `.txt` version, sent to the log channel, the archive channel and the user
- Low and Medium transcripts are deleted from the log channel after 30 days
  (configurable); High priority transcripts and the archive channel are kept
- **Ratings**: the user rates the support from 1 to 5 stars, with an optional comment
- **Telegram notifications** for new, high priority, closed and rated tickets

**Setup**
- Settings stored in **SQLite**, with automatic migration from v1 (`config.json`)
- **Multilingual** bot messages and slash command descriptions (EN / IT / DE)
- **Per-server profile**: each server can give the bot its own name, avatar, banner
  and bio with `/profile`
- Runs with Python, as a **systemd** service or with **Docker**

## Installation

### Requirements
- Python 3.10+ (or Docker)
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
python -m ticketbot
```

### With Docker

```bash
git clone https://github.com/TexAlphaWolf/ticketbot.git
cd ticketbot
cp .env.example .env   # then add your tokens
docker compose up -d --build
docker compose logs -f
```

The database is saved in the `data/` folder next to `docker-compose.yml`.

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

## Commands

| Command | Who | What it does |
|---|---|---|
| `/setup` | Admin | Sets up the ticket system and posts the panel |
| `/guidelines` | Admin | Posts and pins the priority guidelines in the log channel |
| `/settings show` / `language` / `retention` / `archive` | Admin | Shows or changes the settings |
| `/types list` / `add` / `edit` / `remove` | Admin | Manages the ticket types |
| `/telegram link` / `verify` / `status` / `test` / `unlink` | Admin | Manages Telegram notifications |
| `/profile name` / `avatar` / `banner` / `bio` / `reset` | Admin | Changes the bot's profile in this server only |
| `/stats period member` | Staff | Shows ticket statistics |
| `/priority level` | Staff | Changes the priority of the ticket |
| `/transfer member` | Staff | Assigns the ticket to another staff member |
| `/note add` / `list` | Staff | Adds or shows private staff notes |
| `/add user` / `/remove user` | Staff | Adds or removes a member from the ticket |
| `/reopen` | Staff | Reopens a closed ticket |
| `/close reason` | Staff or ticket owner | Closes the ticket |
| `/queue` | Everyone | Shows how many tickets are waiting / in progress |

## Project structure

```
ticketbot/
├── bot.py               # Discord client, events and background tasks
├── commands.py          # slash commands
├── tickets.py           # panel, opening, claiming, closing, reopening, ratings
├── transcripts.py       # HTML and text transcripts
├── db.py                # SQLite storage
├── logic.py             # pure functions (auto-close, stats, retention...)
├── i18n.py              # translations (EN / IT / DE)
├── telegram_notifier.py # Telegram Bot API client
├── migrate.py           # v1 config.json import
└── config.py            # settings and constants
```

## Tests

```bash
python -m pip install pytest
python -m pytest
```

## Terms and privacy

- [Terms of Service](TERMS.md)
- [Privacy Policy](PRIVACY.md)

## License

[MIT](LICENSE)
