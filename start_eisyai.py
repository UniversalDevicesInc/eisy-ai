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


def start_eisyai(provider: str, model: str | None, api_key: str, polyglot) -> str:
    """Configure and start the Eisy AI runtime, returning the selected model."""
    if not provider:
        raise ValueError("Provider is not set")
    if not api_key:
        raise ValueError("API Key is not set")
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")

    provider_settings = get_provider_map(provider)
    if not provider_settings:
        raise ValueError("Provider not found in provider map")

    model = model or provider_settings.get("model")
    if not model:
        raise ValueError("Model is not set and no provider default is available")

    api_key_name = provider_settings.get("api_key_name")
    if not api_key_name:
        raise ValueError("API Key name not found in provider map")
    os.environ[api_key_name] = api_key

    home_directory = Path(__file__).resolve().parent
    preferences_dir = home_directory / "data" / "prefs"
    preferences_dir.mkdir(parents=True, exist_ok=True)
    (home_directory / "logs").mkdir(parents=True, exist_ok=True)

    runtime_config_path = home_directory / f"runtime_config.{provider}.json"
    if not runtime_config_path.exists():
        raise FileNotFoundError(
            f"Runtime config not found for the provider: {provider}"
        )

    ssl_certfile, ssl_keyfile = _ensure_ssl_files(home_directory / "data" / "ssl")

    from unified.run_unified_runtime import _build_parser
    from unified.run_unified_runtime import main as eisyai_main

    args = _build_parser().parse_args([])
    args.backend_api_classpath = "iox.IoXWrapper"
    args.runtime_config = str(runtime_config_path)
    args.preferences_dir = str(preferences_dir)
    args.websocket_port = 8000
    args.ssl_certfile = str(ssl_certfile)
    args.ssl_keyfile = str(ssl_keyfile)
    args.log_level = "INFO"
    args.stream = True
    args.backend_api_base_url = "unix:///tmp/eisyui-listener"
    args.backend_api_username = "eisyai"
    args.backend_api_password = "rules"  

    threading.Thread(target=eisyai_main, args=(args, None)).start()
    return model