from src.query.sql_generator import generate_sql
from src.query.synthesizer import FakeLLMClient


def test_generate_sql_strips_markdown_fences() -> None:
    llm = FakeLLMClient(response="```sql\nselect name from projects\n```")
    sql = generate_sql("list projects", "projects: name (text)", llm)
    assert sql == "select name from projects"


def test_generate_sql_passes_through_raw_sql() -> None:
    llm = FakeLLMClient(response="select name from projects")
    sql = generate_sql("list projects", "projects: name (text)", llm)
    assert sql == "select name from projects"


def test_generate_sql_includes_previous_error_in_prompt() -> None:
    llm = FakeLLMClient(response="select name from projects")
    generate_sql(
        "list projects", "projects: name (text)", llm, previous_error="column x does not exist"
    )
    assert "column x does not exist" in (llm.last_user or "")
