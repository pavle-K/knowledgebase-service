import psycopg

from src.query.sql_generator import introspect_schema


def test_introspect_schema_lists_real_tables_and_columns(db_conn: psycopg.Connection) -> None:
    schema = introspect_schema(db_conn)
    assert "projects:" in schema
    assert "name" in schema
    assert "documents:" in schema
    assert "code_chunks:" in schema
