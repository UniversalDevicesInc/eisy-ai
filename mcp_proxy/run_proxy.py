"""CLI/embeddable entry point for the network-facing MCP proxy.

Binds a TLS TCP listener on the LAN and relays authenticated traffic to
nucore-ai's MCP server over a Unix domain socket (see proxy.py). Phase 1
runs with ``AllowAllAuthHook`` -- see auth.py's docstring for why, and the
loud startup log line below for why that fact is never silent.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import uvicorn

from utils import configure_logging, get_logger

from .auth import AllowAllAuthHook, AuthHook
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
    parser.add_argument("--log-level", type=str, default=None, help="Logger level override")
    parser.add_argument("--log-file", type=str, default=None, help="Optional log file path")
    return parser


def main(args: Any = None, auth_hook: AuthHook | None = None) -> None:
    if args is None:
        args = _build_proxy_parser().parse_args()

    configure_logging(level=args.log_level, log_file=args.log_file, force=True)

    if not args.unix_socket_path:
        raise ValueError("--unix-socket-path is required")
    if not args.ssl_certfile or not args.ssl_keyfile:
        raise ValueError("--ssl-certfile and --ssl-keyfile are both required")

    if auth_hook is None:
        auth_hook = AllowAllAuthHook()
    logger.warning(
        "mcp_proxy starting with auth_hook=%s -- if this is AllowAllAuthHook, "
        "every tool on nucore-ai's MCP server (including run_shell_command and "
        "call_plugin) is reachable by anyone who can reach %s:%s with no "
        "credential at all. This must only run on a controlled test box.",
        type(auth_hook).__name__,
        args.host,
        args.port,
    )

    app = build_proxy_app(unix_socket_path=args.unix_socket_path, auth_hook=auth_hook)
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
