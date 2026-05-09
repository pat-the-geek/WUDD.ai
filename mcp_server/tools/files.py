"""Tools fichiers et recherche corpus pour MCP."""

from __future__ import annotations

import time
from typing import Any

from ..errors import BadRequestError
from ..responses import from_exception, success, truncate_text, viewer_meta
from ..viewer_client import ViewerClient


def tool_list_corpus_files(
    client: ViewerClient,
    *,
    file_type: str | None = None,
    limit: int = 100,
) -> dict:
    started_at = time.perf_counter()
    warnings: list[str] = []
    endpoint = "/api/files"
    try:
        files = client.get(endpoint)
        normalized_type = (file_type or "").strip().lower()
        if normalized_type:
            if normalized_type not in {"json", "markdown"}:
                raise BadRequestError("type doit valoir 'json' ou 'markdown'")
            files = [item for item in files if item.get("type") == normalized_type]
        limit = max(1, min(int(limit), 500))
        if len(files) > limit:
            warnings.append("large_result_capped")
        data = files[:limit]
        return success(
            "list_corpus_files",
            data,
            warnings=warnings,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("list_corpus_files", endpoint, started_at, exc)


def tool_read_corpus_file(client: ViewerClient, *, path: str | None = None) -> dict:
    started_at = time.perf_counter()
    warnings: list[str] = []
    endpoint = "/api/content"
    try:
        file_path = (path or "").strip()
        if not file_path:
            raise BadRequestError("Paramètre path requis")
        payload = client.get(endpoint, params={"path": file_path})
        content = str(payload.get("content", ""))
        content, truncated = truncate_text(content)
        if truncated:
            warnings.append("response_truncated")
        data = {
            "path": payload.get("path", file_path),
            "content": content,
        }
        return success(
            "read_corpus_file",
            data,
            warnings=warnings,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("read_corpus_file", endpoint, started_at, exc)


def tool_search_corpus(
    client: ViewerClient,
    *,
    q: str | None = None,
    file_type: str | None = None,
    sentiment: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/search"
    try:
        query = (q or "").strip()
        if len(query) < 2:
            raise BadRequestError("Le paramètre q doit contenir au moins 2 caractères")
        params: dict[str, Any] = {"q": query}
        if file_type:
            normalized_type = file_type.strip().lower()
            if normalized_type not in {"json", "markdown"}:
                raise BadRequestError("type doit valoir 'json' ou 'markdown'")
            params["type"] = normalized_type
        if sentiment:
            normalized_sentiment = sentiment.strip().lower()
            if normalized_sentiment not in {"positif", "neutre", "négatif"}:
                raise BadRequestError(
                    "sentiment doit valoir 'positif', 'neutre' ou 'négatif'"
                )
            params["sentiment"] = normalized_sentiment
        if source:
            params["source"] = source.strip()
        if date_from:
            params["date_from"] = date_from.strip()
        if date_to:
            params["date_to"] = date_to.strip()
        matches = client.get(endpoint, params=params)
        return success(
            "search_corpus",
            matches,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("search_corpus", endpoint, started_at, exc)
