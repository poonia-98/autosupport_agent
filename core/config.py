from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "autosupport"
    version: str = "4.0.0"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    secret_key: str = Field(default="dev-secret-change-me-32-bytes-minimum")
    jwt_ttl_minutes: int = Field(default=480)

    admin_email: str = Field(default="admin@example.com")
    admin_password: str = Field(default="changeme123")

    # postgresql+asyncpg://user:pass@host:port/db
    database_url: str = Field(
        default="postgresql+asyncpg://autosupport:autosupport@localhost:5433/autosupport"
    )

    redis_url: str = Field(default="redis://localhost:6379/0")

    cors_origins: str = Field(default="*")
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")

    rate_limit_per_minute: int = Field(default=200)

    llm_enabled: bool = Field(default=False)
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_api_key: str = Field(default="")
    llm_model: str = Field(default="gpt-4o-mini")
    llm_timeout: int = Field(default=5)
    llm_cache_ttl: int = Field(default=3600)

    queue_max_jobs: int = Field(default=10)
    queue_job_timeout: int = Field(default=300)
    queue_max_tries: int = Field(default=3)

    sla_sweep_interval: int = Field(default=60)

    # asyncpg uses postgres:// directly (no driver prefix)
    @property
    def asyncpg_dsn(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"invalid log_level: {v}")
        return v

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, v: str) -> str:
        if v not in {"development", "staging", "production"}:
            raise ValueError(f"invalid environment: {v}")
        return v

    @field_validator("debug", mode="before")
    @classmethod
    def _coerce_debug(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return bool(v)

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.environment == "production":
            if self.secret_key == "dev-secret-change-me":
                raise ValueError(
                    "SECRET_KEY must be set in production. "
                    "Run: python -c \"import secrets; print(secrets.token_hex(32))\""
                )
            if self.admin_password == "changeme123":
                raise ValueError("ADMIN_PASSWORD must be changed before production deployment.")
            if self.cors_origins == "*":
                raise ValueError("CORS_ORIGINS must be explicitly set in production.")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
