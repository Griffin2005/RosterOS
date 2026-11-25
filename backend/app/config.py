from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./rosteros.db"
    replica_database_url: str | None = None     # read replica; falls back to primary
    redis_url: str | None = None                # set -> solve jobs go through RQ workers
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 15 * 8
    demo_password: str = "roster@123"
    cors_origins: str = "http://localhost:5173"

    # Google Sheets / Calendar. "embedded" serves the mock in-process,
    # "http" calls SHEETS_BASE_URL (sheets-mock container or real Google).
    sheets_mode: str = "embedded"
    sheets_base_url: str = "http://sheets-mock:8100"
    google_access_token: str | None = None
    rules_spreadsheet_id: str = "rules-and-coverage"
    dashboard_spreadsheet_id: str = "roster-dashboards"
    holiday_calendar_ids: str = "IN-NATIONAL,IN-WB,IN-MH"

    anthropic_api_key: str | None = None
    assistant_model: str = "claude-opus-5-5"

    solver_time_limit_s: float = 30.0
    solver_workers: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
