"""The proxy's relay logic, exercised against a real (temp, local) Unix
socket upstream -- the one piece of this that's worth a real socket round
trip, since header/streaming handling is exactly where a reverse proxy goes
subtly wrong. The outer client-to-proxy leg uses httpx's ASGITransport
(in-process, no second real TCP port needed); the inner proxy-to-upstream
leg is a real AF_UNIX socket, same as production.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
import uvicorn

from mcp_proxy.proxy import _stream_upstream_body, build_proxy_app


async def _fake_upstream(scope, receive, send):
    assert scope["type"] == "http"
    body = b'{"ok": true, "path": "%s"}' % scope["path"].encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


@pytest.fixture
async def upstream_socket(tmp_path):
    sock_path = str(tmp_path / "fake-upstream.sock")
    config = uvicorn.Config(_fake_upstream, uds=sock_path, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if os.path.exists(sock_path):
            break
        await asyncio.sleep(0.02)
    yield sock_path
    server.should_exit = True
    await task


@pytest.mark.asyncio
async def test_proxy_relays_request_and_response(upstream_socket):
    class _AllowHook:
        async def authenticate(self, request):
            return True

    app = build_proxy_app(unix_socket_path=upstream_socket, auth_hook=_AllowHook())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        response = await client.post("/mcp", json={"anything": "goes"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "path": "/mcp"}


@pytest.mark.asyncio
async def test_proxy_rejects_when_auth_hook_denies(upstream_socket):
    class _DenyHook:
        async def authenticate(self, request):
            return False

    app = build_proxy_app(
        unix_socket_path=upstream_socket, auth_hook=_DenyHook(), issuer="https://eisy.local:8260"
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://proxy") as client:
        response = await client.get("/mcp")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == (
        'Bearer resource_metadata="https://eisy.local:8260/.well-known/oauth-protected-resource"'
    )


class _FakeUpstreamResponse:
    """Just enough of httpx.Response's streaming surface for
    _stream_upstream_body -- aiter_raw() and aclose(), nothing else."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def aiter_raw(self):
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_stream_upstream_body_closes_on_normal_completion():
    upstream = _FakeUpstreamResponse([b"chunk-1", b"chunk-2"])
    chunks = [c async for c in _stream_upstream_body(upstream)]
    assert chunks == [b"chunk-1", b"chunk-2"]
    assert upstream.closed is True


@pytest.mark.asyncio
async def test_stream_upstream_body_closes_on_early_cancellation():
    """Simulates exactly what a downstream client disconnect does in
    production: the consumer (StreamingResponse) stops iterating and the
    generator is cancelled mid-stream, before it would have reached the
    second chunk on its own. gen.aclose() is the real mechanism Python uses
    to cancel a suspended async generator -- not a stand-in for it."""
    upstream = _FakeUpstreamResponse([b"chunk-1", b"chunk-2"])
    gen = _stream_upstream_body(upstream)
    first_chunk = await gen.__anext__()
    assert first_chunk == b"chunk-1"
    assert upstream.closed is False  # not yet -- still mid-stream

    await gen.aclose()

    assert upstream.closed is True
