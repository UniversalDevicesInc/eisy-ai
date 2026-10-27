"""The one seam Phase 2 (real authentication) is expected to touch.

``AllowAllAuthHook`` is the Phase 1 default: every request is let through,
with no credential of any kind checked. This is a deliberate, temporary
state (see design/mcp-server.md in the nucore-ai repo for the full
rationale) -- it must not be the configured hook on any customer-facing
unit. A later phase implements a real ``AuthHook`` (validating a platform
session, a JWT, an mTLS client cert, or whatever gets decided) and swaps it
into ``run_proxy.py``'s construction of the proxy app; ``proxy.py``'s relay
logic does not change either way.
"""

from __future__ import annotations

import hashlib
import time
from typing import Protocol

from starlette.requests import Request
from nucore import NuCoreInterface
from utils import get_logger

logger = get_logger(__name__)


class AuthHook(Protocol):
    async def authenticate(self, request: Request) -> bool:
        """Return True to let *request* through to nucore-ai's MCP server,
        False to reject it with 401 (see proxy.py's deny branch). Receives
        the full incoming Starlette Request (headers, method, path, client
        address) so a real implementation has everything it needs (a
        bearer token, a cookie, an mTLS peer cert via request.scope's TLS
        extension, etc.) without this protocol needing to change shape
        later."""
        ...


class AllowAllAuthHook:
    """Phase 1 stub: authenticates nothing, allows everything. Not reachable
    from start_eisyai.py's production wiring any more (see run_proxy.py) --
    kept only for this package's own unit tests and bare local/dev
    invocations with no real NuCoreInterface to authenticate against at
    all. Logs once at startup (see run_proxy.py) rather than per-request,
    so the fact that this is the active hook is impossible to miss in the
    logs without spamming them."""

    async def authenticate(self, request: Request) -> bool:
        return True


class HubBearerAuthHook:
    """Phase 2's real hook: validates the ``Authorization: Bearer <token>``
    header a client presents by replaying it against the hub's own
    ``GET /rest/time`` (``NuCoreInterface.verify_bearer_token`` -- nucore-ai
    repo). Never invents a new credential of its own; the hub's real login
    is the only identity system this trusts, same as every other caller of
    nucore-ai's tools. See design/mcp-server.md's Phase 2 section (nucore-ai
    repo) for the full design and its threat-model scope.

    Caches only confirmed-good tokens, keyed by a hash of the token itself
    (not the MCP ``mcp-session-id`` header) so this works the same way
    regardless of whether a given MCP client implements session semantics
    correctly -- *ttl_seconds* bounds how long a confirmed-good token is
    trusted without re-checking the hub, safely below the hub's own 1-hour
    access-token lifetime (design/iox_apis/authentication.md, nucore-ai
    repo)."""

    def __init__(self, nucore_interface: NuCoreInterface, ttl_seconds: float = 120.0) -> None:
        self._nucore_interface = nucore_interface
        self._ttl_seconds = ttl_seconds
        self._good_until: dict[str, float] = {}

    def _token_key(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def authenticate(self, request: Request) -> bool:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return False

        key = self._token_key(token)
        now = time.monotonic()
        expires_at = self._good_until.get(key)
        if expires_at is not None and expires_at > now:
            return True

        result = await self._nucore_interface.verify_bearer_token(token)
        if result is True:
            self._good_until[key] = now + self._ttl_seconds
            return True
        if result is False:
            logger.info("mcp_proxy: hub rejected a presented bearer token")
        else:
            logger.warning("mcp_proxy: could not reach the hub to verify a presented bearer token")
        return False
