"""mcp_proxy.oauth's OAuth 2.1 wrapper around the hub's real login -- the
full authorization_code+PKCE happy path, the refresh grant, PKCE/credential/
redirect_uri failures, and the "hub not reachable yet" cases, all against a
fake NuCoreInterface stub (no real hub needed) via httpx's ASGITransport
(in-process, no real network).
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.applications import Starlette

from utils import secret_redaction
from mcp_proxy.oauth import build_oauth_routes

_REDIRECT_URI = "http://127.0.0.1:9999/callback"


@pytest.fixture(autouse=True)
def _restore_secret_registry():
    """secret_redaction's registry is process-wide -- isolate this file's
    tests from each other and from any other test module."""
    saved = set(secret_redaction._secrets)
    try:
        yield
    finally:
        secret_redaction._secrets.clear()
        secret_redaction._secrets.update(saved)


class FakeNuCoreInterface:
    def __init__(self):
        self.login_result = {
            "status_code": 200,
            "body": {"successful": True, "data": {"accessToken": "AT", "refreshToken": "RT"}},
        }
        self.refresh_result = {
            "status_code": 200,
            "body": {"successful": True, "data": {"accessToken": "AT2", "refreshToken": "RT2"}},
        }
        self.logout_result = {"status_code": 200, "body": {"successful": True, "data": None}}
        self.calls: list[tuple] = []

    async def login_with_credentials(self, username, password, base_url):
        self.calls.append(("login", username, password, base_url))
        return self.login_result

    async def refresh_access_token(self, refresh_token, base_url):
        self.calls.append(("refresh", refresh_token, base_url))
        return self.refresh_result

    async def logout(self, refresh_token, base_url, access_token=None):
        self.calls.append(("logout", refresh_token, base_url, access_token))
        return self.logout_result

    async def verify_bearer_token(self, access_token):
        return True


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _extract_request_id(html: str) -> str:
    match = re.search(r'name="request_id" value="([^"]+)"', html)
    assert match, html
    return match.group(1)


def _build_app(
    nucore_interface,
    *,
    direct_base_url=lambda: "http://192.168.1.10:80",
    is_unauthorized=lambda: False,
    client_store_path,
):
    routes = build_oauth_routes(
        issuer="https://eisy.local:8260",
        nucore_interface=nucore_interface,
        client_store_path=client_store_path,
        direct_base_url=direct_base_url,
        is_unauthorized=is_unauthorized,
    )
    return Starlette(routes=routes)


@pytest.fixture
def client_store_path(tmp_path):
    return str(tmp_path / "clients.json")


async def _client_for(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="https://eisy.local:8260", follow_redirects=False)


@pytest.mark.asyncio
async def test_discovery_metadata(client_store_path):
    app = _build_app(FakeNuCoreInterface(), client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200
        body = response.json()
        assert body["issuer"] == "https://eisy.local:8260"
        assert body["authorization_endpoint"] == "https://eisy.local:8260/authorize"
        assert body["code_challenge_methods_supported"] == ["S256"]

        response = await client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        assert response.json()["authorization_servers"] == ["https://eisy.local:8260"]


@pytest.mark.asyncio
async def test_register_then_authorize_rejects_unknown_client_or_redirect_uri(client_store_path):
    app = _build_app(FakeNuCoreInterface(), client_store_path=client_store_path)
    async with await _client_for(app) as client:
        register_response = await client.post("/register", json={"redirect_uris": [_REDIRECT_URI]})
        assert register_response.status_code == 201
        client_id = register_response.json()["client_id"]
        assert register_response.json()["client_name"] is None

        # Unknown client_id entirely.
        resp = await client.get(
            "/authorize",
            params={
                "client_id": "not-a-real-client",
                "redirect_uri": _REDIRECT_URI,
                "code_challenge": "x",
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400

        # Registered client, but a redirect_uri that was never registered.
        resp = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": "http://evil.example/callback",
                "code_challenge": "x",
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400


async def _register_and_begin_authorize(client, *, state="xyz"):
    register_response = await client.post("/register", json={"redirect_uris": [_REDIRECT_URI]})
    client_id = register_response.json()["client_id"]
    verifier, challenge = _pkce_pair()
    authorize_response = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": _REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
    )
    assert authorize_response.status_code == 200
    request_id = _extract_request_id(authorize_response.text)
    return client_id, verifier, request_id


@pytest.mark.asyncio
async def test_full_authorization_code_pkce_happy_path(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        client_id, verifier, request_id = await _register_and_begin_authorize(client)

        login_response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        assert login_response.status_code == 302
        location = login_response.headers["location"]
        qs = parse_qs(urlsplit(location).query)
        assert qs["state"] == ["xyz"]
        code = qs["code"][0]
        assert nucore_interface.calls[0] == ("login", "alice", "secret", "http://192.168.1.10:80")

        token_response = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert token_response.status_code == 200
        body = token_response.json()
        assert body["access_token"] == "AT"
        assert body["refresh_token"] == "RT"
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 3600


@pytest.mark.asyncio
async def test_authorization_code_is_single_use(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        client_id, verifier, request_id = await _register_and_begin_authorize(client)
        login_response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        code = parse_qs(urlsplit(login_response.headers["location"]).query)["code"][0]
        token_args = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        }
        first = await client.post("/token", data=token_args)
        assert first.status_code == 200
        second = await client.post("/token", data=token_args)
        assert second.status_code == 400
        assert second.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_wrong_pkce_verifier_rejected(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        login_response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        code = parse_qs(urlsplit(login_response.headers["location"]).query)["code"][0]
        response = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": "completely-wrong-verifier",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_forged_code_rejected(client_store_path):
    app = _build_app(FakeNuCoreInterface(), client_store_path=client_store_path)
    async with await _client_for(app) as client:
        await client.post("/register", json={"redirect_uris": [_REDIRECT_URI]})
        response = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": "totally-made-up",
                "redirect_uri": _REDIRECT_URI,
                "client_id": "whatever",
                "code_verifier": "whatever",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_refresh_token_grant(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "RT"})
        assert response.status_code == 200
        body = response.json()
        assert body["access_token"] == "AT2"
        assert body["refresh_token"] == "RT2"
        assert nucore_interface.calls == [("refresh", "RT", "http://192.168.1.10:80")]


@pytest.mark.asyncio
async def test_refresh_token_grant_hub_rejects_is_invalid_grant(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    nucore_interface.refresh_result = {"status_code": 403, "body": {"successful": False}}
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "RT-used-already"})
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_refresh_token_grant_hub_unreachable_is_temporarily_unavailable(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    nucore_interface.refresh_result = None
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "RT"})
        assert response.status_code == 400
        assert response.json()["error"] == "temporarily_unavailable"


@pytest.mark.asyncio
async def test_refresh_token_grant_direct_base_url_not_resolved_yet(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, direct_base_url=lambda: None, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "RT"})
        assert response.status_code == 400
        assert response.json()["error"] == "temporarily_unavailable"
        assert nucore_interface.calls == []  # never even called the hub


@pytest.mark.asyncio
async def test_login_wrong_credentials_rerenders_form_with_error(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    nucore_interface.login_result = {"status_code": 403, "body": {"successful": False}}
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "wrong"}
        )
        assert response.status_code == 200  # re-rendered form, not a redirect
        assert "Invalid username or password" in response.text


@pytest.mark.asyncio
async def test_login_hub_starting_up_rerenders_form_with_distinct_error(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    nucore_interface.login_result = {"status_code": 503, "body": None}
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        assert response.status_code == 200
        assert "still starting up" in response.text


@pytest.mark.asyncio
async def test_login_hub_unreachable_rerenders_form_with_distinct_error(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    nucore_interface.login_result = None
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        assert response.status_code == 200
        assert "Could not reach" in response.text


@pytest.mark.asyncio
async def test_authorize_post_direct_base_url_not_resolved_yet(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, direct_base_url=lambda: None, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        assert response.status_code == 200
        assert "still starting up" in response.text
        assert nucore_interface.calls == []


@pytest.mark.asyncio
async def test_authorize_post_distinguishes_unauthorized_from_not_resolved_yet(client_store_path):
    """'ISY access not authorized' (this node server's own config will
    never grant direct access on its own) must give a different, actionable
    message from 'not resolved yet' (a transient startup delay) -- the two
    collapsing into the same generic error was the actual bug a real
    customer hit (the permission was never granted, so the message kept
    reappearing on every single attempt, forever, not just at startup)."""
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(
        nucore_interface,
        direct_base_url=lambda: None,
        is_unauthorized=lambda: True,
        client_store_path=client_store_path,
    )
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        response = await client.post(
            "/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"}
        )
        assert response.status_code == 200
        assert "Allow Unrestricted ISY Access by Node Server" in response.text
        assert "still starting up" not in response.text
        assert nucore_interface.calls == []


@pytest.mark.asyncio
async def test_refresh_token_grant_distinguishes_unauthorized_from_not_resolved_yet(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(
        nucore_interface,
        direct_base_url=lambda: None,
        is_unauthorized=lambda: True,
        client_store_path=client_store_path,
    )
    async with await _client_for(app) as client:
        response = await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "RT"})
        assert response.status_code == 400
        assert response.json()["error"] == "temporarily_unavailable"
        assert "Allow Unrestricted ISY Access by Node Server" in response.json()["error_description"]
        assert nucore_interface.calls == []


@pytest.mark.asyncio
async def test_authorize_post_unknown_request_id_rejected(client_store_path):
    app = _build_app(FakeNuCoreInterface(), client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post(
            "/authorize", data={"request_id": "made-up", "username": "alice", "password": "secret"}
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_revoke_calls_hub_logout(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/revoke", data={"token": "RT"})
        assert response.status_code == 200
        assert nucore_interface.calls == [("logout", "RT", "http://192.168.1.10:80", None)]


@pytest.mark.asyncio
async def test_revoke_missing_token_still_returns_200_without_calling_hub(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/revoke", data={})
        assert response.status_code == 200
        assert nucore_interface.calls == []


@pytest.mark.asyncio
async def test_registered_clients_persist_to_disk(client_store_path):
    app = _build_app(FakeNuCoreInterface(), client_store_path=client_store_path)
    async with await _client_for(app) as client:
        response = await client.post("/register", json={"redirect_uris": [_REDIRECT_URI], "client_name": "claude"})
        client_id = response.json()["client_id"]

    # A fresh app instance (same store path) must still know this client --
    # proves it was actually written to disk, not just kept in memory.
    app2 = _build_app(FakeNuCoreInterface(), client_store_path=client_store_path)
    async with await _client_for(app2) as client:
        resp = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": _REDIRECT_URI,
                "code_challenge": "x",
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 200


# --- secret redaction: a submitted password and every issued token must be
# registered the moment they're known, so logger.py's RedactingFilter (and
# nucore-ai's prompt_log.py, if this process ever shares that path) catches
# them -- see design/mcp-server.md's Phase 2 "secret-redaction design". ---


@pytest.mark.asyncio
async def test_authorize_post_registers_submitted_password(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        await client.post("/authorize", data={"request_id": request_id, "username": "alice", "password": "hunter2"})
    assert "hunter2" in secret_redaction._secrets


@pytest.mark.asyncio
async def test_authorize_post_registers_issued_tokens(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        _client_id, _verifier, request_id = await _register_and_begin_authorize(client)
        await client.post("/authorize", data={"request_id": request_id, "username": "alice", "password": "secret"})
    assert "AT" in secret_redaction._secrets  # FakeNuCoreInterface's login_result accessToken
    assert "RT" in secret_redaction._secrets  # ...refreshToken


@pytest.mark.asyncio
async def test_refresh_token_grant_registers_submitted_and_issued_tokens(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        await client.post("/token", data={"grant_type": "refresh_token", "refresh_token": "RT-submitted"})
    assert "RT-submitted" in secret_redaction._secrets  # the token the client sent in
    assert "AT2" in secret_redaction._secrets  # FakeNuCoreInterface's refresh_result accessToken
    assert "RT2" in secret_redaction._secrets  # ...refreshToken


@pytest.mark.asyncio
async def test_revoke_registers_submitted_token(client_store_path):
    nucore_interface = FakeNuCoreInterface()
    app = _build_app(nucore_interface, client_store_path=client_store_path)
    async with await _client_for(app) as client:
        await client.post("/revoke", data={"token": "RT-to-revoke"})
    assert "RT-to-revoke" in secret_redaction._secrets
