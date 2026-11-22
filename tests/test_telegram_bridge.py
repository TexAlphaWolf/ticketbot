"""Two-way Telegram (Beta4): linked accounts, answers to the notifications, the users'
messages sent to Telegram."""

import asyncio
from types import SimpleNamespace

from conftest import new_store
from test_web_actions import GUILD, Member, world  # noqa: F401  (fixture)

from ticketbot.bot import telegram_bridge
from ticketbot.bot.client import TicketBot

CHAT = -100123


class FakeTelegram:
    username = "TicketTestBot"

    def __init__(self):
        self.sent, self.reactions, self.react_works = [], [], True
        self.buttons, self.notices, self.deleted = {}, [], []

    async def send_message(self, chat_id, text, reply_to=None, buttons=None):
        self.sent.append((str(chat_id), text, reply_to))
        message_id = 900 + len(self.sent)
        self.buttons[message_id] = [data for _, data in buttons or []]
        return {"message_id": message_id}

    async def set_buttons(self, chat_id, message_id, buttons):
        self.buttons[message_id] = [data for _, data in buttons]

    async def answer_button(self, callback_id, text="", alert=False):
        self.notices.append((text, alert))

    async def send_document(self, chat_id, content, filename, caption=""):
        self.sent.append((str(chat_id), caption, None))
        self.buttons[900 + len(self.sent)] = []
        return {"message_id": 900 + len(self.sent)}

    async def delete_messages(self, chat_id, message_ids):
        from ticketbot.integrations.telegram import TelegramError
        if chat_id == "-1":
            raise TelegramError("message can't be deleted")
        self.deleted.append((chat_id, message_ids))

    async def react(self, chat_id, message_id, emoji="👍"):
        from ticketbot.integrations.telegram import TelegramError
        if not self.react_works:
            raise TelegramError("reactions are off")
        self.reactions.append(message_id)


def message(text, sender=555, reply_to=None, chat=CHAT, message_id=1):
    m = {"message_id": message_id, "chat": {"id": chat}, "from": {"id": sender},
         "text": text}
    if reply_to is not None:
        m["reply_to_message"] = {"message_id": reply_to}
    if text is None:
        del m["text"]
        m["photo"] = [{"file_id": "x"}]
    return m


def scenario(tmp_path, guild, body):
    async def go():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD, staff_role=5, language="en",
                               telegram_chat_id=str(CHAT))
        tid = await store.create_ticket(guild_id=GUILD, channel_id=100, owner_id=11,
                                        type_key="b", type_label="B", type_emoji="x",
                                        opened_at=1.0, last_activity=1.0,
                                        awaiting_staff_since=1.0)
        bot = TicketBot(store)
        bot.telegram = FakeTelegram()
        bot.get_guild = lambda gid: guild if gid == GUILD else None
        bot.get_user = lambda uid: None
        await body(bot, store, tid)
        await store.close()

    asyncio.run(go())


def test_store_accounts_and_messages(tmp_path):
    async def go():
        store = await new_store(tmp_path / "ticketbot.db")
        await store.save_guild(GUILD)
        tid = await store.create_ticket(guild_id=GUILD, channel_id=100, owner_id=11,
                                        type_key="b", type_label="B", type_emoji="x",
                                        opened_at=1.0, last_activity=1.0)
        await store.link_telegram_account(555, 10, now=1.0)
        await store.link_telegram_account(556, 10, now=2.0)      # a new phone: replaces
        assert await store.telegram_account(555) is None
        assert (await store.telegram_account_of(10))["telegram_user_id"] == 556
        await store.link_telegram_account(556, 12, now=3.0)      # someone else's now
        assert await store.telegram_account_of(10) is None
        assert await store.unlink_telegram_account(discord_user_id=12)
        assert not await store.unlink_telegram_account(telegram_user_id=556)

        await store.track_telegram_message(CHAT, 1, GUILD, tid, now=10.0)
        await store.track_telegram_message(CHAT, 2, GUILD, tid, now=100.0)
        assert (await store.telegram_message(CHAT, 1))["ticket_id"] == tid
        assert await store.telegram_message(-1, 1) is None        # same id, other chat
        assert await store.purge_telegram_messages_before(50.0) == 1
        await store.delete_ticket(tid)                             # goes with the ticket
        assert await store.telegram_message(CHAT, 2) is None
        await store.close()

    asyncio.run(go())


