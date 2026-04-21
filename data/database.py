"""
Database engine and session management.

Uses SQLite for development. To switch to Postgres, replace DATABASE_URL with:
    postgresql+psycopg2://user:password@host:port/dbname
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./steels.db")

# SQLite-specific: enforce foreign keys (disabled by default in SQLite)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,  # Set to True to log all SQL — useful for debugging
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def init_db() -> None:
    """Create all tables. Safe to call multiple times — won't drop existing tables."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for a database session with automatic rollback on error.

    Usage:
        with get_session() as session:
            session.add(some_object)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
