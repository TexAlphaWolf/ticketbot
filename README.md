# TicketBot 🎫

A Discord ticket bot written in Python with [discord.py](https://discordpy.readthedocs.io/).
Users open a ticket with a button, the bot creates a private channel with the staff team,
and when the ticket is closed a transcript of the conversation is saved.

## Features

- Panel with an **Open ticket** button and a form (subject + description)
- A private channel for every ticket, visible only to the user and the staff role
- One open ticket per user
- **Claim**: staff members show who is handling the ticket
- **Close**: `.txt` transcript sent to the log channel, the archive channel (optional) and to the user via DM
- Persistent buttons: they keep working after the bot restarts
- Slash commands: `/setup`, `/archive`, `/add`, `/remove`, `/close`
- Included systemd service for 24/7 hosting on Linux

## Installation

```bash
git clone https://github.com/TexAlphaWolf/ticketbot.git
cd ticketbot
python -m pip install -r requirements.txt
cp .env.example .env   # then add your bot token
python ticketbot.py
```

In the [Developer Portal](https://discord.com/developers/applications), under **Bot**,
enable **Message Content Intent** (required for transcripts).

Permissions required by the bot: Manage Channels, Manage Roles, View Channels,
Send Messages, Embed Links, Attach Files, Read Message History.

## Configuration

As an admin, in your server:

```
/setup staff_role:@Moderators category:Tickets log_channel:#ticket-log panel_channel:#support archive_channel:#ticket-archive
```

`archive_channel` is optional and can be changed later with `/archive`.
The configuration is saved to `config.json` (excluded from git).

## Running 24/7 (Linux)

```bash
cd ~/ticketbot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
nano .env                                        # DISCORD_TOKEN=...
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
| `/add user` | Staff | Adds a user to the ticket |
| `/remove user` | Staff | Removes a user from the ticket |
| `/close` | Staff or ticket owner | Closes the ticket |