def test_link_codes(tmp_path, world):  # noqa: F811
    async def body(bot, store, tid):
        tg = bot.telegram
        await telegram_bridge.handle_message(bot, message("/link NOPE"))
        assert "wrong or expired" in tg.sent[-1][1]
        old = telegram_bridge.new_account_code(bot, 10, "it")
        code = telegram_bridge.new_account_code(bot, 10, "it")     # replaces the old one
        assert old not in bot.telegram_codes and len(code) == 8
        await telegram_bridge.handle_message(bot, message(f"/start {code.lower()}"))
        assert "Collegato all'account Discord" in tg.sent[-1][1]   # the member's language
        assert (await store.telegram_account(555))["discord_user_id"] == 10
        await telegram_bridge.handle_message(bot, message(f"/link {code}"))
        assert "wrong or expired" in tg.sent[-1][1]                # used once only
        expired = telegram_bridge.new_account_code(bot, 12, "en", now=1.0)
        await telegram_bridge.handle_message(bot, message(f"/link {expired}", sender=777))
        assert await store.telegram_account(777) is None
        await telegram_bridge.handle_message(bot, message("/unlink"))
        assert "not linked to Discord anymore" in tg.sent[-1][1]
        assert await store.telegram_account(555) is None

    scenario(tmp_path, world, body)


def test_answers_reach_the_ticket(tmp_path, world):  # noqa: F811
    channel = world.channels[100]

    async def body(bot, store, tid):
        tg = bot.telegram
        await store.track_telegram_message(CHAT, 50, GUILD, tid)

        await telegram_bridge.handle_message(bot, message("hello", reply_to=49))
        assert tg.sent == []                              # not about a ticket: ignored
        await telegram_bridge.handle_message(bot, message("hello", reply_to=50))
        assert "Link your Telegram account first" in tg.sent[-1][1]

        await store.link_telegram_account(555, 10)        # 10 is staff (role 5)
        await store.link_telegram_account(556, 13)        # 13 is not
        await telegram_bridge.handle_message(bot, message("We are on it", reply_to=50,
                                                          message_id=7))
        embed = channel.sent[-1]
        assert embed.description == "We are on it" and embed.author.name == "Staff10"
        assert embed.footer.text == "Sent from Telegram"
        assert tg.reactions == [7]
        t = await store.get_ticket(tid)
        assert t["first_response_at"] and t["last_actor"] == "staff"

        await telegram_bridge.handle_message(bot, message("hi", sender=556, reply_to=50))
        assert tg.sent[-1][1] == "❌ Not done: you are not staff for this ticket anymore"
        await telegram_bridge.handle_message(bot, message(None, reply_to=50))
        assert "Only text answers" in tg.sent[-1][1]
        await telegram_bridge.handle_message(bot, message("/claim"))      # no reply
        assert "Which ticket?" in tg.sent[-1][1]
        await telegram_bridge.handle_message(bot, message("/priority high", reply_to=50))
        assert "/claim or /close" in tg.sent[-1][1]
        await telegram_bridge.handle_message(bot, message("hi", reply_to=50, chat=-5))
        assert len(channel.sent) == 1                     # another chat: not this ticket

        await telegram_bridge.handle_message(bot, message("/claim@TicketTestBot",
                                                          reply_to=50, message_id=8))
        asked = 900 + len(tg.sent)                        # like on Discord: the priority
        assert tg.sent[-1][1] == "Choose the priority of the ticket:"
        assert tg.buttons[asked] == ["claim:low", "claim:medium", "claim:high", "keep"]
        assert (await store.telegram_message(CHAT, asked))["ticket_id"] == tid
        assert (await store.get_ticket(tid))["claimed_by"] is None

        tg.react_works = False
        await telegram_bridge.handle_message(bot, message("/claim Alta", reply_to=50,
                                                          message_id=9))
        t = await store.get_ticket(tid)
        assert (t["claimed_by"], t["priority"]) == (10, "high")
        assert tg.sent[-1] == (str(CHAT), "✅ Done.", 9)  # no reactions: a reply instead
        actions = [(e["action"], e["source"]) for e in await store.audit_entries(GUILD)]
        assert ("ticket.message", "telegram") in actions
        assert ("ticket.claim", "telegram") in actions

    scenario(tmp_path, world, body)


