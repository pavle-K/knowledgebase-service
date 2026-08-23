import asyncio

from src.main import mcp


def test_only_query_impact_healthz_are_exposed_as_tools() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in tools) == ["healthz", "impact", "query"]
