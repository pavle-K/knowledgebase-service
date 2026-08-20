"""L3 dependency graph ingestion: manifest (primary) + static analysis (secondary, drift-catching).

Never fabricate edges - an absent manifest or unresolved reference is recorded
honestly (external / manifest_missing), not guessed.
"""

from __future__ import annotations

import uuid
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Json

from src.ingestion.graph_static_analysis import ExposedRoute, PackageDep
from src.ingestion.manifest import Manifest


def resolve_project_id_by_name(conn: psycopg.Connection, name: str) -> uuid.UUID | None:
    row = conn.execute("select id from projects where name = %s", (name,)).fetchone()
    return row[0] if row else None


def set_manifest_missing(conn: psycopg.Connection, project_id: uuid.UUID, missing: bool) -> None:
    conn.execute("update projects set manifest_missing = %s where id = %s", (missing, project_id))


def upsert_exposed_interface(
    conn: psycopg.Connection,
    project_id: uuid.UUID,
    kind: str,
    identifier: str,
    source: str,
    contract: dict[str, object] | None = None,
    file_path: str | None = None,
) -> None:
    contract_json = Json(contract) if contract else None
    conn.execute(
        """
        insert into exposed_interfaces (project_id, kind, identifier, contract, source, file_path)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (project_id, kind, identifier) do update set
            contract = excluded.contract,
            source = excluded.source,
            file_path = excluded.file_path
        """,
        (project_id, kind, identifier, contract_json, source, file_path),
    )


def upsert_dependency(
    conn: psycopg.Connection,
    consumer_project_id: uuid.UUID,
    kind: str,
    identifier: str,
    source: str,
    provider_project_id: uuid.UUID | None = None,
    external_name: str | None = None,
    version_constraint: str | None = None,
    file_path: str | None = None,
) -> None:
    conn.execute(
        """
        insert into dependencies
            (consumer_project_id, provider_project_id, kind, identifier,
             external_name, version_constraint, source, file_path)
        values (%s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (consumer_project_id, kind, identifier) do update set
            provider_project_id = excluded.provider_project_id,
            external_name = excluded.external_name,
            version_constraint = excluded.version_constraint,
            source = excluded.source,
            file_path = excluded.file_path
        """,
        (
            consumer_project_id,
            provider_project_id,
            kind,
            identifier,
            external_name,
            version_constraint,
            source,
            file_path,
        ),
    )


def sync_manifest(
    conn: psycopg.Connection, project_id: uuid.UUID, manifest: Manifest
) -> dict[str, int]:
    for exposed in manifest.exposes:
        upsert_exposed_interface(
            conn,
            project_id,
            exposed.kind,
            exposed.identifier,
            "manifest",
            contract=exposed.contract,
        )

    for dep in manifest.consumes:
        provider_id = resolve_project_id_by_name(conn, dep.provider) if dep.provider else None
        upsert_dependency(
            conn,
            project_id,
            dep.kind,
            dep.identifier,
            "manifest",
            provider_project_id=provider_id,
            external_name=None if provider_id else dep.provider,
            version_constraint=dep.version_constraint,
        )

    set_manifest_missing(conn, project_id, False)
    return {"exposed": len(manifest.exposes), "consumed": len(manifest.consumes)}


def sync_static_packages(
    conn: psycopg.Connection, project_id: uuid.UUID, deps: list[PackageDep], file_path: str
) -> int:
    for dep in deps:
        upsert_dependency(
            conn,
            project_id,
            "package",
            dep.name,
            "static_analysis",
            external_name=dep.name,
            version_constraint=dep.version_constraint,
            file_path=file_path,
        )
    return len(deps)


def sync_static_routes(
    conn: psycopg.Connection, project_id: uuid.UUID, routes: list[ExposedRoute], file_path: str
) -> int:
    for route in routes:
        upsert_exposed_interface(
            conn,
            project_id,
            "http_endpoint",
            f"{route.method} {route.path}",
            "static_analysis",
            file_path=file_path,
        )
    return len(routes)


def sync_static_http_calls(
    conn: psycopg.Connection, project_id: uuid.UUID, urls: list[str], file_path: str
) -> int:
    for url in urls:
        hostname = urlsplit(url).hostname or url
        upsert_dependency(
            conn,
            project_id,
            "http_call",
            url,
            "static_analysis",
            external_name=hostname,
            file_path=file_path,
        )
    return len(urls)
