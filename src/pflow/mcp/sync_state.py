"""Persisted state helpers for MCP server synchronization."""

import hashlib
import json
from typing import Any

MCP_SERVER_FINGERPRINTS_KEY = "mcp_server_fingerprints"


def fingerprint_server_config(config: dict[str, Any]) -> str:
    """Return a stable fingerprint of one raw persisted server config."""
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def fingerprint_server_configs(configs: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Fingerprint each raw server config without resolving environment references."""
    return {name: fingerprint_server_config(config) for name, config in configs.items()}


def parse_server_fingerprints(value: Any) -> tuple[dict[str, Any], bool]:
    """Return a defensive fingerprint-map copy and whether persisted state was valid."""
    if not isinstance(value, dict):
        return {}, False
    return dict(value), True
