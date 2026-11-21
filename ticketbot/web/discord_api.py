"""The few Discord HTTP API calls of the web dashboard (OAuth2 login)."""

from urllib.parse import urlencode

import aiohttp

from .. import __version__
from ..core.settings import Settings

API = "https://discord.com/api/v10"
AUTHORIZE = "https://discord.com/oauth2/authorize"
SCOPES = "identify guilds"
USER_AGENT = f"DiscordBot (https://github.com/TexAlphaWolf/ticketbot, {__version__})"


class DiscordError(Exception):
    """Discord answered with an error (status) or couldn't be reached (status None)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class DiscordOAuth:
    def __init__(self, settings: Settings):
        self.client_id = settings.discord_client_id
        secret = settings.discord_client_secret
        # The application's credentials, for the token endpoints (HTTP Basic auth)
        self.auth = ({"Authorization": aiohttp.encode_basic_auth(
            self.client_id, secret.get_secret_value())} if self.client_id and secret else {})
        self.redirect_uri = settings.oauth_redirect_uri
        self._session: aiohttp.ClientSession | None = None

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=15))
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    def authorize_url(self, state: str, code_challenge: str) -> str:
        return AUTHORIZE + "?" + urlencode({
            "response_type": "code", "client_id": self.client_id, "scope": SCOPES,
            "redirect_uri": self.redirect_uri, "state": state, "prompt": "none",
            "code_challenge": code_challenge, "code_challenge_method": "S256"})

    async def _call(self, method: str, path: str, **kwargs):
        try:
            async with self._http().request(method, API + path, **kwargs) as r:
                if r.status >= 400:
                    raise DiscordError(f"{method} {path}: HTTP {r.status}", r.status)
                return await r.json() if r.content_type == "application/json" else {}
        except aiohttp.ClientError as e:
            raise DiscordError(f"{method} {path}: {e.__class__.__name__}") from None

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        """The tokens: access_token, refresh_token, expires_in, scope."""
        return await self._call("POST", "/oauth2/token", headers=self.auth, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": self.redirect_uri, "code_verifier": code_verifier})

    async def refresh(self, refresh_token: str) -> dict:
        return await self._call("POST", "/oauth2/token", headers=self.auth, data={
            "grant_type": "refresh_token", "refresh_token": refresh_token})

    async def user_guilds(self, access_token: str) -> list[dict]:
        """The servers of the logged-in user, with their permissions in each."""
        return await self._call("GET", "/users/@me/guilds",
                                headers={"Authorization": f"Bearer {access_token}"})

    async def fetch_user(self, access_token: str) -> dict:
        return await self._call("GET", "/users/@me",
                                headers={"Authorization": f"Bearer {access_token}"})

    async def revoke(self, token: str) -> None:
        await self._call("POST", "/oauth2/token/revoke", headers=self.auth,
                         data={"token": token, "token_type_hint": "access_token"})


def avatar_url(user_id: int, avatar: str | None) -> str:
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=128"
    return f"https://cdn.discordapp.com/embed/avatars/{(user_id >> 22) % 6}.png"


class DiscordBot(DiscordOAuth):
    """Calls made with the bot's token (the web process doesn't connect to the gateway):
    the roles of a member, to know who is staff."""

    def __init__(self, settings: Settings):
        super().__init__(settings)
        token = settings.discord_token
        self.bot_auth = {"Authorization": f"Bot {token.get_secret_value()}"} if token else None

    @property
    def available(self) -> bool:
        return self.bot_auth is not None

    async def member(self, guild_id: int, user_id: int) -> dict | None:
        """The member (with `roles`), or None if they aren't in the server."""
        if self.bot_auth is None:
            return None
        try:
            return await self._call("GET", f"/guilds/{guild_id}/members/{user_id}",
                                    headers=self.bot_auth)
        except DiscordError as e:
            if e.status in (403, 404):      # not a member, or the bot left the server
                return None
            raise

    async def user(self, user_id: int) -> dict | None:
        """A Discord user (name and avatar) who may not be in the server anymore."""
        if self.bot_auth is None:
            return None
        try:
            return await self._call("GET", f"/users/{user_id}", headers=self.bot_auth)
        except DiscordError as e:
            if e.status == 404:
                return None
            raise


def guild_icon_url(guild_id: int, icon: str | None) -> str | None:
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.png?size=128" if icon else None
