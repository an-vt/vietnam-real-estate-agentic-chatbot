"""Import the latest scrape of each listing into PostgreSQL with embeddings."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..db import connect_db
from ..embeddings import DIMENSIONS, get_embedder


TABLE = "vietnamese_real_estate.documents"
MAX_EMBEDDING_INPUTS = 2048
MAX_EMBEDDING_INPUT_TOKENS = 8192
MAX_EMBEDDING_BATCH_TOKENS = 300_000
COLUMNS = (
    "listing_id", "title", "price", "area", "location", "property_type",
    "width", "length", "bedrooms", "bathrooms", "floors", "position",
    "direction", "alley_width", "road_type", "description", "latitude",
    "longitude", "vip_account", "agent_role", "agent_name",
    "agent_listing_count", "province", "scraped_at", "embedding",
)


def parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None


def parse_id(value: str) -> int | None:
    try:
        number = float(value)
        if math.isfinite(number) and number.is_integer() and number > 0:
            return int(number)
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def latest_listings(
    path: Path,
    *,
    max_records: int | None = None,
) -> tuple[dict[int, dict[str, str]], Counter[str]]:
    if max_records is not None and max_records < 1:
        raise ValueError("max_records must be at least 1")
    latest: dict[int, dict[str, str]] = {}
    report: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Listing ID", "Scraped At", "Title"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV is missing columns: {sorted(required - set(reader.fieldnames or []))}")
        for row in reader:
            if max_records is not None and report["csv_rows"] >= max_records:
                break
            report["csv_rows"] += 1
            listing_id = parse_id(row.get("Listing ID", ""))
            scraped_at = parse_timestamp(row.get("Scraped At", ""))
            if listing_id is None or scraped_at is None:
                report["invalid_required_rows"] += 1
                continue
            previous = latest.get(listing_id)
            if previous is None or scraped_at >= parse_timestamp(previous["Scraped At"]):
                latest[listing_id] = row
    report["unique_listings"] = len(latest)
    report["duplicate_rows"] = report["csv_rows"] - report["invalid_required_rows"] - len(latest)
    return latest, report


def optional_number(row: dict[str, str], field: str, report: Counter[str], *, integer: bool = False,
                    minimum: float | None = None, maximum: float | None = None) -> int | float | None:
    value = (row.get(field) or "").strip()
    if not value:
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or (integer and not number.is_integer()):
            raise ValueError
        if (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
            raise ValueError
        return int(number) if integer else number
    except (ValueError, OverflowError):
        report[f"invalid_{field.lower().replace(' ', '_')}"] += 1
        return None


def optional_bool(row: dict[str, str], field: str, report: Counter[str]) -> bool | None:
    value = (row.get(field) or "").strip().lower()
    if not value:
        return None
    if value in {"true", "1", "yes"}:
        return True
    if value in {"false", "0", "no"}:
        return False
    report[f"invalid_{field.lower().replace(' ', '_')}"] += 1
    return None


def optional_text(row: dict[str, str], field: str) -> str | None:
    return (row.get(field) or "").strip() or None


def parse_row(row: dict[str, str], report: Counter[str]) -> dict[str, Any]:
    """Convert one selected CSV row to the document columns except embedding."""
    return {
        "listing_id": parse_id(row["Listing ID"]),
        "title": optional_text(row, "Title") or "",
        "price": optional_number(row, "Price", report, minimum=0),  # millions of VND
        "area": optional_number(row, "Area", report, minimum=0),
        "location": optional_text(row, "Location"),
        "property_type": optional_text(row, "Property Type"),
        "width": optional_number(row, "Width", report, minimum=0),
        "length": optional_number(row, "Length", report, minimum=0),
        "bedrooms": optional_number(row, "Bedrooms", report, integer=True, minimum=0),
        "bathrooms": optional_number(row, "Bathrooms", report, integer=True, minimum=0),
        "floors": optional_number(row, "Floors", report, integer=True, minimum=0),
        "position": optional_text(row, "Position"),
        "direction": optional_text(row, "Direction"),
        "alley_width": optional_number(row, "Alley Width", report, minimum=0),
        "road_type": optional_text(row, "Road Type"),
        "description": optional_text(row, "Description"),
        "latitude": optional_number(row, "Latitude", report, minimum=-90, maximum=90),
        "longitude": optional_number(row, "Longitude", report, minimum=-180, maximum=180),
        "vip_account": optional_bool(row, "VIP Account", report),
        "agent_role": optional_text(row, "Agent Role"),
        "agent_name": optional_text(row, "Agent Name"),
        "agent_listing_count": optional_number(row, "Agent Listing Count", report, integer=True, minimum=0),
        "province": optional_text(row, "Province"),
        "scraped_at": parse_timestamp(row["Scraped At"]),
    }


def embedding_text(document: dict[str, Any]) -> str:
    fields = (
        ("Tiêu đề", "title", ""),
        ("Giá", "price", " triệu VND"),
        ("Loại bất động sản", "property_type", ""),
        ("Địa điểm", "location", ""),
        ("Mô tả", "description", ""),
    )
    return "\n".join(
        f"{label}: {document[key]}{suffix}"
        for label, key, suffix in fields
        if document[key] is not None and document[key] != ""
    )


def approximate_text_length(row: dict[str, str]) -> int:
    """Group similarly sized inputs to reduce padding during batch encoding."""
    return sum(len(row.get(field) or "") for field in
               ("Title", "Price", "Property Type", "Location", "Description"))


def needs_import(scraped_at: datetime, stored_at: datetime | None, force: bool) -> bool:
    return force or stored_at is None or scraped_at > stored_at


def batches(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def embedding_batches(
    items: list[tuple[dict[str, Any], str]],
    size: int,
    *,
    encoder: Any | None = None,
) -> Iterable[list[tuple[dict[str, Any], str]]]:
    """Yield embedding inputs within OpenAI's item and token limits."""
    if encoder is None:
        import tiktoken

        encoder = tiktoken.get_encoding("cl100k_base")
    size = min(size, MAX_EMBEDDING_INPUTS)
    batch: list[tuple[dict[str, Any], str]] = []
    token_count = 0
    for document, text in items:
        tokens = encoder.encode(text)
        if len(tokens) > MAX_EMBEDDING_INPUT_TOKENS:
            text = encoder.decode(tokens[:MAX_EMBEDDING_INPUT_TOKENS])
            tokens = tokens[:MAX_EMBEDDING_INPUT_TOKENS]
        item_tokens = len(tokens)
        if batch and (
            len(batch) >= size
            or token_count + item_tokens > MAX_EMBEDDING_BATCH_TOKENS
        ):
            yield batch
            batch = []
            token_count = 0
        batch.append((document, text))
        token_count += item_tokens
    if batch:
        yield batch


