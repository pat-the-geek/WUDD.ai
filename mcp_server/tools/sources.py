"""Tools sources RSS MCP — wrappent /api/v1/sources."""

from __future__ import annotations

import time

from ..config import MCPConfig
from ..errors import BadRequestError, ForbiddenError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient

_ENDPOINT = "/api/v1/sources"


def tool_list_sources(
    client: ViewerClient,
    *,
    include_inactive: bool = False,
    tag: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    params: dict[str, str] = {}
    if include_inactive:
        params["include_inactive"] = "1"
    if tag and tag.strip():
        params["tag"] = tag.strip()
    try:
        data = client.get(_ENDPOINT, params=params or None)
        return success("list_sources", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("list_sources", _ENDPOINT, started_at, exc)


def tool_add_source(
    client: ViewerClient,
    config: MCPConfig,
    *,
    url: str | None = None,
    nom: str | None = None,
    tags: list[str] | None = None,
    actif: bool | None = None,
    bypass_quota: bool | None = None,
    html_url: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        url_clean = (url or "").strip()
        if not url_clean.startswith("http"):
            raise BadRequestError("Le paramètre url (http/https) est requis")

        body: dict[str, object] = {"url": url_clean}
        if nom and nom.strip():
            body["nom"] = nom.strip()
        if tags is not None:
            body["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        if actif is not None:
            body["actif"] = bool(actif)
        if bypass_quota is not None:
            body["bypass_quota"] = bool(bypass_quota)
        if html_url and html_url.strip():
            body["html_url"] = html_url.strip()

        data = client.post(_ENDPOINT, json_body=body)
        if isinstance(data, dict):
            data = {"action": "added", **data}
        return success("add_source", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("add_source", _ENDPOINT, started_at, exc)


def tool_update_source(
    client: ViewerClient,
    config: MCPConfig,
    *,
    source_id: str | None = None,
    nom: str | None = None,
    tags: list[str] | None = None,
    actif: bool | None = None,
    bypass_quota: bool | None = None,
    html_url: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    sid = (source_id or "").strip()
    endpoint = f"{_ENDPOINT}/{sid}"
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        if not sid:
            raise BadRequestError("Le paramètre source_id est requis")

        body: dict[str, object] = {}
        if nom is not None:
            body["nom"] = str(nom).strip()
        if tags is not None:
            body["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        if actif is not None:
            body["actif"] = bool(actif)
        if bypass_quota is not None:
            body["bypass_quota"] = bool(bypass_quota)
        if html_url is not None:
            body["html_url"] = str(html_url).strip()
        if not body:
            raise BadRequestError("Au moins un champ à modifier est requis")

        data = client.patch(endpoint, json_body=body)
        if isinstance(data, dict):
            data = {"action": "updated", **data}
        return success("update_source", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("update_source", endpoint, started_at, exc)


def tool_toggle_source(
    client: ViewerClient,
    config: MCPConfig,
    *,
    source_id: str | None = None,
    actif: bool | None = None,
) -> dict:
    """Active ou désactive une source (PATCH actif). Si actif=None, bascule."""
    started_at = time.perf_counter()
    sid = (source_id or "").strip()
    endpoint = f"{_ENDPOINT}/{sid}"
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        if not sid:
            raise BadRequestError("Le paramètre source_id est requis")

        if actif is None:
            current = client.get(_ENDPOINT, params={"include_inactive": "1"})
            items = current.get("items", []) if isinstance(current, dict) else []
            target = next((i for i in items if i.get("id") == sid), None)
            if target is None:
                raise BadRequestError(f"Source introuvable : {sid}")
            new_actif = not bool(target.get("actif", True))
        else:
            new_actif = bool(actif)

        data = client.patch(endpoint, json_body={"actif": new_actif})
        if isinstance(data, dict):
            data = {"action": "toggled", "actif": new_actif, **data}
        return success("toggle_source", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("toggle_source", endpoint, started_at, exc)


def tool_delete_source(
    client: ViewerClient,
    config: MCPConfig,
    *,
    source_id: str | None = None,
    hard: bool = False,
) -> dict:
    started_at = time.perf_counter()
    sid = (source_id or "").strip()
    endpoint = f"{_ENDPOINT}/{sid}"
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        if not sid:
            raise BadRequestError("Le paramètre source_id est requis")

        params = {"hard": "1"} if hard else None
        data = client.delete(endpoint, params=params)
        if isinstance(data, dict):
            data = {"action": "deleted" if hard else "deactivated", **data}
        return success("delete_source", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("delete_source", endpoint, started_at, exc)
