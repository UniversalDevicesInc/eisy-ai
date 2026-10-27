from __future__ import annotations

import pytest
from starlette.requests import Request

from mcp_proxy.auth import AllowAllAuthHook, HubBearerAuthHook


@pytest.mark.asyncio
async def test_allow_all_auth_hook_allows_everything():
    hook = AllowAllAuthHook()
    # The real contract takes a Starlette Request; None stands in fine here
    # since AllowAllAuthHook never inspects its argument -- that's the point.
    assert await hook.authenticate(None) is True


def _request_with_auth_header(value: str | None) -> Request:
    headers = [(b"authorization", value.encode())] if value is not None else []
    scope = {"type": "http", "headers": headers}
    return Request(scope)


class _FakeNuCoreInterface:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[str] = []

    async def verify_bearer_token(self, access_token: str):
        self.calls.append(access_token)
        return self.result


@pytest.mark.asyncio
async def test_hub_bearer_auth_hook_accepts_hub_confirmed_token():
    nucore_interface = _FakeNuCoreInterface(True)
    hook = HubBearerAuthHook(nucore_interface)
    assert await hook.authenticate(_request_with_auth_header("Bearer good-token")) is True


@pytest.mark.asyncio
async def test_hub_bearer_auth_hook_rejects_hub_rejected_token():
    nucore_interface = _FakeNuCoreInterface(False)
    hook = HubBearerAuthHook(nucore_interface)
    assert await hook.authenticate(_request_with_auth_header("Bearer bad-token")) is False


@pytest.mark.asyncio
async def test_hub_bearer_auth_hook_rejects_when_hub_unreachable():
    nucore_interface = _FakeNuCoreInterface(None)
    hook = HubBearerAuthHook(nucore_interface)
    assert await hook.authenticate(_request_with_auth_header("Bearer some-token")) is False


@pytest.mark.asyncio
async def test_hub_bearer_auth_hook_rejects_missing_or_non_bearer_header():
    nucore_interface = _FakeNuCoreInterface(True)
    hook = HubBearerAuthHook(nucore_interface)
    assert await hook.authenticate(_request_with_auth_header(None)) is False
    assert await hook.authenticate(_request_with_auth_header("Basic dXNlcjpwYXNz")) is False
    assert nucore_interface.calls == []  # never even asked the hub


@pytest.mark.asyncio
async def test_hub_bearer_auth_hook_caches_confirmed_token_within_ttl():
    nucore_interface = _FakeNuCoreInterface(True)
    hook = HubBearerAuthHook(nucore_interface, ttl_seconds=60.0)
    request = _request_with_auth_header("Bearer good-token")
    assert await hook.authenticate(request) is True
    assert await hook.authenticate(request) is True
    assert nucore_interface.calls == ["good-token"]  # only checked with the hub once


@pytest.mark.asyncio
async def test_hub_bearer_auth_hook_rechecks_after_ttl_expires():
    nucore_interface = _FakeNuCoreInterface(True)
    hook = HubBearerAuthHook(nucore_interface, ttl_seconds=0.0)
    request = _request_with_auth_header("Bearer good-token")
    assert await hook.authenticate(request) is True
    assert await hook.authenticate(request) is True
    assert nucore_interface.calls == ["good-token", "good-token"]  # re-checked every time, ttl=0
