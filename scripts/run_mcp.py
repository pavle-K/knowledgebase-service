"""Runs the MCP server over HTTP, for Claude Desktop or other MCP clients."""

from __future__ import annotations

from src.mcp_server import mcp


def main() -> None:
    mcp.run(transport="http")


if __name__ == "__main__":
    main()
