"""
Minimal async client for the Telegram Bot API, used by TicketBot to send ticket
notifications and receive the answers to them. Built on aiohttp (already a dependency
of discord.py).
"""

import asyncio

import aiohttp

API_URL = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(Exception):
    """Raised when the Telegram API returns an error."""


class TelegramNotifier:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self._token = token
        self._session = session
        self._offset = 0
        self.username: str | None = None

    async def _call(self, method: str, *, json: dict | None = None,
                    data: aiohttp.FormData | None = None, timeout: int = 15):
        url = API_URL.format(token=self._token, method=method)
        try:
            async with self._session.post(
                url, json=json, data=data,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                payload = await resp.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as e:
            raise TelegramError(f"network error: {e}") from e
        if not payload.get("ok"):
            raise TelegramError(payload.get("description", "unknown error"))
        return payload["result"]

    async def get_me(self) -> dict:
        me = await self._call("getMe")
        self.username = me.get("username")
        return me

    async def send_message(self, chat_id: str, text: str, reply_to: int | None = None,
                           buttons: list[tuple[str, str]] | None = None) -> dict:
        """`buttons`: (label, data) shown under the message, in one row."""
        body = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to is not None:
            body["reply_parameters"] = {"message_id": reply_to,
                                        "allow_sending_without_reply": True}
        if buttons:
            body["reply_markup"] = keyboard(buttons)
        return await self._call("sendMessage", json=body)

    async def delete_messages(self, chat_id: str, message_ids: list[int]) -> None:
        """Delete the bot's own messages. Telegram allows it only in the first 48 hours:
        older ones stay (the call fails for them, which is fine)."""
        for start in range(0, len(message_ids), 100):          # at most 100 at a time
            await self._call("deleteMessages", json={
                "chat_id": chat_id, "message_ids": message_ids[start:start + 100]})

    async def set_buttons(self, chat_id: str, message_id: int,
                          buttons: list[tuple[str, str]]) -> None:
        """Change (or with [] remove) the buttons under a message."""
        await self._call("editMessageReplyMarkup", json={
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": keyboard(buttons)})

    async def answer_button(self, callback_id: str, text: str = "",
                            alert: bool = False) -> None:
        """The small notice shown after pressing a button (max 200 characters)."""
        await self._call("answerCallbackQuery", json={
            "callback_query_id": callback_id, "text": text[:200], "show_alert": alert})

    async def react(self, chat_id: str, message_id: int, emoji: str = "👍") -> None:
        """A reaction on a message (e.g. an answer that reached Discord)."""
        await self._call("setMessageReaction", json={
            "chat_id": chat_id, "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}],
        })

    async def send_document(self, chat_id: str, content: bytes, filename: str,
                            caption: str = "") -> dict:
        form = aiohttp.FormData()
        form.add_field("chat_id", str(chat_id))
        form.add_field("caption", caption[:1024])
        form.add_field("parse_mode", "HTML")
        form.add_field("document", content, filename=filename,
                       content_type="text/plain")
        return await self._call("sendDocument", data=form, timeout=60)

    async def poll_forever(self, handler=None, button_handler=None) -> None:
        """Answer /start and /id with the chat ID, so users can find it easily; give
        every other message to `handler` and the buttons pressed to `button_handler`
        (two-way Telegram: answers, /link, Claim and Close)."""
        while True:
            try:
                updates = await self._call("getUpdates", json={
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "callback_query"],
                }, timeout=40)
                for update in updates:
                    self._offset = update["update_id"] + 1
                    if "callback_query" in update:
                        if button_handler is not None:
                            await button_handler(update["callback_query"])
                        continue
                    message = update.get("message") or {}
                    text = (message.get("text") or "").strip()
                    chat_id = (message.get("chat") or {}).get("id")
                    if chat_id is None:
                        continue
                    if not text:
                        if handler is not None and message.get("reply_to_message"):
                            await handler(message)       # e.g. a photo as an answer
                        continue
                    command = text.split()[0].split("@")[0].lower()
                    start_code = command == "/start" and len(text.split()) > 1
                    if command in ("/start", "/id") and not start_code:
                        await self.send_message(str(chat_id), (
                            "👋 This is the <b>TicketBot</b> notification bot.\n\n"
                            f"Your chat ID is: <code>{chat_id}</code>\n\n"
                            "In your Discord server, run "
                            f"<code>/telegram link chat_id:{chat_id}</code> "
                            "to receive ticket notifications here."
                        ))
                    elif handler is not None:
                        await handler(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep polling even after errors
                print(f"[telegram] polling error: {e}")
                await asyncio.sleep(5)


def keyboard(buttons: list[tuple[str, str]]) -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": data}
                                 for label, data in buttons]] if buttons else []}
