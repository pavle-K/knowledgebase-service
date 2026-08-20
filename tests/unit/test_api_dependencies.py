import pytest
from fastapi import HTTPException

from src.api.dependencies import get_conn


def test_get_conn_raises_clearly_when_database_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL_RO", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        next(get_conn())
    assert exc_info.value.status_code == 500
