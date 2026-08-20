"""Deterministic impact analysis: fixed, parameterized recursive CTE - never LLM-generated SQL.

Confidence framing (manifest vs static_analysis vs no-manifest) is surfaced here
as raw fields; harmonizing it into a synthesized "confidence" narrative is Stage 7's job.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg

# A→B→A cycles terminate via the depth bound, not a visited-set - bounded, not infinite.
_IMPACT_CTE = """
with recursive impacted as (
    select d.consumer_project_id, 1 as depth
    from dependencies d
    where d.provider_project_id = %(project_id)s
      and d.identifier = %(interface_identifier)s
    union
    select d2.consumer_project_id, i.depth + 1
    from dependencies d2
    join impacted i on d2.provider_project_id = i.consumer_project_id
    where i.depth < 5
)
select distinct p.name, p.repo_url, min(i.depth) as distance
from impacted i join projects p on p.id = i.consumer_project_id
group by p.name, p.repo_url
order by distance
"""


@dataclass(frozen=True)
class ImpactedProject:
    name: str
    repo_url: str | None
    distance: int


@dataclass(frozen=True)
class ImpactResult:
    project_found: bool
    interface_declared: bool
    interface_source: str | None  # 'manifest' | 'static_analysis' | None
    provider_manifest_missing: bool
    impacted: list[ImpactedProject]


def impact_analysis(
    conn: psycopg.Connection, project_name: str, interface_identifier: str
) -> ImpactResult:
    project_row = conn.execute(
        "select id, manifest_missing from projects where name = %s", (project_name,)
    ).fetchone()
    if project_row is None:
        return ImpactResult(
            project_found=False,
            interface_declared=False,
            interface_source=None,
            provider_manifest_missing=True,
            impacted=[],
        )
    project_id: uuid.UUID = project_row[0]
    manifest_missing: bool = project_row[1]

    interface_row = conn.execute(
        "select source from exposed_interfaces where project_id = %s and identifier = %s",
        (project_id, interface_identifier),
    ).fetchone()

    rows = conn.execute(
        _IMPACT_CTE, {"project_id": project_id, "interface_identifier": interface_identifier}
    ).fetchall()

    return ImpactResult(
        project_found=True,
        interface_declared=interface_row is not None,
        interface_source=interface_row[0] if interface_row else None,
        provider_manifest_missing=manifest_missing,
        impacted=[ImpactedProject(name=r[0], repo_url=r[1], distance=r[2]) for r in rows],
    )
