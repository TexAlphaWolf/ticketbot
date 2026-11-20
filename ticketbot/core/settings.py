"""Settings from the environment and the .env file, checked when the program starts."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Files
    data_dir: Path = Path("data")
    legacy_config: Path = Path("config.json")      # v1 config.json, imported once

    # Automatic backups
    backup_dir: Path | None = None                  # default: <data_dir>/backups
    backup_keep: int = Field(default=7, ge=0)        # 0 disables automatic backups
    backup_interval_hours: float = Field(default=24, gt=0)

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
    def backups_path(self) -> Path:
        return self.backup_dir or self.data_dir / "backups"

    def require_discord_token(self) -> str:
        if self.discord_token is None:
            raise SettingsError("DISCORD_TOKEN is missing: add it to the .env file "
                                "(see .env.example).")
        return self.discord_token.get_secret_value()

    def summary(self) -> list[tuple[str, str]]:
        """What the program will use, with the secrets hidden."""

        def secret(value: SecretStr | None) -> str:
            return "set" if value else "not set"

        return [
            ("DISCORD_TOKEN", secret(self.discord_token)),
            ("TELEGRAM_BOT_TOKEN", secret(self.telegram_bot_token)),
            ("DATA_DIR", str(self.data_dir)),
            ("database", str(self.db_path)),
            ("LEGACY_CONFIG", str(self.legacy_config)),
            ("BACKUP_DIR", str(self.backups_path)),
            ("BACKUP_KEEP", str(self.backup_keep)),
            ("BACKUP_INTERVAL_HOURS", f"{self.backup_interval_hours:g}"),
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
