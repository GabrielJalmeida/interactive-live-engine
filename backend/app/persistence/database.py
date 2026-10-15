"""SQLAlchemy engine/session construction and predictable SQLite path handling."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_database_url(database_url: str) -> URL:
    """Resolve relative SQLite file paths against the repository root, not the CWD."""

    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        return url
    if url.database == ":memory:" or url.database.startswith("file:"):
        return url

    database_path = Path(url.database)
    if not database_path.is_absolute():
        database_path = (PROJECT_ROOT / database_path).resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return url.set(database=str(database_path))


def create_database_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create a synchronous SQLAlchemy engine for short, thread-isolated DB operations."""

    url = resolve_database_url(database_url)
    connect_args: dict[str, object] = {}
    if url.get_backend_name() == "sqlite":
        connect_args = {"check_same_thread": False, "timeout": 30}

    engine = create_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if url.get_backend_name() == "sqlite":

        @event.listens_for(engine, "connect")
        def _configure_sqlite_connection(
            dbapi_connection: object, _connection_record: object
        ) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory; never share Session instances across requests/tasks."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
