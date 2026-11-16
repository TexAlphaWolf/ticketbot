# TicketBot Privacy Policy

_Last updated: November 16, 2026_

This Privacy Policy explains what data TicketBot ("the bot") collects, why, and
how long it is kept. TicketBot is an open source project maintained by
TexAlphaWolf ("the developer"). The source code is public at
<https://github.com/TexAlphaWolf/ticketbot>, so you can verify everything
described here.

By adding TicketBot to a server or using it, you agree to this policy.

## 1. Data we collect

TicketBot only collects the data it needs to run the ticket system.

**Server configuration**, saved when an admin runs `/setup` and the other admin commands:
- Server ID
- IDs of the staff role, ticket category, log, archive and panel channels
- Settings such as the transcript retention period and the ticket counter
- The ID of the Telegram chat linked to the server, if Telegram notifications are enabled

**Open tickets**, saved while a ticket is open:
- Discord user ID of the member who opened the ticket and of the staff member who claimed it
- Ticket type, subject, status and priority
- Timestamps of when the ticket was opened and of the last message, and who sent it
  (member or staff), used for the automatic closing after 24 hours of inactivity
- IDs of the ticket channel and of the bot's own messages

**Transcript references**: channel ID, message ID, priority and closing date of the
transcripts posted in the log channel, used to delete them automatically.

## 2. Message content

TicketBot uses the Message Content intent **only inside ticket channels**.
When a ticket is closed, the bot reads the messages of that ticket to create a
`.txt` transcript. The transcript is generated in memory and is **not saved** on
the bot's host: it is only sent to the places described in section 4.

The bot does not read, store or analyze messages outside ticket channels.

## 3. How we use the data

The data is used only to:
- create, manage and close tickets;
- send transcripts and notifications to the server's staff;
- close inactive tickets and delete old transcripts automatically.

The data is **never sold, shared for advertising or used for any other purpose**.

## 4. Where data is sent

- **Discord**: tickets, logs and transcripts are posted in the server's own channels
  and sent to the ticket owner via direct message.
- **Telegram** (optional): if a server admin links a Telegram chat, notifications
  about new, high priority and closed tickets, including the ticket subject,
  description and transcript, are sent to that chat through the Telegram Bot API.
  Only chats that were verified with a code are used. Chat IDs of people who only
  send `/start` or `/id` to the Telegram bot are not stored.

Discord and Telegram process this data under their own privacy policies.

## 5. Data retention

- **Open ticket data** is deleted as soon as the ticket is closed or its channel is deleted.
- **Transcripts in the log channel**: Low and Medium priority transcripts are deleted
  automatically after the period set by the server (30 days by default). High priority
  transcripts are kept until a server admin deletes them.
- **Transcripts in the archive channel and in direct messages** are kept by Discord
  until they are deleted by the server's admins or by the user.
- **Server configuration** is kept while the bot is in the server and is **deleted
  automatically when the bot is removed** from it.
- **Telegram verification codes** are kept in memory only, for up to 10 minutes.

## 6. Security

The data is stored on the bot's host in a configuration file that is not shared
publicly. Access tokens are kept separate from the code. Only the developer has
access to the host.

## 7. Your rights

You can ask to access or delete the data about you, or ask any question about
this policy, by opening an issue at
<https://github.com/TexAlphaWolf/ticketbot/issues>. Server admins can delete all
the data of their server at any time by removing the bot from the server.

If you live in the European Union, you have the rights granted by the GDPR,
including access, rectification, erasure and the right to lodge a complaint with
your data protection authority.

## 8. Self-hosted instances

TicketBot is open source. If you run your own copy of the bot, you are responsible
for the data processed by your instance, and this policy only applies to the
instance operated by the developer.

## 9. Changes

This policy may be updated. Changes are published in this file, and the
"Last updated" date at the top shows the latest version.
