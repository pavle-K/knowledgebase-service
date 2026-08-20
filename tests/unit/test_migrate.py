import pytest

from src.db.migrate import substitute_env_vars


def test_substitutes_known_placeholder() -> None:
    result = substitute_env_vars("password '${PW}'", {"PW": "secret"})
    assert result == "password 'secret'"


def test_substitutes_multiple_placeholders() -> None:
    result = substitute_env_vars("${A} and ${B}", {"A": "x", "B": "y"})
    assert result == "x and y"


def test_missing_placeholder_raises() -> None:
    with pytest.raises(KeyError):
        substitute_env_vars("${MISSING}", {})


def test_no_placeholders_returns_unchanged() -> None:
    sql = "select * from projects;"
    assert substitute_env_vars(sql, {}) == sql
