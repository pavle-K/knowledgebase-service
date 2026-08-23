import uuid

import psycopg

from src.ingestion.commits import commit_exists, sync_commit
from src.ingestion.documents import upsert_project
from src.ingestion.embedder import FakeEmbedder
from src.ingestion.github_client import CommitDetail, CommitFile, CommitInfo, RepoInfo
from src.query.synthesizer import FakeLLMClient

REAL_CHANGE_PATCH = "@@ -1,2 +1,3 @@\n def f():\n+    log.info('x')\n     return 1\n"


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


def _commit_info(sha: str = "abc123") -> CommitInfo:
    return CommitInfo(
        sha=sha, message="Add logging", author="pavle-K", committed_at="2026-01-15T10:00:00Z"
    )


def test_sync_commit_ingests_and_embeds(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient(response="Adds a logging call to function f.")
    detail = CommitDetail(
        files=[CommitFile(filename="src/f.py", additions=1, deletions=0, patch=REAL_CHANGE_PATCH)],
        additions=1,
        deletions=0,
    )

    status = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)

    assert status == "ingested"
    assert llm.call_count == 1
    assert embedder.call_count == 1

    row = db_conn.execute(
        "select message, diff_summary, files_changed, additions, deletions"
        " from commits where project_id = %s and sha = 'abc123'",
        (project_id,),
    ).fetchone()
    assert row == ("Add logging", "Adds a logging call to function f.", ["src/f.py"], 1, 0)


def test_sync_commit_is_idempotent(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient()
    detail = CommitDetail(
        files=[CommitFile(filename="src/f.py", additions=1, deletions=0, patch=REAL_CHANGE_PATCH)],
        additions=1,
        deletions=0,
    )

    first = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)
    calls_after_first = (embedder.call_count, llm.call_count)
    second = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)

    assert first == "ingested"
    assert second == "skipped_existing"
    assert (embedder.call_count, llm.call_count) == calls_after_first


def test_sync_commit_skips_noise_without_calling_llm_or_embedder(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient()
    detail = CommitDetail(
        files=[CommitFile(filename="package-lock.json", additions=50, deletions=3, patch="...")],
        additions=50,
        deletions=3,
    )

    status = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)

    assert status == "skipped_noise"
    assert llm.call_count == 0
    assert embedder.call_count == 0
    assert commit_exists(db_conn, project_id, "abc123") is False


def test_sync_commit_skips_secret_without_calling_llm_or_embedder(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient()
    secret_patch = '@@ -1 +1 @@\n-x = 1\n+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
    detail = CommitDetail(
        files=[CommitFile(filename="src/config.py", additions=1, deletions=1, patch=secret_patch)],
        additions=1,
        deletions=1,
    )

    status = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)

    assert status == "skipped_secret"
    assert llm.call_count == 0
    assert embedder.call_count == 0

    row = db_conn.execute(
        "select diff_summary, embedding from commits where project_id = %s and sha = 'abc123'",
        (project_id,),
    ).fetchone()
    assert row == (None, None)

    finding = db_conn.execute(
        "select file_path, rule_id from secret_scan_findings where project_id = %s", (project_id,)
    ).fetchone()
    assert finding == ("commit:abc123", "AWS Access Key")


def test_sync_commit_excludes_env_file_diff_from_llm_and_embedder(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient(response="Adds a logging call.")
    secret_patch = "@@ -1 +1 @@\n-x = 1\n+INTERNAL_TOKEN=super-secret-value\n"
    detail = CommitDetail(
        files=[
            CommitFile(filename=".env", additions=1, deletions=1, patch=secret_patch),
            CommitFile(filename="src/f.py", additions=1, deletions=0, patch=REAL_CHANGE_PATCH),
        ],
        additions=2,
        deletions=1,
    )

    status = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)

    assert status == "ingested"
    assert "super-secret-value" not in (llm.last_user or "")
    assert "src/f.py" in (llm.last_user or "")

    row = db_conn.execute(
        "select files_changed from commits where project_id = %s and sha = 'abc123'",
        (project_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == [".env", "src/f.py"]


def test_sync_commit_skips_when_only_excluded_paths_changed(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, _fake_repo())
    embedder = FakeEmbedder()
    llm = FakeLLMClient()
    detail = CommitDetail(
        files=[CommitFile(filename=".env", additions=1, deletions=1, patch="...")],
        additions=1,
        deletions=1,
    )

    status = sync_commit(db_conn, project_id, _commit_info(), detail, embedder, llm)

    assert status == "skipped_noise"
    assert llm.call_count == 0
    assert embedder.call_count == 0
    assert commit_exists(db_conn, project_id, "abc123") is False
