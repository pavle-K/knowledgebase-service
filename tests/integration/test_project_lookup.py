import uuid

import psycopg

from src.ingestion.documents import upsert_account_info, upsert_project
from src.ingestion.github_client import AccountInfo, RepoInfo
from src.ingestion.technologies import sync_technologies
from src.query.project_lookup import (
    get_account_metadata,
    get_project_info,
    get_project_links,
    list_projects,
)


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
        created_at="2020-01-01T00:00:00Z",
        pushed_at="2026-01-15T10:00:00Z",
        stargazers_count=5,
        language="Python",
        forks_count=1,
        open_issues_count=2,
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


def test_get_project_links_returns_all_when_unfiltered(db_conn: psycopg.Connection) -> None:
    repo_a = _fake_repo("link-a")
    repo_b = _fake_repo("link-b")
    upsert_project(db_conn, repo_a)
    upsert_project(db_conn, repo_b)

    links = get_project_links(db_conn)

    by_name = {link.name: link for link in links}
    assert by_name[repo_a.name].repo_url == repo_a.html_url
    assert by_name[repo_b.name].repo_url == repo_b.html_url


def test_get_project_links_filters_to_named_projects(db_conn: psycopg.Connection) -> None:
    wanted = _fake_repo("link-wanted")
    other = _fake_repo("link-other")
    upsert_project(db_conn, wanted)
    upsert_project(db_conn, other)

    links = get_project_links(db_conn, projects=[wanted.name])

    names = {link.name for link in links}
    assert names == {wanted.name}


def test_get_project_links_unknown_project_returns_empty(db_conn: psycopg.Connection) -> None:
    links = get_project_links(db_conn, projects=["does-not-exist"])
    assert links == []


def test_get_project_links_includes_repo_stats(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("stats-proj")
    upsert_project(db_conn, repo)

    links = get_project_links(db_conn, projects=[repo.name])

    link = links[0]
    assert link.stargazers_count == 5
    assert link.language == "Python"
    assert link.forks_count == 1
    assert link.open_issues_count == 2
    assert link.repo_created_at is not None
    assert link.repo_age_days is not None
    assert link.repo_age_days > 365  # created 2020-01-01, well over a year old


def _fake_account(login: str = "pavle-K") -> AccountInfo:
    return AccountInfo(
        login=login,
        name="Pavle",
        bio="Building things.",
        company=None,
        blog="https://meetpavle.duckdns.org/",
        location=None,
        created_at="2015-03-01T00:00:00Z",
        public_repos=12,
        private_repos=4,
        followers=7,
        following=3,
    )


def test_get_account_metadata_returns_not_found_before_any_sync(
    db_conn: psycopg.Connection,
) -> None:
    metadata = get_account_metadata(db_conn)
    assert metadata.found is False


def test_get_account_metadata_returns_synced_account(db_conn: psycopg.Connection) -> None:
    upsert_account_info(db_conn, _fake_account())

    metadata = get_account_metadata(db_conn)

    assert metadata.found is True
    assert metadata.login == "pavle-K"
    assert metadata.public_repos == 12
    assert metadata.private_repos == 4
    assert metadata.account_age_days is not None
    assert metadata.account_age_days > 365


def test_upsert_account_info_is_idempotent_per_login(db_conn: psycopg.Connection) -> None:
    upsert_account_info(db_conn, _fake_account())
    upsert_account_info(db_conn, _fake_account())  # second sync, same login

    row_count = db_conn.execute(
        "select count(*) from github_account where login = %s", ("pavle-K",)
    ).fetchone()
    assert row_count is not None
    assert row_count[0] == 1
