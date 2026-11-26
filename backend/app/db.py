from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def normalise_url(url: str) -> str:
    """Hosted Postgres (Render and others) hands out postgres:// or
    postgresql:// URLs, for which SQLAlchemy would load psycopg2. This app
    ships psycopg 3, so name that driver explicitly."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _make_engine(url: str):
    url = normalise_url(url)
    kw = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"check_same_thread": False}
    eng = create_engine(url, **kw)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):  # enforce FKs in SQLite too
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    return eng


_s = get_settings()
engine = _make_engine(_s.database_url)
read_engine = _make_engine(_s.replica_database_url) if _s.replica_database_url else engine
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
ReadSessionLocal = sessionmaker(bind=read_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_read_db() -> Iterator[Session]:
    """Read replica session for reports and exports, where a second of lag is fine."""
    db = ReadSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny forward-only migration: add columns that exist in the models but
    not in an older database (e.g. a Postgres volume created by an earlier
    version). New columns always carry a server default or are nullable."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'
                if col.server_default is not None:
                    default = col.server_default.arg
                    if str(col.type).upper().startswith("BOOLEAN") and engine.dialect.name == "postgresql":
                        default = "true" if str(default) == "1" else "false"
                    ddl += f" DEFAULT '{default}'" if not str(default).isdigit() else f" DEFAULT {default}"
                    ddl += " NOT NULL" if not col.nullable else ""
                conn.execute(text(ddl))
            if table.name == "user_account" and "password_hash" in have and engine.dialect.name == "postgresql":
                conn.execute(text("ALTER TABLE user_account ALTER COLUMN password_hash DROP NOT NULL"))
