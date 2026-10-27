"""Resolves the hub's own real, direct HTTP(S) address -- bypassing the PG3
relay Unix socket (``/tmp/eisyui-listener``) that nucore-ai's ``IoXWrapper``
otherwise uses for every REST call. Needed because ``/api/login`` and
``/api/jwt/*`` are documented (design/iox_apis/authentication.md, nucore-ai
repo) as "local access only": requests routed through the portal proxy or
that internal relay socket are silently ignored.

This replicates the exact ``poly.subscribe(poly.ISY, ...)`` +
``poly.send({'getIsyInfo': {}}, 'system')`` pattern already proven correct
in two other places -- ``udi_interface``'s own ``ISY`` class
(``udi_interface/isy.py``) and nucore-ai's ``IoXWrapper`` poly-mode
constructor branch -- not a new mechanism, just invoked a second time from
this process's own scope, since eisy-ai's main ``NuCoreInterface`` is
constructed in direct/relay mode instead (see ``start_eisyai.py``), for
reasons unrelated to login.
"""

from __future__ import annotations

import threading
from typing import Any

from utils import get_logger

logger = get_logger(__name__)


class DirectHubAddressResolver:
    """Thread-safe holder for the hub's real ``isy_ip``/``isy_port``/
    ``isy_https``, populated asynchronously whenever Polyglot's ``ISY``
    info event fires (normally within moments of this being constructed).
    ``get()`` returns ``None`` until that first fires -- callers (the OAuth
    wrapper's ``/authorize`` and ``/token`` handlers) must treat that as
    "hub address not yet known," not as a permanent failure, and should
    surface a distinct "try again shortly" response rather than a generic
    error."""

    def __init__(self, polyglot: Any) -> None:
        self._lock = threading.Lock()
        self._base_url: str | None = None
        self._unauthorized = False
        polyglot.subscribe(polyglot.ISY, self._on_isy_info)
        polyglot.send({"getIsyInfo": {}}, "system")

    def _on_isy_info(self, info: dict[str, Any] | None) -> None:
        with self._lock:
            if info is None:
                self._unauthorized = True
                logger.error(
                    "DirectHubAddressResolver: ISY access not authorized -- the MCP OAuth "
                    "login/refresh/logout endpoints will not work until this node server's "
                    "configuration allows unrestricted ISY access."
                )
                return
            scheme = "https" if info.get("isy_https") == 1 else "http"
            self._base_url = f"{scheme}://{info['isy_ip_address']}:{info['isy_port']}"
            self._unauthorized = False

    def get(self) -> str | None:
        """The resolved ``scheme://host:port``, or ``None`` if the ``ISY``
        info event hasn't fired yet, or the most recent one reported
        ``unauthorized`` -- use :meth:`is_unauthorized` to tell those two
        apart; they need very different user-facing messages (one is
        "wait a moment," the other is "fix your node server config, this
        will never resolve on its own")."""
        with self._lock:
            return self._base_url

    def is_unauthorized(self) -> bool:
        """True if the most recent ``ISY`` info event reported this node
        server does not have "Allow Unrestricted ISY Access by Node
        Server" enabled -- a permanent condition until that configuration
        changes, not a transient startup delay. False both before the
        first event has fired at all (ambiguous -- treat as "not yet
        known," same as a plain ``get() is None``) and once a real address
        has been resolved."""
        with self._lock:
            return self._unauthorized
