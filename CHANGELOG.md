# Changelog

## [3.0.0-beta.2] - 2026-11-21

Second beta of TicketBot V3: the new ticket flow. Tickets can go to the right team for
their type, be opened as private threads, climb escalation levels, and a FAQ can solve
a request before a ticket is opened. Everything from Beta1 and 2.3 works as before. Test
it on a test server before using it in production.

### Upgrading from 3.0.0-beta.1
1. Stop the bot and make a backup: `python -m ticketbot backup` (SQLite)
2. Update the files; the requirements did not change
3. Start the bot: it makes another backup and applies the migrations 0003 to 0006
   (`[database] migrated from 0002 to 0006`)

Upgrading from 2.3: follow the steps of 3.0.0-beta.1 below, then start the bot.

### Added
- **Staff per ticket type**: `/types roles add` and `remove` choose the roles that handle
  the tickets of a type (e.g. *Bug report* → @Developers). Those roles, instead of the
  staff role, see the ticket channel, are pinged, can claim, transfer, close and write
  notes, get the staff reminders, and are the only ones picked by auto-assign. Admins
  always have access; types without roles keep using the staff role. `/types list`
  shows who handles each type. Changes are recorded in the audit log
- **Tickets as private threads**: `/settings mode` opens new tickets as private threads
  in the panel channel instead of channels. The bot checks its permissions, gives the
  staff roles *Manage Threads* there (so they see every ticket thread) and announces
  new tickets in the log channel, because role mentions don't reach people outside a
  private thread. Closing locks the thread, reopening unlocks it, `/add` and `/remove`
  add and remove members, and archived threads are found again for the inactivity and
  cleanup checks. Tickets already open keep their mode
- **Escalation levels**: `/escalation add`, `remove` and `list` set up to 5 levels above
  the staff, each with a role and, optionally, after how many hours without a staff
  reply a ticket climbs to it by itself. `/escalate` (staff) brings a ticket to the next
  level or to a chosen one, with an optional reason: the level's role gets access to
  the ticket (in thread mode, *Manage Threads* in the panel channel), is pinged in the
  ticket (and in the log channel for threads) and can handle it like the staff.
  Escalations are sent to Telegram and recorded in the audit log, automatic ones as
  done by the system. Levels never go down; removing a level moves the ones above it
  down by one
