import asyncio

from src.main import mcp


def test_expected_scoped_tools_are_exposed() -> None:
    tools = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in tools) == [
        "get_dependencies",
        "get_project_info",
        "get_recent_commits",
        "healthz",
        "impact",
        "list_projects",
        "search_code",
        "search_commits",
        "search_docs",
    ]


def test_query_is_not_exposed_as_an_mcp_tool() -> None:
    # query stays REST-only - an MCP client can already choose a tool itself,
    # so routing it through the NL intent-router too would be a redundant hop.
    tools = asyncio.run(mcp.list_tools())
    assert "query" not in {t.name for t in tools}
