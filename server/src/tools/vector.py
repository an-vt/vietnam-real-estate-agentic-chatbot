"""Semantic search over the existing PostgreSQL listing embeddings."""

from psycopg.rows import dict_row
from langchain_core.documents import Document

from ..db import connect_db
from ..embeddings import DIMENSIONS, get_embedder


TABLE = "vietnamese_real_estate.documents"
LISTING_FIELDS = (
    ("Title", "title"),
    ("Property type", "property_type"),
    ("Location", "location"),
    ("Price (million VND)", "price"),
    ("Area (m²)", "area"),
    ("Bedrooms", "bedrooms"),
    ("Description", "description"),
)
def search_listings(question: str, k: int) -> list[Document]:
    """Return the nearest listing rows as documents for grading."""
    vector = get_embedder().embed_query(question)
    if len(vector) != DIMENSIONS:
        raise ValueError(f"Expected {DIMENSIONS} embedding dimensions, got {len(vector)}")
    query_vector = "[" + ",".join(str(float(value)) for value in vector) + "]"
    with connect_db(read_only=True) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT listing_id, title, price, area, location, property_type, "
                f"bedrooms, description FROM {TABLE} "
                f"ORDER BY embedding <=> %s::vector LIMIT %s",
                (query_vector, k),
            )
            rows = cursor.fetchall()

    return [
        Document(
            page_content="\n".join(
                f"{label}: {row[field]}"
                for label, field in LISTING_FIELDS
                if row[field] is not None and row[field] != ""
            ),
            metadata={"source": "listing", **row},
        )
        for row in rows
    ]
