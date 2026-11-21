# TicketBot Privacy Policy

_Last updated: November 20, 2026_

This Privacy Policy explains what data TicketBot ("the bot") collects, why, and
how long it is kept. TicketBot is an open source project maintained by
TexAlphaWolf ("the developer"). The source code is public at
<https://github.com/TexAlphaWolf/ticketbot>, so you can verify everything
described here.

By adding TicketBot to a server or using it, you agree to this policy.

## 1. Data we collect

TicketBot only collects the data it needs to run the ticket system.

**Server configuration**, saved when an admin runs `/setup` and the other admin commands:
- Server ID and the bot's language for that server
- IDs of the staff role, ticket category, log, archive and panel channels
- Custom ticket types (name, emoji, description, form questions and the roles that handle
  them) and quick replies written by the admins
- Settings such as the transcript retention period and the ticket counter
- The ID of the Telegram chat linked to the server, if Telegram notifications are enabled

**Tickets**:
- Discord user ID of the member who opened the ticket and of the staff member who
  claimed it or closed it
- Discord user ID of the staff member the ticket was automatically assigned to
- Ticket type, subject, description, status, priority and closing reason
- Timestamps of when the ticket was opened, first answered by the staff and closed, and
  of the last message and who sent it (member or staff), used for the automatic closing
  after 24 hours of inactivity and for the statistics
- IDs of the ticket channel and of the bot's own messages

**Staff notes**: text, author ID and date of the private notes written by the staff
with `/note add`.

**Attachments**: files uploaded in the ticket form are posted in the ticket channel on
Discord; the bot does not keep a copy.

**Staff rotation**: Discord user ID of the staff members who joined the auto-assign
rotation with `/available` and when they were last assigned a ticket; removed when they
leave the rotation, the staff role or the server.

**Blocked members**: Discord user ID of the member blocked from opening tickets, the
reason, the ID of the staff member who blocked them and when the block started and ends.

**Web dashboard logins**: when someone logs in to the web dashboard with Discord, their
Discord user ID, username, display name and avatar, the access and refresh tokens Discord
gives for the login (scopes `identify` and `guilds`: who they are and which servers they
are in, nothing else), the IP address and browser name, and when the login started, was
last used and ends. Tokens, IP and browser name are encrypted; the browser keeps only a
random cookie, and the database only its hash. Logins and logouts are recorded in the
audit log. To decide who may see which tickets, the dashboard asks Discord which servers
the person is in and their roles there; names, avatars and roles shown in the dashboard
are kept only in memory, for one minute, and are never written to the database.

