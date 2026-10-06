"""Create a new PostgreSQL connection for each caller."""

import psycopg

from .config import settings


def connect_db(*, read_only: bool):
    kwargs = {
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "dbname": settings.postgres_db,
        "user": settings.postgres_user,
        "password": settings.postgres_password,
    }
    if read_only:
        kwargs.update(
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        )
    connection = psycopg.connect(**kwargs)
    if read_only:
        connection.read_only = True
    return connection
