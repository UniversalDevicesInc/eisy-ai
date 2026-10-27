"""CLI/embeddable entry point for the network-facing MCP proxy.

Binds a TLS TCP listener on the LAN and relays authenticated traffic to
nucore-ai's MCP server over a Unix domain socket (see proxy.py). Phase 2:
when a real ``NuCoreInterface`` is given, this mounts the OAuth 2.1
wrapper (oauth.py) and defaults the real ``HubBearerAuthHook`` (auth.py)
-- see design/mcp-server.md (nucore-ai repo) for the full design.
``AllowAllAuthHook`` remains only for this package's own unit tests and a
bare local/dev invocation with no real NuCoreInterface to authenticate
against at all; see the loud startup log line below for why that fact is
never silent.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from nucore import NuCoreInterface
from utils import configure_logging, get_logger

from .auth import AllowAllAuthHook, AuthHook, HubBearerAuthHook
from .oauth import build_oauth_routes
from .proxy import build_proxy_app

logger = get_logger(__name__)


def _build_proxy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the network-facing MCP proxy")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Address to bind the TCP listener to.")
    parser.add_argument("--port", type=int, default=8260, help="TCP port to bind the proxy to.")
    parser.add_argument(
        "--unix-socket-path",
        type=str,
        default=None,
        help=(
            "Required. Path of nucore-ai's MCP server Unix domain socket to relay requests to. "
            "Not argparse-required, so an in-process caller building a Namespace via "
            "parse_args([]) and setting attributes manually can still do so."
        ),
    )
    parser.add_argument("--ssl-certfile", type=str, default=None, help="Required. Path to a PEM certificate file.")
    parser.add_argument("--ssl-keyfile", type=str, default=None, help="Required. Path to a PEM private key file.")
    parser.add_argument(
        "--public-base-url",
        type=str,
        default=None,
        help=(
            "This proxy's own externally-reachable scheme://host:port (e.g. "
            "'https://eisy.local:8260') -- required for the OAuth 2.1 wrapper (used as "
            "'issuer' in its discovery metadata and the 401 denial's WWW-Authenticate "
            "challenge). Omit only for a bare local/dev invocation with no real "
            "NuCoreInterface, where the OAuth wrapper isn't mounted at all."
        ),
    )
    parser.add_argument(
        "--oauth-client-store-path",
        type=str,
        default=None,
        help="Where to persist dynamic client registrations (see oauth_store.RegisteredClientStore).",
    )
    parser.add_argument("--log-level", type=str, default=None, help="Logger level override")
    parser.add_argument("--log-file", type=str, default=None, help="Optional log file path")
    return parser


def main(
    args: Any = None,
    auth_hook: AuthHook | None = None,
    nucore_interface: NuCoreInterface | None = None,
    direct_base_url: Any = None,
    direct_base_url_unauthorized: Any = None,
) -> None:
    """*nucore_interface*, when given, is the shared NuCoreInterface instance
    (see start_eisyai.py) this proxy's real HubBearerAuthHook validates
    bearer tokens against, and whose presence also mounts the OAuth 2.1
    wrapper (oauth.py). *direct_base_url* is a zero-argument callable
    returning the hub's real, non-relayed address (or None if not yet
    resolved) -- see isy_direct_address.DirectHubAddressResolver.get;
    required alongside *nucore_interface* for the OAuth wrapper's
    login/refresh/revoke handlers to reach the hub's /api/login/jwt/*
    endpoints. *direct_base_url_unauthorized* (DirectHubAddressResolver.
    is_unauthorized) lets the OAuth wrapper tell "hub address not resolved
    yet" apart from "this node server's config will never let it resolve"
    -- optional, defaults to always-False (ambiguous "not yet known")
    inside build_oauth_routes if omitted. Without both nucore_interface and
    direct_base_url, the OAuth wrapper is not mounted at all and
    *auth_hook* falls back to AllowAllAuthHook -- a bare local/dev
    invocation with nothing real to authenticate against."""
    if args is None:
        args = _build_proxy_parser().parse_args()

    configure_logging(level=args.log_level, log_file=args.log_file, force=True)

    if not args.unix_socket_path:
        raise ValueError("--unix-socket-path is required")
    if not args.ssl_certfile or not args.ssl_keyfile:
        raise ValueError("--ssl-certfile and --ssl-keyfile are both required")

    if auth_hook is None:
        auth_hook = HubBearerAuthHook(nucore_interface) if nucore_interface is not None else AllowAllAuthHook()
    logger.warning(
        "mcp_proxy starting with auth_hook=%s -- if this is AllowAllAuthHook, "
        "every tool on nucore-ai's MCP server (including run_shell_command and "
        "call_plugin) is reachable by anyone who can reach %s:%s with no "
        "credential at all. This must only run on a controlled test box.",
        type(auth_hook).__name__,
        args.host,
        args.port,
    )

    issuer = args.public_base_url
    proxy_app = build_proxy_app(unix_socket_path=args.unix_socket_path, auth_hook=auth_hook, issuer=issuer)

    app: Any = proxy_app
    if nucore_interface is not None and issuer and direct_base_url is not None:
        if not args.oauth_client_store_path:
            raise ValueError("--oauth-client-store-path is required when nucore_interface is given")
        oauth_kwargs: dict[str, Any] = {}
        if direct_base_url_unauthorized is not None:
            oauth_kwargs["is_unauthorized"] = direct_base_url_unauthorized
        oauth_routes = build_oauth_routes(
            issuer=issuer,
            nucore_interface=nucore_interface,
            client_store_path=args.oauth_client_store_path,
            direct_base_url=direct_base_url,
            **oauth_kwargs,
        )
        app = Starlette(routes=[*oauth_routes, Mount("/", app=proxy_app)])
    elif nucore_interface is not None:
        logger.warning(
            "mcp_proxy: nucore_interface was given but --public-base-url or direct_base_url "
            "was not -- the OAuth 2.1 wrapper is NOT mounted; only HubBearerAuthHook's bearer "
            "check runs, with no way for a client to ever obtain a token from this process."
        )

    # sys.stdout may have been replaced by something with no isatty() (e.g.
    # udi_interface's LoggerWriter -- this proxy always runs embedded in
    # eisy-ai's own polyglot process) -- uvicorn's own logging setup calls
    # sys.stdout.isatty() unconditionally unless use_colors is explicitly
    # True/False.
    use_colors = sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
        log_level=(args.log_level or "info").lower(),
        use_colors=use_colors,
    )


if __name__ == "__main__":
    main()
