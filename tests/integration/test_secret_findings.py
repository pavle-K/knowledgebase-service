import uuid

import psycopg

from src.ingestion.documents import upsert_project
from src.ingestion.github_client import RepoInfo
from src.ingestion.secret_findings import mark_secret_resolved


def _fake_repo(name: str) -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"{name}-{unique}",
        full_name=f"pavle-K/{name}-{unique}",
        html_url=f"https://github.com/pavle-K/{name}-{unique}",
        description="demo",
        default_branch="main",
        is_private=False,
        fork=False,
    )


def test_mark_secret_resolved_sets_timestamp(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("secret-proj"))
    row = db_conn.execute(
        "insert into secret_scan_findings (project_id, file_path, rule_id)"
        " values (%s, 'README.md', 'AWS Access Key') returning id",
        (project_id,),
    ).fetchone()
    assert row is not None
    finding_id = row[0]

    resolved = mark_secret_resolved(db_conn, finding_id)

    assert resolved is True
    check = db_conn.execute(
        "select resolved_at from secret_scan_findings where id = %s", (finding_id,)
    ).fetchone()
    assert check is not None
    assert check[0] is not None


def test_mark_secret_resolved_twice_is_a_noop_on_second_call(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("secret-proj2"))
    row = db_conn.execute(
        "insert into secret_scan_findings (project_id, file_path, rule_id)"
        " values (%s, 'README.md', 'AWS Access Key') returning id",
        (project_id,),
    ).fetchone()
    assert row is not None
    finding_id = row[0]

    first = mark_secret_resolved(db_conn, finding_id)
    second = mark_secret_resolved(db_conn, finding_id)

    assert first is True
    assert second is False  # already resolved, nothing to update


def test_mark_secret_resolved_unknown_id_returns_false(db_conn: psycopg.Connection) -> None:
    assert mark_secret_resolved(db_conn, uuid.uuid4()) is False
