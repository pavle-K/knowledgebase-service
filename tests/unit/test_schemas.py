import pytest
from pydantic import ValidationError

from src.api.schemas import MAX_QUERY_LENGTH, QueryRequest


def test_query_within_max_length_is_accepted() -> None:
    QueryRequest(query="x" * MAX_QUERY_LENGTH)


def test_query_over_max_length_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryRequest(query="x" * (MAX_QUERY_LENGTH + 1))
