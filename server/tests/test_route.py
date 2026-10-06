import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from fastapi.testclient import TestClient
from langchain_core.documents import Document

from src.config import load_settings
from src.graph.build import build_graph
from src.graph.chains import RouteQuery
from src.graph.nodes import route_after_rewrite
from src.main import app
from src.tools.sql import SQLQueryError


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
    def test_rewrite_routes_to_selected_source(self):
        self.assertEqual(route_after_rewrite({"datasource": "vectorstore"}), "retrieve")
        self.assertEqual(route_after_rewrite({"datasource": "web_search"}), "web_search")
        edges = {
            (edge.source, edge.target)
            for edge in build_graph().get_graph().edges
            if edge.source == "rewrite_query"
        }
        self.assertEqual(edges, {("rewrite_query", "retrieve"), ("rewrite_query", "__end__")})

    def test_graph_runs_sql_branch(self):
        graph = build_graph()
        self.assertEqual(
            set(graph.get_graph().nodes),
            {"__start__", "route", "retrieve", "grade_documents", "rewrite_query", "query_sql", "__end__"},
        )

        router = FakeRouter("sql")
        document = Document(page_content="count\n2", metadata={"source": "sql"})
        with patch("src.graph.nodes.get_router", return_value=router), \
             patch("src.graph.nodes.get_llm", return_value=object()), \
             patch("src.graph.nodes.run_sql_question", return_value=document) as query:
            updates = list(graph.stream({"question": "How many houses?"}, stream_mode="updates"))
        self.assertEqual([list(update) for update in updates], [["route"], ["query_sql"]])
        self.assertEqual(updates[0]["route"]["datasource"], "sql")
        self.assertEqual(updates[0]["route"]["original_question"], "How many houses?")
        self.assertEqual(updates[0]["route"]["retries"], 0)
        self.assertEqual(updates[1]["query_sql"]["documents"], [document])
        self.assertEqual(router.questions, ["How many houses?"])
        query.assert_called_once()

    def test_api_streams_graded_vector_listings(self):
        document = Document(
            page_content="Quiet apartment in Hà Nội",
            metadata={
                "source": "listing", "listing_id": 12, "title": "Quiet apartment",
                "location": "Hà Nội", "price": 3200, "area": 68,
                "bedrooms": 2, "description": "Near a park.",
            },
        )
        grader = Mock()
        grader.invoke.return_value = "yes"
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("vectorstore")), \
             patch("src.graph.nodes.search_listings", return_value=[document]) as search, \
             patch("src.graph.nodes.get_document_grader", return_value=grader):
            response = TestClient(app).post("/api/chat", json={"message": "Quiet apartment"})
        events = parse_events(response.text)
        self.assertEqual(
            [(data.get("node"), data.get("status")) for name, data in events if name == "step"],
            [
                ("route", "running"), ("route", "completed"),
                ("retrieve", "running"), ("retrieve", "completed"),
                ("grade_documents", "running"), ("grade_documents", "completed"),
            ],
        )
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(events[-1][1]["datasource"], "vectorstore")
        self.assertIn("Quiet apartment (ID 12)", events[-1][1]["result"])
        self.assertIn("3,200 million VND", events[-1][1]["result"])
        self.assertIn("Near a park.", events[-1][1]["result"])
        search.assert_called_once_with("Quiet apartment", 4)
        grader.invoke.assert_called_once_with(
            {"document": document.page_content, "question": "Quiet apartment"}
        )

    def test_vector_rewrites_then_retrieves_again(self):
        bad = Document(page_content="Unrelated land", metadata={"title": "Land"})
        good = Document(page_content="Quiet apartment", metadata={"title": "Apartment"})
        grader = Mock()
        grader.invoke.side_effect = ["no", "yes"]
        rewriter = Mock()
        rewriter.invoke.return_value = "quiet apartment near park"
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("vectorstore")), \
             patch("src.graph.nodes.search_listings", side_effect=[[bad], [good]]) as search, \
             patch("src.graph.nodes.get_document_grader", return_value=grader), \
             patch("src.graph.nodes.get_rewriter", return_value=rewriter):
            updates = list(build_graph().stream(
                {"question": "Quiet apartment"}, stream_mode="updates"
            ))
        self.assertEqual(
            [next(iter(update)) for update in updates],
            ["route", "retrieve", "grade_documents", "rewrite_query", "retrieve", "grade_documents"],
        )
        self.assertEqual(updates[3]["rewrite_query"], {"question": "quiet apartment near park", "retries": 1})
        self.assertEqual(updates[-1]["grade_documents"]["documents"], [good])
        self.assertEqual(search.call_args_list, [
            call("Quiet apartment", 4),
            call("quiet apartment near park", 4),
        ])
        rewriter.invoke.assert_called_once_with({
            "original_question": "Quiet apartment",
            "question": "Quiet apartment",
        })
        self.assertEqual(
            [item.args[0]["question"] for item in grader.invoke.call_args_list],
            ["Quiet apartment", "Quiet apartment"],
        )

    def test_vector_stops_after_two_rewrites_with_no_matches(self):
        rewriter = Mock()
        rewriter.invoke.side_effect = ["search one", "search two"]
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("vectorstore")), \
             patch("src.graph.nodes.search_listings", return_value=[]) as search, \
             patch("src.graph.nodes.get_rewriter", return_value=rewriter):
            response = TestClient(app).post("/api/chat", json={"message": "A quiet home"})
        events = parse_events(response.text)
        self.assertEqual(events[-1], (
            "done", {"datasource": "vectorstore", "result": "No relevant listings found."}
        ))
        self.assertEqual(search.call_count, 3)
        self.assertEqual(rewriter.invoke.call_count, 2)
        self.assertEqual(rewriter.invoke.call_args_list, [
            call({"original_question": "A quiet home", "question": "A quiet home"}),
            call({"original_question": "A quiet home", "question": "search one"}),
        ])
        self.assertEqual(
            [data["node"] for name, data in events if name == "step" and data["status"] == "running"],
            ["route", "retrieve", "grade_documents", "rewrite_query", "retrieve", "grade_documents", "rewrite_query", "retrieve", "grade_documents"],
        )

    def test_web_route_ends_without_retrieval(self):
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("web_search")), \
             patch("src.graph.nodes.search_listings") as search:
            response = TestClient(app).post("/api/chat", json={"message": "Latest market news"})
        self.assertEqual(parse_events(response.text)[-1], ("done", {"datasource": "web_search"}))
        search.assert_not_called()

    def test_api_streams_sql_result(self):
        document = Document(page_content="count\n2", metadata={"source": "sql"})
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("sql")), \
             patch("src.graph.nodes.get_llm", return_value=object()), \
             patch("src.graph.nodes.run_sql_question", return_value=document):
            response = TestClient(app).post("/api/chat", json={"message": "Count listings"})
        events = parse_events(response.text)
        self.assertEqual([name for name, _ in events], ["step", "step", "step", "step", "done"])
        self.assertEqual(events[2][1], {"node": "query_sql", "status": "running"})
        self.assertEqual(events[3][1], {"node": "query_sql", "status": "completed"})
        self.assertEqual(events[4][1], {"datasource": "sql", "result": "count\n2"})

    def test_api_streams_sql_error_without_done(self):
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("sql")), \
             patch("src.graph.nodes.get_llm", return_value=object()), \
             patch("src.graph.nodes.run_sql_question", side_effect=SQLQueryError("bad query")), \
             patch("src.main.logger.exception"):
            response = TestClient(app).post("/api/chat", json={"message": "Count listings"})
        events = parse_events(response.text)
        self.assertEqual([name for name, _ in events], ["step", "step", "step", "error"])
        self.assertEqual(
            events[-1][1]["message"],
            "Could not complete the request. Please try again.",
        )

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
        self.assertEqual(
            events[-1][1]["message"],
            "Could not complete the request. Please try again.",
        )

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

    def test_embedding_defaults_follow_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "openai"}, clear=True):
                settings = load_settings(path)
                self.assertEqual(settings.embedding_model, "text-embedding-3-small")
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(path)
                self.assertEqual(settings.embedding_provider, "local")
                self.assertEqual(settings.embedding_model, "BAAI/bge-m3")

    def test_config_rejects_unknown_embedding_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"EMBEDDING_PROVIDER": "unknown"}, clear=True):
                with self.assertRaisesRegex(ValueError, "Invalid EMBEDDING_PROVIDER"):
                    load_settings(Path(directory) / ".env")


if __name__ == "__main__":
    unittest.main()
