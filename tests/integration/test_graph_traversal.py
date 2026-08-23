import uuid

import psycopg

from src.query.graph_traversal import impact_analysis, list_dependencies


def _make_project(conn: psycopg.Connection, name: str) -> uuid.UUID:
    unique = uuid.uuid4().hex[:8]
    row = conn.execute(
        "insert into projects (name, repo_url, manifest_missing) values (%s, %s, false)"
        " returning id",
        (f"{name}-{unique}", f"https://github.com/pavle-K/{name}-{unique}"),
    ).fetchone()
    assert row is not None
    return row[0]


def _expose(conn: psycopg.Connection, project_id: uuid.UUID, identifier: str) -> None:
    conn.execute(
        "insert into exposed_interfaces (project_id, kind, identifier, source)"
        " values (%s, 'http_endpoint', %s, 'manifest')",
        (project_id, identifier),
    )


def _depend(
    conn: psycopg.Connection, consumer_id: uuid.UUID, provider_id: uuid.UUID, identifier: str
) -> None:
    conn.execute(
        "insert into dependencies"
        " (consumer_project_id, provider_project_id, kind, identifier, source)"
        " values (%s, %s, 'http_call', %s, 'manifest')",
        (consumer_id, provider_id, identifier),
    )


def test_impact_analysis_finds_direct_and_transitive_dependents(
    db_conn: psycopg.Connection,
) -> None:
    a = _make_project(db_conn, "proj-a")
    b = _make_project(db_conn, "proj-b")
    c = _make_project(db_conn, "proj-c")
    d = _make_project(db_conn, "proj-d")  # isolated, no dependents

    _expose(db_conn, a, "endpoint-a")
    _expose(db_conn, b, "endpoint-b")
    _expose(db_conn, d, "endpoint-d")
    _depend(db_conn, b, a, "endpoint-a")  # B depends on A
    _depend(db_conn, c, b, "endpoint-b")  # C depends on B (transitive dependent of A)

    result = impact_analysis(db_conn, _name(db_conn, a), "endpoint-a")

    by_id = {p.name: p.distance for p in result.impacted}
    assert by_id[_name(db_conn, b)] == 1
    assert by_id[_name(db_conn, c)] == 2

    empty_result = impact_analysis(db_conn, _name(db_conn, d), "endpoint-d")
    assert empty_result.impacted == []


def test_impact_analysis_respects_depth_limit(db_conn: psycopg.Connection) -> None:
    # Chain of 7: p0 -> p1 -> p2 -> p3 -> p4 -> p5 -> p6 (p1 is depth 1 from p0, ... p6 is depth 6)
    projects = [_make_project(db_conn, f"chain-{i}") for i in range(7)]
    for i, project_id in enumerate(projects):
        _expose(db_conn, project_id, f"endpoint-{i}")
    for i in range(1, 7):
        _depend(db_conn, projects[i], projects[i - 1], f"endpoint-{i - 1}")

    result = impact_analysis(db_conn, _name(db_conn, projects[0]), "endpoint-0")

    by_name = {p.name: p.distance for p in result.impacted}
    for i in range(1, 6):
        assert by_name[_name(db_conn, projects[i])] == i
    # depth 6 (projects[6]) must not appear - recursion stops once depth reaches 5.
    assert _name(db_conn, projects[6]) not in by_name


def test_impact_analysis_cycle_terminates(db_conn: psycopg.Connection) -> None:
    a = _make_project(db_conn, "cycle-a")
    b = _make_project(db_conn, "cycle-b")
    _expose(db_conn, a, "endpoint-a")
    _expose(db_conn, b, "endpoint-b")
    _depend(db_conn, b, a, "endpoint-a")  # B depends on A
    _depend(db_conn, a, b, "endpoint-b")  # A depends on B - cycle: A -> B -> A

    result = impact_analysis(db_conn, _name(db_conn, a), "endpoint-a")

    # Must terminate (test itself would hang/timeout if the CTE recursion were unbounded)
    # and must not blow up into unbounded duplicate rows.
    names = [p.name for p in result.impacted]
    assert len(names) == len(set(names))
    by_name = {p.name: p.distance for p in result.impacted}
    assert by_name[_name(db_conn, b)] == 1


def test_impact_analysis_project_not_found(db_conn: psycopg.Connection) -> None:
    result = impact_analysis(db_conn, "does-not-exist", "some-endpoint")
    assert result.project_found is False
    assert result.impacted == []


def test_impact_analysis_flags_undeclared_interface(db_conn: psycopg.Connection) -> None:
    a = _make_project(db_conn, "proj-undeclared")
    result = impact_analysis(db_conn, _name(db_conn, a), "never-declared-endpoint")
    assert result.project_found is True
    assert result.interface_declared is False


def test_list_dependencies_returns_direct_edges_only(db_conn: psycopg.Connection) -> None:
    consumer = _make_project(db_conn, "dep-consumer")
    provider = _make_project(db_conn, "dep-provider")
    _depend(db_conn, consumer, provider, "POST /v1/query")
    db_conn.execute(
        "insert into dependencies (consumer_project_id, kind, identifier, external_name, source)"
        " values (%s, 'package', 'httpx', 'httpx', 'manifest')",
        (consumer,),
    )

    deps = list_dependencies(db_conn, _name(db_conn, consumer))

    assert deps is not None
    by_identifier = {d.identifier: d for d in deps}
    assert by_identifier["POST /v1/query"].provider_name == _name(db_conn, provider)
    assert by_identifier["httpx"].provider_name is None
    assert by_identifier["httpx"].external_name == "httpx"


def test_list_dependencies_unknown_project_returns_none(db_conn: psycopg.Connection) -> None:
    assert list_dependencies(db_conn, "does-not-exist") is None


def test_list_dependencies_empty_for_project_with_no_dependencies(
    db_conn: psycopg.Connection,
) -> None:
    isolated = _make_project(db_conn, "dep-isolated")
    assert list_dependencies(db_conn, _name(db_conn, isolated)) == []


def _name(conn: psycopg.Connection, project_id: uuid.UUID) -> str:
    row = conn.execute("select name from projects where id = %s", (project_id,)).fetchone()
    assert row is not None
    return row[0]
