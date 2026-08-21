import pytest
from pydantic import ValidationError

from src.api.schemas import MAX_QUERY_LENGTH, QueryRequest, _max_query_length


def test_query_within_max_length_is_accepted() -> None:
    QueryRequest(query="x" * MAX_QUERY_LENGTH)


def test_query_over_max_length_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query="x" * (MAX_QUERY_LENGTH + 1))


def test_max_query_length_parses_env_value() -> None:
    assert _max_query_length("500") == 500


@pytest.mark.parametrize("raw", [None, ""])
def test_max_query_length_defaults_when_unset(raw: str | None) -> None:
    assert _max_query_length(raw) == 2000
