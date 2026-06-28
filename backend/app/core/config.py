from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "personal-growth-agent"
    environment: str = Field(default="development")
    api_v1_prefix: str = "/api/v1"

    database_url: str | None = None
    database_echo: bool = False

    dashscope_api_key: str | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    embedding_model: str = "text-embedding-v3"
    embedding_model_version: str = "v3-1024-dense"
    embedding_dimension: int = Field(default=1024, ge=1)
    embedding_timeout_seconds: float = Field(default=30, ge=1, le=300)
    embedding_max_retries: int = Field(default=2, ge=0, le=5)
    embedding_batch_size: int = Field(default=10, ge=1, le=10)
    embedding_max_concurrency: int = Field(default=4, ge=1, le=16)

    rag_dense_limit: int = Field(default=12, ge=1, le=100)
    rag_sparse_limit: int = Field(default=12, ge=1, le=100)
    rag_fused_limit: int = Field(default=20, ge=3, le=100)
    rag_final_limit: int = Field(default=3, ge=1, le=3)
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_min_dense_score: float = Field(default=0.35, ge=-1, le=1)

    deepseek_api_key: str | None = None
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = Field(default=60, ge=1, le=300)
    conversation_history_limit: int = Field(default=20, ge=1, le=100)
    mcp_timeout_seconds: float = Field(default=15, ge=1, le=120)
    mcp_stdio_allowed_commands: str = "uvx"

    @property
    def mcp_stdio_command_allowlist(self) -> set[str]:
        return {item.strip().lower() for item in self.mcp_stdio_allowed_commands.split(",") if item.strip()}

    @field_validator("database_url")
    @classmethod
    def normalize_blank_database_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value

    @field_validator("deepseek_api_key", "dashscope_api_key")
    @classmethod
    def normalize_blank_api_key(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value.strip()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
