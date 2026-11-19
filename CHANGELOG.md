# Changelog

## [Unreleased]

### Added
- GitHub Actions workflow: `ruff` lint and tests on Python 3.10, 3.11, 3.12, 3.13 and 3.14
  at every push and pull request, with a status badge in the README
- **Quick replies**: admins save answers with `/replies add`, `edit`, `remove` and `list`
  (multi-line, up to 100 per server); staff send them in a ticket with `/reply`, with
  autocomplete and the `{user}`, `{staff}` and `{server}` placeholders. A quick reply
  counts as a staff answer for the statistics and the auto-close timer

### Changed
- Tool settings (`ruff`, `pytest`) moved to `pyproject.toml`; `pytest.ini` removed

## [2.0.0] - 2026-11-18

### Added
- **Staff tools**: `/transfer` to assign a ticket to another staff member, private staff
  notes (`/note add`, `/note list`) included only in the staff transcript, and `/reopen`
- **Closed tickets** stay available for 12 hours with *Reopen* and *Delete now* buttons
  before the channel is deleted
- **Ratings**: after closing, the user rates the support from 1 to 5 stars with an
  optional comment (in DM, or in the ticket if DMs are closed); ratings are posted in
  the log channel and sent to Telegram
- **Statistics** with `/stats`: tickets by type and priority, average first response and
  resolution time, average rating and staff leaderboard, for 7/30/90 days or all time,
  for the whole team or a single staff member
- **HTML transcripts** that look like Discord, sent together with the `.txt` version;
  transcripts show stickers (name and ID), reactions (with who reacted) and custom
  server emoji
- **Custom ticket types** per server with `/types list`, `add`, `edit`, `remove`;
  the panel updates automatically
- **Languages**: English, Italian and German for bot messages and slash command
  descriptions, detected from the server locale and changeable with `/settings language`
- `/settings show`, `/settings retention`, `/settings archive`
- **Per-server profile** with `/profile name`, `avatar`, `banner`, `bio` and `reset`:
  the bot's name, avatar, banner and bio change only in that server
- **Docker** support (`Dockerfile`, `docker-compose.yml`)

### Changed
- **Breaking**: the bot is now a package started with `python -m ticketbot`
  (update `ExecStart` in the systemd service)
- Ticket channels are named after the type, the username and the number of tickets
  opened by that user (e.g. `bug-mario-2`) instead of a server-wide counter
- **Breaking**: `/archive` and `/retention` moved to `/settings archive` and
  `/settings retention`
- Data is stored in a SQLite database (`data/ticketbot.db`); `config.json` from v1 is
  imported automatically on the first start and renamed to `config.json.migrated`
- The data of servers the bot was removed from while offline is deleted at startup
- Subject, description and staff notes are deleted when a closed ticket's channel is
  deleted; ticket metadata for the statistics is kept for 365 days
- Modals use the new `discord.ui.Label` component (discord.py 2.6 or newer)
- The bot needs the **Change Nickname** permission for `/profile name`

## [1.2.1] - 2026-11-16

### Added
- Terms of Service (`TERMS.md`) and Privacy Policy (`PRIVACY.md`)

### Changed
- All the data of a server is deleted automatically when the bot is removed from it

## [1.2.0] - 2026-11-14

### Added
- Ticket priorities (Low, Medium, High): the staff member who claims a ticket
  chooses the priority; it can be changed with `/priority`
- `/guidelines` command to post and pin the priority guidelines in the log channel
- Automatic deletion of Low and Medium transcripts from the log channel after
  a configurable number of days (`/retention`, default 30); High priority
  transcripts are kept until deleted manually, and the archive channel always
  keeps every transcript
- Telegram notification when a ticket is set to High priority
- Priority and "Claimed by" shown in transcripts, logs and Telegram messages

### Changed
- A ticket can no longer be claimed twice

### Docs
- How to receive notifications in a Telegram group (several admins) and how to
  link the same chat to more than one server

## [1.1.0] - 2026-11-13

### Added
- Ticket types (Support, Bug report, User report, Other) chosen from a menu;
  ticket channels are named after the type (e.g. `bug-0007`)
- Queue info when opening a ticket: number of other tickets waiting and in progress
- `/queue` command
- Automatic closing after 24 hours without a reply from the user, with a reminder
  4 hours before; tickets waiting for the staff are never closed automatically
- Optional closing reason (`/close reason:`), shown in logs, transcripts and DMs
- Telegram notifications for new and closed tickets, with per-server chat linking
  and verification code (`/telegram link`, `verify`, `status`, `test`, `unlink`)
- Unit tests for the auto-close logic and the queue counter

### Changed
- `/setup` no longer resets the existing configuration when run again
- Ticket state is now stored in `config.json`

## [1.0.0] - 2026-11-13

### Added
- First release: ticket panel, private ticket channels, claim and close buttons,
  transcripts to log/archive channels and DM, `/setup`, `/archive`, `/add`,
  `/remove`, `/close`, systemd service
