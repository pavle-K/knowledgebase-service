import pytest

from src.ingestion.embedder import EMBEDDING_DIM, FakeEmbedder, format_vector, get_embedder


def test_fake_embedder_is_deterministic() -> None:
    embedder = FakeEmbedder()
    first = embedder.embed(["hello world"])[0]
    second = embedder.embed(["hello world"])[0]
    assert first == second


def test_fake_embedder_differs_by_input() -> None:
    embedder = FakeEmbedder()
    a, b = embedder.embed(["text a", "text b"])
    assert a != b


def test_fake_embedder_dimension() -> None:
    embedder = FakeEmbedder()
    vector = embedder.embed(["x"])[0]
    assert len(vector) == EMBEDDING_DIM


def test_fake_embedder_tracks_call_count() -> None:
    embedder = FakeEmbedder()
    assert embedder.call_count == 0
    embedder.embed(["a"])
    embedder.embed(["b", "c"])
    assert embedder.call_count == 2


def test_get_embedder_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    assert isinstance(get_embedder(), FakeEmbedder)


def test_get_embedder_openai_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        get_embedder()


def test_get_embedder_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "not-a-real-provider")
    with pytest.raises(ValueError):
        get_embedder()


def test_format_vector() -> None:
    assert format_vector([0.1, -0.2, 1.0]) == "[0.10000000,-0.20000000,1.00000000]"
