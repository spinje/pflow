"""Namespaced shared store implementation for automatic collision prevention.

This module provides a transparent proxy that namespaces all node outputs
under their node ID, preventing collisions when multiple nodes of the same
type write to the same keys.
"""

from collections.abc import Iterator, MutableMapping
from typing import Any


class NamespacedSharedStore(MutableMapping[str, Any]):
    """Proxy that namespaces all node writes while maintaining backward compatibility.

    This proxy ensures that all writes from a node go to ``shared[node_id][key]``
    while reads check both the namespace and root level for backward compatibility
    with CLI inputs and legacy data.

    Inherits from ``collections.abc.MutableMapping`` so consumers using
    duck-typed ``isinstance(_, Mapping)`` checks (e.g. ``TemplateResolver``)
    correctly recognize the proxy as dict-like. Without this, dotted-path
    template resolution (``${node.field}``) silently fails through the proxy
    because ``isinstance(value, dict)`` excludes it. Task 159 cache rendering
    relies on this — see Task 159 Segment 3 verification report.

    Required ABC primitives are implemented below: ``__getitem__``,
    ``__setitem__``, ``__delitem__``, ``__iter__``, ``__len__``,
    ``__contains__``. ``keys`` / ``items`` / ``values`` / ``get`` /
    ``setdefault`` / ``update`` / ``pop`` / ``popitem`` / ``clear`` are
    provided by the ABC mixin and route through these primitives — no manual
    override needed.

    Example:
        >>> shared = {"cli_input": "value"}
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

    @staticmethod
    def _is_special_key(key: object) -> bool:
        """A ``__*__`` key bypasses namespacing and reads/writes at root."""
        return isinstance(key, str) and key.startswith("__") and key.endswith("__")

    def __setitem__(self, key: str, value: Any) -> None:
        """Write to the namespaced location or root for special keys.

        Special keys (``__*__``) are written to root for framework
        coordination. Regular writes go to ``shared[namespace][key]`` to
        prevent collisions.
        """
        if self._is_special_key(key):
            self._parent[key] = value
        else:
            self._parent[self._namespace][key] = value

    def __getitem__(self, key: str) -> Any:
        """Read with namespace priority, falling back to root.

        For special keys (``__*__``): always at root.
        For regular keys: namespace first, then root (CLI inputs, legacy data).

        Raises:
            KeyError: If key not found in namespace or root.
        """
        if self._is_special_key(key):
            if key in self._parent:
                return self._parent[key]
            raise KeyError(f"Key '{key}' not found in root")

        if key in self._parent[self._namespace]:
            return self._parent[self._namespace][key]
        if key in self._parent:
            return self._parent[key]

        raise KeyError(f"Key '{key}' not found in namespace '{self._namespace}' or root")

    def __delitem__(self, key: str) -> None:
        """Delete a key.

        Special keys (``__*__``) are deleted from root. Regular keys are
        deleted from this proxy's namespace only — root reads (CLI inputs,
        other nodes' namespaces) are off-limits because writes never go
        there in the first place. Raises ``KeyError`` if the key isn't in
        the targeted location.

        Required by ``collections.abc.MutableMapping`` (the ABC's mixin
        ``pop`` / ``popitem`` / ``clear`` call this internally).
        """
        if self._is_special_key(key):
            del self._parent[key]
            return
        ns = self._parent[self._namespace]
        if key not in ns:
            raise KeyError(f"Key '{key}' not found in namespace '{self._namespace}'")
        del ns[key]

    def __contains__(self, key: object) -> bool:
        """Check if key exists in namespace or root.

        Special keys (``__*__``) are only checked at root. Regular keys are
        checked in both namespace and root.
        """
        if self._is_special_key(key):
            return key in self._parent

        # Non-string non-special keys can't be in either location.
        if not isinstance(key, str):
            return False

        return key in self._parent[self._namespace] or key in self._parent

    def __iter__(self) -> Iterator[str]:
        """Iterate over combined keys, namespace priority for dedup.

        Skips ``self._namespace`` (the node's own dict in the parent) to
        avoid surfacing it as a top-level key — it's the container for
        namespaced writes, not a value the node itself stored.
        """
        seen: set[str] = set()
        for k in self._parent[self._namespace]:
            seen.add(k)
            yield k
        for k in self._parent:
            if k != self._namespace and k not in seen:
                yield k

    def __len__(self) -> int:
        """Number of distinct keys visible (namespace + root, deduped)."""
        # Sum sizes minus the overlap and minus the namespace bucket itself.
        ns_keys = self._parent[self._namespace]
        overlap = sum(1 for k in ns_keys if k in self._parent and k != self._namespace)
        return len(ns_keys) + len(self._parent) - overlap - 1  # -1 for self._namespace bucket

    def __repr__(self) -> str:
        """String representation for debugging."""
        ns_keys = list(self._parent[self._namespace].keys())
        return f"NamespacedSharedStore(namespace='{self._namespace}', keys={ns_keys})"
