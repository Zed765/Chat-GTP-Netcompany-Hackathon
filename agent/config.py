from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gateway_url: str = Field(default="http://gateway:8000", validation_alias="GATEWAY_URL")
    max_steps: int = Field(default=8, description="Model calls allowed for one user message")
    request_timeout_s: float = 120.0
