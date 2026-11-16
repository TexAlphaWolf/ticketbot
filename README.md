# TicketBot 🎫

A Discord ticket bot written in Python with [discord.py](https://discordpy.readthedocs.io/).
Users pick a ticket type and open a ticket with a button, the bot creates a private
channel with the staff team, and when the ticket is closed a transcript of the
conversation is saved. Each server can also receive notifications on its own Telegram chat.

## Features

- **Ticket types**: Support, Bug report, User report, Other, chosen from a menu
- Panel with an **Open ticket** button and a form (subject + description)
- A private channel for every ticket, visible only to the user and the staff role
- One open ticket per user
- **Queue info**: when opening a ticket, users see how many other tickets are
  *waiting* and how many are *in progress* (also available with `/queue`)
- **Claim with priority**: the staff member who claims a ticket chooses its priority
  (🟢 Low, 🟡 Medium, 🔴 High), based on guidelines that can be pinned in the log
  channel with `/guidelines`. It can be changed later with `/priority`
- **Close**: `.txt` transcript sent to the log channel, the archive channel (optional)
  and to the user via DM, with the closing reason
- **Auto-close after 24h of user inactivity**: if the staff replied and the user
  doesn't answer within 24 hours, the ticket is closed with the reason
  *"No response from the user"*. The user gets a reminder 4 hours before.
  A ticket waiting for the staff is **never** closed automatically.
- **Transcript retention**: Low and Medium transcripts are deleted automatically
  from the log channel after 30 days (configurable with `/retention`), while High
  priority transcripts are kept until an admin deletes them. The archive channel
  always keeps every transcript
- **Telegram notifications** for new, high priority and closed tickets (with the transcript),
  sent only to the chat linked to that server
- Persistent buttons: they keep working after the bot restarts
- Included systemd service for 24/7 hosting on Linux

## Installation

```bash
git clone https://github.com/TexAlphaWolf/ticketbot.git
cd ticketbot
python -m pip install -r requirements.txt
cp .env.example .env   # then add your tokens
python ticketbot.py
```

In the [Developer Portal](https://discord.com/developers/applications), under **Bot**,
enable **Message Content Intent** (required for transcripts).

Permissions required by the bot: Manage Channels, Manage Roles, View Channels,
Send Messages, Manage Messages, Pin Messages, Embed Links, Attach Files,
Read Message History.

## Configuration

As an admin, in your server:

```
/setup staff_role:@Moderators category:Tickets log_channel:#ticket-log panel_channel:#support archive_channel:#ticket-archive
```

`archive_channel` is optional and can be changed later with `/archive`.
Then run `/guidelines` to post and pin the priority guidelines in the log channel.
The configuration and the state of open tickets are saved to `config.json`
(excluded from git).

## Telegram notifications

1. Create a bot with [@BotFather](https://t.me/BotFather) and put its token in `.env`
   as `TELEGRAM_BOT_TOKEN` (optional: without it, Telegram features are disabled).
2. Open your Telegram bot and send `/start`: it replies with your **chat ID**.
   For a group, add the bot to the group and send `/id` there.
3. In Discord, run `/telegram link chat_id:<your chat ID>`.
4. The bot sends a 6-digit code to that Telegram chat: confirm it with
   `/telegram verify code:<code>`.

The verification step makes sure nobody can link a chat they don't own.
Every Discord server links its own chat, so each server only receives its own
tickets: different servers can share the same TicketBot instance without seeing
each other's tickets.

### Multiple people or devices

- **Same Telegram account on several devices**: nothing to do, Telegram syncs
  the notifications on every phone, tablet and PC where you are logged in.
- **Several admins or moderators**: create a Telegram group with everyone who
  should receive the tickets, add the Telegram bot to the group and send `/id`
  there. Link the group's chat ID (a negative number, e.g. `-1001234567890`) with
  `/telegram link` and confirm the code that arrives in the group. To add or
  remove people, just add or remove them from the group.

### Multiple servers in the same chat

A Telegram chat can be linked to more than one Discord server: run
`/telegram link` and `/telegram verify` with the same chat ID in each server.
Every notification shows the server name, so you always know where a ticket
comes from. Each server still sends only its own tickets to the chat linked to it.

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

## Commands

| Command | Who | What it does |
|---|---|---|
| `/setup` | Admin | Sets up the ticket system and posts the panel |
| `/archive channel` | Admin | Sets (or disables, if empty) the archive channel |
| `/guidelines` | Admin | Posts and pins the priority guidelines in the log channel |
| `/retention days` | Admin | Sets after how many days Low/Medium transcripts are deleted from the log |
| `/telegram link chat_id` | Admin | Starts linking a Telegram chat (sends a code) |
| `/telegram verify code` | Admin | Confirms the link with the received code |
| `/telegram status` / `test` / `unlink` | Admin | Shows, tests or removes the Telegram link |
| `/queue` | Everyone | Shows how many tickets are waiting / in progress |
| `/priority level` | Staff | Changes the priority of the ticket |
| `/add user` | Staff | Adds a user to the ticket |
| `/remove user` | Staff | Removes a user from the ticket |
| `/close reason` | Staff or ticket owner | Closes the ticket (reason is optional) |

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
