"""Connection setup shared by the importer and read-only search tools."""

import unittest
from unittest.mock import MagicMock, patch

from src.db import connect_db


class DatabaseConnectionTests(unittest.TestCase):
    def test_readers_and_writer_get_separate_connections(self):
        reader = MagicMock()
        writer = MagicMock()
        with patch("src.db.psycopg.connect", side_effect=[reader, writer]) as connect:
            self.assertIs(connect_db(read_only=True), reader)
            self.assertIs(connect_db(read_only=False), writer)

        self.assertTrue(reader.read_only)
        self.assertNotIn("options", connect.call_args_list[1].kwargs)
        self.assertIn("default_transaction_read_only=on", connect.call_args_list[0].kwargs["options"])


if __name__ == "__main__":
    unittest.main()
