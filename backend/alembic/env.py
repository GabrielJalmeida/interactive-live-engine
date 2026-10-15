"""Alembic environment using the central database URL and SQLAlchemy metadata."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from backend.app.config import Settings
from backend.app.persistence.database import create_database_engine, resolve_database_url
from backend.app.persistence.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
target_metadata = Base.metadata
resolved_url = resolve_database_url(settings.database_url)
config.set_main_option(
    "sqlalchemy.url",
    resolved_url.render_as_string(hide_password=False).replace("%", "%%"),
)


def run_migrations_offline() -> None:
    """Run migrations without opening a DBAPI connection."""

    context.configure(
        url=resolved_url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using the configured SQLAlchemy engine."""

    connectable = create_database_engine(settings.database_url, echo=False)
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                compare_server_default=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
