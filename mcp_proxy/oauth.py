"""Thin OAuth 2.1 wrapper around the hub's own real login
(``/api/login``/``/api/jwt/refresh``/``/api/jwt/logout``, see
design/iox_apis/authentication.md in the nucore-ai repo), built because
real MCP clients require full OAuth 2.1 discovery + dynamic client
registration + PKCE -- Claude Desktop's remote-MCP connector has no
fallback to a static bearer header at all. This wrapper never invents a
new identity system: every credential check still ultimately goes through
the hub's own login, replayed via ``nucore_interface``'s
``login_with_credentials``/``refresh_access_token``/``logout`` (nucore-ai
repo, ``src/nucore/nucore_interface.py``). See design/mcp-server.md's
Phase 2 section for the full design.
"""

from __future__ import annotations

import base64
import hashlib
import html
from typing import Any, Callable
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from nucore import NuCoreInterface
from utils import get_logger, register_secret

from .oauth_store import AuthorizationCodeStore, PendingAuthorizationStore, RegisteredClientStore

logger = get_logger(__name__)

# Matches the hub's own documented access-token lifetime
# (design/iox_apis/authentication.md: "Access token ... Expiry 1 hour").
_ACCESS_TOKEN_EXPIRES_IN_S = 3600


def _pkce_matches(code_verifier: str, code_challenge: str) -> bool:
    """S256 only (OAuth 2.1's minimum bar) -- ``plain`` is never accepted."""
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return computed == code_challenge


def _append_query(url: str, params: dict[str, str]) -> str:
    scheme, netloc, path, query, fragment = urlsplit(url)
    extra = urlencode({k: v for k, v in params.items() if v is not None})
    new_query = f"{query}&{extra}" if query else extra
    return urlunsplit((scheme, netloc, path, new_query, fragment))


def _is_well_formed_redirect_uri(uri: str) -> bool:
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    return bool(parsed.scheme) and bool(parsed.netloc or parsed.path)


def _render_login_form(request_id: str, error: str | None = None) -> str:
    error_html = f'<p style="color:red">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html><head><title>Sign in</title></head>
<body>
<h1>Sign in to this eisy</h1>
{error_html}
<form method="post" action="/authorize">
  <input type="hidden" name="request_id" value="{html.escape(request_id)}">
  <label>Username <input type="text" name="username" required autofocus></label><br>
  <label>Password <input type="password" name="password" required></label><br>
  <button type="submit">Sign in</button>
