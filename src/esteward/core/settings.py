"""Configuration contract: every value comes from the environment (`ESTEWARD_*`), validated once."""

from datetime import timedelta
from enum import StrEnum, auto
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvSettings(StrEnum):
    """Log rendering: flat text for a terminal, JSON for CI and machines."""

    DEV = auto()
    PROD = auto()


class Settings(BaseSettings):
    """The engine's settings: credentials, endpoints and limits."""

    model_config = SettingsConfigDict(env_prefix="ESTEWARD_", frozen=True)

    github_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ESTEWARD_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
    )
    env: EnvSettings = EnvSettings.DEV
    log_level: str = "INFO"
    fleet_dir: Path = Path("fleet")
    github_api: str = "https://api.github.com"
    pypi_url: str = "https://pypi.org"
    crates_api: str = "https://crates.io/api/v1"
    osv_api: str = "https://api.osv.dev/v1"
    user_agent: str = "esteward (+https://github.com/edamlabs/esteward)"
    http_timeout: timedelta = timedelta(seconds=30)
    concurrency: int = 8
    work_dir: Path = Path(".workspaces")
    git_remote: str = "https://github.com/{slug}.git"
    act_timeout: timedelta = timedelta(minutes=10)


settings = Settings()