def test_close_from_telegram(tmp_path, world, monkeypatch):  # noqa: F811
    import ticketbot.bot.web_commands as wc

    closed = []

    async def fake_close(client, channel, ticket, member, reason, source=None):
        closed.append((member.id, reason, source))

    monkeypatch.setattr(wc, "close_ticket", fake_close)

    async def body(bot, store, tid):
        await store.track_telegram_message(CHAT, 50, GUILD, tid)
        await store.link_telegram_account(555, 10)
        await telegram_bridge.handle_message(bot, message("/close Solved by phone",
                                                          reply_to=50))
        await telegram_bridge.handle_message(bot, message("/close", reply_to=50))
        assert closed == [(10, "Solved by phone", "telegram"),
                          (10, "Closed by the staff", "telegram")]

    scenario(tmp_path, world, body)


def test_users_messages_go_to_telegram(tmp_path, world):  # noqa: F811
    channel = world.channels[100]

    def discord_message(author, text, attachments=()):
        return SimpleNamespace(author=author, clean_content=text, guild=world,
                               channel=channel, attachments=list(attachments))

    owner = Member(id=11, display_name="Mario", bot=False, roles=[],
                   guild_permissions=SimpleNamespace(administrator=False))
    world.name = "Test <Server>"

    async def body(bot, store, tid):
        tg = bot.telegram
        cfg = await store.get_guild(GUILD)
        ticket = await store.get_ticket(tid)
        await telegram_bridge.forward_user_message(
            bot, discord_message(owner, "It <crashes>", ["log.txt"]), ticket, cfg)
        text = tg.sent[-1][1]
        assert "<b>Mario</b> in #t-100 on <b>Test &lt;Server&gt;</b>" in text
        assert "It &lt;crashes&gt;" in text and "📎 1 attachment(s)" in text
        assert "Reply to this message" in text
        tracked = await store.telegram_message(CHAT, 900 + len(tg.sent))
        assert tracked["ticket_id"] == tid                # answerable
        assert tg.buttons[900 + len(tg.sent)] == ["claim", "close"]

        # The owner is a user in their ticket even when they are staff (admins testing)
        owner_staff = Member(id=11, display_name="Mario", bot=False, roles=[],
                             guild_permissions=SimpleNamespace(administrator=True))
        await telegram_bridge.forward_user_message(
            bot, discord_message(owner_staff, "Still broken"), ticket, cfg)
        assert len(tg.sent) == 2
        await store.update_ticket(tid, claimed_by=10)     # once claimed: only Close
        await telegram_bridge.forward_user_message(
            bot, discord_message(owner, "Thanks"), ticket, cfg)
        assert tg.buttons[900 + len(tg.sent)] == ["close"]
        assert len(tg.sent) == 3

        staff = world.members[10]
        await telegram_bridge.forward_user_message(
            bot, discord_message(staff, "On it"), ticket, cfg)
        assert len(tg.sent) == 3                          # the staff's own messages: no
        cfg = await store.save_guild(GUILD, telegram_messages=False)
        await telegram_bridge.forward_user_message(
            bot, discord_message(owner, "Again"), ticket, cfg)
        assert len(tg.sent) == 3                          # turned off

    scenario(tmp_path, world, body)


