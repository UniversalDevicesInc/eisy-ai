"""Load provider-specific runtime settings from provider_map.json."""

import json
from pathlib import Path


def get_provider_map(provider: str):
    """Return settings for provider, or None when it is not configured."""
    if not provider:
        return None

    provider_map_path = Path(__file__).with_name("provider_map.json")
    with provider_map_path.open("r", encoding="utf-8") as provider_map_file:
        provider_map = json.load(provider_map_file)
    return provider_map.get(provider)