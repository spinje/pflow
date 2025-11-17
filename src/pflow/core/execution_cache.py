"""Execution cache for structure-only mode.

Stores node execution results to enable two-phase retrieval:
1. Execute node → return structure-only + execution_id
2. Read specific fields → retrieve values from cache

Cache location: ~/.pflow/cache/registry-run/{execution_id}.json
TTL: 24 hours (stored but not enforced in MVP)
"""

import base64
import json
import secrets
import time
from pathlib import Path
from typing import Any, Optional


class ExecutionCache:
    """Manage cached node execution results for structure-only mode.

    This cache enables efficient token usage by allowing AI agents to:
    1. See data structure without actual values (structure-only mode)
    2. Selectively retrieve specific field values when needed

    Cache entries are stored as JSON files with 24-hour TTL metadata
    (automatic cleanup deferred to post-MVP).
    """

    def __init__(self) -> None:
        """Initialize cache with default directory."""
        self.cache_dir = Path.home() / ".pflow" / "cache" / "registry-run"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_execution_id() -> str:
        """Generate unique execution ID.

        Format: exec-{timestamp}-{random_hex}
        Example: exec-1705234567-a1b2c3d4

        Returns:
            Unique execution ID (24 characters)
        """
        timestamp = int(time.time())
        random_hex = secrets.token_hex(4)  # 8 hex characters
        return f"exec-{timestamp}-{random_hex}"

    def store(
        self,
        execution_id: str,
        node_type: str,
        params: dict[str, Any],
        outputs: dict[str, Any],
    ) -> None:
        """Store execution results in cache.

        Args:
            execution_id: Unique identifier for this execution
            node_type: Node type identifier (e.g., "mcp-github-list-issues")
            params: Parameters used for node execution
            outputs: Node execution outputs (will be encoded if binary)

        Raises:
            OSError: If cache file cannot be written
        """
        # Handle binary data encoding
        encoded_outputs = self._encode_binary(outputs)

        cache_data = {
            "execution_id": execution_id,
            "node_type": node_type,
            "timestamp": time.time(),
            "ttl_hours": 24,  # Stored but not enforced in MVP
            "params": params,
            "outputs": encoded_outputs,
        }

        filepath = self.cache_dir / f"{execution_id}.json"

        # Write cache file with UTF-8 encoding
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, indent=2, default=str)

    def retrieve(self, execution_id: str) -> Optional[dict[str, Any]]:
        """Retrieve cached execution results.

        Args:
            execution_id: Execution ID from previous registry run

        Returns:
            Cache data dict with decoded binary data, or None if not found

        Note:
            TTL checking is not enforced in MVP - all cache entries
            are returned regardless of age.
        """
        filepath = self.cache_dir / f"{execution_id}.json"

        if not filepath.exists():
            return None

        with open(filepath, encoding="utf-8") as f:
            cache_data = json.load(f)

        # Decode binary data
        cache_data["outputs"] = self._decode_binary(cache_data["outputs"])

        # Type assertion for mypy (_decode_binary returns Any but we know structure is preserved)
        return cache_data  # type: ignore[no-any-return]

    def list_cached_executions(self) -> list[dict[str, Any]]:
        """List all cached executions with metadata.

        Returns:
            List of dicts with execution_id, node_type, timestamp

        Note:
            This reads only the metadata, not full outputs.
        """
        executions = []

        for filepath in self.cache_dir.glob("exec-*.json"):
            try:
                with open(filepath, encoding="utf-8") as f:
                    cache_data = json.load(f)

                executions.append({
                    "execution_id": cache_data["execution_id"],
                    "node_type": cache_data["node_type"],
                    "timestamp": cache_data["timestamp"],
                })
            except (json.JSONDecodeError, KeyError):
                # Skip malformed cache files
                continue

        # Sort by timestamp (newest first)
        executions.sort(key=lambda x: x["timestamp"], reverse=True)

        return executions

    def _encode_binary(self, data: Any) -> Any:
        """Recursively encode binary data to base64.

        Args:
            data: Any data structure (may contain bytes)

        Returns:
            Data with bytes encoded as {"__type": "base64", "data": "..."}

        Note:
            Follows existing pflow pattern for binary data handling.
        """
        if isinstance(data, bytes):
            return {"__type": "base64", "data": base64.b64encode(data).decode("ascii")}
        elif isinstance(data, dict):
            return {k: self._encode_binary(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._encode_binary(item) for item in data]
        return data

    def _decode_binary(self, data: Any) -> Any:
        """Recursively decode base64 data to bytes.

        Args:
            data: Data structure with base64-encoded binary

        Returns:
            Data with base64 strings decoded to bytes

        Note:
            Recognizes {"__type": "base64", "data": "..."} pattern.
        """
        if isinstance(data, dict):
            if data.get("__type") == "base64":
                return base64.b64decode(data["data"])
            return {k: self._decode_binary(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._decode_binary(item) for item in data]
        return data
