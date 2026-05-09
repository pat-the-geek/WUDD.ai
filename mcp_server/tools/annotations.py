"""Tools annotations MCP."""

from __future__ import annotations

import time

from ..config import MCPConfig
from ..errors import BadRequestError, ForbiddenError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient

_ENDPOINT = "/api/annotations"


def tool_list_annotations(
    client: ViewerClient,
    *,
    url: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        data = client.get(_ENDPOINT)
        target_url = (url or "").strip()
        if target_url:
            data = {target_url: data[target_url]} if target_url in data else {}
        return success("list_annotations", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("list_annotations", _ENDPOINT, started_at, exc)


def tool_create_annotation(
    client: ViewerClient,
    config: MCPConfig,
    *,
    url: str | None = None,
    is_important: bool | None = None,
    is_read: bool | None = None,
    is_hidden: bool | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
    wf_status: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        article_url = (url or "").strip()
        if not article_url:
            raise BadRequestError("Le paramètre url est requis")
        body: dict[str, object] = {"url": article_url}
        if is_important is not None:
            body["is_important"] = bool(is_important)
        if is_read is not None:
            body["is_read"] = bool(is_read)
        if is_hidden is not None:
            body["is_hidden"] = bool(is_hidden)
        if tags is not None:
            clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()][:20]
            body["tags"] = clean_tags
        if notes is not None:
            body["notes"] = str(notes)[:5000]
        if wf_status is not None:
            body["wf_status"] = str(wf_status).strip()
        data = client.post(_ENDPOINT, json_body=body)
        if isinstance(data, dict):
            annotation = data.get("annotation")
            data = {
                "action": "upserted",
                "url": data.get("url", article_url),
                "annotation": annotation if isinstance(annotation, dict) else {},
                **data,
            }
        return success(
            "create_annotation",
            data,
            meta=viewer_meta(_ENDPOINT, started_at),
        )
    except Exception as exc:
        return from_exception("create_annotation", _ENDPOINT, started_at, exc)


def tool_delete_annotation(
    client: ViewerClient,
    config: MCPConfig,
    *,
    url: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        article_url = (url or "").strip()
        if not article_url:
            raise BadRequestError("Le paramètre url est requis")
        data = client.delete(_ENDPOINT, params={"url": article_url})
        if isinstance(data, dict):
            data = {
                "action": "deleted",
                "url": data.get("url", article_url),
                **data,
            }
        return success(
            "delete_annotation",
            data,
            meta=viewer_meta(_ENDPOINT, started_at),
        )
    except Exception as exc:
        return from_exception("delete_annotation", _ENDPOINT, started_at, exc)
