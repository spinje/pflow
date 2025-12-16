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

        # Lazy load settings manager to avoid circular import
        self._settings_manager: Optional[Any] = None

    @property
    def settings_manager(self) -> Any:
        """Lazy load SettingsManager to avoid circular imports."""
        if self._settings_manager is None:
            from pflow.core.settings import SettingsManager

            self._settings_manager = SettingsManager()
        return self._settings_manager

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
                # Use 'module' before 'file_path' so dotted patterns (pflow.nodes.git.*)
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

        IMPORTANT: This saves ALL nodes to the registry (unfiltered).
        Filtering is applied at load time based on settings.

        Args:
            nodes: Dictionary mapping node names to metadata

        Note:
            This completely replaces the existing registry file.
            Manual edits will be lost on save.
        """
        # Ensure parent directory exists
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Preserve metadata if it exists
        metadata = {}
        if self.registry_path.exists():
            try:
                with open(self.registry_path) as f:
                    existing_data = json.load(f)
                    metadata = existing_data.get("__metadata__", {})
            except Exception as e:
                logger.debug(f"Could not read existing metadata, starting fresh: {e}")

        # Create structure with metadata
        registry_data = dict(nodes)
        if metadata:
            registry_data["__metadata__"] = metadata

        # Write JSON with pretty formatting
        try:
            content = json.dumps(registry_data, indent=2, sort_keys=True)
            self.registry_path.write_text(content)
            logger.info(f"Saved {len(nodes)} nodes to registry")
        except Exception:
            logger.exception("Failed to save registry")
            raise

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata value from registry.

        Args:
            key: The metadata key to retrieve
            default: Default value if key not found

        Returns:
            The metadata value or default if not found
        """
        config = self.load()
        metadata = config.get("__metadata__", {})
        return metadata.get(key, default)

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata value in registry.

        Args:
            key: The metadata key to set
            value: The value to store
        """
        config = self.load(include_filtered=True)
        if "__metadata__" not in config:
            config["__metadata__"] = {}
        config["__metadata__"][key] = value

        # Extract nodes and metadata separately for save
        metadata = config.pop("__metadata__", {})
        nodes = config  # Everything else is nodes

        # Save nodes, but first update the metadata directly
        # We need to handle this specially since save() only takes nodes
        if self.registry_path.exists():
            # Read existing registry to preserve structure
            with open(self.registry_path) as f:
                existing = json.load(f)
                existing["__metadata__"] = metadata
                # Write back with updated metadata
                content = json.dumps(existing, indent=2, sort_keys=True)
                self.registry_path.write_text(content)
                logger.debug(f"Updated metadata key '{key}' in registry")
        else:
            # No existing registry, create new with metadata
            registry_data = dict(nodes)
            registry_data["__metadata__"] = metadata
            content = json.dumps(registry_data, indent=2, sort_keys=True)
            self.registry_path.write_text(content)
            logger.debug(f"Created registry with metadata key '{key}'")

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

        # Scan and save
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
