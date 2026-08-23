import uuid

import psycopg

from src.ingestion.documents import upsert_project
from src.ingestion.github_client import RepoInfo
from src.ingestion.technologies import sync_technologies
from src.query.project_lookup import get_project_info, list_projects


def _fake_repo(name: str) -> RepoInfo:
    unique = uuid.uuid4().hex[:8]
    return RepoInfo(
        name=f"{name}-{unique}",
        full_name=f"pavle-K/{name}-{unique}",
        html_url=f"https://github.com/pavle-K/{name}-{unique}",
        description="demo project",
        default_branch="main",
        is_private=False,
        fork=False,
    )


def test_list_projects_filters_by_technology(db_conn: psycopg.Connection) -> None:
    postgres_repo = _fake_repo("uses-postgres")
    other_repo = _fake_repo("uses-mongo")
    postgres_id = upsert_project(db_conn, postgres_repo)
    other_id = upsert_project(db_conn, other_repo)
    sync_technologies(db_conn, postgres_id, ["python", "postgres"])
    sync_technologies(db_conn, other_id, ["python", "mongo"])

    results = list_projects(db_conn, technology="postgres")

    names = {p.name for p in results}
    assert postgres_repo.name in names
    assert other_repo.name not in names


def test_list_projects_returns_all_when_no_technology_filter(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("unfiltered")
    project_id = upsert_project(db_conn, repo)
    sync_technologies(db_conn, project_id, ["rust"])

    results = list_projects(db_conn)

    match = next(p for p in results if p.name == repo.name)
    assert match.technologies == ["rust"]


def test_get_project_info_returns_metadata_and_tech_stack(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("info-proj")
    project_id = upsert_project(db_conn, repo)
    sync_technologies(db_conn, project_id, ["fastapi", "aws-lambda"])

    info = get_project_info(db_conn, repo.name)

    assert info.found is True
    assert info.repo_url == repo.html_url
    assert info.technologies == ["aws-lambda", "fastapi"]


def test_get_project_info_unknown_project(db_conn: psycopg.Connection) -> None:
    info = get_project_info(db_conn, "does-not-exist")
    assert info.found is False
