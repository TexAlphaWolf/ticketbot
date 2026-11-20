"""
Minimal async client for the Telegram Bot API, used by TicketBot to send
ticket notifications. Built on aiohttp (already a dependency of discord.py).
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

    async def send_message(self, chat_id: str, text: str) -> dict:
        return await self._call("sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
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

    async def poll_forever(self) -> None:
        """Answer /start and /id with the chat ID, so users can find it easily."""
        while True:
            try:
                updates = await self._call("getUpdates", json={
                    "offset": self._offset,
                    "timeout": 30,
                    "allowed_updates": ["message"],
                }, timeout=40)
                for update in updates:
                    self._offset = update["update_id"] + 1
                    message = update.get("message") or {}
                    text = (message.get("text") or "").strip()
                    chat_id = (message.get("chat") or {}).get("id")
                    if not text or chat_id is None:
                        continue
                    command = text.split()[0].split("@")[0].lower()
                    if command in ("/start", "/id"):
                        await self.send_message(str(chat_id), (
                            "👋 This is the <b>TicketBot</b> notification bot.\n\n"
                            f"Your chat ID is: <code>{chat_id}</code>\n\n"
                            "In your Discord server, run "
                            f"<code>/telegram link chat_id:{chat_id}</code> "
                            "to receive ticket notifications here."
                        ))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # keep polling even after errors
                print(f"[telegram] polling error: {e}")
                await asyncio.sleep(5)
