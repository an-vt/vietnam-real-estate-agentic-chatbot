"""Embedding providers shared by listing ingestion and vector retrieval."""

from functools import lru_cache
from typing import Protocol

from .config import settings

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
    def __init__(self, model_name: str):
        from openai import OpenAI

        self.client = OpenAI()
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
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    if settings.embedding_provider == "local":
        return LocalEmbedder(settings.embedding_model)
    if settings.embedding_provider == "openai":
        return OpenAIEmbedder(settings.embedding_model)
    raise ValueError(f"Invalid EMBEDDING_PROVIDER: {settings.embedding_provider}")
