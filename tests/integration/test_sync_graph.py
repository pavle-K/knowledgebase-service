import uuid

import psycopg

from src.ingestion.documents import upsert_project
from src.ingestion.github_client import RepoInfo
from src.ingestion.graph import (
    resolve_project_id_by_name,
    set_manifest_missing,
    sync_manifest,
    sync_static_http_calls,
    sync_static_packages,
    sync_static_routes,
)
from src.ingestion.graph_static_analysis import ExposedRoute, PackageDep
from src.ingestion.manifest import Dependency, ExposedInterface, Manifest


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


def test_sync_manifest_populates_edges_and_clears_missing_flag(
    db_conn: psycopg.Connection,
) -> None:
    provider = _fake_repo("provider")
    provider_id = upsert_project(db_conn, provider)

    consumer = _fake_repo("consumer")
    consumer_id = upsert_project(db_conn, consumer)

    manifest = Manifest(
        name=consumer.name,
        exposes=[ExposedInterface(kind="http_endpoint", identifier="GET /health")],
        consumes=[
            Dependency(kind="http_call", identifier="POST /v1/query", provider=provider.name)
        ],
    )

    stats = sync_manifest(db_conn, consumer_id, manifest)
    assert stats == {"exposed": 1, "consumed": 1}

    exposed_row = db_conn.execute(
        "select kind, identifier, source from exposed_interfaces where project_id = %s",
        (consumer_id,),
    ).fetchone()
    assert exposed_row == ("http_endpoint", "GET /health", "manifest")

    dep_row = db_conn.execute(
        "select provider_project_id, external_name, source from dependencies"
        " where consumer_project_id = %s",
        (consumer_id,),
    ).fetchone()
    assert dep_row == (provider_id, None, "manifest")

    missing = db_conn.execute(
        "select manifest_missing from projects where id = %s", (consumer_id,)
    ).fetchone()
    assert missing == (False,)


def test_sync_manifest_unresolved_provider_recorded_as_external(
    db_conn: psycopg.Connection,
) -> None:
    consumer = _fake_repo("consumer-external")
    consumer_id = upsert_project(db_conn, consumer)

    manifest = Manifest(
        name=consumer.name,
        consumes=[
            Dependency(kind="http_call", identifier="POST /x", provider="not-a-real-project")
        ],
    )
    sync_manifest(db_conn, consumer_id, manifest)

    dep_row = db_conn.execute(
        "select provider_project_id, external_name from dependencies"
        " where consumer_project_id = %s",
        (consumer_id,),
    ).fetchone()
    assert dep_row == (None, "not-a-real-project")


def test_set_manifest_missing(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("flagged"))
    set_manifest_missing(db_conn, project_id, True)
    row = db_conn.execute(
        "select manifest_missing from projects where id = %s", (project_id,)
    ).fetchone()
    assert row == (True,)


def test_resolve_project_id_by_name(db_conn: psycopg.Connection) -> None:
    repo = _fake_repo("resolvable")
    project_id = upsert_project(db_conn, repo)
    assert resolve_project_id_by_name(db_conn, repo.name) == project_id
    assert resolve_project_id_by_name(db_conn, "does-not-exist") is None


def test_sync_static_packages(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("pkgs"))
    deps = [PackageDep(name="httpx", version_constraint=">=0.27")]
    count = sync_static_packages(db_conn, project_id, deps, "requirements.txt")
    assert count == 1
    row = db_conn.execute(
        "select kind, identifier, external_name, source from dependencies"
        " where consumer_project_id = %s",
        (project_id,),
    ).fetchone()
    assert row == ("package", "httpx", "httpx", "static_analysis")


def test_sync_static_routes(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("routes"))
    routes = [ExposedRoute(method="GET", path="/healthz")]
    count = sync_static_routes(db_conn, project_id, routes, "src/main.py")
    assert count == 1
    row = db_conn.execute(
        "select kind, identifier, source from exposed_interfaces where project_id = %s",
        (project_id,),
    ).fetchone()
    assert row == ("http_endpoint", "GET /healthz", "static_analysis")


def test_sync_static_http_calls(db_conn: psycopg.Connection) -> None:
    project_id = upsert_project(db_conn, _fake_repo("calls"))
    count = sync_static_http_calls(
        db_conn, project_id, ["https://api.github.com/user/repos"], "src/client.py"
    )
    assert count == 1
    row = db_conn.execute(
        "select kind, identifier, external_name, source from dependencies"
        " where consumer_project_id = %s",
        (project_id,),
    ).fetchone()
    assert row == (
        "http_call",
        "https://api.github.com/user/repos",
        "api.github.com",
        "static_analysis",
    )
