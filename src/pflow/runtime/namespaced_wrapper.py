"""Node wrapper for automatic namespacing of shared store access.

This module provides a transparent wrapper that intercepts a node's
shared store access and redirects it through a namespaced proxy.
"""

from typing import Any, Dict

from .namespaced_store import NamespacedSharedStore


class NamespacedNodeWrapper:
    """Wrapper that provides namespaced shared store access to nodes.

    This wrapper intercepts the _run() method to provide a namespaced
    view of the shared store, ensuring all node outputs are isolated
    under their node ID to prevent collisions.

    The wrapper is transparent - it delegates all other attributes
    to the inner node, maintaining full compatibility with PocketFlow's
    node interface including the >> and - operators.
    """

    def __init__(self, inner_node: Any, node_id: str) -> None:
        """Initialize the wrapper.

        Args:
            inner_node: The node to wrap (could be another wrapper)
            node_id: The node ID to use as namespace
        """
        self._inner_node = inner_node
        self._node_id = node_id

    def _run(self, shared: Dict[str, Any]) -> Any:
        """Execute the node with a namespaced shared store.

        This intercepts the _run method to provide a namespaced proxy
        instead of the raw shared store.

        Args:
            shared: The actual shared store

        Returns:
            The result from the inner node's _run method
        """
        # Create namespaced proxy for this node
        namespaced_shared = NamespacedSharedStore(shared, self._node_id)

        # Execute inner node with namespaced store
        return self._inner_node._run(namespaced_shared)

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to the inner node.

        This makes the wrapper transparent for all operations except _run.
        """
        # Prevent infinite recursion during copy operations
        if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Get inner_node without triggering __getattr__ again
        inner = object.__getattribute__(self, "_inner_node")
        return getattr(inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Set attributes, handling special wrapper attributes.

        Wrapper-specific attributes (_inner_node, _node_id) are set on
        the wrapper itself. All others are delegated to the inner node.
        """
        if name in ("_inner_node", "_node_id"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner_node, name, value)

    def __rshift__(self, other: Any) -> Any:
        """Support the >> operator for flow construction.

        This delegates to the inner node's >> operator to maintain
        compatibility with PocketFlow's flow construction syntax.
        """
        return self._inner_node >> other

    def __sub__(self, action: str) -> Any:
        """Support the - operator for conditional routing.

        This delegates to the inner node's - operator to maintain
        compatibility with PocketFlow's conditional routing syntax.
        """
        return self._inner_node - action

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"NamespacedNodeWrapper(node_id='{self._node_id}', inner={self._inner_node})"
