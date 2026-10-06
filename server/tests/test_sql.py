"""Text-to-SQL validation, correction, and bounded result tests."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psycopg
from langchain_core.runnables import RunnableLambda

from src.tools.sql import (
    SQLQuery,
    SQLQueryError,
    _execute_query,
    _relevant_values,
    get_value_hints,
    is_safe_select,
    run_sql_question,
)


TABLE = "vietnamese_real_estate.documents"


class FakeStructuredLLM:
    def __init__(self, queries):
        self.queries = list(queries)
        self.prompts = []

    def with_structured_output(self, schema, method):
        assert schema is SQLQuery
        assert method == "json_schema"
        return RunnableLambda(self._respond)

    def _respond(self, prompt):
        self.prompts.append(prompt.to_string())
        return SQLQuery(query=self.queries.pop(0))


class SQLTests(unittest.TestCase):
    def test_relevant_values_match_vietnamese_names_and_fall_back(self):
        provinces = ["dak-lak", "ha-noi", "tp-ho-chi-minh"]
        self.assertEqual(_relevant_values("Đắk Lắk", provinces, "province"), ["dak-lak"])
        self.assertEqual(_relevant_values("Hà Nội", provinces, "province"), ["ha-noi"])
        self.assertEqual(
            _relevant_values("Hồ Chí Minh", provinces, "province"),
            ["tp-ho-chi-minh"],
        )
        self.assertEqual(_relevant_values("bán đất", ["Đất", "Nhà riêng"], "property_type"), ["Đất"])
        self.assertEqual(_relevant_values("land listings", ["Đất", "Nhà riêng"], "property_type"), ["Đất"])
        self.assertEqual(_relevant_values("all listings", provinces, "province"), provinces)

    def test_value_hints_use_exact_stored_values_in_read_only_queries(self):
        cursor = MagicMock()
        cursor.fetchall.side_effect = [
            [("dak-lak",), ("ha-noi",)],
            [("Đất",), ("Nhà riêng",)],
        ]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch("src.tools.sql.psycopg.connect", return_value=connection):
            hints = json.loads(get_value_hints("Đắk Lắk đất"))
        self.assertEqual(hints, {"province": ["dak-lak"], "property_type": ["Đất"]})
        self.assertEqual(cursor.execute.call_count, 2)
        for call in cursor.execute.call_args_list:
            self.assertIn(TABLE, call.args[0])
            self.assertNotIn("Đắk Lắk", call.args[0])
        self.assertTrue(connection.read_only)

    def test_accepts_listing_filters_and_aggregates(self):
        for sql in (
            f"SELECT COUNT(*) FROM {TABLE}",
            f"SELECT province, COUNT(*) FROM {TABLE} GROUP BY province ORDER BY COUNT(*) DESC LIMIT 20",
            f"SELECT title, price FROM {TABLE} WHERE province ILIKE '%Hà Nội%' AND price < 3000 LIMIT 20",
            f"SELECT ROUND(AVG(price), 2) FROM {TABLE}",
            f"SELECT d.title FROM {TABLE} AS d WHERE d.bedrooms >= 3",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(is_safe_select(sql))

    def test_accepts_reference_select_syntax(self):
        for sql in (
            f"SELECT * FROM {TABLE}",
            f"SELECT embedding FROM {TABLE}",
            "SELECT md5('example')",
            "SELECT title FROM public.users",
            "WITH listings AS (SELECT 1) SELECT * FROM listings",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(is_safe_select(sql))

    def test_rejects_writes_and_multiple_statements(self):
        for sql in (
            f"SELECT title FROM {TABLE}; DROP TABLE {TABLE}",
            f"WITH x AS (DELETE FROM {TABLE} RETURNING title) SELECT title FROM x",
            "SELECT 1; SELECT 2",
            f"DELETE FROM {TABLE}",
            f"UPDATE {TABLE} SET price = 1",
        ):
            with self.subTest(sql=sql):
                self.assertFalse(is_safe_select(sql))

    def test_retries_bad_sql_with_feedback(self):
        llm = FakeStructuredLLM(["DELETE FROM vietnamese_real_estate.documents", f"SELECT COUNT(*) FROM {TABLE}"])
        with patch("src.tools.sql.get_value_hints", return_value='{"province": ["ha-noi"]}'), \
             patch("src.tools.sql._execute_query", return_value="count\n2") as execute:
            document = run_sql_question("How many listings?", llm)
        execute.assert_called_once_with(f"SELECT COUNT(*) FROM {TABLE}")
        self.assertIn("previous query failed", llm.prompts[1])
        self.assertIn("province = 'ha-noi'", llm.prompts[0])
        self.assertIn("CREATE TABLE IF NOT EXISTS vietnamese_real_estate.documents", llm.prompts[0])
        self.assertIn("province: dak-lak", llm.prompts[0])
        self.assertIn('"province": ["ha-noi"]', llm.prompts[0])
        self.assertNotIn("0.018296372", llm.prompts[0])
        self.assertEqual(document.page_content, "count\n2")
        self.assertEqual(document.metadata["query"], f"SELECT COUNT(*) FROM {TABLE}")

    def test_retries_database_query_error(self):
        llm = FakeStructuredLLM([f"SELECT title FROM {TABLE}", f"SELECT COUNT(*) FROM {TABLE}"])
        with patch("src.tools.sql.get_value_hints", return_value="{}"), \
             patch("src.tools.sql._execute_query", side_effect=[psycopg.ProgrammingError("bad column"), "count\n2"]):
            document = run_sql_question("How many listings?", llm)
        self.assertIn("bad column", llm.prompts[1])
        self.assertEqual(document.page_content, "count\n2")

    def test_reports_empty_result_without_rewriting(self):
        llm = FakeStructuredLLM([f"SELECT title FROM {TABLE} WHERE price < 0"])
        with patch("src.tools.sql.get_value_hints", return_value="{}"), \
             patch("src.tools.sql._execute_query", return_value="(no rows returned)"):
            document = run_sql_question("Any free listings?", llm)
        self.assertEqual(document.page_content, "(no rows returned)")
        self.assertEqual(len(llm.prompts), 1)

    def test_exhausted_attempts_raise_error(self):
        llm = FakeStructuredLLM([f"DELETE FROM {TABLE}"] * 3)
        with patch("src.tools.sql.get_value_hints", return_value="{}"), \
             patch("src.tools.sql._execute_query") as execute:
            with self.assertRaises(SQLQueryError):
                run_sql_question("Delete listings", llm)
        execute.assert_not_called()

    def test_value_lookup_failure_is_sql_error(self):
        llm = FakeStructuredLLM([])
        with patch("src.tools.sql.get_value_hints", side_effect=psycopg.OperationalError("offline")):
            with self.assertRaises(SQLQueryError):
                run_sql_question("How many listings?", llm)
        self.assertEqual(llm.prompts, [])

    def test_formats_only_first_twenty_rows_and_uses_read_only_connection(self):
        cursor = MagicMock()
        cursor.description = [SimpleNamespace(name="listing_id"), SimpleNamespace(name="title")]
        cursor.fetchmany.return_value = [(index, f"House {index}") for index in range(21)]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch("src.tools.sql.psycopg.connect", return_value=connection) as connect:
            result = _execute_query(f"SELECT listing_id, title FROM {TABLE}")
        self.assertIn("House 19", result)
        self.assertNotIn("House 20", result)
        self.assertIn("showing first 20 rows", result)
        self.assertTrue(connection.read_only)
        self.assertIn("default_transaction_read_only=on", connect.call_args.kwargs["options"])
        self.assertIn("statement_timeout=5000", connect.call_args.kwargs["options"])


if __name__ == "__main__":
    unittest.main()
