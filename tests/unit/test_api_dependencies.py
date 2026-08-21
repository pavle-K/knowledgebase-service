from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException, Request

from src.api.dependencies import get_conn, get_conn_rw, get_github_client_dep


def _request(privileged: bool) -> Request:
    return cast(Request, SimpleNamespace(state=SimpleNamespace(privileged=privileged)))


def test_get_conn_raises_clearly_when_public_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_RO_PUBLIC", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        next(get_conn(_request(privileged=False)))
    assert exc_info.value.status_code == 500
    assert "DATABASE_URL_RO_PUBLIC" in exc_info.value.detail


def test_get_conn_raises_clearly_when_privileged_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_RO", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        next(get_conn(_request(privileged=True)))
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "DATABASE_URL_RO is not configured"


def test_get_conn_defaults_to_the_public_role_when_tier_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unauthenticated-looking request must never fall through to app_ro."""
    monkeypatch.delenv("DATABASE_URL_RO_PUBLIC", raising=False)
    monkeypatch.setenv("DATABASE_URL_RO", "postgresql://app_ro:pw@localhost/db")
    request = cast(Request, SimpleNamespace(state=SimpleNamespace()))
    with pytest.raises(HTTPException) as exc_info:
        next(get_conn(request))
    assert "DATABASE_URL_RO_PUBLIC" in exc_info.value.detail


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
