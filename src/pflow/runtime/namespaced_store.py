"""Namespaced shared store implementation for automatic collision prevention.

This module provides a transparent proxy that namespaces all node outputs
under their node ID, preventing collisions when multiple nodes of the same
type write to the same keys.
"""

from collections.abc import Iterator
from typing import Any, Optional


class NamespacedSharedStore:
    """Proxy that namespaces all node writes while maintaining backward compatibility.

    This proxy ensures that all writes from a node go to shared[node_id][key]
    while reads check both the namespace and root level for backward compatibility
    with CLI inputs and legacy data.

    Example:
        >>> shared = {"cli_input": "value"}  # Root level data
        >>> proxy = NamespacedSharedStore(shared, "node1")
        >>> proxy["output"] = "data"  # Writes to shared["node1"]["output"]
        >>> proxy.get("cli_input")  # Reads from root level
        'value'
        >>> proxy.get("output")  # Reads from namespace
        'data'
    """

    def __init__(self, parent_store: dict[str, Any], namespace: str) -> None:
        """Initialize the namespaced proxy.

        Args:
            parent_store: The actual shared store dictionary
            namespace: The node ID to use as namespace
        """
        self._parent = parent_store
        self._namespace = namespace

        # Ensure namespace exists in parent store
        if namespace not in parent_store:
            parent_store[namespace] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        """Write to the namespaced location.

        All writes go to shared[namespace][key] to prevent collisions.
        """
        self._parent[self._namespace][key] = value

    def __getitem__(self, key: str) -> Any:
        """Read with namespace priority, falling back to root.

        Check order:
        1. shared[namespace][key] - For self-reading nodes or namespaced data
        2. shared[key] - For CLI inputs, legacy data, or cross-node reads

        Raises:
            KeyError: If key not found in namespace or root
        """
        # Check own namespace first (for self-reading nodes if any)
        if key in self._parent[self._namespace]:
            return self._parent[self._namespace][key]

        # Fall back to root level (for CLI inputs, legacy data)
        if key in self._parent:
            return self._parent[key]

        # Key not found in either location
        raise KeyError(f"Key '{key}' not found in namespace '{self._namespace}' or root")

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """Safe get with namespace priority.

        Args:
            key: The key to look up
            default: Value to return if key not found

        Returns:
            The value if found, otherwise default
        """
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        """Check if key exists in namespace or root.

        Used by 'in' operator. Checks both namespace and root level.
        """
        return key in self._parent[self._namespace] or key in self._parent

    def setdefault(self, key: str, default: Any = None) -> Any:
        """Set default value if key doesn't exist.

        If key exists in namespace or root, return its value.
        Otherwise, set it in namespace and return default.
        """
        if key in self:
            return self[key]
        self[key] = default
        return default

    def keys(self) -> set[str]:
        """Return combined keys from namespace and root.

        This is needed for dict() conversion and iteration.
        """
        # Combine keys from both namespace and root
        namespace_keys = set(self._parent[self._namespace].keys())
        root_keys = set(self._parent.keys())

        # Don't include our own namespace as a key (would cause recursion)
        root_keys.discard(self._namespace)

        return namespace_keys | root_keys

    def items(self) -> list[tuple[str, Any]]:
        """Return combined items from namespace and root.

        Namespace items take priority over root items.
        """
        result = []
        seen = set()

        # First add namespace items
        for key, value in self._parent[self._namespace].items():
            result.append((key, value))
            seen.add(key)

        # Then add root items (except our own namespace to avoid recursion)
        for key, value in self._parent.items():
            if key not in seen and key != self._namespace:
                result.append((key, value))
                seen.add(key)

        return result

    def values(self) -> list[Any]:
        """Return combined values from namespace and root."""
        return [value for _, value in self.items()]

    def __iter__(self) -> Iterator[str]:
        """Iterate over combined keys."""
        return iter(self.keys())

    def __len__(self) -> int:
        """Return count of combined unique keys."""
        return len(self.keys())

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"NamespacedSharedStore(namespace='{self._namespace}', keys={list(self._parent[self._namespace].keys())})"
        )
