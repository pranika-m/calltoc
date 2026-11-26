"""Application settings loaded from environment variables / .env."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed configuration for the AI Sales Voice Agent."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM provider (OpenAI-compatible)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # Voice providers
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"

    # Database — SQLite by default so the app runs with zero external services.
    # For production set DATABASE_URL to a PostgreSQL DSN.
    database_url: str = f"sqlite:///{(ROOT_DIR / 'data' / 'app.db').as_posix()}"

    # Seed realistic demo records on first boot (development only).
    seed_demo_data: bool = True

    # Lead scoring thresholds
    lead_hot_threshold: int = 70
    lead_warm_threshold: int = 40

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    default_language: str = "en"
    public_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    auth_required: bool = False
    auth_secret: str = "change-me-in-production"

    # Telephony (Twilio)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""


settings = Settings()
