"""Tests de l'authentification MCP."""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.auth import StaticTokenAuthProvider, validate_bearer_token
from mcp_server.errors import UnauthorizedError


def test_validate_bearer_token_accepts_valid_token():
    validate_bearer_token("Bearer secret-token", "secret-token")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, UnauthorizedError),
        ("", UnauthorizedError),
        ("Token secret-token", UnauthorizedError),
        ("Bearer wrong-token", UnauthorizedError),
    ],
)
def test_validate_bearer_token_rejects_invalid_header(header, expected):
    with pytest.raises(expected):
        validate_bearer_token(header, "secret-token")


def test_static_token_auth_provider_verifies_token():
    provider = StaticTokenAuthProvider("secret-token")

    token = asyncio.run(provider.verify_token("secret-token"))
    missing = asyncio.run(provider.verify_token("wrong-token"))

    assert token is not None
    assert token.client_id == "wudd-mcp-client"
    assert missing is None
