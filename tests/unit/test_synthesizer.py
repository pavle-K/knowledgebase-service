from unittest.mock import patch

import pytest

from src.query.synthesizer import (
    SYSTEM_PROMPT,
    FakeLLMClient,
    format_context,
    get_langfuse_client,
    get_llm_client,
    synthesize,
)
from src.query.vector_search import SearchResult

RESULT_A = SearchResult(
    project_name="demo-project",
    source_path="README.md",
    content="Uses FastAPI and Postgres.",
    distance=0.1,
)


def test_format_context_empty() -> None:
    assert format_context([]) == "No matching documents were found."


def test_format_context_includes_project_and_content() -> None:
    context = format_context([RESULT_A])
    assert "demo-project" in context
    assert "README.md" in context
    assert "Uses FastAPI and Postgres." in context


def test_synthesize_passes_system_prompt_and_returns_llm_response() -> None:
    llm = FakeLLMClient(response="canned answer")
    answer = synthesize("what does demo-project use?", [RESULT_A], llm)

    assert answer == "canned answer"
    assert llm.call_count == 1
    assert llm.last_system == SYSTEM_PROMPT
    assert "what does demo-project use?" in (llm.last_user or "")
    assert "demo-project" in (llm.last_user or "")


def test_get_llm_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_llm_client()


def test_get_llm_client_uses_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    client = get_llm_client()
    assert client._model == "claude-haiku-4-5-20251001"


def test_get_llm_client_respects_llm_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("LLM_MODEL", "claude-opus-5")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    client = get_llm_client()
    assert client._model == "claude-opus-5"


def test_get_llm_client_disables_langfuse_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    client = get_llm_client()
    assert client._langfuse is None


def test_get_langfuse_client_returns_none_without_both_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-fake")
    assert get_langfuse_client() is None

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-fake")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert get_langfuse_client() is None


def test_get_langfuse_client_constructs_when_both_keys_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-fake")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-fake")
    sentinel = object()
    with patch("langfuse.get_client", return_value=sentinel) as mock_get_client:
        assert get_langfuse_client() is sentinel
        mock_get_client.assert_called_once()
