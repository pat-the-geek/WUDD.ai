"""Configuration du serveur MCP WUDD.ai."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def resolve_project_root() -> Path:
    """Retourne la racine du dépôt."""
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class MCPConfig:
    """Configuration runtime du serveur MCP."""

    project_root: Path
    host: str
    port: int
    token: str
    viewer_base_url: str
    enable_write_tools: bool
    request_timeout: int
    heavy_request_timeout: int
    log_level: str
    streamable_http_path: str

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "MCPConfig":
        root = project_root or resolve_project_root()
        env_file = root / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

        token = os.getenv("MCP_TOKEN", "").strip()
        viewer_base_url = os.getenv(
            "MCP_VIEWER_BASE_URL",
            "http://127.0.0.1:5050",
        ).strip().rstrip("/")

        config = cls(
            project_root=root,
            host=os.getenv("MCP_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=int(os.getenv("MCP_PORT", "8765")),
            token=token,
            viewer_base_url=viewer_base_url,
            enable_write_tools=os.getenv(
                "MCP_ENABLE_WRITE_TOOLS",
                "true",
            ).strip().lower()
            in {"1", "true", "yes", "on"},
            request_timeout=max(1, int(os.getenv("MCP_REQUEST_TIMEOUT", "10"))),
            heavy_request_timeout=max(
                1, int(os.getenv("MCP_HEAVY_REQUEST_TIMEOUT", "30"))
            ),
            log_level=os.getenv("MCP_LOG_LEVEL", "INFO").strip().upper() or "INFO",
            streamable_http_path=os.getenv("MCP_PATH", "/mcp").strip() or "/mcp",
        )
        config.validate()
        return config

    def validate(self) -> None:
        errors: list[str] = []
        if not self.token:
            errors.append("Variable d'environnement manquante: MCP_TOKEN")
        if not self.viewer_base_url.startswith(("http://", "https://")):
            errors.append(
                "MCP_VIEWER_BASE_URL doit commencer par http:// ou https://"
            )
        if not (1 <= self.port <= 65535):
            errors.append("MCP_PORT doit être compris entre 1 et 65535")
        if not self.streamable_http_path.startswith("/"):
            errors.append("MCP_PATH doit commencer par '/'")
        if errors:
            raise ValueError("Configuration MCP invalide:\n- " + "\n- ".join(errors))
