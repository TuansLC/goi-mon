"""Application configuration via pydantic-settings.

Reads environment variables (optionally from a local .env file) and exposes a
cached ``get_settings()`` accessor so the parsed settings object is created once
per process.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from the environment.

    Attributes map directly to environment variables (case-insensitive).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core infrastructure (R10.1, R10.3) ---
    database_url: str = "postgresql+asyncpg://qorder:qorder@localhost:5432/qorder"
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth / JWT (R12) ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 12 * 60  # 12h shifts for staff

    # --- WebSocket ticket (design: one-shot ticket) ---
    ws_ticket_ttl_seconds: int = 30

    # --- Scheduler (R13, R9) ---
    abandon_sweep_interval_minutes: int = 5
    scheduler_lock_ttl_seconds: int = 300

    # --- Google Sheets reporting (R9) ---
    google_service_account_json: str | None = None  # path to SA key JSON

    # --- Printing (R6.3, R6.4) ---
    printer_type: str = "none"  # "usb", "network", or "none"
    printer_ip: str | None = None  # IP for network printers
    printer_port: int = 9100  # default ESC/POS network port
    bill_pdf_output_dir: str = "/tmp/qorder_bills"  # PDF fallback directory

    # --- App meta ---
    app_name: str = "QOrder API"
    base_url: str = "http://localhost:3000"
    debug: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide cached ``Settings`` instance."""

    return Settings()
