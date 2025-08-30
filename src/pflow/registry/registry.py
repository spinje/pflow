"""Registry for managing discovered pflow nodes."""

import json
import logging
from collections.abc import Collection
from datetime import datetime
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

    def load(self) -> dict[str, dict[str, Any]]:
        """Load registry from JSON file, auto-discovering core nodes if needed.

        Returns empty dict if file doesn't exist or is corrupt.
        Logs warnings for errors but doesn't raise exceptions.

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

        # Cache the nodes
        self._cached_nodes = nodes
        return nodes

    def _load_from_file(self) -> dict[str, dict[str, Any]]:
        """Load registry from JSON file without auto-discovery.

        Returns:
            Dictionary mapping node names to metadata, or empty dict on error
        """
        if not self.registry_path.exists():
            logger.debug(f"Registry file not found at {self.registry_path}")
            return {}

        try:
            content = self.registry_path.read_text()
            if not content.strip():
                logger.debug("Registry file is empty")
                return {}

            data = json.loads(content)

            # Handle new format with metadata
            if isinstance(data, dict) and "nodes" in data:
                return data["nodes"]  # type: ignore[no-any-return]

            # Handle old format (direct node dict)
            return data  # type: ignore[no-any-return]

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse registry JSON: {e}")
            return {}
        except Exception as e:
            logger.warning(f"Error reading registry file: {e}")
            return {}

    def save(self, nodes: dict[str, dict[str, Any]]) -> None:
        """Save nodes dictionary to registry JSON file.

        Creates parent directory if it doesn't exist.
        Pretty-prints JSON with indent=2 for readability.

        Args:
            nodes: Dictionary mapping node names to metadata

        Note:
            This completely replaces the existing registry file.
            Manual edits will be lost on save.
        """
        # Ensure parent directory exists
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON with pretty formatting
        try:
            content = json.dumps(nodes, indent=2, sort_keys=True)
            self.registry_path.write_text(content)
            logger.info(f"Saved {len(nodes)} nodes to registry")
        except Exception:
            logger.exception("Failed to save registry")
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

        # Load the full registry
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

        # Scan all subdirectories (skip __pycache__ directories)
        subdirs = [d for d in nodes_path.iterdir() if d.is_dir() and not d.name.startswith("__")]

        logger.info(f"Scanning for core nodes in: {subdirs}")

        # Scan and save
        scan_results = scan_for_nodes(subdirs)

        # Convert to registry format with type marking
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

        # Save with metadata
        self._save_with_metadata(registry_nodes)

    def _save_with_metadata(self, nodes: dict[str, dict[str, Any]]) -> None:
        """Save nodes with metadata like version and timestamps."""
        import pflow

        data = {
            "version": getattr(pflow, "__version__", "0.0.1"),
            "last_core_scan": datetime.now().isoformat(),
            "nodes": nodes,
        }

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)

        logger.info(f"Saved {len(nodes)} nodes to registry with metadata")

    def _core_nodes_outdated(self, nodes: dict[str, dict[str, Any]]) -> bool:
        """Check if core nodes need refresh due to version change.

        For MVP, always return False (no version checking).
        """
        # TODO: In future, check if pflow version differs from registry version
        return False

    def _refresh_core_nodes(self, nodes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Refresh core nodes while preserving user nodes.

        For MVP, just returns nodes unchanged.
        """
        # TODO: In future, re-scan core nodes and merge with user nodes
        return nodes

    def search(self, query: str) -> list[tuple[str, dict[str, Any], int]]:
        """Simple substring search with scoring.

        Args:
            query: Search string

        Returns:
            List of (name, metadata, score) tuples, sorted by score descending
        """
        if not query:
            return []

        query_lower = query.lower()
        results = []
        nodes = self.load()

        for name, metadata in nodes.items():
            name_lower = name.lower()

            # Get description from interface
            interface = metadata.get("interface", {})
            desc_lower = interface.get("description", "").lower()

            # Simple scoring
            score = 0
            if name_lower == query_lower:
                score = 100  # Exact match
            elif name_lower.startswith(query_lower):
                score = 90  # Prefix match
            elif query_lower in name_lower:
                score = 70  # Name contains
            elif query_lower in desc_lower:
                score = 50  # Description contains

            if score > 0:
                results.append((name, metadata, score))

        # Sort by score desc, then name
        results.sort(key=lambda x: (-x[2], x[0]))
        return results

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
