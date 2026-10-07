import io
import logging
import unittest
from contextlib import redirect_stderr

from src.logger import setup_logging


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.app_logger = logging.getLogger("src")
        self.original_level = self.app_logger.level
        self.original_propagate = self.app_logger.propagate
        self.original_handlers = self.app_logger.handlers[:]
        for handler in self.original_handlers:
            self.app_logger.removeHandler(handler)

    def tearDown(self):
        for handler in self.app_logger.handlers[:]:
            self.app_logger.removeHandler(handler)
            handler.close()
        for handler in self.original_handlers:
            self.app_logger.addHandler(handler)
        self.app_logger.setLevel(self.original_level)
        self.app_logger.propagate = self.original_propagate

    def test_setup_keeps_other_handlers_and_does_not_duplicate_its_own(self):
        other_handler = logging.NullHandler()
        self.app_logger.addHandler(other_handler)

        setup_logging("INFO")
        setup_logging("INFO")

        self.assertEqual(len(self.app_logger.handlers), 2)
        self.assertIn(other_handler, self.app_logger.handlers)
        self.assertFalse(self.app_logger.propagate)

    def test_level_change_filters_application_messages(self):
        output = io.StringIO()
        with redirect_stderr(output):
            setup_logging("INFO")
            node_logger = logging.getLogger("src.graph.nodes")
            node_logger.info("shown at INFO")
            setup_logging("WARNING")
            node_logger.info("hidden at WARNING")
            node_logger.warning("shown at WARNING")

        self.assertIn("INFO src.graph.nodes: shown at INFO", output.getvalue())
        self.assertRegex(
            output.getvalue(),
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z INFO src\.graph\.nodes",
        )
        self.assertNotIn("hidden at WARNING", output.getvalue())
        self.assertIn("WARNING src.graph.nodes: shown at WARNING", output.getvalue())


if __name__ == "__main__":
    unittest.main()
