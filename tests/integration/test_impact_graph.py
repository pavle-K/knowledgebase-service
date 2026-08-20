import uuid

import psycopg

from src.query.impact_graph import run_impact_query


def test_run_impact_query_wires_graph_traversal_node(db_conn: psycopg.Connection) -> None:
    unique = uuid.uuid4().hex[:8]
    provider = db_conn.execute(
        "insert into projects (name, repo_url, manifest_missing) values (%s, %s, false)"
        " returning id",
        (f"provider-{unique}", f"https://github.com/pavle-K/provider-{unique}"),
    ).fetchone()
    assert provider is not None
    provider_id = provider[0]

    consumer = db_conn.execute(
        "insert into projects (name, repo_url, manifest_missing) values (%s, %s, false)"
        " returning id",
        (f"consumer-{unique}", f"https://github.com/pavle-K/consumer-{unique}"),
    ).fetchone()
    assert consumer is not None
    consumer_id = consumer[0]

    db_conn.execute(
        "insert into exposed_interfaces (project_id, kind, identifier, source)"
        " values (%s, 'http_endpoint', 'GET /x', 'manifest')",
        (provider_id,),
    )
    db_conn.execute(
        "insert into dependencies"
        " (consumer_project_id, provider_project_id, kind, identifier, source)"
        " values (%s, %s, 'http_call', 'GET /x', 'manifest')",
        (consumer_id, provider_id),
    )

    result = run_impact_query(db_conn, f"provider-{unique}", "GET /x")

    assert result.project_found is True
    assert result.interface_declared is True
    assert len(result.impacted) == 1
    assert result.impacted[0].name == f"consumer-{unique}"
    assert result.impacted[0].distance == 1
