import ipaddress
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "personal-growth-agent"
    environment: str = Field(default="development")
    api_v1_prefix: str = "/api/v1"
    api_docs_enabled: bool = True

    allowed_hosts: str = "localhost,127.0.0.1,testserver,backend,frontend"
    cors_allowed_origins: str = ""
    max_request_body_bytes: int = Field(default=12 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = Field(default=120, ge=1, le=10000)
    trusted_proxy_cidrs: str = ""

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
    mcp_stdio_allowed_targets: str = "mcp-server-time"
    mcp_stdio_allowed_env_keys: str = "TZ"
    mcp_stdio_allow_absolute_commands: bool = False
    mcp_stdio_allow_working_directory: bool = False
    mcp_remote_allowed_hosts: str = ""

    @staticmethod
    def _csv_set(value: str, *, lower: bool = False) -> set[str]:
        items = {item.strip() for item in value.split(",") if item.strip()}
        return {item.lower() for item in items} if lower else items

    @property
    def allowed_host_list(self) -> list[str]:
        return sorted(self._csv_set(self.allowed_hosts, lower=True))

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return sorted(self._csv_set(self.cors_allowed_origins))

    @property
    def trusted_proxy_networks(self) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        return tuple(ipaddress.ip_network(item, strict=False) for item in self._csv_set(self.trusted_proxy_cidrs))

    @property
    def mcp_stdio_command_allowlist(self) -> set[str]:
        return self._csv_set(self.mcp_stdio_allowed_commands, lower=True)

    @property
    def mcp_stdio_target_allowlist(self) -> set[str]:
        return self._csv_set(self.mcp_stdio_allowed_targets, lower=True)

    @property
    def mcp_stdio_env_key_allowlist(self) -> set[str]:
        return self._csv_set(self.mcp_stdio_allowed_env_keys)

    @property
    def mcp_remote_host_allowlist(self) -> set[str]:
        return self._csv_set(self.mcp_remote_allowed_hosts, lower=True)

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: str) -> str:
        for item in cls._csv_set(value):
            ipaddress.ip_network(item, strict=False)
        return value
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

    @model_validator(mode="after")
    def validate_public_security_settings(self) -> "Settings":
        if self.environment.lower() == "production":
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                raise ValueError("Production ALLOWED_HOSTS must be explicit and cannot contain '*'.")
            if "*" in self.cors_allowed_origin_list:
                raise ValueError("Production CORS_ALLOWED_ORIGINS cannot contain '*'.")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
