import psycopg

from src.ingestion.documents import sync_document, upsert_project
from src.ingestion.embedder import FakeEmbedder
from src.ingestion.github_client import RepoInfo

FAKE_REPO = RepoInfo(
    name="demo-project",
    full_name="pavle-K/demo-project",
    html_url="https://github.com/pavle-K/demo-project",
    description="A demo project",
    default_branch="main",
    is_private=False,
    fork=False,
)

FAKE_AWS_KEY = 'AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'


def test_upsert_project_is_idempotent_and_updates_fields(db_conn: psycopg.Connection) -> None:
    first_id = upsert_project(db_conn, FAKE_REPO)
    second_id = upsert_project(db_conn, FAKE_REPO)
    assert first_id == second_id

    updated_repo = RepoInfo(**{**FAKE_REPO.__dict__, "description": "Updated description"})
    upsert_project(db_conn, updated_repo)

    row = db_conn.execute("select description from projects where id = %s", (first_id,)).fetchone()
    assert row is not None
    assert row[0] == "Updated description"


def test_sync_document_embeds_new_content(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()
    content = "# Title\nintro\n\n## Section\nbody\n"

    stats = sync_document(db_conn, project_id, "readme", "README.md", content, embedder)

    assert stats == {"chunks": 2, "embedded": 2, "skipped_unchanged": 0, "skipped_secret": 0}
    assert embedder.call_count == 2

    rows = db_conn.execute(
        "select chunk_index, content_hash from documents"
        " where project_id = %s and source_path = 'README.md' order by chunk_index",
        (project_id,),
    ).fetchall()
    assert len(rows) == 2


def test_sync_document_skips_unchanged_content_on_rerun(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()
    content = "# Title\nsame content every time\n"

    sync_document(db_conn, project_id, "readme", "README.md", content, embedder)
    calls_after_first = embedder.call_count

    stats = sync_document(db_conn, project_id, "readme", "README.md", content, embedder)

    assert stats == {"chunks": 1, "embedded": 0, "skipped_unchanged": 1, "skipped_secret": 0}
    assert embedder.call_count == calls_after_first


def test_sync_document_reembeds_changed_content(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()

    sync_document(db_conn, project_id, "readme", "README.md", "# Title\nversion one\n", embedder)
    calls_after_first = embedder.call_count

    stats = sync_document(
        db_conn, project_id, "readme", "README.md", "# Title\nversion two\n", embedder
    )

    assert stats["embedded"] == 1
    assert embedder.call_count == calls_after_first + 1


def test_sync_document_skips_and_records_secret_content(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()

    stats = sync_document(db_conn, project_id, "readme", "README.md", FAKE_AWS_KEY, embedder)

    assert stats == {"chunks": 1, "embedded": 0, "skipped_unchanged": 0, "skipped_secret": 1}
    assert embedder.call_count == 0

    doc_rows = db_conn.execute(
        "select count(*) from documents where project_id = %s", (project_id,)
    ).fetchone()
    assert doc_rows is not None
    assert doc_rows[0] == 0

    finding_rows = db_conn.execute(
        "select file_path, rule_id from secret_scan_findings where project_id = %s", (project_id,)
    ).fetchall()
    assert len(finding_rows) == 1
    assert finding_rows[0] == ("README.md", "AWS Access Key")
    assert "AKIAIOSFODNN7EXAMPLE" not in str(finding_rows)


def test_sync_document_skips_excluded_path_entirely(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()

    stats = sync_document(db_conn, project_id, "docs", "docs/.env", FAKE_AWS_KEY, embedder)

    assert stats == {"chunks": 0, "embedded": 0, "skipped_unchanged": 0, "skipped_secret": 0}
    assert embedder.call_count == 0

    doc_rows = db_conn.execute(
        "select count(*) from documents where project_id = %s", (project_id,)
    ).fetchone()
    assert doc_rows is not None
    assert doc_rows[0] == 0

    finding_rows = db_conn.execute(
        "select count(*) from secret_scan_findings where project_id = %s", (project_id,)
    ).fetchone()
    assert finding_rows is not None
    assert finding_rows[0] == 0


def test_secret_finding_is_not_duplicated_on_rerun(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()

    sync_document(db_conn, project_id, "readme", "README.md", FAKE_AWS_KEY, embedder)
    sync_document(db_conn, project_id, "readme", "README.md", FAKE_AWS_KEY, embedder)

    finding_rows = db_conn.execute(
        "select count(*) from secret_scan_findings where project_id = %s", (project_id,)
    ).fetchone()
    assert finding_rows is not None
    assert finding_rows[0] == 1


def test_secret_in_one_paragraph_does_not_drop_surrounding_content(
    db_conn: psycopg.Connection,
) -> None:
    project_id = upsert_project(db_conn, FAKE_REPO)
    embedder = FakeEmbedder()
    content = (
        "## Configuration\n"
        "Useful setup notes that explain how the service is wired together.\n\n"
        f"{FAKE_AWS_KEY}\n"
        "More useful architecture notes that should still be retrievable.\n"
    )

    stats = sync_document(db_conn, project_id, "readme", "README.md", content, embedder)

    assert stats == {"chunks": 3, "embedded": 2, "skipped_unchanged": 0, "skipped_secret": 1}

    rows = db_conn.execute(
        "select content from documents where project_id = %s order by chunk_index", (project_id,)
    ).fetchall()
    stored_content = [row[0] for row in rows]
    assert any("Useful setup notes" in c for c in stored_content)
    assert any("More useful architecture notes" in c for c in stored_content)
    assert not any("AKIAIOSFODNN7EXAMPLE" in c for c in stored_content)
