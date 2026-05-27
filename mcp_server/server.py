"""Point d'entrée du serveur MCP WUDD.ai."""

from __future__ import annotations

import asyncio
import logging

from fastmcp import FastMCP

from . import __version__
from .auth import StaticTokenAuthProvider
from .config import MCPConfig
from .tool_registry import register_tools
from .viewer_client import ViewerClient


def create_server(config: MCPConfig | None = None) -> FastMCP:
    """Construit l'instance FastMCP configurée pour WUDD.ai."""
    cfg = config or MCPConfig.from_env()
    auth_provider = StaticTokenAuthProvider(cfg.token)
    server = FastMCP(
        name="WUDD.ai MCP",
        instructions=(
            "Serveur MCP WUDD.ai pour explorer le corpus, les entités, les "
            "alertes et appliquer des écritures sûres sur annotations et watchlists."
        ),
        version=__version__,
        auth=auth_provider,
        mask_error_details=False,
    )
    client = ViewerClient(
        cfg.viewer_base_url,
        timeout=cfg.request_timeout,
        heavy_timeout=cfg.heavy_request_timeout,
        api_token=cfg.viewer_api_token or None,
    )
    register_tools(server, client, cfg)
    return server


async def run() -> None:
    """Démarre le serveur MCP Streamable HTTP."""
    config = MCPConfig.from_env()
    logging.basicConfig(level=getattr(logging, config.log_level, logging.INFO))
    server = create_server(config)
    await server.run_http_async(
        transport="streamable-http",
        host=config.host,
        port=config.port,
        path=config.streamable_http_path,
        log_level=config.log_level.lower(),
    )


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
