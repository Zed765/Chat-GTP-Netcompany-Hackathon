from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MISSING_KEY = "OPENAI_API_KEY is required: copy .env.example to .env and set it there."


class MissingKeyError(RuntimeError):
    """Not a `ValueError`, which pydantic would wrap in a validation error of its own."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASPIDA_", extra="ignore")

    database_url: str = "postgresql+asyncpg://aspida:aspida@postgres:5432/aspida"
    redis_url: str = "redis://redis:6379/0"
    readonly_db_password: SecretStr | None = Field(
        default=None, description="For the analyst chat's login; generated if not set"
    )

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    model_inline: str = "gpt-6-luna"
    model_offline: str = "gpt-5-mini"
    model_embedding: str = "text-embedding-3-large"
    inline_timeout_s: float = 2.0

    seed_demo_data: bool = Field(default=False, validation_alias="SEED_DEMO_DATA")
    keys_dir: Path = Path("/var/lib/aspida/keys")
    defaults_dir: Path = Path("/srv/defaults")
    policies_dir: Path = Path("/srv/policies")

    mock_upstream_url: str = "http://mock-upstream:9100"
    crm_url: str = "http://mcp-crm:9001"
    mail_url: str = "http://mcp-mail:9002"
    web_tool_url: str = "http://mcp-web:9003"

    vault_ttl_hours: int = 24
    retention_days: int = 90
    session_hours: int = 12
    internal_mail_domain: str = "aspida-demo.example"
    trusted_mcp_servers: tuple[str, ...] = ("crm",)
    log_inbox_dir: Path = Path("/var/lib/aspida/inbox")
    site_descriptions_path: Path = Path("/srv/seeder/site_descriptions.json")

    @model_validator(mode="after")
    def _key_is_required(self) -> Self:
        key = self.openai_api_key
        if key is None or not key.get_secret_value().strip():
            raise MissingKeyError(MISSING_KEY)
        return self

    @property
    def api_key(self) -> str:
        assert self.openai_api_key is not None
        return self.openai_api_key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """This process's settings. A missing key ends it with one line, not a traceback."""
    try:
        return Settings()
    except MissingKeyError as error:
        raise SystemExit(str(error)) from None
