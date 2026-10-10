import asyncio
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
from src.graph.nodes import (
    decide_after_grading, grade_generation, route, route_after_rewrite,
)
from src.main import app
from src.tools.sql import SQLQueryError


class FakeRouter:
    def __init__(self, datasource: str):
        self.datasource = datasource
        self.questions: list[str] = []

    def invoke(self, data: dict[str, str]) -> RouteQuery:
        self.questions.append(data["question"])
        return RouteQuery(datasource=self.datasource)


class FakeAsyncChain:
    def __init__(self, result: str):
        self.result = result

    async def ainvoke(self, data):
        return self.result


def parse_events(body: str) -> list[tuple[str, dict[str, str]]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        events.append(
            (
                lines[0].removeprefix("event: "),
                json.loads(lines[1].removeprefix("data: ")),
            )
        )
    return events


class RouteTests(unittest.TestCase):
    def test_explicit_latest_question_uses_ollama_router(self):
        router = FakeRouter("sql")
        with patch("src.graph.nodes.get_router", return_value=router):
            selected = route({"question": "giá nhà Mỹ Đình dưới 5 tỉ mới nhất"})
        self.assertEqual(selected["datasource"], "sql")
        self.assertEqual(router.questions, ["giá nhà Mỹ Đình dưới 5 tỉ mới nhất"])

    def test_rewrite_routes_to_selected_source(self):
        self.assertEqual(route_after_rewrite({"datasource": "vectorstore"}), "retrieve")
        self.assertEqual(
            route_after_rewrite({"datasource": "web_search"}), "web_search"
        )
        edges = {
            (edge.source, edge.target)
            for edge in build_graph().get_graph().edges
            if edge.source == "rewrite_query"
        }
        self.assertEqual(
            edges, {("rewrite_query", "retrieve"), ("rewrite_query", "web_search")}
        )

    def test_graph_runs_sql_branch(self):
        graph = build_graph()
        self.assertEqual(
            set(graph.get_graph().nodes),
            {
                "__start__",
                "route",
                "retrieve",
                "grade_documents",
                "rewrite_query",
                "web_search",
                "generate",
                "query_sql",
                "__end__",
            },
        )

        router = FakeRouter("sql")
        document = Document(page_content="count\n2", metadata={"source": "sql"})
        with patch("src.graph.nodes.get_router", return_value=router), patch(
            "src.graph.nodes.get_llm", return_value=object()
        ), patch("src.graph.nodes.run_sql_question", return_value=document) as query, patch(
            "src.graph.nodes.get_generator",
            return_value=FakeAsyncChain("There are 2 listings."),
        ):
            async def collect_updates():
                return [
                    update async for update in graph.astream(
                        {"question": "How many houses?"}, stream_mode="updates"
                    )
                ]

            updates = asyncio.run(collect_updates())
        self.assertEqual(
            [list(update) for update in updates],
            [["route"], ["query_sql"], ["generate"]],
        )
        self.assertEqual(updates[0]["route"]["datasource"], "sql")
        self.assertEqual(updates[0]["route"]["original_question"], "How many houses?")
        self.assertEqual(updates[0]["route"]["retries"], 0)
        self.assertEqual(updates[1]["query_sql"]["documents"], [document])
        self.assertEqual(updates[2]["generate"]["generation"], "There are 2 listings.")
        self.assertEqual(router.questions, ["How many houses?"])
        query.assert_called_once()

    def test_api_streams_graded_vector_listings(self):
        document = Document(
            page_content="Quiet apartment in Hà Nội",
            metadata={
                "source": "listing",
                "listing_id": 12,
                "title": "Quiet apartment",
                "location": "Hà Nội",
                "price": 3200,
                "area": 68,
                "bedrooms": 2,
                "description": "Near a park.",
            },
        )
        grader = Mock()
        grader.invoke.return_value = "yes"
        with patch(
            "src.graph.nodes.get_router", return_value=FakeRouter("vectorstore")
        ), patch(
            "src.graph.nodes.search_listings", return_value=[document]
        ) as search, patch(
            "src.graph.nodes.get_document_grader", return_value=grader
        ), patch(
            "src.graph.nodes.get_generator",
            return_value=FakeAsyncChain("I found a quiet apartment in Hà Nội."),
        ), patch(
            "src.graph.nodes.get_grounding_grader",
            return_value=Mock(invoke=Mock(return_value="yes")),
        ):
            response = TestClient(app).post(
                "/api/chat", json={"message": "Quiet apartment"}
            )
        events = parse_events(response.text)
        self.assertEqual(
            [
                (data.get("node"), data.get("status"))
                for name, data in events
                if name == "step"
            ],
            [
                ("route", "running"),
                ("route", "completed"),
                ("retrieve", "running"),
                ("retrieve", "completed"),
                ("grade_documents", "running"),
                ("grade_documents", "completed"),
                ("generate", "running"),
                ("generate", "completed"),
            ],
        )
        self.assertEqual(events[-1][0], "done")
        self.assertEqual(events[-1][1]["datasource"], "vectorstore")
        self.assertEqual(
            events[-1][1]["result"], "I found a quiet apartment in Hà Nội."
        )
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
        with patch(
            "src.graph.nodes.get_router", return_value=FakeRouter("vectorstore")
        ), patch(
            "src.graph.nodes.search_listings", side_effect=[[bad], [good]]
        ) as search, patch(
            "src.graph.nodes.get_document_grader", return_value=grader
        ), patch(
            "src.graph.nodes.get_rewriter", return_value=rewriter
        ), patch(
            "src.graph.nodes.get_generator",
            return_value=FakeAsyncChain("A quiet apartment is available."),
        ), patch(
            "src.graph.nodes.get_grounding_grader",
            return_value=Mock(invoke=Mock(return_value="yes")),
        ):
            async def collect_updates():
                return [
                    update async for update in build_graph().astream(
                        {"question": "Quiet apartment"}, stream_mode="updates"
                    )
                ]

            updates = asyncio.run(collect_updates())
        self.assertEqual(
            [next(iter(update)) for update in updates],
            [
                "route",
                "retrieve",
                "grade_documents",
                "rewrite_query",
                "retrieve",
                "grade_documents",
                "generate",
            ],
        )
        self.assertEqual(
            updates[3]["rewrite_query"],
            {"question": "quiet apartment near park", "retries": 1},
        )
        self.assertEqual(updates[-2]["grade_documents"]["documents"], [good])
        self.assertEqual(
            updates[-1]["generate"]["generation"], "A quiet apartment is available."
        )
        self.assertEqual(
            search.call_args_list,
            [
                call("Quiet apartment", 4),
                call("quiet apartment near park", 4),
            ],
        )
        rewriter.invoke.assert_called_once_with(
            {
                "original_question": "Quiet apartment",
                "question": "Quiet apartment",
            }
        )
        self.assertEqual(
            [item.args[0]["question"] for item in grader.invoke.call_args_list],
            ["Quiet apartment", "quiet apartment near park"],
        )

    def test_vector_decisions_fall_back_to_web_after_retries(self):
        self.assertEqual(
            decide_after_grading({"documents": [], "retries": 1}), "rewrite"
        )
        self.assertEqual(
            decide_after_grading({"documents": [], "retries": 2}), "web_search"
        )
        self.assertEqual(
            decide_after_grading({"documents": [Document(page_content="fact")], "retries": 0}),
            "generate",
        )

    def test_api_streams_sql_result(self):
        document = Document(page_content="count\n2", metadata={"source": "sql"})
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("sql")), patch(
            "src.graph.nodes.get_llm", return_value=object()
        ), patch("src.graph.nodes.run_sql_question", return_value=document), patch(
            "src.graph.nodes.get_generator",
            return_value=FakeAsyncChain("There are 2 listings."),
        ):
            response = TestClient(app).post(
                "/api/chat", json={"message": "Count listings"}
            )
        events = parse_events(response.text)
        self.assertEqual(
            [name for name, _ in events],
            ["step", "step", "step", "step", "step", "step", "done"],
        )
        self.assertEqual(events[2][1], {"node": "query_sql", "status": "running"})
        self.assertEqual(events[3][1], {"node": "query_sql", "status": "completed"})
        self.assertEqual(events[4][1], {"node": "generate", "status": "running"})
        self.assertEqual(events[5][1], {"node": "generate", "status": "completed"})
        self.assertEqual(
            events[6][1],
            {
                "datasource": "sql",
                "result": "There are 2 listings.",
                "sources": [{"title": "sql", "url": "sql"}],
            },
        )

    def test_generation_grading_rewrites_only_when_needed(self):
        state = {
            "datasource": "vectorstore",
            "documents": [Document(page_content="fact", metadata={"source": "db"})],
            "generation": "unsupported answer",
            "retries": 0,
        }
        grader = Mock()
        grader.invoke.return_value = "no"
        with patch("src.graph.nodes.get_grounding_grader", return_value=grader):
            self.assertEqual(grade_generation(state), "rewrite")
            state["retries"] = 2
            self.assertEqual(grade_generation(state), "useful")
        self.assertEqual(
            grade_generation({
                "datasource": "sql",
                "documents": state["documents"],
                "generation": "answer",
                "retries": 0,
            }),
            "useful",
        )

    def test_api_streams_sql_error_without_done(self):
        with patch("src.graph.nodes.get_router", return_value=FakeRouter("sql")), patch(
            "src.graph.nodes.get_llm", return_value=object()
        ), patch(
            "src.graph.nodes.run_sql_question", side_effect=SQLQueryError("bad query")
        ), patch(
            "src.main.logger.exception"
        ):
            response = TestClient(app).post(
                "/api/chat", json={"message": "Count listings"}
            )
        events = parse_events(response.text)
        self.assertEqual(
            [name for name, _ in events], ["step", "step", "step", "error"]
        )
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
                response = TestClient(app).post(
                    "/api/chat", json={"message": "A question"}
                )
        events = parse_events(response.text)
        self.assertEqual([name for name, _ in events], ["step", "error"])
        self.assertNotIn("datasource", events[-1][1])
        self.assertEqual(
            events[-1][1]["message"],
            "Could not complete the request. Please try again.",
        )

    def test_api_handles_timeout_as_a_generic_error(self):
        class BrokenGraph:
            async def astream(self, state, stream_mode):
                raise TimeoutError
                yield  # Make this an async generator.

        with patch("src.main.get_graph", return_value=BrokenGraph()), patch(
            "src.main.logger.exception"
        ):
            response = TestClient(app).post(
                "/api/chat", json={"message": "Latest news"}
            )
        self.assertEqual(
            parse_events(response.text),
            [
                ("step", {"node": "route", "status": "running"}),
                (
                    "error",
                    {"message": "Could not complete the request. Please try again."},
                ),
            ],
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

    def test_config_rejects_unknown_llm_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}, clear=True):
                with self.assertRaisesRegex(ValueError, "Invalid LLM_PROVIDER"):
                    load_settings(Path(directory) / ".env")

    def test_config_accepts_supported_provider_names(self):
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("local", "openai", "openrouter"):
                with self.subTest(provider=provider), patch.dict(
                    os.environ,
                    {"LLM_PROVIDER": provider},
                    clear=True,
                ):
                    settings = load_settings(Path(directory) / ".env")
                    self.assertEqual(settings.llm_provider, provider)

    def test_embedding_defaults_follow_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}, clear=True):
                settings = load_settings(path)
                self.assertEqual(settings.llm_embedding_model, "text-embedding-3-small")
            with patch.dict(os.environ, {}, clear=True):
                settings = load_settings(path)
                self.assertEqual(settings.llm_embedding_model, "BAAI/bge-m3")

    def test_config_reads_docker_secret_files(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_dir = Path(directory)
            api_key_file = secret_dir / "llm_api_key"
            password_file = secret_dir / "postgres_password"
            api_key_file.write_text("api-key-from-file\n")
            password_file.write_text("password-from-file\n")
            with patch.dict(
                os.environ,
                {
                    "LLM_PROVIDER": "openai",
                    "LLM_API_KEY_FILE": str(api_key_file),
                    "POSTGRES_PASSWORD_FILE": str(password_file),
                },
                clear=True,
            ):
                settings = load_settings(secret_dir / ".env")
            self.assertEqual(settings.llm_api_key, "api-key-from-file")
            self.assertEqual(settings.postgres_password, "password-from-file")


if __name__ == "__main__":
    unittest.main()
