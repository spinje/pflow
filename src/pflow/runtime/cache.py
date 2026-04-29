"""Persistent memoization cache for workflow node execution.

Stores node outputs keyed by a hash of their configuration and resolved inputs.
Uses SQLite for persistent, concurrent-safe storage with TTL-based eviction.
"""

import hashlib
import json
import logging
import sqlite3
import time
import zlib
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default TTL: 24 hours
DEFAULT_TTL_SECONDS = 86400.0

# Eviction frequency: run eviction every N puts
_EVICTION_INTERVAL = 50


def _make_serializable(obj: Any) -> Any:
    """Convert an object to a JSON-serializable representation for hashing.

    Handles common non-serializable objects by converting them to
    deterministic string representations.

    Args:
        obj: Object to make serializable

    Returns:
        JSON-serializable version of the object
    """
    # Task 159 B3.3: defense against a leaked _CHUNK_ABSENT sentinel. The
    # catch-all branch at the bottom would silently serialize the sentinel to
    # a stable type-name string and fold it into the cache hash — the
    # silent-stale-cache regression class. Lazy-import keeps cache.py
    # dependency-free at module load.
    from pflow.core.cache_render import _ChunkAbsentSentinel

    if isinstance(obj, _ChunkAbsentSentinel):
        raise TypeError(
            "_CHUNK_ABSENT must be filtered before serialization; reached "
            "_make_serializable. Caller forgot to drop ABSENT chunks before "
            "passing prompt_cache_content into compute_node_config (DD#19)."
        )
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if isinstance(key, str) and key.startswith("__") and key.endswith("__"):
                # Internal keys: use type name for deterministic hash
                result[key] = f"<{type(value).__name__}>" if value is not None else "<None>"
            else:
                result[key] = _make_serializable(value)
        return result
    elif isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    elif isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    else:
        return f"<{type(obj).__module__}.{type(obj).__name__}>"


def _deterministic_json(obj: Any) -> str:
    """Serialize an object to a deterministic JSON string for hashing.

    Args:
        obj: Object to serialize (must be JSON-serializable after _make_serializable)

    Returns:
        JSON string with sorted keys
    """
    return json.dumps(_make_serializable(obj), sort_keys=True)


def compute_node_cache_key(
    config_hash: str,
    resolved_inputs: Optional[dict[str, Any]] = None,
) -> str:
    """Compute memoization cache key for a non-batch node.

    cache_key = md5(config_hash + hash(filtered_resolved_inputs))

    Args:
        config_hash: Hash of the node's static configuration
        resolved_inputs: Resolved template parameters (merged_params from resolve_templates)

    Returns:
        MD5 hex digest cache key

    GH #357: ``_*_source_line`` keys are filtered from the cache key just
    like ``compute_node_config`` filters them from the config hash. They
    are cosmetic line-number metadata (used by python_code.py at runtime
    for error reporting) that shift on every workflow edit AND on every
    invocation of a saved-library workflow (since the library mutates the
    file's frontmatter post-run, growing the prefix and shifting body
    line numbers). Without this filter, the cache_key changed on every
    saved-workflow run and memo cache never hit.
    """
    parts = [config_hash]
    if resolved_inputs is not None:
        filtered = {k: v for k, v in resolved_inputs.items() if not k.endswith("_source_line")}
        parts.append(_deterministic_json(filtered))
    combined = "|".join(parts)
    return hashlib.md5(combined.encode()).hexdigest()  # noqa: S324


def compute_batch_cache_key(
    config_hash: str,
    semantic_batch_config: dict[str, Any],
    resolved_items: list[Any],
) -> str:
    """Compute memoization cache key for a batch node.

    cache_key = md5(config_hash + hash(batch_config) + hash(resolved_items))

    Args:
        config_hash: Hash of the inner node's configuration
        semantic_batch_config: Batch config that affects results (items_template, item_alias, etc.)
        resolved_items: Resolved items list from shared store

    Returns:
        MD5 hex digest cache key
    """
    parts = [
        config_hash,
        _deterministic_json(semantic_batch_config),
        _deterministic_json(resolved_items),
    ]
    combined = "|".join(parts)
    return hashlib.md5(combined.encode()).hexdigest()  # noqa: S324


