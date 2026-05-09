"""Tools d'export MCP."""

from __future__ import annotations

import time
from urllib.parse import urlencode

from ..errors import BadRequestError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient


def tool_export_dataset(
    client: ViewerClient,
    *,
    format: str | None = None,
    path: str | None = None,
    flux: str | None = None,
    keyword: str | None = None,
    max_entries: int = 50,
) -> dict:
    started_at = time.perf_counter()
    endpoint = "/api/export"
    try:
        export_format = (format or "").strip().lower()
        if export_format not in {"atom", "csv", "xlsx"}:
            raise BadRequestError("format doit valoir atom, csv ou xlsx")

        if export_format == "atom":
            query = {
                "max_entries": max(1, min(int(max_entries), 200)),
            }
            if flux:
                query["flux"] = flux.strip()
            elif keyword:
                query["keyword"] = keyword.strip()
            download_path = "/api/export/atom"
        else:
            file_path = (path or "").strip()
            if not file_path:
                raise BadRequestError("path est requis pour csv et xlsx")
            client.get("/api/content", params={"path": file_path})
            query = {"path": file_path}
            download_path = f"/api/export/{export_format}"

        query_string = urlencode(query)
        data = {
            "format": export_format,
            "download_url": f"{client.build_url(download_path)}?{query_string}",
            "viewer_endpoint": f"{download_path}?{query_string}",
        }
        return success(
            "export_dataset",
            data,
            meta=viewer_meta(endpoint, started_at),
        )
    except Exception as exc:
        return from_exception("export_dataset", endpoint, started_at, exc)
