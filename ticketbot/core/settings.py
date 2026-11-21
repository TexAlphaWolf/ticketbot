"""Settings from the environment and the .env file, checked when the program starts."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import ArgumentError

from ..db.engine import normalize_url, safe_url
from .crypto import Keyring, parse_key


class SettingsError(Exception):
    """The .env file or the environment has a missing or invalid value."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,   # TELEGRAM_BOT_TOKEN= counts as "not set"
        extra="ignore",          # other variables in .env are not ours
        frozen=True,
    )

    # Secrets: SecretStr hides them in logs, errors and repr()
    discord_token: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None

    # Database: SQLite file in data_dir unless DATABASE_URL says otherwise
    # (e.g. postgresql://ticketbot:password@localhost/ticketbot). A secret: it can hold
    # the password.
    database_url: SecretStr | None = None

    # Encryption of the sensitive text in the database (python -m ticketbot keygen).
    # Old keys, comma-separated, are only needed while values are re-encrypted.
    encryption_key: SecretStr | None = None
    encryption_old_keys: SecretStr | None = None

    # Files
    data_dir: Path = Path("data")
    legacy_config: Path = Path("config.json")      # v1 config.json, imported once

    # Automatic backups
    backup_dir: Path | None = None                  # default: <data_dir>/backups
    backup_keep: int = Field(default=7, ge=0)        # 0 disables automatic backups
    backup_interval_hours: float = Field(default=24, gt=0)

    # Web dashboard (python -m ticketbot web). By default only this computer can open it;
    # to reach it from outside, put it behind HTTPS (e.g. a tunnel or a reverse proxy).
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8080, ge=1, le=65535)
    web_public_url: str | None = None              # e.g. https://tickets.example.com
    web_api_docs: bool = True                      # interactive API docs at /api/docs
    web_trusted_proxies: str = "127.0.0.1"         # who may set X-Forwarded-For/-Proto
    web_session_days: int = Field(default=7, ge=1, le=30)

    # Login with Discord: OAuth2 page of the bot's application in the Developer Portal
    discord_client_id: str | None = None
    discord_client_secret: SecretStr | None = None

    @field_validator("discord_client_id")
    @classmethod
    def _client_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value.isdigit():
            raise ValueError("the client ID is a number (OAuth2 page in the Developer Portal)")
        return value

    @field_validator("web_public_url")
    @classmethod
    def _public_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        scheme, sep, rest = value.partition("://")
        if scheme not in ("http", "https") or not sep or not rest or "/" in rest:
            raise ValueError("use the address of the dashboard only, e.g. "
                             "https://tickets.example.com")
        return value

    @field_validator("database_url")
    @classmethod
    def _supported_database(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            normalize_url(value.get_secret_value())
        except ValueError as e:
            raise ValueError(str(e)) from None
        except ArgumentError:
            raise ValueError("not a valid database URL") from None
        return value

    @field_validator("encryption_key", "encryption_old_keys")
    @classmethod
    def _valid_keys(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        for key in value.get_secret_value().split(","):
            if key.strip():
                parse_key(key)
        return value

    @field_validator("discord_token", "telegram_bot_token")
    @classmethod
    def _no_placeholder(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        token = value.get_secret_value().strip()
        if not token or token.startswith("paste_your"):
            return None
        if any(c.isspace() for c in token):
            raise ValueError("a token can't contain spaces")
        return SecretStr(token)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ticketbot.db"

    @property
    def db_url(self) -> str:
        """Async SQLAlchemy URL of the database (V3 storage), password included."""
        if self.database_url is not None:
            url = self.database_url.get_secret_value()
        else:
            url = f"sqlite:///{self.db_path.as_posix()}"
        return normalize_url(url).render_as_string(hide_password=False)

    @property
    def sqlite_path(self) -> Path | None:
        """The SQLite database file, or None when the database is PostgreSQL."""
        url = normalize_url(self.db_url)
        if url.get_backend_name() != "sqlite" or not url.database:
            return None
        return Path(url.database)

    @property
    def web_base_url(self) -> str:
        """Where the browser reaches the dashboard."""
        if self.web_public_url:
            return self.web_public_url
        host = "127.0.0.1" if self.web_host in ("0.0.0.0", "::") else self.web_host
        return f"http://{host}:{self.web_port}"

    @property
    def oauth_redirect_uri(self) -> str:
        """To add in the Developer Portal → OAuth2 → Redirects."""
        return f"{self.web_base_url}/api/v1/auth/callback"

    @property
    def discord_login(self) -> bool:
        return bool(self.discord_client_id and self.discord_client_secret)

    @property
    def web_https(self) -> bool:
        return bool(self.web_public_url and self.web_public_url.startswith("https://"))

    @property
    def backups_path(self) -> Path:
        return self.backup_dir or self.data_dir / "backups"

    def require_discord_token(self) -> str:
        if self.discord_token is None:
            raise SettingsError("DISCORD_TOKEN is missing: add it to the .env file "
                                "(see .env.example).")
        return self.discord_token.get_secret_value()

    def keyring(self) -> Keyring:
        if self.encryption_key is None:
            raise SettingsError(
                "ENCRYPTION_KEY is missing: create one with `python -m ticketbot keygen`, "
                "add it to .env and keep a copy somewhere safe (without it the encrypted "
                "data can't be read).")
        old = []
        if self.encryption_old_keys is not None:
            old = [parse_key(k) for k in self.encryption_old_keys.get_secret_value().split(",")
                   if k.strip()]
        return Keyring(parse_key(self.encryption_key.get_secret_value()), old)

    def summary(self) -> list[tuple[str, str]]:
        """What the program will use, with the secrets hidden."""

        def secret(value: SecretStr | None) -> str:
            return "set" if value else "not set"

        return [
            ("DISCORD_TOKEN", secret(self.discord_token)),
            ("TELEGRAM_BOT_TOKEN", secret(self.telegram_bot_token)),
            ("ENCRYPTION_KEY", f"set (id {self.keyring().current_id})"
             if self.encryption_key else "not set"),
            ("ENCRYPTION_OLD_KEYS", secret(self.encryption_old_keys)),
            ("DATA_DIR", str(self.data_dir)),
            ("DATABASE_URL", safe_url(self.db_url)),
            ("LEGACY_CONFIG", str(self.legacy_config)),
            ("BACKUP_DIR", str(self.backups_path)),
            ("BACKUP_KEEP", str(self.backup_keep)),
            ("BACKUP_INTERVAL_HOURS", f"{self.backup_interval_hours:g}"),
            ("WEB_HOST", self.web_host),
            ("WEB_PORT", str(self.web_port)),
            ("WEB_PUBLIC_URL", self.web_public_url or "not set"),
            ("WEB_API_DOCS", "on" if self.web_api_docs else "off"),
            ("WEB_TRUSTED_PROXIES", self.web_trusted_proxies),
            ("WEB_SESSION_DAYS", str(self.web_session_days)),
            ("DISCORD_CLIENT_ID", self.discord_client_id or "not set"),
            ("DISCORD_CLIENT_SECRET", secret(self.discord_client_secret)),
            ("OAuth2 redirect", self.oauth_redirect_uri),
        ]


def describe_errors(error: ValidationError) -> str:
    lines = ["Invalid settings in .env or in the environment:"]
    for e in error.errors():
        name = ".".join(str(part) for part in e["loc"]).upper()
        lines.append(f"  {name}: {e['msg']}")
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read the settings once; raises SettingsError with a readable message."""
    try:
        return Settings()
    except ValidationError as e:
        raise SettingsError(describe_errors(e)) from None