- **FAQ before the ticket form**: `/faq add`, `edit`, `remove` and `list` manage up to
  50 questions with their answers, written in a form (Markdown and new lines work), for
  one ticket type or for all of them. After choosing the type, a member first sees up to
  5 answers (the type's own, then the general ones) with *It's solved* and *Open a
  ticket anyway*; without FAQ the form opens straight away as before. `/stats` shows
  how many requests were solved without a ticket. The results are anonymous and kept
  for 365 days

## [3.0.0-beta.1] - 2026-11-20

First beta of TicketBot V3: new foundations (storage, migrations, encryption, audit log)
under the same bot. Every feature of 2.3 works as before. Test it on a test server
before using it in production.

### Upgrading from 2.3
1. Stop the bot and make a backup: `python -m ticketbot backup`
2. Update the files and run `python -m pip install -r requirements.txt` (Python 3.11+)
3. Create the encryption key with `python -m ticketbot keygen`, add the line to `.env`
   and keep a copy somewhere safe
4. Check the settings with `python -m ticketbot settings` and start the bot: it adopts
   the database (after another backup), applies the migrations and encrypts the
   sensitive data


### Changed
- The code is split into packages: `core` (settings, translations, rules, statistics,
  transcripts; no Discord code), `db` (storage, backups, v1 import), `bot` (Discord
  client, commands, views) and `integrations` (Telegram). Nothing changes for users:
  the bot still starts with `python -m ticketbot` (or the new `python -m ticketbot bot`)
- CI also runs on the `v3-dev` branch
- Settings are read and validated with `pydantic-settings` when the program starts: a
  missing or invalid value in `.env` stops it with a clear message (e.g.
  `BACKUP_KEEP: Input should be a valid integer`) instead of an error later. Tokens are
  kept as secrets and never appear in logs or error messages. The `.env` variables
  are the same as before

- **`ENCRYPTION_KEY` is required** in `.env` (see *Encryption* in the README)
- **Python 3.11 or newer is required** (Python 3.10 reached end of life in October 2026;
  SQLAlchemy 2.1 needs 3.11)
- `aiohttp` 3.14 or newer is required

- **The bot uses the new async storage**: every database call goes through SQLAlchemy and
  no longer blocks the bot while it waits for the disk. The same code runs on SQLite and
  PostgreSQL. At startup the database is brought to the latest schema: a new one is
  created, a TicketBot 2 database is adopted in place after an automatic backup (v2.0 to
  v2.2 files first get their missing columns), a v1 `config.json` is still imported
- Automatic backups run in a background thread; with PostgreSQL they are skipped and
  `python -m ticketbot backup` / `restore` explain to use `pg_dump` / `pg_restore`
- On/off values are stored as real booleans
- A Telegram chat ID imported from a v1 `config.json` is always stored as text
- Quieter startup: no Alembic details and no warnings about voice libraries (the bot
  never joins voice channels)

### Added
- New storage layer for V3: SQLAlchemy 2 models of every table,
  an async engine for SQLite (default) and PostgreSQL, and Alembic migrations. The first
  migration is exactly the v2.3 schema, so an existing database can be adopted without
  copying data. Discord IDs are stored as 64-bit integers and on/off settings as
  booleans, so the same schema works on PostgreSQL
- `DATABASE_URL` setting (e.g. `postgresql://user:password@host/ticketbot`); the
  password is hidden in `python -m ticketbot settings` and in error messages
- Storage tests on SQLite and, in CI, on PostgreSQL: the migrations must build exactly
  the models, a v2.3 database must have the same tables and keys as the first
  migration, Discord IDs over 32 bits and cascading deletes must work
- **Encryption of the sensitive data**: ticket subject, description and form answers,
  staff notes, closing reason, rating comment and block reason are stored encrypted with
  AES-256-GCM. Each value carries the id of its key and is tied to its column, so a
  changed or moved value is detected. The key is the new required `ENCRYPTION_KEY`
  setting (`python -m ticketbot keygen` creates one); data from TicketBot 2 is encrypted
  at the first start and, on SQLite, no plain copy is left in the file
  (`secure_delete` and a one-time `VACUUM`)
- **Key rotation**: with the new key in `ENCRYPTION_KEY` and the old one in
  `ENCRYPTION_OLD_KEYS`, the bot re-encrypts everything at start (or run
  `python -m ticketbot db encrypt`)
- **Audit log**: settings, ticket types and questions, quick replies, blocks, Telegram
  links, profile changes, ticket opening, claim, priority, transfer, members, notes,
  closing, reopening, deletion, ratings, exports and views of another member's tickets
  are recorded with who, when and the source (discord, web, system). Details and IP
  addresses are encrypted; entries are kept 365 days and deleted with the server's
  data. `/audit` shows the latest 25 to the admins, optionally for one member
- **Queue of actions from the web dashboard** (`bot_commands`): the dashboard of Beta3
  will ask the bot to close a ticket or refresh the panel and the guidelines; the bot
  checks the queue every 3 seconds, checks the permissions again and records the result.
  Commands interrupted by a restart are retried
- `python -m ticketbot db copy <url>` copies all the data to an empty database, e.g. from
  SQLite to PostgreSQL: schema and data in one transaction, same ids, PostgreSQL id
  sequences continued after the copied tickets and notes, row counts checked for every
  table. `python -m ticketbot db status` shows the database in use (password hidden)
  and its schema version
- `python -m ticketbot settings` checks the `.env` file and shows the settings in use,
  with the tokens hidden

## [2.3.0] - 2026-11-20

### Added
- **Auto-assign**: with `/settings autoassign` on, every new ticket is assigned to one of
  the staff members who joined the rotation with `/available`: whoever has the fewest
  open tickets, then whoever has waited longest since their last assignment. Only the
  assigned member is pinged (instead of the whole staff role) and is shown in the
  ticket; the staff reminders go to them too. Any staff member can still claim the
  ticket. Members who left the server or the staff role are removed from the rotation,
  and if nobody is available the staff role is pinged as before
- **`/export`**: the staff can download the tickets of the last 7, 30 or 90 days (or all
  time) as an **Excel** file, with a *Tickets* sheet (real dates, filters, frozen
  header) and a *Summary* sheet with totals, averages, tickets per type and the staff
  leaderboard, or as a **CSV** file (UTF-8, opens correctly in Excel). Only metadata is
  exported, never the subject or the messages; dates are in UTC and the column names
  follow the server's language. Text written by users is escaped so it can't run as a
  spreadsheet formula (CSV injection)

### Changed
- New dependency: `openpyxl` for the Excel export (`pip install -r requirements.txt`)

### Upgrading
- Make a backup with `python -m ticketbot backup`, update the files, run
  `pip install -r requirements.txt` and restart the bot: the database is upgraded
  automatically. With Docker, rebuild the image with `docker compose up -d --build`

## [2.2.0] - 2026-11-20

### Added
- **Custom questions per ticket type** with `/types questions add`, `remove` and `list`:
  up to 3 questions per type, with short or long answers, required or optional, and an
  example shown inside the field. The form shows the subject and the questions of the
  chosen type (types without questions keep subject + description); the answers become
  the ticket description and are shown in the ticket, the transcripts and on Telegram
- **Attachments in the ticket form**: an optional field to upload up to 5 files when
  opening a ticket. Discord keeps form uploads only for a while, so the bot posts them
  again in the ticket channel (and therefore in the transcripts). For safety, files that
  can run code (`.exe`, `.bat`, `.ps1`, `.js`, `.jar`, `.apk`...) and files over the
  server's upload limit are skipped and listed in the ticket
- **`/mytickets`**: shows your open tickets (status and channel link) and your latest
  10 closed tickets with type, dates and rating. Staff members can use the `member`
  option to see the history of another member
- **Abuse protection**: `/block add`, `remove` and `list` let the staff block a member
  from opening tickets for 1 hour, 1 day, 7 days, 30 days or permanently, with an
  optional reason shown to the member; every block and unblock is noted in the log
  channel. `/settings cooldown` sets a minimum time between two tickets of the same
  member (off by default). Staff members are never blocked or slowed down, and the
  checks run both on the panel button and when the form is sent

### Upgrading
- Update the files and restart the bot: the database gets the new table and columns
  automatically. Make a backup first with `python -m ticketbot backup`

## [2.1.0] - 2026-11-20

### Added
- GitHub Actions workflow: `ruff` lint and tests on Python 3.10, 3.11, 3.12, 3.13 and 3.14
  at every push and pull request, with a status badge in the README
- **Quick replies**: admins save answers with `/replies add`, `edit`, `remove` and `list`
  (multi-line, up to 100 per server); staff send them in a ticket with `/reply`, with
  autocomplete and the `{user}`, `{staff}` and `{server}` placeholders. A quick reply
  counts as a staff answer for the statistics and the auto-close timer
- **Staff reminders**: when a ticket waits for a staff reply longer than its priority
  allows (High 2h, Medium 24h, Low 48h, no priority 12h), the bot mentions the staff
  member who claimed it (or the staff role) in the ticket and notifies Telegram; the
  reminder repeats every same interval until the staff answers. The wait starts from
  the first unanswered user message. Turn it on or off with `/settings reminders`;
  the times are shown in the pinned guidelines
- **Automatic backups** of the database every 24 hours, made with SQLite's backup API
  while the bot is running, verified with an integrity check and gzip-compressed in
  `data/backups/`; the last 7 are kept (`BACKUP_KEEP`, `BACKUP_INTERVAL_HOURS`,
  `BACKUP_DIR` in `.env`)
- Command line: `python -m ticketbot backup`, `backups` and `restore <file>`; a restore
  checks the backup first and keeps the current database as `ticketbot.db.before-restore`

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
