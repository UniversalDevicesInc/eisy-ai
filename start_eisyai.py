"""Start the Eisy AI unified runtime outside the IoX controller lifecycle."""

import datetime
import os
import threading
from pathlib import Path

from provider_map import get_provider_map
from unified.provider_clients import build_provider_clients_from_runtime_config


SUPPORTED_PROVIDERS = {"anthropic", "openai", "grok"}


def _resolve_startup_notice(runtime_config: dict, env: dict[str, str]) -> str | None:
    """Returns a human-readable notice if eisy-ai can't fully start as
    configured, or None if nothing's wrong. Reuses the exact same client-
    building logic build_default_dispatch_adapter uses deeper inside
    run_unified_runtime.main() (which raises ValueError when this comes
    back empty) -- checked here, upfront, so a missing API key becomes a
    clear eisy-ai notice instead of the chat thread dying silently with an
    uncaught exception. mcp_server's own threads never need an LLM key at
    all (confirmed directly: run_mcp_server.py never builds one), so a
    missing key never affects MCP -- only which notice (if any) is shown.
    """
    has_llm_key = bool(build_provider_clients_from_runtime_config(runtime_config, env=env))
    if has_llm_key:
        return None
    if runtime_config.get("mcp_server") is True:
        return (
            "No LLM provider API key is configured, so eisy-ai is running in MCP-only mode: "
            "web chat is not available until a key is set (see README.md's Configuration "
            "section). MCP tool access does not need one and is still active."
        )
    return (
        "No LLM provider API key is configured -- eisy-ai cannot start web chat or plugin "
        "authoring until one is set. See the Configuration section of README.md."
    )


def _ensure_ssl_files(ssl_dir: Path) -> tuple[Path, Path]:
    ssl_dir.mkdir(parents=True, exist_ok=True)
    ssl_certfile = ssl_dir / "cert.pem"
    ssl_keyfile = ssl_dir / "key.pem"
    if ssl_certfile.exists() and ssl_keyfile.exists():
        return ssl_certfile, ssl_keyfile

    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    with ssl_keyfile.open("wb") as key_file:
        key_file.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "California"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "Los Angeles"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Universal Devices"),
            x509.NameAttribute(NameOID.COMMON_NAME, "eisy.local"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256(), default_backend())
    )
    with ssl_certfile.open("wb") as cert_file:
        cert_file.write(certificate.public_bytes(serialization.Encoding.PEM))
    return ssl_certfile, ssl_keyfile


def start_eisyai(runtime_config: dict, polyglot) -> str | None:
    """Configure and start the Eisy AI runtime. Returns a human-readable
    notice if something about the current config means a thread below was
    deliberately not started (see _resolve_startup_notice) -- the caller
    (EisyaiControllerNode.start()) is expected to surface this via
    self.setNotices, and to clear any prior notice when this returns None."""



#    provider_settings = get_provider_map(provider)
#    if not provider_settings:
#        raise ValueError("Provider not found in provider map")
#

#    api_key_name = provider_settings.get("api_key_name")
#    if not api_key_name:
#        raise ValueError("API Key name not found in provider map")
#    os.environ[api_key_name] = api_key

    home_directory = Path(__file__).resolve().parent
    data_dir = home_directory / "persist" 
    data_dir.mkdir(parents=True, exist_ok=True)
    preferences_dir = data_dir / "prefs"
    preferences_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = home_directory / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "eisyai.log"
    prompts_file = logs_dir / "nucore.prompt.jsonl"
    plugin_root_directory = Path("/tmp/eisy-ai/generated_plugins")
    plugin_root_directory.mkdir(parents=True, exist_ok=True)
    #change group permission recursively for the plugin root directory

    from unified.run_unified_runtime import _build_parser
    from unified.run_unified_runtime import main as eisyai_main

    args = _build_parser().parse_args([])
    args.backend_api_classpath = "iox.IoXWrapper"
    args.runtime_config = runtime_config
    args.preferences_dir = str(preferences_dir)
#### Use these for TCP/WebSocket connections instead of Unix socket
#    ssl_certfile, ssl_keyfile = _ensure_ssl_files(home_directory / "data" / "ssl")
#    args.websocket_port = 8000
#    args.websocket_host = "0.0.0.0"
#    args.ssl_certfile = str(ssl_certfile)
#    args.ssl_keyfile = str(ssl_keyfile)
#### End of TCP/WebSocket configuration
#### Use these for Unix socket connections instead of TCP/WebSocket
    args.websocket_host = "unix:///tmp/ai-listener"
    args.websocket_client_id = 348 
