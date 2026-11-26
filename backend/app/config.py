from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"                    # "production" turns on the strict checks below
    database_url: str = "sqlite:///./rosteros.db"
    replica_database_url: str | None = None     # read replica; falls back to primary
    redis_url: str | None = None                # set -> solve jobs go through RQ workers
    cors_origins: str = "http://localhost:5173"

    # ---- auth & sessions --------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    session_ttl_minutes: int = 8 * 60           # absolute session lifetime
    cookie_secure: bool | None = None           # None: secure cookies whenever env=production
    # Bootstrap credentials for the seeded accounts. Never committed: set them
    # as secrets (Render dashboard, .env). If unset in development a random
    # password is generated and printed once; in production the admin password
    # is required and demo accounts stay disabled until an admin resets them.
    admin_password: str | None = None
    demo_password: str | None = None

    # ---- password policy & brute-force protection --------------------------
    password_min_length: int = 12
    login_max_failures: int = 5                 # per account, then locked
    lockout_minutes: int = 15
    login_rate_per_minute: int = 20             # per client IP
    argon2_time_cost: int = 2                   # OWASP 2024 minimum for Argon2id:
    argon2_memory_kib: int = 19456              # m=19 MiB, t=2, p=1
    argon2_parallelism: int = 1

    # ---- Google Sheets / Calendar ------------------------------------------
    # "embedded" serves the mock in-process, "http" calls SHEETS_BASE_URL
    # (sheets-mock container or real Google).
    sheets_mode: str = "embedded"
    sheets_base_url: str = "http://sheets-mock:8100"
    google_access_token: str | None = None
    rules_spreadsheet_id: str = "rules-and-coverage"
    dashboard_spreadsheet_id: str = "roster-dashboards"
    holiday_calendar_ids: str = "IN-NATIONAL,IN-WB,IN-MH"

    # ---- AI assistant -------------------------------------------------------
    anthropic_api_key: str | None = None
    assistant_model: str = "claude-opus-5-5"
    assistant_rate_per_10min: int = 30          # per user, bounds cost and abuse

    # ---- solver -------------------------------------------------------------
    solver_time_limit_s: float = 30.0
    solver_workers: int = 8

    @property
    def production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def secure_cookies(self) -> bool:
        return self.production if self.cookie_secure is None else self.cookie_secure


@lru_cache
def get_settings() -> Settings:
    return Settings()
