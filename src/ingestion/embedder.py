"""Pluggable embedding provider, selected via EMBEDDING_PROVIDER. Never hardcode the provider."""

from __future__ import annotations

import hashlib
import os
from typing import Protocol

EMBEDDING_DIM = 1536


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small") -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            input=texts, model=self._model, dimensions=EMBEDDING_DIM
        )
        return [item.embedding for item in response.data]


class FakeEmbedder:
    """Deterministic hash-seeded vectors, no network calls. For tests only."""

    def __init__(self) -> None:
        self.call_count = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        return [self._vector_for(text) for text in texts]

    @staticmethod
    def _vector_for(text: str) -> list[float]:
        values = []
        for i in range(EMBEDDING_DIM):
            digest = hashlib.sha256(f"{text}:{i}".encode()).digest()
            values.append(int.from_bytes(digest[:4], "big") / 2**32)
        return values


def get_embedder() -> Embedder:
    provider = os.environ.get("EMBEDDING_PROVIDER", "openai")
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        return OpenAIEmbedder(api_key=api_key)
    if provider == "fake":
        return FakeEmbedder()
    raise ValueError(f"unknown EMBEDDING_PROVIDER: {provider}")


def format_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"
