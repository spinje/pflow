"""Registry for managing discovered pflow nodes."""

import json
import logging
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

    def load(self) -> dict[str, dict[str, Any]]:
        """Load registry from JSON file.

        Returns empty dict if file doesn't exist or is corrupt.
        Logs warnings for errors but doesn't raise exceptions.

        Returns:
            Dictionary mapping node names to metadata
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

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse registry JSON: {e}")
            return {}
        except Exception as e:
            logger.warning(f"Error reading registry file: {e}")
            return {}
        else:
            logger.info(f"Loaded {len(data)} nodes from registry")
            return data  # type: ignore[no-any-return]

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