def migrate(revision: str) -> None:
    """Apply the schema revision before import and the index revision after it."""
    from alembic import command
    from alembic.config import Config

    server_dir = Path(__file__).resolve().parents[2]
    config = Config(str(server_dir / "alembic.ini"))
    command.upgrade(config, revision)


def upsert_sql(force: bool) -> str:
    names = ", ".join(COLUMNS)
    placeholders = ", ".join(["%s"] * len(COLUMNS))
    updates = ", ".join(f"{name} = EXCLUDED.{name}" for name in COLUMNS if name != "listing_id")
    condition = "TRUE" if force else f"EXCLUDED.scraped_at > {TABLE}.scraped_at"
    return (f"INSERT INTO {TABLE} ({names}) VALUES ({placeholders}) "
            f"ON CONFLICT (listing_id) DO UPDATE SET {updates} WHERE {condition}")


def import_csv(
    path: Path,
    batch_size: int,
    force: bool,
    max_records: int | None = None,
) -> Counter[str]:
    migrate("20261005_01")
    latest, report = latest_listings(path, max_records=max_records)
    print(json.dumps({"status": "selected", **dict(report)}, ensure_ascii=False), flush=True)
    connection = connect_db(read_only=False)
    embedder = None
    started_at = time.monotonic()
    try:
        sql = upsert_sql(force)
        for batch_number, raw_batch in enumerate(
            batches(sorted(latest.values(), key=approximate_text_length), batch_size),
            start=1,
        ):
            ids = [parse_id(row["Listing ID"]) for row in raw_batch]
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT listing_id, scraped_at FROM {TABLE} WHERE listing_id = ANY(%s)", (ids,))
                stored = dict(cursor.fetchall())
            pending = [row for row, listing_id in zip(raw_batch, ids)
                       if needs_import(parse_timestamp(row["Scraped At"]), stored.get(listing_id), force)]
            report["skipped_current"] += len(raw_batch) - len(pending)
            if not pending:
                continue
            docs = [parse_row(row, report) for row in pending]
            docs_with_text = [(doc, embedding_text(doc)) for doc in docs]
            report["skipped_empty_embedding_text"] += sum(
                not text.strip() for _, text in docs_with_text
            )
            docs_with_text = [(doc, text) for doc, text in docs_with_text if text.strip()]
            if not docs_with_text:
                continue
            if embedder is None:
                embedder = get_embedder()
            for embedding_batch in embedding_batches(docs_with_text, batch_size):
                vectors = embedder.embed_documents([text for _, text in embedding_batch])
                if len(vectors) != len(embedding_batch):
                    raise ValueError("Embedding provider returned the wrong number of vectors")
                values = []
                for (doc, _), vector in zip(embedding_batch, vectors):
                    if len(vector) != DIMENSIONS:
                        raise ValueError(f"Expected {DIMENSIONS} embedding dimensions, got {len(vector)}")
                    doc["embedding"] = "[" + ",".join(str(float(value)) for value in vector) + "]"
                    values.append(tuple(doc[name] for name in COLUMNS))
                with connection.cursor() as cursor:
                    cursor.executemany(sql, values)
                connection.commit()
                report["upserted"] += len(values)
            print(json.dumps({
                "status": "progress",
                "batch": batch_number,
                "batch_records": len(raw_batch),
                "upserted": report["upserted"],
                "skipped_current": report["skipped_current"],
                "skipped_empty_embedding_text": report["skipped_empty_embedding_text"],
                "elapsed_seconds": round(time.monotonic() - started_at, 1),
            }, ensure_ascii=False), flush=True)
    finally:
        connection.close()
    migrate("head")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Path to CSV on the host")
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Read at most this many physical CSV data rows; omitted means all rows",
    )
    parser.add_argument("--force", action="store_true", help="Re-embed and upsert all listings")
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_EMBEDDING_INPUTS:
        parser.error(f"--batch-size must be between 1 and {MAX_EMBEDDING_INPUTS}")
    if args.max_records is not None and args.max_records < 1:
        parser.error("--max-records must be at least 1")
    report = import_csv(args.csv, args.batch_size, args.force, args.max_records)
    print(json.dumps(dict(report), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
