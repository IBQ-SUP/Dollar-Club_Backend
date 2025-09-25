from functools import lru_cache
from typing import List

from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        case_sensitive=False,
        extra='ignore',
    )

    PROJECT_NAME: str = "Trading Strategy Hub API"
    ENV: str = "development"

    SECRET_KEY: str = Field(default="change-me", min_length=16)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALGORITHM: str = "HS256"

    DATABASE_URL: str
    SYNC_DATABASE_URL: str

    REDIS_URL: AnyUrl
    CELERY_BROKER_URL: AnyUrl | None = None
    CELERY_RESULT_BACKEND: AnyUrl | None = None

    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]

    # Google OAuth
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: str | None = None
    GOOGLE_REDIRECT_URI: str | None = None
    FRONTEND_URL: str = "http://localhost:8080"

    @property
    def celery_broker(self) -> str:
        return str(self.CELERY_BROKER_URL or self.REDIS_URL)

    @property
    def celery_backend(self) -> str:
        return str(self.CELERY_RESULT_BACKEND or self.REDIS_URL)

    @property
    def async_database_url(self) -> str:
        """Normalize to an async SQLAlchemy URL for Postgres."""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql+psycopg://"):
            return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def sync_database_url(self) -> str:
        """Normalize to a sync SQLAlchemy URL for Postgres."""
        url = self.SYNC_DATABASE_URL
        if url.startswith("postgresql+psycopg://"):
            return url
        if url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

