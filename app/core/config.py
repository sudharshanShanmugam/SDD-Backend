"""Application configuration using Pydantic Settings."""
from functools import lru_cache
from typing import Any, Optional
from pydantic import AnyHttpUrl, EmailStr, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "SDD Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", pattern="^(development|staging|production|test)$")
    DEBUG: bool = False
    SECRET_KEY: str = Field(min_length=32)
    API_V1_PREFIX: str = "/api/v1"

    ALLOWED_HOSTS: list[str] = ["localhost", "127.0.0.1"]
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:4173",
        "https://sdd-frontend.onrender.com",
    ]

    @field_validator("ALLOWED_HOSTS", "ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_list_from_string(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [item.strip() for item in v.split(",")]
        return v

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://sdd_user:sdd_password@localhost:5432/sdd_platform"
    DATABASE_POOL_SIZE: int = Field(default=20, ge=1, le=100)
    DATABASE_MAX_OVERFLOW: int = Field(default=40, ge=0, le=200)
    DATABASE_POOL_TIMEOUT: int = Field(default=30, ge=5, le=120)
    DATABASE_POOL_RECYCLE: int = 3600
    DATABASE_ECHO: bool = False

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL for Alembic migrations."""
        return self.DATABASE_URL.replace("+asyncpg", "+psycopg2").replace(
            "asyncpg", "psycopg2"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 50
    CACHE_TTL_SECONDS: int = 3600

    # ── JWT ───────────────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=5, le=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=30, ge=1, le=365)
    JWT_ISSUER: str = "sdd-platform"
    JWT_AUDIENCE: str = "sdd-platform-api"

    # ── Superuser ─────────────────────────────────────────────────────────────
    FIRST_SUPERUSER_EMAIL: EmailStr = "admin@sdd-platform.com"
    FIRST_SUPERUSER_PASSWORD: str = Field(default="Pass@1234", min_length=8)
    FIRST_SUPERUSER_NAME: str = "Platform Admin"

    # ── DeepInfra (OpenAI-compatible) ─────────────────────────────────────────
    DEEPINFRA_API_KEY: str = "sk-placeholder"
    DEEPINFRA_BASE_URL: str = "https://api.deepinfra.com/v1/openai"
    LLM_MODEL: str = "openai/gpt-oss-120b-Turbo"
    EMBED_MODEL: str = "BAAI/bge-large-en-v1.5"
    ENTITY_MODEL: str = "meta-llama/Meta-Llama-3.1-8B-Instruct"
    OPENAI_MAX_TOKENS: int = Field(default=4096, ge=256, le=128000)
    OPENAI_TEMPERATURE: float = Field(default=0.1, ge=0.0, le=2.0)
    OPENAI_REQUEST_TIMEOUT: int = 120

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    CHROMA_COLLECTION_NAME: str = "sdd_documents"
    CHROMA_VECTOR_SIZE: int = 1024  # BAAI/bge-large-en-v1.5

    # ── AWS S3 ────────────────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "sdd-platform-documents"
    S3_ENDPOINT_URL: Optional[str] = None

    # ── Celery ────────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"

    # ── Frontend ──────────────────────────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:3000"

    # ── Email ─────────────────────────────────────────────────────────────────
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "noreply@sdd-platform.com"
    SMTP_PASSWORD: Optional[str] = None
    SMTP_TLS: bool = True
    EMAIL_FROM_NAME: str = "SDD Platform"

    # ── Sentry ────────────────────────────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.1, ge=0.0, le=1.0)

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"
    OTEL_SERVICE_NAME: str = "sdd-platform-backend"
    OTEL_ENABLED: bool = False

    # ── Rate Limiting ─────────────────────────────────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_PER_HOUR: int = 1000
    RATE_LIMIT_PER_DAY: int = 10000
    RATE_LIMIT_ENABLED: bool = True

    # ── File Upload ───────────────────────────────────────────────────────────
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_FILE_TYPES: list[str] = ["pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "md"]

    @field_validator("ALLOWED_FILE_TYPES", mode="before")
    @classmethod
    def parse_file_types(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [item.strip() for item in v.split(",")]
        return v

    # ── Pagination ────────────────────────────────────────────────────────────
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # ── Computed properties ───────────────────────────────────────────────────
    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "test"

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        # Always ensure the production frontend origin is allowed, even if
        # ALLOWED_ORIGINS is overridden by an env var with only localhost values.
        _prod_frontend = "https://sdd-frontend.onrender.com"
        if _prod_frontend not in self.ALLOWED_ORIGINS:
            self.ALLOWED_ORIGINS = list(self.ALLOWED_ORIGINS) + [_prod_frontend]

        if self.is_production:
            if "placeholder" in self.DEEPINFRA_API_KEY.lower():
                raise ValueError("DEEPINFRA_API_KEY must be set in production")
            if len(self.SECRET_KEY) < 64:
                raise ValueError("SECRET_KEY must be at least 64 characters in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()


settings = get_settings()