</form>
</body></html>
"""


def _authorization_server_metadata(issuer: str) -> dict[str, Any]:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/authorize",
        "token_endpoint": f"{issuer}/token",
        "registration_endpoint": f"{issuer}/register",
        "revocation_endpoint": f"{issuer}/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


def _protected_resource_metadata(issuer: str) -> dict[str, Any]:
    return {
        "resource": issuer,
        "authorization_servers": [issuer],
    }


def build_oauth_routes(
    *,
    issuer: str,
    nucore_interface: NuCoreInterface,
    client_store_path: str,
    direct_base_url: Callable[[], str | None],
    is_unauthorized: Callable[[], bool] = lambda: False,
) -> list[Route]:
    """*issuer* is this proxy's own externally-reachable base URL (e.g.
    ``"https://eisy.local:8260"``) -- the same value already threaded
    through to nucore-ai's ``get_system_prompt`` tool, reused here so this
    wrapper and that tool agree on one address for this device.
    *direct_base_url* resolves the hub's real, non-relayed address at call
    time (see isy_direct_address.py) -- a callable, not a plain string,
    because it may not be known yet at startup and can only be read when
    actually needed. *is_unauthorized*, when it returns True, means
    *direct_base_url* will never resolve on its own -- this node server's
    own configuration does not grant it "Allow Unrestricted ISY Access by
    Node Server" -- a permanent misconfiguration, not a startup delay;
    callers below must give a distinctly different, actionable message for
    this case rather than "try again shortly."""
    clients = RegisteredClientStore(client_store_path)
    pending_authorizations = PendingAuthorizationStore()
    authorization_codes = AuthorizationCodeStore()

    async def discovery_metadata(request: Request) -> Response:
        return JSONResponse(_authorization_server_metadata(issuer))

    async def protected_resource_metadata(request: Request) -> Response:
        return JSONResponse(_protected_resource_metadata(issuer))

    async def register(request: Request) -> Response:
        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        redirect_uris = payload.get("redirect_uris")
        if not isinstance(redirect_uris, list) or not redirect_uris or not all(
            isinstance(uri, str) and _is_well_formed_redirect_uri(uri) for uri in redirect_uris
        ):
            return JSONResponse({"error": "invalid_redirect_uri"}, status_code=400)
        grant_types = payload.get("grant_types") or ["authorization_code", "refresh_token"]
        record = clients.register(
            redirect_uris=redirect_uris,
            client_name=payload.get("client_name"),
            grant_types=grant_types,
        )
        return JSONResponse(record, status_code=201)

    async def authorize_get(request: Request) -> Response:
        params = request.query_params
        client_id = params.get("client_id")
        redirect_uri = params.get("redirect_uri")
        code_challenge = params.get("code_challenge")
        code_challenge_method = params.get("code_challenge_method")
        if not client_id or not redirect_uri or not code_challenge:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if code_challenge_method != "S256":
            return JSONResponse({"error": "invalid_request", "error_description": "only S256 PKCE is supported"}, status_code=400)
        # Exact match only -- standard OAuth 2.1 open-redirect defense.
        # Checked before anything is rendered, so an unregistered client or
        # an off-list redirect_uri never even gets a login form.
        if not clients.has_redirect_uri(client_id, redirect_uri):
            return JSONResponse({"error": "invalid_request", "error_description": "unknown client_id or redirect_uri"}, status_code=400)
        request_id = pending_authorizations.create(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=params.get("state"),
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=params.get("scope"),
        )
        return HTMLResponse(_render_login_form(request_id))

    async def authorize_post(request: Request) -> Response:
        form = await request.form()
        request_id = form.get("request_id")
        pending = pending_authorizations.get(request_id) if request_id else None
        if pending is None:
            return JSONResponse({"error": "invalid_request", "error_description": "expired or unknown authorization attempt"}, status_code=400)

        username = form.get("username")
        password = form.get("password")
        if not username or not password:
            return HTMLResponse(_render_login_form(request_id, error="Username and password are required."))
        register_secret(password)

        base_url = direct_base_url()
        if base_url is None:
            if is_unauthorized():
                return HTMLResponse(
                    _render_login_form(
                        request_id,
                        error=(
                            "This eisy's node server configuration does not allow unrestricted ISY "
                            "access, so sign-in can never complete until that's changed -- go to this "
                            "node server's configuration and enable 'Allow Unrestricted ISY Access by "
                            "Node Server', then try again."
                        ),
                    )
                )
            return HTMLResponse(_render_login_form(request_id, error="This eisy is still starting up -- try again shortly."))

        result = await nucore_interface.login_with_credentials(username, password, base_url)
        if result is None:
            return HTMLResponse(_render_login_form(request_id, error="Could not reach this eisy right now -- try again shortly."))

        status_code = result["status_code"]
        body = result["body"] or {}
        if status_code == 200 and body.get("successful") is True:
            data = body.get("data") or {}
            register_secret(data.get("accessToken"))
            register_secret(data.get("refreshToken"))
            code = authorization_codes.create(
                client_id=pending["client_id"],
                redirect_uri=pending["redirect_uri"],
                code_challenge=pending["code_challenge"],
                code_challenge_method=pending["code_challenge_method"],
                access_token=data.get("accessToken"),
                refresh_token=data.get("refreshToken"),
            )
            redirect_url = _append_query(pending["redirect_uri"], {"code": code, "state": pending.get("state")})
            return RedirectResponse(redirect_url, status_code=302)
        if status_code == 503:
            return HTMLResponse(_render_login_form(request_id, error="This eisy is still starting up -- try again shortly."))
        # 403 ("invalid credentials") and any other non-success response
        # both land here as "wrong username or password" -- the hub is the
        # one source of truth on what counts as invalid.
        return HTMLResponse(_render_login_form(request_id, error="Invalid username or password."))

    async def token(request: Request) -> Response:
        form = await request.form()
        grant_type = form.get("grant_type")

        if grant_type == "authorization_code":
            code = form.get("code")
            code_verifier = form.get("code_verifier")
            redirect_uri = form.get("redirect_uri")
            client_id = form.get("client_id")
            pending_code = authorization_codes.consume(code) if code else None
            if pending_code is None:
                return JSONResponse({"error": "invalid_grant", "error_description": "unknown, expired, or already-used code"}, status_code=400)
            if pending_code["client_id"] != client_id or pending_code["redirect_uri"] != redirect_uri:
                return JSONResponse({"error": "invalid_grant", "error_description": "client_id/redirect_uri mismatch"}, status_code=400)
            if not code_verifier or not _pkce_matches(code_verifier, pending_code["code_challenge"]):
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)
            return JSONResponse(
                {
                    "access_token": pending_code["access_token"],
                    "refresh_token": pending_code["refresh_token"],
                    "token_type": "Bearer",
                    "expires_in": _ACCESS_TOKEN_EXPIRES_IN_S,
                }
            )

        if grant_type == "refresh_token":
            refresh_token = form.get("refresh_token")
            if not refresh_token:
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            register_secret(refresh_token)
            base_url = direct_base_url()
            if base_url is None:
                if is_unauthorized():
                    return JSONResponse(
                        {
                            "error": "temporarily_unavailable",
                            "error_description": (
                                "this eisy's node server configuration does not allow unrestricted "
                                "ISY access -- enable 'Allow Unrestricted ISY Access by Node Server' "
                                "in this node server's configuration; this will never resolve on its "
                                "own"
                            ),
                        },
                        status_code=400,
                    )
                return JSONResponse({"error": "temporarily_unavailable", "error_description": "this eisy is still starting up"}, status_code=400)
            result = await nucore_interface.refresh_access_token(refresh_token, base_url)
            if result is None:
                return JSONResponse({"error": "temporarily_unavailable", "error_description": "could not reach this eisy"}, status_code=400)
            status_code = result["status_code"]
            body = result["body"] or {}
            if status_code == 200 and body.get("successful") is True:
                data = body.get("data") or {}
                register_secret(data.get("accessToken"))
                register_secret(data.get("refreshToken"))
                return JSONResponse(
                    {
                        "access_token": data.get("accessToken"),
                        "refresh_token": data.get("refreshToken"),
                        "token_type": "Bearer",
                        "expires_in": _ACCESS_TOKEN_EXPIRES_IN_S,
                    }
                )
            # The hub's own documented condition for this exact status is
            # "invalid, expired, or already used" -- maps directly onto
            # OAuth's own invalid_grant.
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    async def revoke(request: Request) -> Response:
        form = await request.form()
        refresh_token = form.get("token")
        if not refresh_token:
            # RFC 7009: the server should still respond 200 even for a
            # missing/invalid token, so a client can't use this endpoint to
            # probe for which tokens are real.
            return Response(status_code=200)
        register_secret(refresh_token)
        base_url = direct_base_url()
        if base_url is not None:
            result = await nucore_interface.logout(refresh_token, base_url)
            if result is None or result["status_code"] not in (200, 403):
                logger.warning("mcp oauth: /revoke could not confirm revocation with the hub")
        return Response(status_code=200)

    return [
        Route("/.well-known/oauth-authorization-server", endpoint=discovery_metadata, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", endpoint=protected_resource_metadata, methods=["GET"]),
        Route("/register", endpoint=register, methods=["POST"]),
        Route("/authorize", endpoint=authorize_get, methods=["GET"]),
        Route("/authorize", endpoint=authorize_post, methods=["POST"]),
        Route("/token", endpoint=token, methods=["POST"]),
        Route("/revoke", endpoint=revoke, methods=["POST"]),
    ]
