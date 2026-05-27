"""Tools mots-clés MCP — wrappent /api/v1/keywords."""

from __future__ import annotations

import time
from urllib.parse import quote

from ..config import MCPConfig
from ..errors import BadRequestError, ForbiddenError
from ..responses import from_exception, success, viewer_meta
from ..viewer_client import ViewerClient

_ENDPOINT = "/api/v1/keywords"


def tool_list_keywords(
    client: ViewerClient,
    *,
    tag: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    params: dict[str, str] = {}
    if tag and tag.strip():
        params["tag"] = tag.strip()
    try:
        data = client.get(_ENDPOINT, params=params or None)
        return success("list_keywords", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("list_keywords", _ENDPOINT, started_at, exc)


def tool_add_keyword(
    client: ViewerClient,
    config: MCPConfig,
    *,
    expression: str | None = None,
    tags: list[str] | None = None,
    seuil_alerte: int | None = None,
    ou: list[str] | None = None,
    et: list[str] | None = None,
) -> dict:
    started_at = time.perf_counter()
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        expr = (expression or "").strip()
        if not expr:
            raise BadRequestError("Le paramètre expression est requis")

        body: dict[str, object] = {"expression": expr}
        if tags is not None:
            body["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        if seuil_alerte is not None:
            try:
                body["seuil_alerte"] = int(seuil_alerte)
            except (TypeError, ValueError):
                raise BadRequestError("seuil_alerte doit être un entier")
        if ou is not None:
            body["ou"] = [str(t).strip() for t in ou if str(t).strip()]
        if et is not None:
            body["et"] = [str(t).strip() for t in et if str(t).strip()]

        data = client.post(_ENDPOINT, json_body=body)
        if isinstance(data, dict):
            data = {"action": "added", **data}
        return success("add_keyword", data, meta=viewer_meta(_ENDPOINT, started_at))
    except Exception as exc:
        return from_exception("add_keyword", _ENDPOINT, started_at, exc)


def tool_update_keyword(
    client: ViewerClient,
    config: MCPConfig,
    *,
    keyword_id: str | None = None,
    expression: str | None = None,
    tags: list[str] | None = None,
    seuil_alerte: int | None = None,
    ou: list[str] | None = None,
    et: list[str] | None = None,
) -> dict:
    started_at = time.perf_counter()
    kid = (keyword_id or "").strip()
    endpoint = f"{_ENDPOINT}/{kid}"
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        if not kid:
            raise BadRequestError("Le paramètre keyword_id est requis")

        body: dict[str, object] = {}
        if expression is not None:
            body["expression"] = str(expression).strip()
        if tags is not None:
            body["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        if seuil_alerte is not None:
            try:
                body["seuil_alerte"] = int(seuil_alerte)
            except (TypeError, ValueError):
                raise BadRequestError("seuil_alerte doit être un entier")
        if ou is not None:
            body["ou"] = [str(t).strip() for t in ou if str(t).strip()]
        if et is not None:
            body["et"] = [str(t).strip() for t in et if str(t).strip()]
        if not body:
            raise BadRequestError("Au moins un champ à modifier est requis")

        data = client.patch(endpoint, json_body=body)
        if isinstance(data, dict):
            data = {"action": "updated", **data}
        return success("update_keyword", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("update_keyword", endpoint, started_at, exc)


def tool_delete_keyword(
    client: ViewerClient,
    config: MCPConfig,
    *,
    keyword_id: str | None = None,
) -> dict:
    started_at = time.perf_counter()
    kid = (keyword_id or "").strip()
    endpoint = f"{_ENDPOINT}/{kid}"
    try:
        if not config.enable_write_tools:
            raise ForbiddenError("Les tools d'écriture sont désactivés")
        if not kid:
            raise BadRequestError("Le paramètre keyword_id est requis")

        data = client.delete(endpoint)
        if isinstance(data, dict):
            data = {"action": "deleted", **data}
        return success("delete_keyword", data, meta=viewer_meta(endpoint, started_at))
    except Exception as exc:
        return from_exception("delete_keyword", endpoint, started_at, exc)


def tool_get_keyword_articles(
    client: ViewerClient,
    *,
    keyword_id: str | None = None,
    days: int | None = None,
) -> dict:
    started_at = time.perf_counter()
    kid = (keyword_id or "").strip()
    endpoint = f"{_ENDPOINT}/{quote(kid, safe='')}/articles"
    try:
        if not kid:
            raise BadRequestError("Le paramètre keyword_id est requis")
        params: dict[str, str | int] = {}
        if days is not None:
            try:
                params["days"] = max(1, int(days))
            except (TypeError, ValueError):
                raise BadRequestError("days doit être un entier")
        data = client.get(
            endpoint,
            params=params or None,
            timeout=client.heavy_timeout,
        )
        return success(
            "get_keyword_articles", data, meta=viewer_meta(endpoint, started_at)
        )
    except Exception as exc:
        return from_exception("get_keyword_articles", endpoint, started_at, exc)
