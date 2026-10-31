"""
Brightloop Software Subscription Management System
====================================================
Central configuration pulled from environment variables with sane dev defaults.

Why Pydantic Settings instead of raw os.environ:
  - Type coercion is automatic (str → int, comma-separated → list).
  - `.env` file support means devs never commit secrets.
  - IDE autocomplete on `settings.DATABASE_URL` beats `os.getenv("DATABASE_URL")`.
"""

from typing import List, Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Database ---
    # Default to SQLite for seamless zero-config local runs; overridden by env in Docker (PostgreSQL)
    DATABASE_URL: str = "sqlite+aiosqlite:///./brightloop.db"
    DATABASE_URL_SYNC: str = "sqlite:///./brightloop.db"

    # --- JWT Auth ---
    SECRET_KEY: str = "brightloop-dev-secret-change-in-prod-2026"
    JWT_ALGORITHM: str = "HS256"
    # Why 480 minutes (8 hours): matches a typical business day so staff don't
    # get logged out mid-shift, but tokens still rotate daily.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    RESET_TOKEN_EXPIRE_MINUTES: int = 15

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:4321,http://127.0.0.1:4321,http://localhost:3000,http://127.0.0.1:3000,http://localhost:4322,http://127.0.0.1:4322"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    # --- Billing Engine ---
    BILLING_BATCH_SIZE: int = 500
    BILLING_CRON_HOUR: int = 0
    BILLING_CRON_MINUTE: int = 5

    # --- DataStax Astra DB Telemetry ---
    # Optional credentials for continuous cloud event telemetry/logging.
    # When not set, the adapter runs locally in zero-config offline mode.
    ASTRA_DB_API_ENDPOINT: Optional[str] = None
    ASTRA_DB_APPLICATION_TOKEN: Optional[str] = None
    ASTRA_DB_KEYSPACE: str = "brightloop"
    ASTRA_DB_COLLECTION: str = "telemetry_events"

    # --- App Meta ---
    APP_NAME: str = "Brightloop Subscription Manager"
    APP_VERSION: str = "1.0.0"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
