"""In-memory (and one persisted) state backing the OAuth 2.1 wrapper in
oauth.py.

``PendingAuthorization``/``AuthorizationCode`` are short-lived, single-
process state with no need to survive a restart -- a dropped PKCE
challenge or stale code just makes the human log in again, same cost as
any expired-token retry. ``RegisteredClientStore`` is persisted to disk:
losing every dynamically-registered MCP client (Claude Desktop, etc.) on
each eisy-ai restart would force every one of them to re-register and the
human to re-approve, a real UX cost worth avoiding -- mirrors
``src/unified/plugin_authoring/developer_config.py``'s own small-JSON-file
pattern in the nucore-ai repo.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any


class _TTLStore:
    """Shared sweep-on-access TTL bookkeeping for the two in-memory stores
    below -- no background thread, since this is a single-hub, low-
    concurrency device and expiry only ever needs to be checked when
    something is actually read or written."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}

    def _sweep(self) -> None:
        now = time.monotonic()
        for key in [k for k, (expires_at, _) in self._entries.items() if expires_at <= now]:
            del self._entries[key]

    def _create(self, key: str, value: dict[str, Any]) -> None:
        self._sweep()
        self._entries[key] = (time.monotonic() + self._ttl_seconds, value)

    def _peek(self, key: str) -> dict[str, Any] | None:
        self._sweep()
        entry = self._entries.get(key)
        return entry[1] if entry else None

    def _pop(self, key: str) -> dict[str, Any] | None:
        self._sweep()
        entry = self._entries.pop(key, None)
        return entry[1] if entry else None


class PendingAuthorizationStore(_TTLStore):
    """The OAuth params captured at ``GET /authorize`` time, before any
    credential is collected -- the login form's only hidden field is the
    opaque request id this returns, never the raw
    ``redirect_uri``/``client_id``, so a forged login POST can't swap them
    underneath an in-flight login."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        super().__init__(ttl_seconds)

    def create(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        state: str | None,
        code_challenge: str,
        code_challenge_method: str,
        scope: str | None,
    ) -> str:
        request_id = secrets.token_urlsafe(32)
        self._create(
            request_id,
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "scope": scope,
            },
        )
        return request_id

    def get(self, request_id: str) -> dict[str, Any] | None:
        return self._peek(request_id)


class AuthorizationCodeStore(_TTLStore):
    """Single-use: holds the hub's already-obtained JWT pair (fetched at
    the ``/authorize`` POST step) plus the PKCE challenge, consumed exactly
    once by ``POST /token``'s ``authorization_code`` grant."""

    def __init__(self, ttl_seconds: float = 60.0) -> None:
        super().__init__(ttl_seconds)

    def create(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str,
        access_token: str,
        refresh_token: str,
    ) -> str:
        code = secrets.token_urlsafe(32)
        self._create(
            code,
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
        )
        return code

    def consume(self, code: str) -> dict[str, Any] | None:
        """Pops *code* -- single-use, whether or not the caller goes on to
        validate it successfully. A code that's been looked at once is
        done either way; replaying it is exactly the "use a code twice"
        attack this is here to prevent."""
        return self._pop(code)


class RegisteredClientStore:
    """Dynamic client registration (RFC 7591) records, persisted as one
    small JSON file -- no client secret is ever stored (PKCE substitutes
    for one; every registered client is a public client)."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._clients: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._clients, indent=2) + "\n", encoding="utf-8")

    def register(self, *, redirect_uris: list[str], client_name: str | None, grant_types: list[str]) -> dict[str, Any]:
        client_id = secrets.token_urlsafe(24)
        record = {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": list(redirect_uris),
            "grant_types": list(grant_types),
            "token_endpoint_auth_method": "none",
        }
        self._clients[client_id] = record
        self._save()
        return record

    def get(self, client_id: str) -> dict[str, Any] | None:
        return self._clients.get(client_id)

    def has_redirect_uri(self, client_id: str, redirect_uri: str) -> bool:
        client = self.get(client_id)
        return bool(client) and redirect_uri in client.get("redirect_uris", [])
