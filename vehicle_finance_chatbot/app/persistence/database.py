from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {},
)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def get_engine():
    return _engine


def get_session() -> Session:
    return _SessionLocal()


def init_db() -> None:
    # Import models so they register with the Base metadata.
    from app.persistence import models  # noqa: F401

    Base.metadata.create_all(bind=_engine)
