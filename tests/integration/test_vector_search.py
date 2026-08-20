import datetime as dt
import uuid

import psycopg

from src.ingestion.code import sync_code_file
from src.ingestion.commits import sync_commit
from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder, format_vector
from src.ingestion.github_client import CommitDetail, CommitFile, CommitInfo, RepoInfo
from src.query.synthesizer import FakeLLMClient
from src.query.vector_search import search_all, search_code_chunks, search_commits, search_documents
from tests.integration.conftest import MigratedDb


def _fake_repo() -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"demo-project-{unique}",
        full_name=f"pavle-K/demo-project-{unique}",
        html_url=f"https://github.com/pavle-K/demo-project-{unique}",
        description="A demo project",
        default_branch="main",
        is_private=False,
        fork=False,
    )


def _insert_document(
    conn: psycopg.Connection,
    project_id: uuid.UUID,
    source_path: str,
    content: str,
    embedder: FakeEmbedder,
) -> None:
    embedding = embedder.embed([content])[0]
    conn.execute(
        """
        insert into documents
            (project_id, doc_type, source_path, chunk_index, content, embedding, content_hash)
        values (%s, 'readme', %s, 0, %s, %s::vector, 'hash')
        """,
        (project_id, source_path, content, format_vector(embedding)),
    )


def test_search_documents_ranks_exact_match_first(
    db_conn: psycopg.Connection, migrated_db: MigratedDb
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()

    _insert_document(db_conn, project_id, "README.md", "content about databases", embedder)
    _insert_document(
        db_conn, project_id, "docs/other.md", "totally unrelated other topic", embedder
    )
    db_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        results = search_documents(ro_conn, "content about databases", embedder, limit=5)

    assert len(results) == 2
    assert results[0].source_path == "README.md"
    assert results[0].distance < results[1].distance


def test_search_documents_respects_limit(
    db_conn: psycopg.Connection, migrated_db: MigratedDb
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()

    for i in range(3):
        _insert_document(db_conn, project_id, f"doc{i}.md", f"content number {i}", embedder)
    db_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        results = search_documents(ro_conn, "content number 0", embedder, limit=2)

    assert len(results) == 2


def test_search_code_chunks_ranks_exact_match_first(
    db_conn: psycopg.Connection, migrated_db: MigratedDb
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()

    sync_code_file(
        db_conn, project_id, "src/rate_limit.py", "def rate_limit():\n    return True\n", embedder
    )
    sync_code_file(
        db_conn, project_id, "src/unrelated.py", "def totally_unrelated():\n    pass\n", embedder
    )
    db_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        results = search_code_chunks(
            ro_conn, "def rate_limit():\n    return True", embedder, limit=5
        )

    assert results[0].symbol_name == "rate_limit"
    assert results[0].symbol_type == "function"
    assert results[0].layer == "code"


def test_search_all_merges_documents_and_code_by_distance(
    db_conn: psycopg.Connection, migrated_db: MigratedDb
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()

    target = "def rate_limit():\n    return True\n"
    _insert_document(db_conn, project_id, "README.md", "unrelated doc content", embedder)
    sync_code_file(db_conn, project_id, "src/rate_limit.py", target, embedder)
    db_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        results = search_all(ro_conn, target, embedder, limit=5)

    assert any(r.layer == "code" and r.symbol_name == "rate_limit" for r in results)
    assert results == sorted(results, key=lambda r: r.distance)


def test_search_commits_ranks_exact_match_first(
    db_conn: psycopg.Connection, migrated_db: MigratedDb
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient(response="Adds rate limiting to the API.")

    detail = CommitDetail(
        files=[
            CommitFile(filename="src/f.py", additions=1, deletions=0, patch="@@ -1 +1,2 @@\n+x\n")
        ],
        additions=1,
        deletions=0,
    )
    info = CommitInfo(
        sha="abc123",
        message="Add rate limiting",
        author="pavle-K",
        committed_at="2026-01-15T10:00:00Z",
    )
    sync_commit(db_conn, project_id, info, detail, embedder, llm)

    other_info = CommitInfo(
        sha="def456", message="Unrelated fix", author="pavle-K", committed_at="2026-01-10T10:00:00Z"
    )
    other_llm = FakeLLMClient(response="Totally unrelated change.")
    sync_commit(db_conn, project_id, other_info, detail, embedder, other_llm)
    db_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        results = search_commits(
            ro_conn, "Add rate limiting\n\nAdds rate limiting to the API.", embedder, limit=5
        )

    assert results[0].source_path == "abc123"
    assert results[0].layer == "commit"
    assert results[0].committed_at is not None


def test_search_commits_time_filter(db_conn: psycopg.Connection, migrated_db: MigratedDb) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    detail = CommitDetail(
        files=[
            CommitFile(filename="src/f.py", additions=1, deletions=0, patch="@@ -1 +1,2 @@\n+x\n")
        ],
        additions=1,
        deletions=0,
    )

    old_info = CommitInfo(
        sha="old111", message="Old change", author="pavle-K", committed_at="2020-01-01T00:00:00Z"
    )
    new_info = CommitInfo(
        sha="new222", message="New change", author="pavle-K", committed_at="2026-01-01T00:00:00Z"
    )
    sync_commit(db_conn, project_id, old_info, detail, embedder, FakeLLMClient())
    sync_commit(db_conn, project_id, new_info, detail, embedder, FakeLLMClient())
    db_conn.commit()

    with psycopg.connect(migrated_db.app_ro_url) as ro_conn:
        results = search_commits(
            ro_conn, "change", embedder, limit=10, since=dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
        )

    shas = {r.source_path for r in results}
    assert "new222" in shas
    assert "old111" not in shas