#### End of Unix socket configuration
    args.log_level = "INFO"
    args.log_file = str(log_file)
    args.prompt_log_file = str(prompts_file)
    args.plugin_output_root = str(plugin_root_directory)
    
    args.stream = True

    args.backend_api_base_url = "unix:///tmp/eisyui-listener"
    args.backend_api_username = "eisyai"
    args.backend_api_password = "rules"

    notice = _resolve_startup_notice(runtime_config, dict(os.environ))
    # Only spawn the chat thread when it actually has what it needs --
    # otherwise build_default_dispatch_adapter raises ValueError the
    # moment that thread starts, uncaught, with no clearer signal than
    # whatever shows up in the logs. Skipping it here is strictly more
    # graceful than attempting and immediately failing.
    if notice is None:
        threading.Thread(target=eisyai_main, args=(args, None)).start()

    # MCP (Model Context Protocol) access to nucore-ai's tools -- see
    # design/mcp-server.md (nucore-ai repo). One flag gates both halves:
    # nucore-ai's MCP server (a Unix socket only, no app-level auth, same
    # trust model as the websocket thread above) and this repo's own
    # network-facing proxy (TCP + TLS). Phase 2: the proxy requires a real
    # hub login via OAuth 2.1 (mcp_proxy/auth.py's HubBearerAuthHook,
    # mcp_proxy/oauth.py) -- AllowAllAuthHook is no longer reachable from
    # this wiring. Default off: absent or anything other than exactly
    # `true` leaves all three threads unstarted.
    if runtime_config.get("mcp_server") is True:
        from unified.provider_clients import resolve_env_placeholder
        from unified.run_mcp_server import _build_mcp_parser as _build_nucore_mcp_parser
        from unified.run_mcp_server import main as nucore_mcp_main
        from unified.run_unified_runtime import _BACKEND_API_JSON_OUTPUT, _load_backend_api
        from mcp_proxy.isy_direct_address import DirectHubAddressResolver
        from mcp_proxy.run_proxy import _build_proxy_parser, main as mcp_proxy_main

        mcp_unix_socket_path = "/tmp/mcp-listener"
        ssl_certfile, ssl_keyfile = _ensure_ssl_files(data_dir / "ssl")

        # Same resolution run_unified_runtime.main() applies to runtime_config's
        # own 'search_engine'/'search_engine_api_key' keys -- duplicated here
        # deliberately since run_mcp_server's CLI takes pre-resolved strings,
        # not a runtime_config dict.
        search_engine = runtime_config.get("search_engine")
        search_engine_api_key = resolve_env_placeholder(runtime_config.get("search_engine_api_key"), dict(os.environ))

        # The proxy's real externally-reachable address -- "0.0.0.0" below is
        # a *bind* address, not something a client can ever connect to.
        # "eisy.local" is the one stable, known hostname for this device (it's
        # also the TLS cert's own CN, see _ensure_ssl_files above). nucore-ai's
        # MCP server only ever binds a Unix socket and has no way to know this
        # itself (see build_mcp_protocol_server's public_base_url docstring,
        # nucore-ai repo) -- without it, get_system_prompt's plain-HTTP
        # retrieval instructions could only give a relative path, which a
        # real client has no way to resolve (confirmed directly: one guessed
        # the hub's own web UI/REST ports instead and got nowhere).
        mcp_proxy_port = 8260
        mcp_proxy_public_base_url = f"https://eisy.local:{mcp_proxy_port}"

        nucore_mcp_args = _build_nucore_mcp_parser().parse_args([])
        nucore_mcp_args.unix_socket_path = mcp_unix_socket_path
        nucore_mcp_args.plugin_output_root = str(plugin_root_directory)
        nucore_mcp_args.search_engine = search_engine
        nucore_mcp_args.search_engine_api_key = search_engine_api_key
        nucore_mcp_args.preferences_dir = str(preferences_dir)
        nucore_mcp_args.log_level = args.log_level
        nucore_mcp_args.log_file = args.log_file
        nucore_mcp_args.public_base_url = mcp_proxy_public_base_url
        # Byte-identical to args.* above so run_unified_runtime's
        # _load_backend_api_cached lru_cache hits the SAME NuCoreInterface
        # instance for both threads -- no second Unix-socket connection to IoX.
        nucore_mcp_args.backend_api_classpath = args.backend_api_classpath
        nucore_mcp_args.backend_api_base_url = args.backend_api_base_url
        nucore_mcp_args.backend_api_username = args.backend_api_username
        nucore_mcp_args.backend_api_password = args.backend_api_password

        threading.Thread(target=nucore_mcp_main, args=(nucore_mcp_args, None)).start()

        # Phase 2 (design/mcp-server.md, nucore-ai repo): the proxy's real
        # HubBearerAuthHook and OAuth 2.1 wrapper both need a real
        # NuCoreInterface to authenticate against -- the exact same
        # singleton the two threads above already share (byte-identical
        # backend_api_* args hit the same _load_backend_api_cached entry,
        # confirmed directly against run_unified_runtime.py; calling it a
        # third time here, in this thread, synchronously, before any of
        # the three threads spawn, is safe regardless of which one
        # populates the cache first -- lru_cache is thread-safe).
        nucore_interface = _load_backend_api(
            classpath=args.backend_api_classpath,
            base_url=args.backend_api_base_url,
            username=args.backend_api_username,
            password=args.backend_api_password,
            json_output=_BACKEND_API_JSON_OUTPUT,
            poly=None,
        )
        # /api/login and /api/jwt/* are "local access only" (design/iox_apis/
        # authentication.md, nucore-ai repo) -- silently ignored over the
        # same PG3-relay Unix socket (backend_api_base_url above) nucore_interface
        # otherwise uses for every other REST call. This resolves the hub's
        # real, non-relayed address independently, via the same
        # subscribe(poly.ISY, ...)/send(getIsyInfo) pattern IoXWrapper's own
        # poly-mode branch and udi_interface's own ISY class both already use.
        direct_hub_address = DirectHubAddressResolver(polyglot)

        proxy_args = _build_proxy_parser().parse_args([])
        proxy_args.host = "0.0.0.0"
        proxy_args.port = mcp_proxy_port
        proxy_args.unix_socket_path = mcp_unix_socket_path
        proxy_args.ssl_certfile = str(ssl_certfile)
        proxy_args.ssl_keyfile = str(ssl_keyfile)
        proxy_args.public_base_url = mcp_proxy_public_base_url
        proxy_args.oauth_client_store_path = str(data_dir / "mcp_oauth_clients.json")
        proxy_args.log_level = args.log_level
        proxy_args.log_file = args.log_file

        threading.Thread(
            target=mcp_proxy_main,
            args=(proxy_args,),
            kwargs={
                "nucore_interface": nucore_interface,
                "direct_base_url": direct_hub_address.get,
                "direct_base_url_unauthorized": direct_hub_address.is_unauthorized,
            },
        ).start()

    return notice