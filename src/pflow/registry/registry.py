"""Registry for managing discovered pflow nodes."""

import contextlib
import json
import logging
import os
import tempfile
from collections.abc import Collection
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Set up logging
logger = logging.getLogger(__name__)


class Registry:
    """Manages persistent storage of discovered node metadata."""

    def __init__(self, registry_path: Optional[Path] = None):
        """Initialize Registry with optional custom path.

        Args:
            registry_path: Path to registry JSON file. Defaults to ~/.pflow/registry.json
        """
        if registry_path is None:
            self.registry_path = Path.home() / ".pflow" / "registry.json"
        else:
            self.registry_path = Path(registry_path)

        # Add caching
        self._cached_nodes: Optional[dict[str, dict[str, Any]]] = None
        self._registry_version: Optional[str] = None
        self._registry_last_scan: Optional[str] = None

        # Lazy load settings manager to avoid circular import
        self._settings_manager: Optional[Any] = None

    def __deepcopy__(self, memo: dict[int, Any]) -> "Registry":
        """Return self on deep copy — Registry is a shared, read-only resource.

        The Registry (and its SettingsManager with threading.RLock) cannot be
        deep-copied. Parallel batch execution deep-copies the node chain, and
        Registry is injected as a param. All threads should share the same
        Registry instance since it's read-only during workflow execution.
        """
        memo[id(self)] = self
        return self

    @property
    def settings_manager(self) -> Any:
        """Lazy load SettingsManager to avoid circular imports."""
        if self._settings_manager is None:
            from pflow.core.settings import SettingsManager

            self._settings_manager = SettingsManager()
        return self._settings_manager

    @staticmethod
    def _get_version() -> str:
        """Get current pflow version from package metadata."""
        from pflow import get_version

        return get_version()

    @staticmethod
    def _now_iso() -> str:
        """Current time as UTC ISO string — portable, comparable via .timestamp()."""
        return datetime.now(timezone.utc).isoformat()

    def _read_wrapper(self) -> dict[str, Any]:
        """Read the raw registry file and return the full structured wrapper dict.

        Returns the top-level dict if it's in structured format (has "nodes" key),
        or empty dict if missing, flat format, or corrupt.
        """
        if not self.registry_path.exists():
            return {}
        try:
            content = self.registry_path.read_text()
            if not content.strip():
                return {}
            data = json.loads(content)
            if isinstance(data, dict) and "nodes" in data:
                return data
            return {}
        except Exception as e:
            logger.debug(f"Could not read registry wrapper: {e}")
            return {}

    def load(self, include_filtered: bool = False) -> dict[str, dict[str, Any]]:
        """Load registry from JSON file, auto-discovering core nodes if needed.

        Returns empty dict if file doesn't exist or is corrupt.
        Logs warnings for errors but doesn't raise exceptions.

        Args:
            include_filtered: If True, return ALL nodes including filtered ones.
                            If False (default), return only nodes allowed by settings.

        Returns:
            Dictionary mapping node names to metadata
        """
        # Check if registry exists
        if not self.registry_path.exists():
            logger.info("Registry not found, auto-discovering core nodes...")
            # First time - auto-discover core nodes
            self._auto_discover_core_nodes()

        # Try to load from file
        nodes = self._load_from_file()

        # Check if core nodes need refresh (version change)
        if self._core_nodes_outdated(nodes):
            nodes = self._refresh_core_nodes(nodes)

        # Cache the nodes (always cache the full set)
        self._cached_nodes = nodes

        # Apply filtering if requested (default behavior)
        if not include_filtered:
            filtered_nodes = {}
            for node_name, node_data in nodes.items():
                # Priority: module_path > module > file_path
                # Use 'module' before 'file_path' so dotted patterns
                # work correctly - file_path is a filesystem path that won't match
                module_path = node_data.get("module_path") or node_data.get("module") or node_data.get("file_path", "")
                if self.settings_manager.should_include_node(node_name, module_path):
                    filtered_nodes[node_name] = node_data
            return filtered_nodes

        return nodes

    def _load_from_file(self) -> dict[str, dict[str, Any]]:
        """Load registry from JSON file without auto-discovery.

        Returns:
            Dictionary mapping node names to metadata, or empty dict on error
        """
        # Try structured format first (delegates to _read_wrapper)
        wrapper = self._read_wrapper()
        if wrapper:
            self._registry_version = wrapper.get("version")
            self._registry_last_scan = wrapper.get("last_core_scan")
            return wrapper.get("nodes", {})  # type: ignore[no-any-return]

        # Fall through to legacy flat format handling
        if not self.registry_path.exists():
            logger.debug(f"Registry file not found at {self.registry_path}")
            return {}

        try:
            content = self.registry_path.read_text()
            if not content.strip():
                logger.debug("Registry file is empty")
                return {}

            data = json.loads(content)
            data.pop("__metadata__", None)  # Strip legacy metadata from node dict
            return data  # type: ignore[no-any-return]

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse registry JSON: {e}")
            return {}
        except Exception as e:
            logger.warning(f"Error reading registry file: {e}")
            return {}

    def save(self, nodes: dict[str, dict[str, Any]]) -> None:
        """Save nodes dictionary to registry JSON file in structured format.

        Always writes the structured wrapper format: {version, last_core_scan,
        metadata, nodes}. Preserves existing version/timestamp/metadata from
        the wrapper if present.

        IMPORTANT: This saves ALL nodes to the registry (unfiltered).
        Filtering is applied at load time based on settings.

        Args:
            nodes: Dictionary mapping node names to metadata

        Note:
            This completely replaces the nodes in the registry file.
            Manual edits will be lost on save.
        """
        # Preserve existing wrapper metadata (version, timestamps, metadata)
        existing = self._read_wrapper()

        data = {
            "version": existing.get("version", self._get_version()),
            "last_core_scan": existing.get("last_core_scan", self._now_iso()),
            "metadata": existing.get("metadata", {}),
            "nodes": nodes,
        }

        try:
            self._write_atomic(data)
            logger.info(f"Saved {len(nodes)} nodes to registry")
        except Exception:
            logger.exception("Failed to save registry")
            raise

    def _write_atomic(self, data: dict[str, Any]) -> None:
        """Persist the registry wrapper to ``registry_path`` atomically.

        A plain truncate-and-write lets a concurrent reader (e.g. parallel
        ``pflow ui`` requests, or two CLI processes) observe a half-written file
        → invalid JSON → an empty node set → spurious "unknown node type"
        errors. ``os.replace`` is atomic on POSIX, so a reader always sees either
        the complete old file or the complete new one. Mirrors the
        tempfile+replace pattern ``WorkflowManager``/``SettingsManager`` use.
        """
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        # Dot-prefixed temp file (hidden, namespaced) in the SAME dir as the
        # target — matches settings.py/manager.py and keeps os.replace on one
        # filesystem (cross-fs rename would raise).
        fd, tmp = tempfile.mkstemp(dir=self.registry_path.parent, prefix=".registry.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.registry_path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value from registry.

        Reads directly from the structured wrapper's metadata field.

        Args:
            key: The metadata key to retrieve
            default: Default value if key not found

        Returns:
            The metadata value or default if not found
        """
        wrapper = self._read_wrapper()
        return wrapper.get("metadata", {}).get(key, default)

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata value in registry.

        Updates the structured wrapper's metadata field directly.

        Args:
            key: The metadata key to set
            value: The value to store
        """
        wrapper = self._read_wrapper()

        if "metadata" not in wrapper:
            wrapper["metadata"] = {}
        wrapper["metadata"][key] = value

        # Ensure required wrapper fields exist
        if "nodes" not in wrapper:
            wrapper["nodes"] = {}
        if "version" not in wrapper:
            wrapper["version"] = self._get_version()
        if "last_core_scan" not in wrapper:
            wrapper["last_core_scan"] = self._now_iso()

        try:
            self._write_atomic(wrapper)
            logger.debug(f"Updated metadata key '{key}' in registry")
        except Exception:
            logger.exception("Failed to update registry metadata")
            raise

    def update_from_scanner(self, scan_results: list[dict[str, Any]]) -> None:
        """Update registry with scanner results.

        Converts scanner's list format to registry's dict format.
        Logs warnings for duplicate node names (last-wins).

        Args:
            scan_results: List of node metadata dictionaries from scanner

        Note:
            This performs a complete replacement of the registry.
            Previous contents and manual edits will be lost.
        """
        nodes = {}
        duplicates = []

        for node_metadata in scan_results:
            name = node_metadata.get("name")
            if not name:
                logger.warning(f"Node missing 'name' field: {node_metadata}")
                continue

            if name in nodes:
                duplicates.append(name)

            # Store node with name as key, removing name from metadata
            node_data = {k: v for k, v in node_metadata.items() if k != "name"}
            nodes[name] = node_data

        if duplicates:
            logger.warning(f"Duplicate node names found (using last occurrence): {duplicates}")

        # Save the updated registry
        self.save(nodes)

    def get_nodes_metadata(self, node_types: Collection[str]) -> dict[str, dict[str, Any]]:
        """Get metadata for specific node types.

        Args:
            node_types: Collection of node type names to retrieve

        Returns:
            Dict mapping node type names to their metadata.
            Only includes node types that exist in registry.

        Raises:
            TypeError: If node_types is None
        """
        if node_types is None:
            raise TypeError("node_types cannot be None")

        # Load the registry (filtered by default)
        registry_data = self.load()

        # Filter to only requested node types
        result = {}
        for node_type in node_types:
            # Skip non-string items
            if not isinstance(node_type, str):
                continue

            # Include only if exists in registry
            if node_type in registry_data:
                result[node_type] = registry_data[node_type]

        return result

    def _auto_discover_core_nodes(self) -> None:
        """Auto-discover and save core nodes on first use."""
        import pflow.nodes
        from pflow.registry.scanner import scan_for_nodes

        # Find core nodes directory
        nodes_path = Path(pflow.nodes.__file__).parent

        # Scan all subdirectories (skip __pycache__ only)
        # We'll filter test nodes based on settings, not here
        subdirs = [d for d in nodes_path.iterdir() if d.is_dir() and not d.name.startswith("__")]

        logger.info(f"Scanning for core nodes in: {subdirs}")

        # Capture scan-start time BEFORE reading sources. Stamping the registry
        # with a POST-scan timestamp would lose concurrent edits made during the
        # scan window (their mtime would sit < stored timestamp, so the next
        # mtime check wouldn't refresh).
        scan_start = self._now_iso()
        scan_results = scan_for_nodes(subdirs)

        # Convert to registry format with type marking
        # NOTE: We save ALL nodes to registry, filtering happens at load time
        registry_nodes = {}

        for node in scan_results:
            name = node.get("name")
            if not name:
                continue

            node_copy = dict(node)
            node_copy["type"] = "core"  # Mark as core node
            del node_copy["name"]  # Registry doesn't store name in value
            registry_nodes[name] = node_copy

        logger.info(f"Auto-discovered {len(registry_nodes)} core nodes")

        # Save with metadata, using the pre-scan timestamp
        self._save_with_metadata(registry_nodes, scan_time=scan_start)

    def _save_with_metadata(self, nodes: dict[str, dict[str, Any]], scan_time: Optional[str] = None) -> None:
        """Save nodes with updated version and timestamp.

        Unlike save(), this always updates the version and last_core_scan fields
        to reflect the current pflow version and time.

        Args:
            nodes: The node metadata dict to persist.
            scan_time: UTC ISO timestamp captured BEFORE reading sources. When
                omitted, defaults to "now" (safe for merge/post-refresh saves
                that aren't wrapping a live scan).
        """
        # Preserve existing metadata (MCP sync hashes, etc.)
        existing = self._read_wrapper()

        data = {
            "version": self._get_version(),
            "last_core_scan": scan_time or self._now_iso(),
            "metadata": existing.get("metadata", {}),
            "nodes": nodes,
        }

        self._write_atomic(data)

        logger.info(f"Saved {len(nodes)} nodes to registry with metadata")

    def _core_nodes_outdated(self, nodes: dict[str, dict[str, Any]]) -> bool:
        """Check if core nodes need refresh.

        Triggers when either:
        - Stored registry version differs from current pflow version, OR
        - Any core node source file is newer than the last scan timestamp
          (catches docstring changes across editable/from-source installs
          where pflow's version string hasn't moved).

        Without either a stored version OR a scan timestamp there's no basis
        for comparison, so the check short-circuits to False — matches the
        pre-mtime defensive behavior and avoids spurious refreshes on
        partially-written or externally-produced registries.
        """
        if not self._registry_version and not self._registry_last_scan:
            return False

        if self._registry_version:
            current_version = self._get_version()
            if self._registry_version != current_version:
                logger.info(
                    f"Registry version {self._registry_version} differs from "
                    f"pflow version {current_version}, refreshing core nodes"
                )
                return True

        if self._source_newer_than_scan():
            logger.info("Node source files modified since last scan, refreshing core nodes")
            return True

        return False

    def _source_newer_than_scan(self) -> bool:
        """Return True if any core node source file is newer than last_core_scan.

        Fails safe: any parse or filesystem error returns False (with a warning)
        so ``load()`` never crashes on a filesystem oddity. A missing
        ``last_core_scan`` is treated as stale so structured-format registries
        missing the timestamp self-heal on next load.

        Deletion detection: mtime of surviving files doesn't move when a sibling
        is removed, so this check won't catch a deleted node source file. Version
        bump is the heal path for deletions.
        """
        if not self._registry_last_scan:
            return True

        try:
            last_scan = datetime.fromisoformat(self._registry_last_scan)
            if last_scan.tzinfo is None:
                # Legacy naive timestamp — treat as local time for comparison
                last_scan = last_scan.astimezone()
            last_scan_ts = last_scan.timestamp()

            import pflow.nodes

            nodes_path = Path(pflow.nodes.__file__).parent
            if not nodes_path.exists():
                return False

            for py_file in nodes_path.rglob("*.py"):
                if "__pycache__" in py_file.parts:
                    continue
                try:
                    if py_file.stat().st_mtime > last_scan_ts:
                        return True
                except OSError:
                    # A single unreadable file shouldn't abort the whole check —
                    # keep walking in case a reachable file is stale.
                    continue

            return False
        except Exception as e:
            # Surface to users debugging "my edit isn't picked up" — self-heal
            # failing is exactly what they need to see without --verbose.
            logger.warning(f"Could not check node source mtimes (auto-refresh disabled this run): {e}")
            return False

    def _refresh_core_nodes(self, nodes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Refresh core nodes while preserving every non-core node.

        The refresh re-discovers core nodes, so everything that isn't core (user,
        mcp, or an untyped legacy entry) must survive. Keyed on "not core" rather
        than an allowlist of known types so it fails safe: an entry we don't
        recognize is kept, never silently dropped. This also self-heals MCP
        entries synced before they were stamped with type="mcp" — their absent
        type is not "core", so they're preserved.

        Freshly-discovered core metadata wins on a name collision: preserved
        entries are merged *under* the fresh scan, not over it. So a stale entry
        sharing a core node's name (e.g. an untyped "shell" left by the removed
        `registry scan` CLI) can neither resurrect nor shadow a core node — the
        broadened predicate can only add non-core names, never override core ones.
        """
        # Preserve every non-core node (see docstring: fail-safe, self-healing).
        preserved = {name: data for name, data in nodes.items() if data.get("type") != "core"}

        # Re-discover core nodes — _auto_discover_core_nodes stamps
        # last_core_scan with a PRE-scan timestamp (race-safe).
        self._auto_discover_core_nodes()

        # Reload — populates self._registry_last_scan from the pre-scan stamp.
        refreshed = self._load_from_file()

        # Merge preserved nodes UNDER the fresh core scan: setdefault adds a
        # preserved entry only when its name is free, so fresh core metadata
        # always wins a name collision (see docstring).
        for name, data in preserved.items():
            refreshed.setdefault(name, data)

        # Save the merged result, propagating the pre-scan timestamp so the
        # race-safety is preserved through the final merge write. Without this,
        # the merge save would stamp "now" (post-scan) and lose any edit made
        # during the scan window.
        self._save_with_metadata(refreshed, scan_time=self._registry_last_scan)

        return refreshed

    def search(self, query: str) -> list[tuple[str, dict[str, Any], int]]:
        """Search with multi-keyword support (AND logic).

        Supports single or multiple space-separated keywords. All keywords must match
        for a node to be included. Scores are averaged across keywords.

        Examples:
            search("github")      → Single keyword
            search("github api")  → Both "github" AND "api" must match

        Args:
            query: Single keyword or space-separated keywords

        Returns:
            List of (name, metadata, avg_score) tuples, sorted by score descending
        """
        if not query or not query.strip():
            return []

        # Split into keywords (space-separated)
        keywords = [k.strip().lower() for k in query.split() if k.strip()]
        if not keywords:
            return []

        results = []
        nodes = self.load()  # Uses filtered nodes by default

        for name, metadata in nodes.items():
            # Try to match all keywords against this node
            keyword_scores = self._score_node_against_keywords(name, metadata, keywords)

            # Only include if ALL keywords matched
            if len(keyword_scores) == len(keywords):
                avg_score = sum(keyword_scores) // len(keyword_scores)
                results.append((name, metadata, avg_score))

        # Sort by score desc, then name
        results.sort(key=lambda x: (-x[2], x[0]))
        return results

    def _score_node_against_keywords(self, name: str, metadata: dict[str, Any], keywords: list[str]) -> list[int]:
        """Score a node against multiple keywords (AND logic).

        Args:
            name: Node name
            metadata: Node metadata
            keywords: List of keywords to match (lowercase)

        Returns:
            List of scores (one per keyword). If any keyword doesn't match,
            returns incomplete list (for AND logic check).
        """
        name_lower = name.lower()

        # Get description from interface
        interface = metadata.get("interface", {})
        desc_lower = interface.get("description", "").lower()

        keyword_scores = []
        for keyword in keywords:
            score = self._calculate_keyword_score(keyword, name_lower, desc_lower)

            if score == 0:
                # This keyword doesn't match - skip node entirely (AND logic)
                break

            keyword_scores.append(score)

        return keyword_scores

    def _calculate_keyword_score(self, keyword: str, name_lower: str, desc_lower: str) -> int:
        """Calculate match score for a single keyword.

        Args:
            keyword: Keyword to match (lowercase)
            name_lower: Node name (lowercase)
            desc_lower: Node description (lowercase)

        Returns:
            Score: 100 (exact), 90 (prefix), 70 (name contains), 50 (desc contains), 0 (no match)
        """
        if name_lower == keyword:
            return 100  # Exact match
        elif name_lower.startswith(keyword):
            return 90  # Prefix match
        elif keyword in name_lower:
            return 70  # Name contains
        elif keyword in desc_lower:
            return 50  # Description contains
        return 0  # No match

    def scan_user_nodes(self, path: Path) -> list[dict[str, Any]]:
        """Scan for user nodes with validation.

        Args:
            path: Directory path to scan

        Returns:
            List of discovered node metadata dicts
        """
        from pflow.registry.scanner import scan_for_nodes

        if not path.exists():
            logger.warning(f"Scan path does not exist: {path}")
            return []

        if not path.is_dir():
            logger.warning(f"Scan path is not a directory: {path}")
            return []

        # Scan the path
        scan_results = scan_for_nodes([path])

        # Mark as user nodes
        for node in scan_results:
            node["type"] = "user"

        logger.info(f"Found {len(scan_results)} user nodes in {path}")
        return scan_results

    def list_nodes(self, include_filtered: bool = False) -> list[str]:
        """List all available nodes with optional filtering.

        Args:
            include_filtered: If True, bypass filtering and show all nodes

        Returns:
            List of node names, sorted alphabetically
        """
        # Load with appropriate filtering
        nodes = self.load(include_filtered=include_filtered)
        return sorted(nodes.keys())
