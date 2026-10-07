"""Embedding provider selection and OpenAI request behavior."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.embeddings import DIMENSIONS, OpenAIEmbedder, get_embedder


class EmbeddingTests(unittest.TestCase):
    def tearDown(self):
        get_embedder.cache_clear()

    def test_factory_uses_configured_provider_and_model(self):
        for provider, class_name, expected_kwargs in (
            ("local", "LocalEmbedder", {}),
            ("openai", "OpenAIEmbedder", {"api_key": "openai-key"}),
            (
                "openrouter",
                "OpenAIEmbedder",
                {"api_key": "router-key", "base_url": "https://openrouter.ai/api/v1"},
            ),
        ):
            with self.subTest(provider=provider):
                get_embedder.cache_clear()
                settings = SimpleNamespace(
                    llm_provider=provider,
                    llm_embedding_model="chosen-model",
                    llm_api_key="openai-key" if provider == "openai" else "router-key",
                )
                with patch("src.embeddings.settings", settings), patch(
                    f"src.embeddings.{class_name}"
                ) as constructor:
                    self.assertIs(get_embedder(), constructor.return_value)
                    constructor.assert_called_once_with(
                        "chosen-model", **expected_kwargs
                    )

    def test_factory_rejects_unknown_provider(self):
        settings = SimpleNamespace(
            llm_provider="unknown",
            llm_embedding_model="chosen-model",
            llm_api_key=None,
        )
        with patch("src.embeddings.settings", settings):
            with self.assertRaisesRegex(ValueError, "Invalid LLM_PROVIDER"):
                get_embedder()

    def test_openrouter_requires_api_key(self):
        settings = SimpleNamespace(
            llm_provider="openrouter",
            llm_embedding_model="chosen-model",
            llm_api_key=None,
        )
        with patch("src.embeddings.settings", settings):
            with self.assertRaisesRegex(ValueError, "LLM_API_KEY"):
                get_embedder()

    def test_openai_requests_1024_dimensions_and_preserves_input_order(self):
        client = MagicMock()
        client.embeddings.create.return_value.data = [
            SimpleNamespace(index=1, embedding=[2.0] * DIMENSIONS),
            SimpleNamespace(index=0, embedding=[1.0] * DIMENSIONS),
        ]
        with patch("openai.OpenAI", return_value=client):
            embedder = OpenAIEmbedder("text-embedding-3-small")
        vectors = embedder.embed_documents(["first", "second"])
        self.assertEqual(vectors[0][0], 1.0)
        self.assertEqual(vectors[1][0], 2.0)
        client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=["first", "second"],
            dimensions=1024,
            encoding_format="float",
        )
        self.assertEqual(embedder.embed_documents([]), [])
        client.embeddings.create.assert_called_once()

    def test_openrouter_embedder_configures_openrouter_client(self):
        with patch("openai.OpenAI") as constructor:
            OpenAIEmbedder(
                "embedding-model",
                api_key="router-key",
                base_url="https://openrouter.ai/api/v1",
            )
        constructor.assert_called_once_with(
            api_key="router-key",
            base_url="https://openrouter.ai/api/v1",
        )


if __name__ == "__main__":
    unittest.main()
