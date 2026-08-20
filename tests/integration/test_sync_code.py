import uuid

import psycopg

from src.ingestion.code import sync_code_file
from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder
from src.ingestion.github_client import RepoInfo

FAKE_AWS_KEY_PY = 'def connect():\n    aws_key = "AKIAIOSFODNN7EXAMPLE"\n    return aws_key\n'


def _fake_repo() -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"demo-{unique}",
        full_name=f"pavle-K/demo-{unique}",
        html_url=f"https://github.com/pavle-K/demo-{unique}",
        description="demo",
        default_branch="main",
        is_private=False,
        fork=False,
    )


def test_sync_code_file_embeds_new_content(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    content = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"

    stats = sync_code_file(db_conn, project_id, "src/math.py", content, embedder)

    assert stats == {"chunks": 2, "embedded": 2, "skipped_unchanged": 0, "skipped_secret": 0}
    rows = db_conn.execute(
        "select symbol_name, symbol_type from code_chunks"
        " where project_id = %s order by start_line",
        (project_id,),
    ).fetchall()
    assert rows == [("add", "function"), ("sub", "function")]


def test_sync_code_file_skips_unchanged_on_rerun(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    content = "def add(a, b):\n    return a + b\n"

    sync_code_file(db_conn, project_id, "src/math.py", content, embedder)
    calls_after_first = embedder.call_count

    stats = sync_code_file(db_conn, project_id, "src/math.py", content, embedder)

    assert stats == {"chunks": 1, "embedded": 0, "skipped_unchanged": 1, "skipped_secret": 0}
    assert embedder.call_count == calls_after_first


def test_sync_code_file_reembeds_changed_content(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()

    original = "def add(a, b):\n    return a + b\n"
    sync_code_file(db_conn, project_id, "src/math.py", original, embedder)
    calls_after_first = embedder.call_count

    stats = sync_code_file(
        db_conn, project_id, "src/math.py", "def add(a, b):\n    return a + b + 1\n", embedder
    )

    assert stats["embedded"] == 1
    assert embedder.call_count == calls_after_first + 1


def test_sync_code_file_skips_secret_chunk(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()

    stats = sync_code_file(db_conn, project_id, "src/config.py", FAKE_AWS_KEY_PY, embedder)

    assert stats["skipped_secret"] == 1
    doc_rows = db_conn.execute(
        "select count(*) from code_chunks where project_id = %s", (project_id,)
    ).fetchone()
    assert doc_rows is not None
    assert doc_rows[0] == 0
    finding_rows = db_conn.execute(
        "select file_path, rule_id from secret_scan_findings where project_id = %s", (project_id,)
    ).fetchall()
    assert finding_rows == [("src/config.py", "AWS Access Key")]


def test_sync_code_file_module_level_heuristic_chunks_are_idempotent(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    content = "\n".join(f"line {i}" for i in range(100))

    sync_code_file(db_conn, project_id, "deploy.sh", content, embedder)
    calls_after_first = embedder.call_count
    stats = sync_code_file(db_conn, project_id, "deploy.sh", content, embedder)

    assert stats["embedded"] == 0
    assert stats["skipped_unchanged"] == stats["chunks"]
    assert embedder.call_count == calls_after_first

    rows = db_conn.execute(
        "select count(*) from code_chunks where project_id = %s", (project_id,)
    ).fetchone()
    assert rows is not None
    assert rows[0] == stats["chunks"]
