"""Compatibility entry point for the MCP server in ``src/offline_package``."""

from __future__ import annotations

from src.offline_package.mcp_server import *  # noqa: F403
from src.offline_package.mcp_server import main


if __name__ == "__main__":
    main()
