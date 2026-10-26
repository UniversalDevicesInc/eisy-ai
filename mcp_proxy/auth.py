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

from typing import Protocol

from starlette.requests import Request
from utils import get_logger

logger = get_logger(__name__)


class AuthHook(Protocol):
    async def authenticate(self, request: Request) -> bool:
        """Return True to let *request* through to nucore-ai's MCP server,
        False to reject it with 403. Receives the full incoming Starlette
        Request (headers, method, path, client address) so a real
        implementation has everything it needs (a bearer token, a cookie,
        an mTLS peer cert via request.scope's TLS extension, etc.) without
        this protocol needing to change shape later."""
        ...


class AllowAllAuthHook:
    """Phase 1 stub: authenticates nothing, allows everything. Logs once at
    startup (see run_proxy.py) rather than per-request, so the fact that
    this is the active hook is impossible to miss in the logs without
    spamming them."""

    async def authenticate(self, request: Request) -> bool:
        return True
