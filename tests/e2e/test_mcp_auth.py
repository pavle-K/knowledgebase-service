import asyncio
from collections.abc import Iterator

import psycopg
import pytest

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
    mcp = build_mcp()

    async def call() -> dict:
        _, structured = await mcp._call_tool_mcp("query", {"query": "test question"})
        return structured

    structured = asyncio.run(call())
    assert structured["summary"] == "mcp test summary"


def test_impact_tool_forwards_auth_token_to_underlying_route(
    monkeypatch: pytest.MonkeyPatch, _overridden_app: None
) -> None:
    monkeypatch.setenv("API_AUTH_KEY", API_AUTH_KEY)
    mcp = build_mcp()

    async def call() -> dict:
        _, structured = await mcp._call_tool_mcp(
            "impact", {"project": "does-not-exist", "interface": "x"}
        )
        return structured

    structured = asyncio.run(call())
    assert structured["project_found"] is False
