import unittest
from unittest.mock import MagicMock, Mock, patch

from src.tools.vector import search_listings


class VectorSearchTests(unittest.TestCase):
    def test_embeds_question_and_reads_nearest_listings(self):
        embedder = Mock()
        embedder.embed_query.return_value = [0.0] * 1023 + [1.0]
        row = {
            "listing_id": 12, "title": "Quiet apartment", "price": 3200,
            "area": 68, "location": "Hà Nội", "property_type": "Apartment",
            "bedrooms": 2, "description": "Near a park.",
        }
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = [row]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value = cursor

        with patch("src.tools.vector.get_embedder", return_value=embedder), \
             patch("src.db.psycopg.connect", return_value=connection) as connect:
            documents = search_listings("quiet home", 4)

        embedder.embed_query.assert_called_once_with("quiet home")
        sql, params = cursor.execute.call_args.args
        self.assertIn("ORDER BY embedding <=> %s::vector LIMIT %s", sql)
        self.assertEqual(params[1], 4)
        self.assertEqual(params[0].count(","), 1023)
        self.assertTrue(connection.read_only)
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
        self.assertEqual(documents[0].metadata["listing_id"], 12)
        self.assertIn("Near a park.", documents[0].page_content)

    def test_empty_table_returns_no_documents(self):
        embedder = Mock()
        embedder.embed_query.return_value = [0.0] * 1024
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = []
        with patch("src.tools.vector.get_embedder", return_value=embedder), \
             patch("src.db.psycopg.connect", return_value=connection):
            self.assertEqual(search_listings("quiet home", 4), [])

    def test_budget_text_does_not_add_a_price_filter(self):
        embedder = Mock()
        embedder.embed_query.return_value = [0.0] * 1024
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value
        cursor.__enter__.return_value = cursor
        cursor.fetchall.return_value = []
        with patch("src.tools.vector.get_embedder", return_value=embedder), \
             patch("src.db.psycopg.connect", return_value=connection):
            search_listings("Căn hộ view cây xanh giá dưới 5 tỉ", 4)
        sql, params = cursor.execute.call_args.args
        self.assertNotIn("WHERE", sql)
        self.assertEqual(len(params), 2)


if __name__ == "__main__":
    unittest.main()