**Audit log**: for the actions that change something or read other people's data
(settings, ticket types, blocks, claims, transfers, escalations, closings, exports,
viewing another member's tickets...): the server ID, the Discord user ID of who did it, the action, what
it was about (e.g. a ticket number) and when. Details such as a closing or escalation
reason are encrypted. For actions from the web dashboard, the IP address is recorded, encrypted.

**Actions from the web dashboard**: what a staff member asks from the dashboard (e.g.
close a ticket with a reason, answer in a ticket), or a ticket a member opens from the
dashboard (type, subject and answers), waits in a queue until the bot carries
it out: who asked it, the server, the action and its content (encrypted), and how it
went. Finished actions are deleted after 30 days.

**FAQ**: when a member reads the FAQ before opening a ticket and presses *It's solved*
or *Open a ticket anyway*, only the server, the ticket type, which button and when are
recorded, to count the tickets avoided. Who pressed it is not recorded.

**Ratings**: the score from 1 to 5 and the optional comment the user gives after a
ticket is closed.

**Transcripts in the database**: when a ticket is closed, its conversation (messages,
names and avatars of the authors, attachment links, embeds and the staff notes) is also
saved in the database, encrypted, so the staff can read it in the web dashboard. It is
deleted with the ticket's data (see section 5).

**Transcript references**: channel ID, message ID, priority and closing date of the
transcripts posted in the log channel, used to delete them automatically.

**Server profile**: the name, bio and images an admin sets with `/profile` are sent
directly to Discord to update the bot's profile in that server and are not stored by
the bot.

## 2. Message content

TicketBot uses the Message Content intent **only inside ticket channels**.
When a ticket is closed, the bot reads the messages of that ticket to create a
transcript (HTML and plain text). The transcript includes the messages, the display
names and avatars of the participants, links to the attachments, the stickers used and
the reactions with the names of who reacted. It is generated in
memory and is **not saved** on the bot's host: it is only sent to the places described
in section 4. The copy sent to the user does not include the staff notes.

The bot does not read, store or analyze messages outside ticket channels.

## 3. How we use the data

The data is used only to:
- create, manage, close and reopen tickets;
- send transcripts, ratings and notifications to the server's staff;
- close inactive tickets and delete old transcripts automatically;
- show ticket statistics to the server's staff with `/stats` and let them download the
  same ticket metadata as an Excel or CSV file with `/export` (the file is created in
  memory, sent only to the staff member who asked for it and not saved by the bot);
- show members their own ticket history with `/mytickets` (the staff can see the history
  of any member of their server).

The data is **never sold, shared for advertising or used for any other purpose**.

## 4. Where data is sent

- **Discord**: tickets, logs, ratings and transcripts are posted in the server's own
  channels, and the transcript is sent to the ticket owner via direct message.
- **Telegram** (optional): if a server admin links a Telegram chat, notifications
  about new, high priority, closed and rated tickets, including the ticket subject,
  description, rating comment and transcript, are sent to that chat through the
  Telegram Bot API. Only chats that were verified with a code are used. Chat IDs of
  people who only send `/start` or `/id` to the Telegram bot are not stored.

Discord and Telegram process this data under their own privacy policies.

## 5. Data retention

- **Closed tickets** can be reopened for 12 hours, then the channel is deleted. At that
  moment the **subject, description and staff notes are deleted**.
- **Ticket metadata** used for the statistics (IDs, type, priority, timestamps, closing
  reason and rating) is kept for **365 days** after the ticket is closed, then deleted.
- **Transcripts in the log channel**: Low and Medium priority transcripts are deleted
  automatically after the period set by the server (30 days by default). High priority
  transcripts are kept until a server admin deletes them.
- **Transcripts in the archive channel and in direct messages** are kept by Discord
  until they are deleted by the server's admins or by the user.
- **Server configuration and all the data of a server** are kept while the bot is in
  the server and are **deleted automatically when the bot is removed** from it.
- **Audit log** entries are kept for **365 days**, then deleted, and are deleted with the
  rest of the server's data when the bot is removed from it.
- **FAQ results** (anonymous) are kept for **365 days** for `/stats`, then deleted.
- **Blocks** are deleted when they end or when the staff removes them with `/block remove`.
- **Web dashboard logins** last 7 days by default (`WEB_SESSION_DAYS`) and are deleted
  when they end or at logout; at logout the Discord token is also revoked.
- **Transcripts in the database** are deleted together with the ticket: after 365 days,
  when the bot is removed from the server, or at once when an admin deletes the ticket
  from the dashboard or deletes its transcript from the archive channel. If the person
  running the bot sets `LEGAL_HOLD_DAYS` (default 0, off), a hidden, encrypted copy of
  the transcript is kept for that many days after the deletion, for legal reasons only:
  it isn't shown in the dashboard, can only be read from the server's command line, and
  every read is recorded in the audit log.
- **Telegram verification codes** are kept in memory only, for up to 10 minutes.

## 6. Security

The data is stored on the bot's host in a database that is not shared publicly. The
text written about a ticket (subject, description and form answers, staff notes, closing
reason, rating comment and the reason of a block) is **encrypted** in the database with
AES-256-GCM; the key is kept outside the database and the code. Access tokens are kept
separate from the code. Only the developer has access to the host.

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
