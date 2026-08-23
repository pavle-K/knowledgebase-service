from collections.abc import Iterator

import psycopg
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from src.api.dependencies import get_conn, get_embedder_dep, get_llm_dep
from src.ingestion.embedder import FakeEmbedder
from src.main import app
from src.query.synthesizer import FakeLLMClient
from tests.integration.conftest import db_conn, migrated_db  # noqa: F401

API_AUTH_KEY = "test-mcp-auth-key"


def _call_tool(client: TestClient, token: str, name: str, arguments: dict) -> None:
    client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def test_mcp_tool_call_uses_the_actual_callers_own_privilege_tier(
    monkeypatch: pytest.MonkeyPatch,
    db_conn: psycopg.Connection,  # noqa: F811
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", "public-key")
    monkeypatch.setenv("API_ADMIN_KEY", "admin-key")

    seen_privileged: list[bool] = []

    def override_get_conn(request: Request) -> Iterator[psycopg.Connection]:
        seen_privileged.append(getattr(request.state, "privileged", False))
        yield db_conn

    app.dependency_overrides[get_conn] = override_get_conn
    app.dependency_overrides[get_embedder_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[get_llm_dep] = lambda: FakeLLMClient(response="ok")
    try:
        with TestClient(app) as client:
            _call_tool(client, "admin-key", "search_docs", {"query": "x"})
            _call_tool(client, "public-key", "search_docs", {"query": "x"})
    finally:
        app.dependency_overrides.clear()

    assert seen_privileged == [True, False]


def test_mounted_mcp_endpoint_is_reachable_and_requires_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", API_AUTH_KEY)

    with TestClient(app) as client:
        unauthenticated = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert unauthenticated.status_code == 401

        response = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {API_AUTH_KEY}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0.1"},
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["result"]["serverInfo"]["name"] == "knowledgebase-service"
