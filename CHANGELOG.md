# Changelog

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
