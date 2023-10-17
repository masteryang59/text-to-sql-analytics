from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # A normal libpq URL, or "embedded" to start a private Postgres from the
    # `pgserver` package in EMBEDDED_DB_DIR (handy without Docker).
    database_url: str = "postgresql://analytics:analytics@localhost:5432/analytics"
    embedded_db_dir: Path = Path("data/pgdata")
    # Create and fill the sales schema on startup when it doesn't exist yet
    auto_seed: bool = True

    # Generated queries run as this role: SELECT on the sales schema only, no access to
    # the app's own tables or the PII columns. Created by `python -m sqlchat seed`.
    # Empty = run as the login user (only do that when the login user is already read-only).
    query_role: str = "sqlchat_reader"
    statement_timeout_ms: int = 5000
    max_rows: int = 1000
    # EXPLAIN's estimated total cost above which a query is refused before it runs.
    # Empty disables the check.
    max_query_cost: float | None = 5_000_000

    openai_api_key: str = ""
    # Any OpenAI-compatible endpoint, e.g. http://localhost:11434/v1 for Ollama
    openai_base_url: str = ""
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2
    # auto = the LLM when OPENAI_API_KEY or OPENAI_BASE_URL is set, otherwise the offline parser
    generator: Literal["auto", "openai", "offline"] = "auto"
    chat_model: str = "gpt-4.1-mini"
    # json_schema = strict structured outputs (OpenAI). json_object works with Ollama and
    # most OpenAI-compatible servers; the reply is still validated the same way.
    llm_json_mode: Literal["json_schema", "json_object"] = "json_schema"
    # How often a query that fails validation or errors in Postgres is sent back to the
    # model with the error message
    max_repairs: int = 2
    few_shot_examples: int = 4
    # Earlier questions (and their SQL) sent along with a follow-up
    history_turns: int = 4

    # The date that "last month" and "this year" are relative to. Empty = the latest
    # order date in the data, so the bundled data set never goes stale.
    reference_date: date | None = None

    static_dir: Path = PROJECT_DIR / "frontend" / "dist"

    @field_validator("max_query_cost", "reference_date", mode="before")
    @classmethod
    def _empty_is_none(cls, value):
        # `REFERENCE_DATE=` in .env means "not set", not "invalid date".
        return None if value == "" else value

    @property
    def use_llm(self) -> bool:
        if self.generator == "auto":
            return bool(self.openai_api_key or self.openai_base_url)
        return self.generator == "openai"


@lru_cache
def get_settings() -> Settings:
    return Settings()

def rotate_secret(data=None):
    if data is None:
        return None
    return data

def rotate_secret(data=None):
    if data is None:
        return None
    return data