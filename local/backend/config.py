"""Application settings loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Flat settings for IntakeAI local Phase 1."""

    model_config = SettingsConfigDict(
        env_file=str(_LOCAL_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    twilio_twiml_app_sid: str = ""

    # Ngrok
    ngrok_url: str = ""

    # Gemini
    gemini_api_key: str = ""

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "intakeai"
    postgres_user: str = "intakeai"
    postgres_password: str = "intakeai_dev"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "intakeai_dev"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # App
    app_port: int = 8000
    log_level: str = "INFO"
    environment: str = "development"

    @property
    def sqlalchemy_database_uri(self) -> str:
        """Build async SQLAlchemy DSN for Postgres."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
