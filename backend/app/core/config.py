from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "personal-growth-agent"
    environment: str = Field(default="development")
    api_v1_prefix: str = "/api/v1"

    database_url: str | None = None
    database_echo: bool = False
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, ge=1)

    @field_validator("database_url")
    @classmethod
    def normalize_blank_database_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
