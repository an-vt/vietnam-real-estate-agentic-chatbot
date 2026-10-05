"""Import the latest scrape of each listing into PostgreSQL with BGE-M3 vectors."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


MODEL_NAME = "BAAI/bge-m3"
DIMENSIONS = 1024
TABLE = "vietnamese_real_estate.documents"
COLUMNS = (
    "listing_id", "title", "price", "area", "location", "property_type",
    "width", "length", "bedrooms", "bathrooms", "floors", "position",
    "direction", "alley_width", "road_type", "description", "latitude",
    "longitude", "vip_account", "agent_role", "agent_name",
    "agent_listing_count", "province", "scraped_at", "embedding",
)


def local_env() -> None:
    """Use Compose's local settings on the host, without overriding exported values."""
    path = Path(__file__).resolve().parents[3] / "infra/local/.env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


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


def latest_listings(path: Path) -> tuple[dict[int, dict[str, str]], Counter[str]]:
    latest: dict[int, dict[str, str]] = {}
    report: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Listing ID", "Scraped At", "Title"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV is missing columns: {sorted(required - set(reader.fieldnames or []))}")
        for row in reader:
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
    return "\n".join(
        f"{label}: {document[key]}" for label, key in (
            ("Tiêu đề", "title"), ("Loại bất động sản", "property_type"),
            ("Địa điểm", "location"), ("Mô tả", "description"),
        ) if document[key]
    )


def approximate_text_length(row: dict[str, str]) -> int:
    """Group similarly sized inputs to reduce padding during batch encoding."""
    return sum(len(row.get(field) or "") for field in
               ("Title", "Property Type", "Location", "Description"))


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


def make_encoder() -> Any:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    model.max_seq_length = 512
    if str(model.device).startswith("mps"):
        model.half()
    return model


def import_csv(path: Path, batch_size: int, force: bool) -> Counter[str]:
    import psycopg

    local_env()
    migrate("20261005_01")
    latest, report = latest_listings(path)
    connection = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5433")),
        dbname=os.getenv("POSTGRES_DB", "vietnam_real_estate"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )
    encoder = None
    try:
        sql = upsert_sql(force)
        for raw_batch in batches(sorted(latest.values(), key=approximate_text_length), batch_size):
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
            if encoder is None:
                encoder = make_encoder()
            vectors = encoder.encode(
                [embedding_text(doc) for doc in docs],
                batch_size=batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            values = []
            for doc, vector in zip(docs, vectors):
                if len(vector) != DIMENSIONS:
                    raise ValueError(f"Expected {DIMENSIONS} embedding dimensions, got {len(vector)}")
                doc["embedding"] = "[" + ",".join(str(float(value)) for value in vector) + "]"
                values.append(tuple(doc[name] for name in COLUMNS))
            with connection.cursor() as cursor:
                cursor.executemany(sql, values)
            connection.commit()
            report["upserted"] += len(values)
            if report["upserted"] % (batch_size * 100) == 0:
                print(json.dumps(dict(report), ensure_ascii=False), flush=True)
    finally:
        connection.close()
    migrate("head")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path, help="Path to CSV on the host")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true", help="Re-embed and upsert all listings")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    report = import_csv(args.csv, args.batch_size, args.force)
    print(json.dumps(dict(report), ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
