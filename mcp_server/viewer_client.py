"""Client HTTP vers le Viewer Flask de WUDD.ai."""

from __future__ import annotations

from typing import Any

import requests

from .errors import (
    BadRequestError,
    ForbiddenError,
    MCPError,
    NotFoundError,
    UpstreamError,
    UpstreamUnavailableError,
)


class ViewerClient:
    """Client fin pour consommer l'API du Viewer."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 10,
        heavy_timeout: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.heavy_timeout = heavy_timeout or max(timeout, 30)
        self.retryable_methods = {"GET", "DELETE"}
        self.max_retries = 1
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "WUDD.ai-MCP/0.1.0",
            }
        )

    def build_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> Any:
        return self._request("GET", path, params=params, timeout=timeout)

    def post(
        self,
        path: str,
        json_body: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> Any:
        return self._request("POST", path, json_body=json_body, timeout=timeout)

    def delete(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> Any:
        return self._request("DELETE", path, params=params, timeout=timeout)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> Any:
        url = self.build_url(path)
        request_timeout = timeout or self.timeout
        response = None
        last_exception: Exception | None = None

        attempts = self.max_retries + 1 if method in self.retryable_methods else 1
        for _ in range(attempts):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=json_body,
                    timeout=request_timeout,
                )
                last_exception = None
                break
            except requests.Timeout as exc:
                last_exception = exc
            except requests.RequestException as exc:
                last_exception = exc

        if last_exception is not None:
            if isinstance(last_exception, requests.Timeout):
                raise UpstreamUnavailableError(
                    "Le Viewer ne répond pas dans le délai imparti",
                    {
                        "endpoint": path,
                        "method": method,
                        "timeout_s": request_timeout,
                        "attempts": attempts,
                        "retries": max(0, attempts - 1),
                    },
                ) from last_exception
            raise UpstreamUnavailableError(
                "Le Viewer est injoignable",
                {
                    "endpoint": path,
                    "method": method,
                    "timeout_s": request_timeout,
                    "attempts": attempts,
                    "retries": max(0, attempts - 1),
                },
            ) from last_exception

        if response.status_code >= 400:
            self._raise_for_status(path, response)

        content_type = response.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise UpstreamError(
                "Réponse non JSON inattendue du Viewer",
                {"endpoint": path, "content_type": content_type},
            )

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(
                "Réponse JSON invalide du Viewer",
                {"endpoint": path},
            ) from exc

    def _raise_for_status(self, path: str, response: requests.Response) -> None:
        message = _extract_error_message(response)
        details = {"endpoint": path, "status_code": response.status_code}
        if response.status_code == 400:
            raise BadRequestError(message, details)
        if response.status_code == 403:
            raise ForbiddenError(message, details)
        if response.status_code == 404:
            raise NotFoundError(message, details)
        raise UpstreamError(message, details)


def _extract_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, str) and error.strip():
                return error.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    except ValueError:
        pass

    text = (response.text or "").strip()
    if text:
        return text[:300]
    return f"Erreur Viewer HTTP {response.status_code}"
