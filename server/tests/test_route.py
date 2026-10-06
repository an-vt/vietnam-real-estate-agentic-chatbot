import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.config import load_settings
from src.graph.build import build_graph
from src.graph.chains import RouteQuery
from src.main import app


class FakeRouter:
    def __init__(self, datasource: str):
        self.datasource = datasource
        self.questions: list[str] = []

    def invoke(self, data: dict[str, str]) -> RouteQuery:
        self.questions.append(data["question"])
        return RouteQuery(datasource=self.datasource)


def parse_events(body: str) -> list[tuple[str, dict[str, str]]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


class RouteTests(unittest.TestCase):
    def test_graph_compiles_without_ollama_and_stops_after_route(self):
        graph = build_graph()
        self.assertEqual(set(graph.get_graph().nodes), {"__start__", "route", "__end__"})

        router = FakeRouter("sql")
        with patch("src.graph.nodes.get_router", return_value=router):
            updates = list(graph.stream({"question": "How many houses?"}, stream_mode="updates"))
        self.assertEqual([list(update) for update in updates], [["route"]])
        self.assertEqual(updates[0]["route"]["datasource"], "sql")
        self.assertEqual(updates[0]["route"]["original_question"], "How many houses?")
        self.assertEqual(updates[0]["route"]["retries"], 0)
        self.assertEqual(router.questions, ["How many houses?"])

    def test_api_streams_each_route(self):
        client = TestClient(app)
        for datasource in ("sql", "vectorstore", "web_search"):
            with self.subTest(datasource=datasource):
                with patch("src.graph.nodes.get_router", return_value=FakeRouter(datasource)):
                    response = client.post("/api/chat", json={"message": "  A question  "})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
                events = parse_events(response.text)
                self.assertEqual([name for name, _ in events], ["step", "step", "done"])
                self.assertEqual(events[0][1], {"node": "route", "status": "running"})
                self.assertEqual(events[1][1]["datasource"], datasource)
                self.assertEqual(events[2][1], {"datasource": datasource})

    def test_api_streams_error_without_fake_route(self):
        class BrokenRouter:
            def invoke(self, data):
                raise RuntimeError("model unavailable")

        with patch("src.graph.nodes.get_router", return_value=BrokenRouter()):
            with patch("src.main.logger.exception"):
                response = TestClient(app).post("/api/chat", json={"message": "A question"})
        events = parse_events(response.text)
        self.assertEqual([name for name, _ in events], ["step", "error"])
        self.assertNotIn("datasource", events[-1][1])

    def test_blank_message_is_rejected(self):
        response = TestClient(app).post("/api/chat", json={"message": "   "})
        self.assertEqual(response.status_code, 422)

    def test_config_prefers_exported_values_over_file(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "APP_LOG_LEVEL=WARNING\nLLM_MODEL=file-model\n"
                "SQL_DESCRIPTION=From the file\nPOSTGRES_PORT=5439\n"
            )
            with patch.dict(
                os.environ,
                {"APP_LOG_LEVEL": "debug", "LLM_MODEL": "exported-model"},
                clear=True,
            ):
                settings = load_settings(env_file)
                self.assertEqual(settings.app_log_level, "DEBUG")
                self.assertEqual(settings.llm_model, "exported-model")
                self.assertEqual(settings.sql_description, "From the file")
                self.assertEqual(settings.postgres_port, 5439)

    def test_config_rejects_invalid_log_level(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"APP_LOG_LEVEL": "TRACE"}, clear=True):
                with self.assertRaisesRegex(ValueError, "Invalid APP_LOG_LEVEL"):
                    load_settings(Path(directory) / ".env")


if __name__ == "__main__":
    unittest.main()
