"""Create the HNSW cosine index after embeddings are loaded.

Revision ID: 20261005_02
Revises: 20261005_01
"""

from alembic import op


revision = "20261005_02"
down_revision = "20261005_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS documents_embedding_hnsw_cosine_idx
        ON vietnamese_real_estate.documents
        USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX vietnamese_real_estate.documents_embedding_hnsw_cosine_idx")
