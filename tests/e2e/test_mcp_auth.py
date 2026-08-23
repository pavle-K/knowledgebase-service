import asyncio
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_conn, get_embedder_dep, get_llm_dep
from src.ingestion.embedder import FakeEmbedder
from src.main import app
from src.mcp_server import build_mcp
from src.query.synthesizer import FakeLLMClient
from tests.integration.conftest import db_conn, migrated_db  # noqa: F401

API_AUTH_KEY = "test-mcp-auth-key"


@pytest.fixture
def _overridden_app(db_conn: psycopg.Connection) -> Iterator[None]:  # noqa: F811
    def override_get_conn() -> Iterator[psycopg.Connection]:
        yield db_conn

    app.dependency_overrides[get_conn] = override_get_conn
    app.dependency_overrides[get_embedder_dep] = lambda: FakeEmbedder()
    app.dependency_overrides[get_llm_dep] = lambda: FakeLLMClient(response="mcp test summary")
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def test_query_tool_forwards_auth_token_to_underlying_route(
    monkeypatch: pytest.MonkeyPatch, _overridden_app: None
) -> None:
    # Regression test: FastMCP.from_fastapi calls the app's real HTTP routes
    # internally, which hit the same auth middleware as any other caller.
    # Without forwarding the token, every tool call except healthz 401s.
    monkeypatch.setenv("API_AUTH_KEY", API_AUTH_KEY)
    mcp = build_mcp(app)

    async def call() -> dict:
        _, structured = await mcp._call_tool_mcp("query", {"query": "test question"})
        return structured

    structured = asyncio.run(call())
    assert structured["summary"] == "mcp test summary"


def test_impact_tool_forwards_auth_token_to_underlying_route(
    monkeypatch: pytest.MonkeyPatch, _overridden_app: None
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", API_AUTH_KEY)
    mcp = build_mcp(app)

    async def call() -> dict:
        _, structured = await mcp._call_tool_mcp(
            "impact", {"project": "does-not-exist", "interface": "x"}
        )
        return structured

    structured = asyncio.run(call())
    assert structured["project_found"] is False


def test_mounted_mcp_endpoint_is_reachable_and_requires_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This is the actually-deployed transport (src/main.py mounts mcp.http_app()
    # at /mcp), as opposed to the tests above which call tools directly through
    # a standalone FastMCP instance. Regression test for the lifespan wiring:
    # without `app.router.lifespan_context = mcp_app.router.lifespan_context`,
    # every /mcp request 500s with "Task group is not initialized."
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
