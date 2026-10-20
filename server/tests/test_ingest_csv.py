import csv
import tempfile
import unittest
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.script.ingest_csv import (
    MAX_EMBEDDING_INPUT_TOKENS,
    embedding_text,
    embedding_batches,
    latest_listings,
    needs_import,
    parse_row,
    upsert_sql,
)


class IngestCsvTests(unittest.TestCase):
    class FakeEncoder:
        def encode(self, text):
            return list(text)

        def decode(self, tokens):
            return "".join(tokens)

    def test_latest_scrape_wins_even_when_csv_is_out_of_order(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listings.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Listing ID", "Scraped At", "Title"])
                writer.writeheader()
                writer.writerows([
                    {"Listing ID": "12.0", "Scraped At": "2025-09-13 00:00:00", "Title": "new"},
                    {"Listing ID": "12.0", "Scraped At": "2025-09-12 00:00:00", "Title": "old"},
                    {"Listing ID": "13.0", "Scraped At": "2025-09-13 00:00:00", "Title": "other"},
                    {"Listing ID": "bad", "Scraped At": "2025-09-13 00:00:00", "Title": "invalid"},
                ])
            rows, report = latest_listings(path)
        self.assertEqual(rows[12]["Title"], "new")
        self.assertEqual(len(rows), 2)
        self.assertEqual(report["duplicate_rows"], 1)
        self.assertEqual(report["invalid_required_rows"], 1)

    def test_max_records_stops_after_raw_csv_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listings.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Listing ID", "Scraped At", "Title"])
                writer.writeheader()
                writer.writerows([
                    {"Listing ID": "12.0", "Scraped At": "2025-09-12 00:00:00", "Title": "old"},
                    {"Listing ID": "12.0", "Scraped At": "2025-09-13 00:00:00", "Title": "new"},
                    {"Listing ID": "13.0", "Scraped At": "2025-09-13 00:00:00", "Title": "not read"},
                ])
            rows, report = latest_listings(path, max_records=2)
        self.assertEqual(report["csv_rows"], 2)
        self.assertEqual(report["duplicate_rows"], 1)
        self.assertEqual(set(rows), {12})
        self.assertEqual(rows[12]["Title"], "new")

    def test_max_records_must_be_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "listings.csv"
            path.write_text("Listing ID,Scraped At,Title\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                latest_listings(path, max_records=0)

    def test_invalid_optional_values_become_null_and_are_counted(self):
        report = Counter()
        doc = parse_row({
            "Listing ID": "12.0", "Scraped At": "2025-09-13 00:00:00",
            "Title": "Bán nhà", "Location": "Hà Nội", "Price": "2500.0",
            "Area": "nan", "Bedrooms": "2.5", "Latitude": "91", "VIP Account": "maybe",
        }, report)
        self.assertEqual(doc["price"], 2500.0)
        self.assertIsNone(doc["area"])
        self.assertIsNone(doc["bedrooms"])
        self.assertIsNone(doc["latitude"])
        self.assertIsNone(doc["vip_account"])
        self.assertEqual(sum(report.values()), 4)
        self.assertIn("Bán nhà", embedding_text(doc))
        self.assertIn("Hà Nội", embedding_text(doc))
        self.assertIn("Giá: 2500.0 triệu VND", embedding_text(doc))

    def test_embedding_batches_respect_item_and_token_limits(self):
        items = [
            ({"listing_id": 1}, "a" * 5),
            ({"listing_id": 2}, "b" * (MAX_EMBEDDING_INPUT_TOKENS + 10)),
            ({"listing_id": 3}, "c" * 5),
        ]
        grouped = list(embedding_batches(items, 2, encoder=self.FakeEncoder()))
        self.assertEqual([len(batch) for batch in grouped], [2, 1])
        self.assertEqual(len(grouped[0][1][1]), MAX_EMBEDDING_INPUT_TOKENS)

    def test_rerun_skips_equal_or_older_scrapes_unless_forced(self):
        now = datetime(2025, 9, 13)
        older = datetime(2025, 9, 12)
        self.assertFalse(needs_import(now, now, False))
        self.assertFalse(needs_import(older, now, False))
        self.assertTrue(needs_import(now, older, False))
        self.assertTrue(needs_import(now, None, False))
        self.assertTrue(needs_import(now, now, True))
        self.assertNotIn("created_at =", upsert_sql(False))
        self.assertIn("EXCLUDED.scraped_at >", upsert_sql(False))


if __name__ == "__main__":
    unittest.main()
