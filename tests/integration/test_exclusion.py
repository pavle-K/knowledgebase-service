import uuid

import psycopg

from src.ingestion.documents import upsert_project
from src.ingestion.exclusion import purge_project_data
from src.ingestion.github_client import RepoInfo


def _fake_repo(name: str) -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"{name}-{unique}",
        full_name=f"pavle-K/{name}-{unique}",
        html_url=f"https://github.com/{name}-{unique}",
        description="demo",
        default_branch="main",
        is_private=False,
        fork=False,
    )


def _seed_all_layers(conn: psycopg.Connection, project_id: uuid.UUID) -> None:
    conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, content_hash)
        values (%s, 'readme', 'README.md', 0, 'hello', 'hash1')
        """,
        (project_id,),
    )
    conn.execute(
        """
        insert into code_chunks
            (project_id, file_path, symbol_name, symbol_type, language, content, content_hash)
        values (%s, 'src/app.py', 'foo', 'function', 'python', 'def foo(): pass', 'hash2')
        """,
        (project_id,),
    )
    conn.execute(
        """
        insert into commits (project_id, sha, message, author, diff_summary)
        values (%s, 'abc123', 'a commit', 'pavle-K', 'summary')
        """,
        (project_id,),
    )
    conn.execute(
        """
        insert into exposed_interfaces (project_id, kind, identifier, source)
        values (%s, 'http_endpoint', 'GET /x', 'manifest')
        """,
        (project_id,),
    )
    conn.execute(
        """
        insert into dependencies (consumer_project_id, kind, identifier, external_name, source)
        values (%s, 'package', 'boto3', 'boto3', 'static_analysis')
        """,
        (project_id,),
    )


def _counts(conn: psycopg.Connection, project_id: uuid.UUID) -> dict[str, int]:
    return {
        table: conn.execute(
            f"select count(*) from {table} where {col} = %s", (project_id,)
        ).fetchone()[0]  # type: ignore[index]
        for table, col in (
            ("documents", "project_id"),
            ("code_chunks", "project_id"),
            ("commits", "project_id"),
            ("exposed_interfaces", "project_id"),
            ("dependencies", "consumer_project_id"),
        )
    }


def test_purge_project_data_deletes_rows_across_all_layers(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("purge-target"))
    _seed_all_layers(db_conn, project_id)
    assert all(n == 1 for n in _counts(db_conn, project_id).values())

    result = purge_project_data(db_conn, project_id)

    assert result == {
        "documents": 1,
        "code_chunks": 1,
        "commits": 1,
        "exposed_interfaces": 1,
        "dependencies": 1,
    }
    assert all(n == 0 for n in _counts(db_conn, project_id).values())


def test_purge_project_data_is_a_no_op_for_a_project_with_no_data(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, _fake_repo("never-synced"))

    result = purge_project_data(db_conn, project_id)

    assert result == {
        "documents": 0,
        "code_chunks": 0,
        "commits": 0,
        "exposed_interfaces": 0,
        "dependencies": 0,
    }


def test_purge_project_data_does_not_touch_other_projects(db_conn: psycopg.Connection) -> None:
    excluded_id = upsert_project(db_conn, _fake_repo("excluded"))
    kept_id = upsert_project(db_conn, _fake_repo("kept"))
    _seed_all_layers(db_conn, excluded_id)
    _seed_all_layers(db_conn, kept_id)

    purge_project_data(db_conn, excluded_id)

    assert all(n == 0 for n in _counts(db_conn, excluded_id).values())
    assert all(n == 1 for n in _counts(db_conn, kept_id).values())
