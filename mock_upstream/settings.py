from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MISSING_KEY = "OPENAI_API_KEY is required: copy .env.example to .env and set it there."


class MissingKeyError(RuntimeError):
    """Not a `ValueError`, which pydantic would wrap in a validation error of its own."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(default=None, validation_alias="OPENAI_BASE_URL")
    model: str = Field(default="gpt-6-luna", validation_alias="ASPIDA_MODEL_INLINE")

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
