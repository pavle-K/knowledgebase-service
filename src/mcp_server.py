"""Wraps a FastAPI app as an MCP server, exposing only query/impact/healthz as tools.

Everything else is explicitly excluded - auto-generation would otherwise turn
every route (including future webhook/badge endpoints) into a tool.

FastMCP.from_fastapi routes tool calls through the app's real HTTP endpoints
internally, which means they hit the same Bearer-token auth middleware as any
other caller - the internal httpx client needs the token too, or query/impact
fail with 401 (healthz doesn't, since it's auth-exempt).

Takes `app` as a parameter rather than importing it from src.main: src.main
mounts the MCP server built here back onto that same app (see src/main.py),
so importing it here would be circular.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r"^/healthz$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["POST"], pattern=r"^/v1/query$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["POST"], pattern=r"^/v1/impact$", mcp_type=MCPType.TOOL),
    RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
]


def build_mcp(app: FastAPI) -> FastMCP:
    api_auth_key = os.environ.get("API_AUTH_KEY")
    httpx_client_kwargs = (
        {"headers": {"Authorization": f"Bearer {api_auth_key}"}} if api_auth_key else None
    )
    return FastMCP.from_fastapi(
        app,
        name="knowledgebase-service",
        route_maps=_ROUTE_MAPS,
        httpx_client_kwargs=httpx_client_kwargs,
    )