class MemoizationCache:
    """Persistent memoization cache backed by SQLite.

    Stores node execution results keyed by a hash of configuration + inputs.
    Uses WAL journal mode for concurrent read/write safety.

    Args:
        db_path: Path to SQLite database file. Defaults to ~/.pflow/cache/cache.db
        ttl_seconds: Time-to-live for cache entries in seconds (default: 24 hours)
        read_enabled: Whether cache reads are enabled (False for --no-cache mode)
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        read_enabled: bool = True,
    ):
        if db_path is None:
            db_path = Path.home() / ".pflow" / "cache" / "cache.db"
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self.read_enabled = read_enabled
        self._put_count = 0

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database schema."""
        try:
            conn = self._connect()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        cache_key TEXT PRIMARY KEY,
                        node_id TEXT NOT NULL,
                        workflow_path TEXT,
                        action TEXT NOT NULL,
                        output BLOB NOT NULL,
                        output_hash TEXT NOT NULL,        -- reserved for future trace unification (Task 133)
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_created_at ON cache_entries(created_at);
                    CREATE INDEX IF NOT EXISTS idx_workflow_path ON cache_entries(workflow_path);
                    CREATE INDEX IF NOT EXISTS idx_node_id_created_at ON cache_entries(node_id, created_at DESC);
                """)
            finally:
                conn.close()
        except sqlite3.Error:
            logger.warning(
                "Memoization cache unavailable — all nodes will execute fresh. Check permissions on ~/.pflow/cache/",
                exc_info=True,
            )

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection with WAL mode.

        Returns:
            SQLite connection
        """
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get(self, cache_key: str) -> Optional[tuple[str, dict[str, Any]]]:
        """Look up cache entry.

        Args:
            cache_key: The cache key to look up

        Returns:
            Tuple of (action, output) or None if not found or reads disabled
        """
        if not self.read_enabled:
            return None

        try:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "SELECT action, output, created_at FROM cache_entries WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                action, output_blob, created_at = row

                # Check TTL
                if time.time() - created_at > self.ttl_seconds:
                    # Expired — delete and return miss
                    conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
                    conn.commit()
                    return None

                # Decompress and deserialize output
                output_json = zlib.decompress(output_blob).decode()
                output = json.loads(output_json)
                return (action, output)
            finally:
                conn.close()
        except (sqlite3.Error, zlib.error, json.JSONDecodeError, OSError):
            logger.debug("Memoization cache read failed", exc_info=True)
            return None

    def get_with_age(self, cache_key: str) -> Optional[tuple[str, dict[str, Any], float]]:
        """Look up cache entry with its creation time.

        Args:
            cache_key: The cache key to look up

        Returns:
            Tuple of (action, output, created_at_epoch_seconds) or None if not
            found, expired, or reads disabled
        """
        if not self.read_enabled:
            return None

        try:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "SELECT action, output, created_at FROM cache_entries WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                action, output_blob, created_at = row

                if time.time() - created_at > self.ttl_seconds:
                    conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
                    conn.commit()
                    return None

                output_json = zlib.decompress(output_blob).decode()
                output = json.loads(output_json)
                return (action, output, created_at)
            finally:
                conn.close()
        except (sqlite3.Error, zlib.error, json.JSONDecodeError, OSError):
            logger.debug("Memoization cache get_with_age failed", exc_info=True)
            return None

    def get_latest_for_node(
        self, node_id: str, *, workflow_path: Optional[str] = None
    ) -> Optional[tuple[dict[str, Any], float]]:
        """Look up the newest cache entry for a node_id.

        Args:
            node_id: Node identifier to search for.
            workflow_path: When provided, scope the lookup to entries written
                by this workflow. Prevents cross-workflow pollution for common
                node names (e.g., two workflows both with a "classify" node).
                When None, falls back to unscoped lookup — required for
                direct-IR / content-string runs where `_pflow_workflow_file`
                is never set and rows are written with a NULL `workflow_path`
                column (SQL `= NULL` matches zero rows).

        Returns:
            Tuple of (output, created_at_epoch_seconds) or None if not found,
            expired, or reads disabled.
        """
        if not self.read_enabled:
            return None

        try:
            conn = self._connect()
            try:
                if workflow_path is not None:
                    cursor = conn.execute(
                        "SELECT cache_key, output, created_at FROM cache_entries "
                        "WHERE node_id = ? AND workflow_path = ? "
                        "ORDER BY created_at DESC LIMIT 1",
                        (node_id, workflow_path),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT cache_key, output, created_at FROM cache_entries "
                        "WHERE node_id = ? ORDER BY created_at DESC LIMIT 1",
                        (node_id,),
                    )
                row = cursor.fetchone()
                if row is None:
                    return None

                cache_key, output_blob, created_at = row

                if time.time() - created_at > self.ttl_seconds:
                    conn.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
                    conn.commit()
                    return None

                output_json = zlib.decompress(output_blob).decode()
                output = json.loads(output_json)
                return (output, created_at)
            finally:
                conn.close()
        except (sqlite3.Error, zlib.error, json.JSONDecodeError, OSError):
            logger.debug("Memoization cache get_latest_for_node failed", exc_info=True)
            return None

    def put(
        self,
        cache_key: str,
        node_id: str,
        workflow_path: Optional[str],
        action: str,
        output: dict[str, Any],
    ) -> None:
        """Store cache entry. Overwrites existing entry with same key.

        Args:
            cache_key: The cache key
            node_id: Node identifier (for debugging/inspection)
            workflow_path: Which workflow this belongs to
            action: Action string returned by node
            output: Node output dictionary
        """
        try:
            # Serialize and compress output (use default=str for non-JSON types,
            # NOT _make_serializable which mangles __dunder__ key values)
            output_json = json.dumps(output, default=str)
            output_blob = zlib.compress(output_json.encode())
            output_hash = hashlib.md5(output_json.encode()).hexdigest()  # noqa: S324

            conn = self._connect()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO cache_entries
                       (cache_key, node_id, workflow_path, action, output, output_hash, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (cache_key, node_id, workflow_path, action, output_blob, output_hash, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

            self._put_count += 1
            # Periodic eviction
            if self._put_count % _EVICTION_INTERVAL == 0:
                self.evict_expired()

        except (sqlite3.Error, OSError):
            logger.debug("Memoization cache write failed", exc_info=True)

    def evict_expired(self, ttl_seconds: Optional[float] = None) -> int:
        """Remove entries older than TTL.

        Args:
            ttl_seconds: Override TTL for eviction. Uses instance default if None.

        Returns:
            Count of removed entries
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        cutoff = time.time() - ttl

        try:
            conn = self._connect()
            try:
                cursor = conn.execute("DELETE FROM cache_entries WHERE created_at < ?", (cutoff,))
                conn.commit()
                count = cursor.rowcount
                if count > 0:
                    logger.debug(f"Evicted {count} expired cache entries")
                return count
            finally:
                conn.close()
        except sqlite3.Error:
            logger.debug("Memoization cache eviction failed", exc_info=True)
            return 0

    def clear(self, workflow_path: Optional[str] = None) -> int:
        """Clear all entries, or entries for a specific workflow.

        Args:
            workflow_path: If provided, only clear entries for this workflow

        Returns:
            Count of removed entries
        """
        try:
            conn = self._connect()
            try:
                if workflow_path:
                    cursor = conn.execute("DELETE FROM cache_entries WHERE workflow_path = ?", (workflow_path,))
                else:
                    cursor = conn.execute("DELETE FROM cache_entries")
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()
        except sqlite3.Error:
            logger.debug("Memoization cache clear failed", exc_info=True)
            return 0
