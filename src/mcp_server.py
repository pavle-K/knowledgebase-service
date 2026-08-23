"""Wraps a FastAPI app as an MCP server, exposing only query/impact/healthz as tools.

Takes `app` as a parameter instead of importing it from src.main to avoid a
circular import (src.main mounts the server built here back onto itself).
"""

from __future__ import annotations

from collections.abc import Generator

import httpx
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap

_ROUTE_MAPS = [
    RouteMap(methods=["GET"], pattern=r"^/healthz$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["POST"], pattern=r"^/v1/query$", mcp_type=MCPType.TOOL),
    RouteMap(methods=["POST"], pattern=r"^/v1/impact$", mcp_type=MCPType.TOOL),
    RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
]


class ForwardCallerAuth(httpx.Auth):
    """Forwards the actual MCP caller's own Authorization header, not a fixed key."""

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        auth_header = get_http_headers(include={"authorization"}).get("authorization")
        if auth_header:
            request.headers["Authorization"] = auth_header
        yield request


def build_mcp(app: FastAPI) -> FastMCP:
    return FastMCP.from_fastapi(
        app,
        name="knowledgebase-service",
        route_maps=_ROUTE_MAPS,
        httpx_client_kwargs={"auth": ForwardCallerAuth()},
    )
