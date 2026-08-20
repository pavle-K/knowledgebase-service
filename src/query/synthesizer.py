"""Synthesizes a plain-English answer from vector search results, via a pluggable LLM client."""

from __future__ import annotations

import os
from typing import Protocol

from src.query.vector_search import SearchResult

SYSTEM_PROMPT = (
    "You answer questions about the user's own software projects using only the provided "
    "context snippets. Be concise. If the context doesn't answer the question, say so."
)


class LLMClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class AnthropicLLMClient:
    def __init__(self, api_key: str, model: str) -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in response.content if block.type == "text")


class FakeLLMClient:
    """Returns a canned response, no network calls. For tests only."""

    def __init__(self, response: str = "fake synthesized answer") -> None:
        self.response = response
        self.call_count = 0
        self.last_system: str | None = None
        self.last_user: str | None = None

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        self.last_system = system
        self.last_user = user
        return self.response


def get_llm_client() -> LLMClient:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return AnthropicLLMClient(api_key=api_key, model=model)


def format_context(results: list[SearchResult]) -> str:
    if not results:
        return "No matching documents were found."
    return "\n\n".join(f"[{_context_label(r)}]\n{r.content}" for r in results)


def _context_label(result: SearchResult) -> str:
    if result.layer == "code" and result.symbol_name:
        symbol = f"{result.symbol_type} {result.symbol_name}"
        return f"{result.project_name} - {result.source_path} ({symbol})"
    return f"{result.project_name} - {result.source_path}"


def synthesize(query: str, results: list[SearchResult], llm: LLMClient) -> str:
    user_prompt = f"Question: {query}\n\nContext:\n{format_context(results)}"
    return llm.complete(SYSTEM_PROMPT, user_prompt)
