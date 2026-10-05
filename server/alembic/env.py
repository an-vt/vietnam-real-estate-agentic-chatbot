"""Alembic environment for the local PostgreSQL database."""

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.script.ingest_csv import local_env


local_env()
url = URL.create(
    "postgresql+psycopg",
    username=os.getenv("POSTGRES_USER", "postgres"),
    password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
    port=int(os.getenv("POSTGRES_PORT", "5433")),
    database=os.getenv("POSTGRES_DB", "vietnam_real_estate"),
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
