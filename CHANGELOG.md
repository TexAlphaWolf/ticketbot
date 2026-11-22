# Changelog

## [Unreleased] - V3 Beta4

### Upgrading from 3.0.0-beta.3
Update the files, run `python -m pip install -r requirements.txt` (new: `tzdata`, the time
zones for the weekly report) and start the bot: it makes a backup and applies the
migrations 0010 and 0011 (`[database] migrated from 0009 to 0011`). Optional: set
`REPORT_TIMEZONE`, `REPORT_DAY` and `REPORT_HOUR` in `.env` (default: Monday 9:00 UTC).

### Added
- **Two-way Telegram**: the notifications about a ticket (new ticket, high priority,
  escalation, staff reminder) can be answered on Telegram. Each staff member links their
  Telegram account once with `/telegram-account link` (a one-time code, sent to the
  Telegram bot with `/link` or by opening a link); then a **reply** to a notification is
  posted in the ticket with their name ("Sent from Telegram"), and the buttons under
  it take the ticket (**Claim**, then the priority, like on Discord) or close it
  (**Close**, with a confirmation); answering `/claim high` or `/close reason` does the
  same. The same permissions as on Discord and in the
  dashboard apply, every action is in the audit log (source `telegram`), and the bot
  reacts 👍 when the answer reached Discord or says why not
- What users write in their tickets (the owner included, even when staff) is also sent
  to the Telegram chat, and can be answered the same way: `/telegram messages enabled:False` or the dashboard's settings
  turn it off
- `/telegram-account status` and `unlink` on Discord, `/unlink` on Telegram
- Deleting a ticket everywhere (dashboard, or its transcript in the archive channel) also
  deletes the bot's notifications about it on Telegram, the closing one with the
  transcript included (Telegram allows it in the first 48 hours)
- **Weekly report**: every week (default Monday 9:00, `REPORT_TIMEZONE`, `REPORT_DAY`,
  `REPORT_HOUR` in `.env`, summer time included) each server gets a summary of its
  tickets compared with the week before: opened, closed, still open, average first
  response and resolution, rating, escalations, the most active staff and the busiest
  types, FAQ results. In the log channel (or the one chosen with `/settings report`) and
  on Telegram; sent once a week also across restarts, skipped when there are no tickets.
  `/report` shows the last 7 days at any time; the dashboard's settings turn it on or off
- Migration 0011: `guilds.weekly_report`, `report_channel` and `last_report_at`
- Migration 0010: `telegram_accounts`, `telegram_messages` (chat and message IDs of the
  notifications, kept 30 days or until the ticket is deleted) and
  `guilds.telegram_messages`

## [3.0.0-beta.3] - 2026-11-22

Third beta of TicketBot V3: the web dashboard. Staff and admins handle tickets, read
the statistics and manage the server from the browser, with live updates; every member
can open a ticket from the browser and read the conversation of their closed tickets.
Transcripts are now kept in the database, and deleting one deletes the ticket
everywhere. Docker starts the bot and the dashboard together. The bot works exactly as
before without the dashboard. Test it on a test server before using it in production.

### Upgrading from 3.0.0-beta.2
1. Stop the bot and make a backup: `python -m ticketbot backup` (SQLite)
2. Update the files and the packages: `python -m pip install -r requirements.txt`
   (new: FastAPI and uvicorn for the web server)
3. Start the bot: it makes another backup and applies the migrations 0007 to 0009
   (`[database] migrated from 0006 to 0009`)
