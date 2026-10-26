"""A dumb pass-through reverse proxy: relays every request (any path,
method, headers, body) to nucore-ai's MCP server over a Unix domain socket,
after the request clears the configured AuthHook (auth.py). No MCP/JSON-RPC
awareness here at all, deliberately -- that logic stays in nucore-ai, next
to the tool definitions it reasons about; this is transport only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Mount

from utils import get_logger

from .auth import AuthHook

logger = get_logger(__name__)

# Headers that must never be forwarded verbatim: httpx computes its own Host
# and framing (Content-Length/Transfer-Encoding) for the outbound request to
# the Unix socket, and Connection is a hop-by-hop header that has no meaning
# carried across a proxy.
_STRIPPED_REQUEST_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}
_STRIPPED_RESPONSE_HEADERS = {"content-length", "transfer-encoding", "connection"}


async def _stream_upstream_body(upstream_response: httpx.Response) -> AsyncIterator[bytes]:
    """``finally``, not just a trailing ``aclose()`` -- if the downstream
    client disconnects mid-stream, uvicorn cancels the task running this
    generator while ``aiter_raw()`` is mid-read, which would skip any
    cleanup placed after the loop instead. This guarantees the upstream
    connection is always released, including on that (routine, not
    exceptional) client-disconnect path. Module-level, not an inline
    closure, so it's directly testable without a real network disconnect --
    see ``tests/mcp_proxy/test_proxy.py``."""
    try:
        async for chunk in upstream_response.aiter_raw():
            yield chunk
    finally:
        await upstream_response.aclose()


class _ProxyApp:
    def __init__(self, unix_socket_path: str, auth_hook: AuthHook) -> None:
        self._auth_hook = auth_hook
        transport = httpx.AsyncHTTPTransport(uds=unix_socket_path)
        # base_url's host is never actually resolved (uds= replaces the
        # connection step entirely) -- it only has to be a well-formed URL.
        # timeout=None: httpx's own default is a flat 5s on every leg
        # (connect/read/write/pool), which is far too short for a relay --
        # a tool call on the other end of this socket (an LLM-backed one,
        # especially) can legitimately run well past 5s, and this is a
        # dumb pass-through with no opinion of its own on how long that
        # should take; the real client's own timeout is what should govern.
        self._client = httpx.AsyncClient(transport=transport, base_url="http://nucore-mcp", timeout=None)

    async def __call__(self, scope, receive, send) -> None:
        request = Request(scope, receive=receive)

        if not await self._auth_hook.authenticate(request):
            response = Response("forbidden", status_code=403)
            await response(scope, receive, send)
            return

        body = await request.body()
        forward_headers = [
            (name, value) for name, value in request.headers.raw if name.decode("latin-1").lower() not in _STRIPPED_REQUEST_HEADERS
        ]
        upstream_request = self._client.build_request(
            request.method,
            request.url.path,
            headers=forward_headers,
            content=body,
        )

        try:
            upstream_response = await self._client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            logger.error("mcp_proxy: upstream unix-socket request failed: %s", exc)
            response = Response("upstream unavailable", status_code=502)
            await response(scope, receive, send)
            return

        response_headers = [
            (name, value)
            for name, value in upstream_response.headers.raw
            if name.decode("latin-1").lower() not in _STRIPPED_RESPONSE_HEADERS
        ]

        response = StreamingResponse(
            _stream_upstream_body(upstream_response),
            status_code=upstream_response.status_code,
            headers=dict((n.decode("latin-1"), v.decode("latin-1")) for n, v in response_headers),
        )
        await response(scope, receive, send)


def build_proxy_app(*, unix_socket_path: str, auth_hook: AuthHook) -> Starlette:
    """Mount at the root (not a fixed path): the upstream MCP server's own
    path (``/mcp``) is forwarded through unchanged, so this proxy never
    needs to know or care what path nucore-ai actually serves on. Mount,
    not Route: Route treats a plain function/method endpoint as
    ``func(request) -> response``, the wrong calling convention for a raw
    ASGI app -- see unified/mcp/server.py's own note on the same pitfall."""
    app = _ProxyApp(unix_socket_path=unix_socket_path, auth_hook=auth_hook)
    return Starlette(routes=[Mount("/", app=app)])
