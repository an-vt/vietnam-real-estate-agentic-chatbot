"""Backend settings. Python code reads environment variables only here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ENV = PROJECT_ROOT / "infra/local/.env"


@dataclass(frozen=True)
class Settings:
    app_log_level: str
    llm_model: str
    ollama_base_url: str
    llm_temperature: float
    kb_description: str
    sql_description: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str


def load_settings(env_file: Path = LOCAL_ENV) -> Settings:
    """Load local defaults without overriding exported or Compose variables."""
    load_dotenv(env_file, override=False)
    app_log_level = os.getenv("APP_LOG_LEVEL", "INFO").upper()
    if app_log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"Invalid APP_LOG_LEVEL: {app_log_level}")
    return Settings(
        app_log_level=app_log_level,
        llm_model=os.getenv("LLM_MODEL", "qwen2.5:3b"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11435"),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0")),
        kb_description=os.getenv(
            "KB_DESCRIPTION",
            "Vietnamese real estate listings in PostgreSQL with titles, locations, "
            "property types and descriptions. Use semantic search for descriptive "
            "or meaning-based property requests.",
        ),
        sql_description=os.getenv(
            "SQL_DESCRIPTION",
            "The same Vietnamese real estate listings in PostgreSQL, with exact "
            "fields such as price (millions of VND), area, province, property "
            "type, bedrooms and scraped date. Use SQL for exact filters, counts "
            "and calculations.",
        ),
        postgres_host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5433")),
        postgres_db=os.getenv("POSTGRES_DB", "vietnam_real_estate"),
        postgres_user=os.getenv("POSTGRES_USER", "postgres"),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )


settings = load_settings()
