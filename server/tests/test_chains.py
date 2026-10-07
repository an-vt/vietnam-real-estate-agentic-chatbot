"""LLM provider factory tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.graph.chains import get_llm


class LLMFactoryTests(unittest.TestCase):
    def tearDown(self):
        get_llm.cache_clear()

    def settings(self, provider: str, *, llm_api_key: str | None = "router-key"):
        return SimpleNamespace(
            llm_provider=provider,
            llm_model="chosen-model",
            llm_api_key=llm_api_key,
            ollama_base_url="http://ollama:11434",
            llm_temperature=0.2,
        )

    def test_local_uses_chat_ollama(self):
        with patch("src.graph.chains.settings", self.settings("local")), \
             patch("src.graph.chains.ChatOllama") as constructor:
            self.assertIs(get_llm(96), constructor.return_value)
        constructor.assert_called_once_with(
            model="chosen-model",
            base_url="http://ollama:11434",
            temperature=0.2,
            num_predict=96,
            client_kwargs={"timeout": 30},
        )

    def test_openai_uses_chat_openai(self):
        with patch("src.graph.chains.settings", self.settings("openai", llm_api_key="openai-key")), \
             patch("src.graph.chains.ChatOpenAI") as constructor:
            self.assertIs(get_llm(96), constructor.return_value)
        constructor.assert_called_once_with(
            model="chosen-model",
            temperature=0.2,
            max_tokens=96,
            timeout=30,
            max_retries=2,
            api_key="openai-key",
        )

    def test_openrouter_uses_chat_openai_with_router_endpoint(self):
        with patch("src.graph.chains.settings", self.settings("openrouter")), \
             patch("src.graph.chains.ChatOpenAI") as constructor:
            self.assertIs(get_llm(96), constructor.return_value)
        constructor.assert_called_once_with(
            model="chosen-model",
            temperature=0.2,
            max_tokens=96,
            timeout=30,
            max_retries=2,
            api_key="router-key",
            base_url="https://openrouter.ai/api/v1",
            extra_body={"reasoning": {"effort": "none"}},
        )

    def test_factory_rejects_unknown_provider(self):
        with patch("src.graph.chains.settings", self.settings("unknown")):
            with self.assertRaisesRegex(ValueError, "Invalid LLM_PROVIDER"):
                get_llm()

    def test_openrouter_requires_api_key(self):
        with patch("src.graph.chains.settings", self.settings("openrouter", llm_api_key=None)):
            with self.assertRaisesRegex(ValueError, "LLM_API_KEY"):
                get_llm()


if __name__ == "__main__":
    unittest.main()