def test_buttons_under_the_notifications(tmp_path, world, monkeypatch):  # noqa: F811
    import ticketbot.bot.web_commands as wc

    closed = []

    async def fake_close(client, channel, ticket, member, reason, source=None):
        closed.append((member.id, reason, source))
        await client.db.update_ticket(ticket["id"], status="closed")

    monkeypatch.setattr(wc, "close_ticket", fake_close)

    def press(data, sender=555, message_id=50, chat=CHAT):
        return {"id": "q", "from": {"id": sender}, "data": data,
                "message": {"message_id": message_id, "chat": {"id": chat}}}

    async def body(bot, store, tid):
        tg = bot.telegram
        await store.track_telegram_message(CHAT, 50, GUILD, tid)
        await telegram_bridge.handle_button(bot, press("claim", message_id=49))
        assert "too old" in tg.notices[-1][0] and tg.notices[-1][1]
        await telegram_bridge.handle_button(bot, press("claim"))
        assert tg.notices[-1] == ("🔗 Link your Telegram account first: run "
                                  "/telegram-account link on Discord.", True)
        await store.link_telegram_account(555, 10)
        await store.link_telegram_account(556, 13)            # not staff

        await telegram_bridge.handle_button(bot, press("claim"))   # the priority first
        assert tg.buttons[50] == ["claim:low", "claim:medium", "claim:high", "keep"]
        await telegram_bridge.handle_button(bot, press("keep"))
        assert tg.buttons[50] == ["claim", "close"]
        await telegram_bridge.handle_button(bot, press("claim:high", sender=556))
        assert tg.notices[-1] == ("❌ Not done: you are not staff for this ticket anymore",
                                  True)
        await telegram_bridge.handle_button(bot, press("claim:low"))
        assert tg.notices[-1] == ("✅ Done.", False)
        t = await store.get_ticket(tid)
        assert (t["claimed_by"], t["priority"]) == (10, "low")
        assert tg.buttons[50] == ["close"]                         # Claim is done

        await telegram_bridge.handle_button(bot, press("close"))   # asks first
        assert tg.buttons[50] == ["close!", "keep"] and closed == []
        await telegram_bridge.handle_button(bot, press("keep"))
        assert tg.buttons[50] == ["close"]
        await telegram_bridge.handle_button(bot, press("close"))
        await telegram_bridge.handle_button(bot, press("close!"))
        assert closed == [(10, "Closed by the staff", "telegram")]
        assert tg.buttons[50] == []                                # nothing left to press
        actions = [(e["action"], e["source"]) for e in await store.audit_entries(GUILD)]
        assert ("ticket.claim", "telegram") in actions

    scenario(tmp_path, world, body)


def test_deleted_tickets_leave_telegram_too(tmp_path, world):  # noqa: F811
    from ticketbot.bot.common import telegram_notify
    from ticketbot.bot.web_commands import delete_transcript_messages

    async def body(bot, store, tid):
        tg = bot.telegram
        cfg = await store.get_guild(GUILD)
        await telegram_notify(bot, cfg, "New", ticket_id=tid)
        await telegram_notify(bot, cfg, "Closed", document=b"<html>", filename="t.html",
                              ticket_id=tid, answerable=False)
        assert tg.buttons[901] == ["claim", "close"]
        assert tg.buttons[902] == [] and "Reply to this message" not in tg.sent[-1][1]
        pairs = await store.telegram_messages_of(tid)
        assert sorted(pairs) == [[CHAT, 901], [CHAT, 902]]       # both deleted with it

        await delete_transcript_messages(bot, GUILD, [],
                                         telegram=pairs + [[-1, 5], [CHAT, 900]])
        assert tg.deleted == [(str(CHAT), [900, 901, 902])]      # one call per chat;
                                                                 # a failing chat is skipped
    scenario(tmp_path, world, body)