4. Optional, for the dashboard:
   - in the [Developer Portal](https://discord.com/developers/applications), open the
     bot's application → **OAuth2**, copy the Client ID and the Client Secret into
     `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` in `.env` and add the redirect
     `http://127.0.0.1:8080/api/v1/auth/callback` (`python -m ticketbot settings` shows
     the one to use)
   - build it once with Node.js 22.22 or newer: `cd frontend`, `npm ci`, `npm run build`
   - start it next to the bot: `python -m ticketbot web` (http://127.0.0.1:8080)
5. Optional: `LEGAL_HOLD_DAYS` in `.env` keeps a hidden copy of the transcripts of
   deleted tickets for that many days (default 0: deleted at once)

With Docker: `git pull` and `docker compose up -d --build`. The dashboard is built inside
the image and starts with the bot (container `ticketbot-web`); only the Developer Portal
step above is needed.

Upgrading from 3.0.0-beta.1 or 2.3: follow the steps of the older versions below first,
the bot applies all the migrations at once.

### Added
- **Web API (base)**: `python -m ticketbot web` starts a FastAPI server next to the bot
  (by default only on this computer, `http://127.0.0.1:8080`), with
  `GET /api/v1/health` and the interactive API documentation at `/api/docs`. It sends
  strict security headers (Content Security Policy, no framing, no caching of the API,
  HSTS when `WEB_PUBLIC_URL` is HTTPS) and never migrates the database: it asks to start
  the bot first when the schema is older, and says so when the port is already in
  use. New `WEB_*` settings in `.env.example`
- **Login with Discord**: OAuth2 authorization code flow with PKCE, scopes `identify` and
  `guilds` only (`/api/v1/auth/login`, `/callback`, `/me`, `/logout`). Logins last 7
  days (`WEB_SESSION_DAYS`) and live in an HttpOnly, SameSite=Lax cookie (`__Host-`
  and Secure over HTTPS); the database keeps only the SHA-256 of the cookie and the
  Discord tokens encrypted. Requests that change something need the CSRF token and
  can't come from another site; after the login only pages of the dashboard are
  opened. Logout revokes the Discord token. Logins and logouts go in the audit log,
  expired logins are deleted every hour. New settings `DISCORD_CLIENT_ID` and
  `DISCORD_CLIENT_SECRET`; `python -m ticketbot settings` shows the redirect to add in
  the Developer Portal. A temporary home page shows who is logged in
- **Read-only web API**: `GET /api/v1/guilds` lists the servers where you are admin or
  staff and TicketBot is set up; `/guilds/{id}` gives the ticket types and the queue,
  `/guilds/{id}/tickets` the tickets (open, closed or all, by type, 50 per page),
  `/guilds/{id}/tickets/{n}` one ticket with its form answers, notes, closing and
  rating, `/guilds/{id}/stats` the numbers of `/stats` with the FAQ results. Everyone
  sees exactly the tickets they could handle on Discord (admins all; staff role, type
  roles and escalation roles as on Discord). Servers you can't use answer 404, like
  servers that don't exist. Names and avatars come from Discord; its answers are
  cached for a minute and the Discord login is renewed by itself. Opening someone
  else's ticket is recorded in the audit log. The login also checks that the answer
  comes from Discord (`iss`)
- **Ticket actions from the web**: claim with a priority, change the priority,
  transfer, escalate, answer in the ticket and close (`POST /api/v1/guilds/{id}/tickets/
  {n}/...`). They go in the queue and the bot carries them out within a few seconds,
  after checking the member's roles again; `GET /api/v1/guilds/{id}/commands/{n}` gives
  the result (done, or failed with the reason). Answers from the dashboard are posted
  by the bot with the staff member's name and avatar and count as a staff reply
  (first response, reminders, auto-close). Private notes are saved at once. Every
  action is recorded in the audit log with source `web`
- **Server management from the web** (admins of the server only): settings (language,
  transcript retention, reminders, auto-assign, cooldown) and the ticket mode; ticket
  types with their form questions and roles; FAQ; escalation levels; the server's
  roles to choose from. Same limits and checks as the commands on Discord (emoji, up to
  25 types, 3 questions, 50 FAQ, 5 levels, no @everyone or bot roles). Changes are
  saved at once and recorded in the audit log; the bot refreshes the panel and the
  guidelines, checks its permissions for thread mode and gives the new roles access to
  the threads
- **Live dashboard**: `GET /api/v1/guilds/{id}/events` (Server-Sent Events) tells the
  dashboard when a ticket you can see is opened, answered, claimed, closed or deleted,
  and the lists, the ticket page and the statistics reload by themselves; a dot in the
  sidebar shows the live connection. Tickets have a new `updated_at` (migration 0009).
  Stopping the web server with Ctrl+C ends the live connections at once
- **Search and filters in the dashboard's ticket list**: a search bar (ticket number,
  channel name, type, subject, form answers or a Discord ID; searched while typing) and
  filters by priority, opening dates and person (click a name: tickets they opened,
  claimed or were assigned). Filters live in the address, so a search can be
  bookmarked. The API gets `q`, `priority`, `person`, `from` and `to` on
  `GET /api/v1/guilds/{id}/tickets`; the encrypted subject and answers are decrypted and
  searched on the server, up to 2000 tickets per page
- **Transcripts in the database and in the dashboard**: when a ticket closes, its
  transcript (messages, embeds, attachment links, staff notes) is saved encrypted in a
  new `transcripts` table (migration 0008) and shown on the ticket's page, with *Download
  HTML* (the same file as in the log channel; served as a download with a sandbox CSP).
  Reading a transcript is recorded in the audit log
- **Delete a ticket everywhere**: deleting its transcript message from the archive
  channel, or *Delete ticket* in the dashboard (admins, closed tickets), removes the
  ticket, its notes and transcript from the dashboard and the statistics and deletes the
  transcript messages in the log and archive channels. New `LEGAL_HOLD_DAYS` (default 0):
  keep a hidden, encrypted copy of a deleted ticket's transcript for that many days, also
  when tickets are purged after 365 days or the bot leaves a server;
  `python -m ticketbot held [id]` lists the copies or saves one as HTML (recorded in the
  audit log)
- The *Claimed by* button shows the staff member's name also when the ticket is
  claimed or transferred from the dashboard (it showed the ID)
- **Web dashboard (second part)**: in a ticket, reply (posted by the bot with your name),
  add a private note, claim with a priority, change the priority, transfer to another
  staff member, escalate and close; the dashboard waits for the bot and says whether it
  worked. A statistics page (periods, response and resolution times, ratings, types,
  priorities, FAQ, staff) and, for admins, pages for the settings and the ticket mode,
  the ticket types with their questions and roles, the FAQ and the escalation levels.
  New `GET /api/v1/guilds/{id}/staff` (staff to transfer to: the auto-assign rotation
  and whoever handled a ticket in the last 90 days) and the number of escalation
  levels in `/guilds/{id}`
- **Web dashboard (first part)**: a React 19 + TypeScript app in `frontend/`, built
  with Vite and served by `python -m ticketbot web`. Login with Discord, your servers,
  the overview of a server (queue and ticket types), the tickets with filters by status
  and type and more pages on demand, and each ticket with its form answers, notes,
  closing and rating, with names and avatars. English, Italian and German (from the
  browser, or chosen in the sidebar), light and dark theme. It works with the strict
  Content Security Policy (no inline scripts, no external files except Discord's
  avatars). The CI also type-checks and builds it
- **Panel of servers set up with TicketBot 1**: their panel message was never saved,
  so changing types or language didn't update it. Now the bot learns it the first time
  someone presses *Open ticket* on it (and updates it at once); until then, a panel
  update asked from the web fails with a clear message instead of "ok"
- The names in the web API also cover members who left the server (from their Discord
  profile)
- Claiming, priority changes and transfers are shared by Discord and the web
  (`claim_ticket`, `change_priority`, `move_ticket`); the web actions moved to
  `bot/web_commands.py`
- `requirements-dev.txt` with the tools for the tests (pytest, httpx2, ruff)
- **Open a ticket from the browser**: every member of a server with TicketBot can log in
  to the dashboard and open a ticket under *Open a ticket*: the same types, form
  questions and FAQ as the panel on Discord, with the same limits (open tickets, cooldown,
  blacklist). The bot opens it within a few seconds and the page links to the new
  channel; the ticket's embed says it was opened from the web dashboard. The same page
  lists your own tickets with a link to Discord, and the conversation of the closed ones
  (without the staff notes). New `GET /api/v1/me/guilds`, `/me/guilds/{id}`,
  `POST /me/guilds/{id}/tickets` and `/faq`, `GET /me/guilds/{id}/commands/{n}` and
  `/me/guilds/{id}/tickets/{n}/transcript`
- The dashboard asks Discord once when several pages need the same answer at the same
  time, waits when Discord asks for a short pause (HTTP 429) and, if Discord can't
  answer, uses the last answer of the past 10 minutes instead of an error. Right after
  a ticket closes, its page says the transcript is being saved and shows it as soon as
  the bot has saved it
- Deleting a ticket everywhere (from the dashboard or by deleting its transcript from
  the archive channel) also deletes its channel when it is still there, e.g. a ticket
  closed a few hours ago and waiting to be deleted after the reopen time; before, the
  channel stayed forever
- Transcripts keep the author and the footer of embeds, so the answers sent from the
  dashboard show who wrote them (transcripts saved before show them without)
- The transcript in the dashboard shows stickers, reactions and image previews too,
  like the HTML file (`stickers` and `reactions` in the transcript API)
- **Docker with the dashboard**: the image is built in stages (Node.js builds the
  dashboard, the final image has only Python, the packages and the built files, and runs
  as a normal user) and `docker-compose.yml` starts the bot and the dashboard
  (`ticketbot-web`, on `127.0.0.1:8080`, with a health check) from the same image, on the
  same `data/` folder. Optional PostgreSQL container with
  `docker compose --profile postgres up -d`. Python 3.14 in the image
- `python -m ticketbot web --wait SECONDS`: if the database isn't ready yet (the bot is
  creating or updating it, PostgreSQL is starting), the dashboard tries again for up to
  that long instead of stopping
- The tests on GitHub also build the Docker image and check that the dashboard starts

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
