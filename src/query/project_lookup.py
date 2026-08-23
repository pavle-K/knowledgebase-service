"""Project metadata and tech-stack lookups - fixed SQL, no LLM involved."""

from __future__ import annotations

from dataclasses import dataclass, field

import psycopg


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
