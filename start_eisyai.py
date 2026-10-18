"""Start the Eisy AI unified runtime outside the IoX controller lifecycle."""

import datetime
import os
import threading
from pathlib import Path

from provider_map import get_provider_map


SUPPORTED_PROVIDERS = {"anthropic", "openai", "grok"}


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


def start_eisyai(runtime_config: dict, polyglot) -> str:
    """Configure and start the Eisy AI runtime, returning the selected model."""



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
    plugin_root_directory = data_dir / "generated_plugins"
    plugin_root_directory.mkdir(parents=True, exist_ok=True)

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

    threading.Thread(target=eisyai_main, args=(args, None)).start()