import uuid

import psycopg

from src.ingestion.documents import upsert_project
from src.ingestion.github_client import RepoInfo
from src.ingestion.technologies import sync_technologies


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


def test_sync_technologies_links_project(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("tech-proj"))

    count = sync_technologies(db_conn, project_id, ["python", "fastapi", "postgres"])

    assert count == 3
    rows = db_conn.execute(
        """
        select t.name from project_technologies pt
        join technologies t on t.id = pt.technology_id
        where pt.project_id = %s order by t.name
        """,
        (project_id,),
    ).fetchall()
    assert [r[0] for r in rows] == ["fastapi", "postgres", "python"]


def test_sync_technologies_shares_rows_across_projects(db_conn: psycopg.Connection) -> None:
    project_a = upsert_project(db_conn, _fake_repo("proj-a"))
    project_b = upsert_project(db_conn, _fake_repo("proj-b"))

    sync_technologies(db_conn, project_a, ["python"])
    sync_technologies(db_conn, project_b, ["python"])

    count = db_conn.execute("select count(*) from technologies where name = 'python'").fetchone()
    assert count is not None
    assert count[0] == 1  # same technology row reused, not duplicated


def test_sync_technologies_is_idempotent(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("idempotent-proj"))

    sync_technologies(db_conn, project_id, ["python"])
    sync_technologies(db_conn, project_id, ["python"])

    count = db_conn.execute(
        "select count(*) from project_technologies where project_id = %s", (project_id,)
    ).fetchone()
    assert count is not None
    assert count[0] == 1


def test_sync_technologies_skips_blank_entries(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("blank-proj"))
    count = sync_technologies(db_conn, project_id, ["python", "  ", ""])
    assert count == 1
