from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
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
