"""Embedding providers shared by listing ingestion and vector retrieval."""

from functools import lru_cache
from typing import Protocol

from .config import get_openai_client_config, settings

DIMENSIONS = 1024


class Embedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)
        self.model.max_seq_length = 512
        if str(self.model.device).startswith("mps"):
            self.model.half()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self.model.encode(texts, normalize_embeddings=True).tolist()


class OpenAIEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        from openai import OpenAI

        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model_name = model_name

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(
            model=self.model_name,
            input=texts,
            dimensions=DIMENSIONS,
            encoding_format="float",
        )
        if len(response.data) != len(texts):
            raise ValueError("Embedding provider returned the wrong number of vectors")
        return [
            item.embedding
            for item in sorted(response.data, key=lambda item: item.index)
        ]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.llm_provider == "local":
        return LocalEmbedder(settings.llm_embedding_model)
    if settings.llm_provider in {"openai", "openrouter"}:
        client = get_openai_client_config(settings.llm_provider, settings)
        kwargs = {}
        if client.api_key:
            kwargs["api_key"] = client.api_key
        if client.base_url:
            kwargs["base_url"] = client.base_url
        return OpenAIEmbedder(settings.llm_embedding_model, **kwargs)
    raise ValueError(f"Invalid LLM_PROVIDER: {settings.llm_provider}")
