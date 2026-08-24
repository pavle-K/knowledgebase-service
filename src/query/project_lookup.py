"""Project metadata and tech-stack lookups - fixed SQL, no LLM involved."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import psycopg


def _age_days(since: dt.datetime | None) -> int | None:
    if since is None:
        return None
    now = dt.datetime.now(dt.UTC)
    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.UTC)
    return (now - since).days


@dataclass(frozen=True)
class ProjectSummary:
    name: str
    repo_url: str | None
    description: str | None
    technologies: list[str]
    manifest_missing: bool


def list_projects(conn: psycopg.Connection, technology: str | None = None) -> list[ProjectSummary]:
    rows = conn.execute(
        """
        select p.name, p.repo_url, p.description, p.manifest_missing,
               coalesce(array_agg(t.name) filter (where t.name is not null), '{}')
        from projects p
        left join project_technologies pt on pt.project_id = p.id
        left join technologies t on t.id = pt.technology_id
        where (
            %s::text is null
            or exists (
                select 1
                from project_technologies pt2
                join technologies t2 on t2.id = pt2.technology_id
                where pt2.project_id = p.id and t2.name ilike %s
            )
        )
        group by p.id, p.name, p.repo_url, p.description, p.manifest_missing
        order by p.name
        """,
        (technology, technology),
    ).fetchall()
    return [
        ProjectSummary(
            name=r[0],
            repo_url=r[1],
            description=r[2],
            manifest_missing=r[3],
            technologies=sorted(r[4]),
        )
        for r in rows
    ]


@dataclass(frozen=True)
class ProjectInfo:
    found: bool
    name: str | None = None
    repo_url: str | None = None
    description: str | None = None
    default_branch: str | None = None
    is_private: bool = False
    manifest_missing: bool = True
    technologies: list[str] = field(default_factory=list)


def get_project_info(conn: psycopg.Connection, project_name: str) -> ProjectInfo:
    row = conn.execute(
        """
        select p.name, p.repo_url, p.description, p.default_branch, p.is_private,
               p.manifest_missing,
               coalesce(array_agg(t.name) filter (where t.name is not null), '{}')
        from projects p
        left join project_technologies pt on pt.project_id = p.id
        left join technologies t on t.id = pt.technology_id
        where p.name = %s
        group by p.id, p.name, p.repo_url, p.description, p.default_branch, p.is_private,
                 p.manifest_missing
        """,
        (project_name,),
    ).fetchone()
    if row is None:
        return ProjectInfo(found=False)
    return ProjectInfo(
        found=True,
        name=row[0],
        repo_url=row[1],
        description=row[2],
        default_branch=row[3],
        is_private=row[4],
        manifest_missing=row[5],
        technologies=sorted(row[6]),
    )


@dataclass(frozen=True)
class ProjectLink:
    name: str
    repo_url: str | None
    description: str | None
    is_private: bool
    repo_created_at: dt.datetime | None
    repo_age_days: int | None
    repo_pushed_at: dt.datetime | None
    stargazers_count: int | None
    language: str | None
    forks_count: int | None
    open_issues_count: int | None


def get_project_links(
    conn: psycopg.Connection, projects: list[str] | None = None
) -> list[ProjectLink]:
    """Canonical name, repo link, and generic per-repo stats (age, stars, language,
    activity) - for citing an exact source and its basic facts rather than prose
    recalling them. `projects` narrows to those names (e.g. resolving links for
    projects a prior search/impact call already surfaced); omitted, returns all."""
    rows = conn.execute(
        """
        select name, repo_url, description, is_private, repo_created_at, repo_pushed_at,
               stargazers_count, language, forks_count, open_issues_count
        from projects
        where %s::text[] is null or name = any(%s)
        order by name
        """,
        (projects, projects),
    ).fetchall()
    return [
        ProjectLink(
            name=r[0],
            repo_url=r[1],
            description=r[2],
            is_private=r[3],
            repo_created_at=r[4],
            repo_age_days=_age_days(r[4]),
            repo_pushed_at=r[5],
            stargazers_count=r[6],
            language=r[7],
            forks_count=r[8],
            open_issues_count=r[9],
        )
        for r in rows
    ]


@dataclass(frozen=True)
class AccountMetadata:
    found: bool
    login: str | None = None
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    blog: str | None = None
    location: str | None = None
    account_created_at: dt.datetime | None = None
    account_age_days: int | None = None
    public_repos: int | None = None
    private_repos: int | None = None
    followers: int | None = None
    following: int | None = None
    synced_at: dt.datetime | None = None


def get_account_metadata(conn: psycopg.Connection) -> AccountMetadata:
    """Account-level facts (age, repo/follower counts) - not project-scoped, so no
    name/project argument. `found=False` means no sync has populated it yet."""
    row = conn.execute(
        """
        select login, name, bio, company, blog, location, account_created_at,
               public_repos, private_repos, followers, following, synced_at
        from github_account
        order by synced_at desc
        limit 1
        """
    ).fetchone()
    if row is None:
        return AccountMetadata(found=False)
    return AccountMetadata(
        found=True,
        login=row[0],
        name=row[1],
        bio=row[2],
        company=row[3],
        blog=row[4],
        location=row[5],
        account_created_at=row[6],
        account_age_days=_age_days(row[6]),
        public_repos=row[7],
        private_repos=row[8],
        followers=row[9],
        following=row[10],
        synced_at=row[11],
    )
