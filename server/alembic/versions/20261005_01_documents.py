"""Create the pgvector documents table.

Revision ID: 20261005_01
Revises:
"""

from alembic import op


revision = "20261005_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS vietnamese_real_estate")
    op.execute("""
        CREATE TABLE IF NOT EXISTS vietnamese_real_estate.documents (
            listing_id bigint PRIMARY KEY,
            title text NOT NULL,
            price numeric,
            area numeric,
            location text,
            property_type text,
            width numeric,
            length numeric,
            bedrooms integer,
            bathrooms integer,
            floors integer,
            position text,
            direction text,
            alley_width numeric,
            road_type text,
            description text,
            latitude double precision,
            longitude double precision,
            vip_account boolean,
            agent_role text,
            agent_name text,
            agent_listing_count integer,
            province text,
            scraped_at timestamp NOT NULL,
            embedding vector(1024) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE vietnamese_real_estate.documents")
    op.execute("DROP SCHEMA vietnamese_real_estate")
