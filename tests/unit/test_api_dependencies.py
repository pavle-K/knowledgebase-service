import pytest
from fastapi import HTTPException

from src.api.dependencies import get_conn, get_conn_rw, get_github_client_dep


def test_get_conn_raises_clearly_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_RO", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        next(get_conn())
    assert exc_info.value.status_code == 500


def test_get_conn_rw_raises_clearly_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_RW", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        next(get_conn_rw())
    assert exc_info.value.status_code == 500


def test_get_github_client_dep_raises_clearly_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        next(get_github_client_dep())
    assert exc_info.value.status_code == 500
