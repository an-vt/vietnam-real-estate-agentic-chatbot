"""Alembic environment for the local PostgreSQL database."""

import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import settings


url = URL.create(
    "postgresql+psycopg",
    username=settings.postgres_user,
    password=settings.postgres_password,
    host=settings.postgres_host,
    port=settings.postgres_port,
    database=settings.postgres_db,
)


if context.is_offline_mode():
    context.configure(url=url.render_as_string(hide_password=False), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
