from __future__ import annotations

from logging.config import fileConfig
from sqlalchemy import create_engine
from sqlalchemy import pool
from alembic import context

from database.config import DATABASE_URL
from database.base import Base
import database.models.asset
import database.models.finding
import database.models.host
import database.models.notification
import database.models.program
import database.models.program_settings
import database.models.scan_run
import database.models.scope
import database.models.subdomain
import database.models.technology
import database.models.tool_execution
import database.models.url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
