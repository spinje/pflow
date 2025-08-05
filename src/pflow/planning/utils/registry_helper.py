"""Registry data extraction utilities."""

from typing import Any, cast


def get_node_interface(node_type: str, registry_data: dict[str, Any]) -> dict[str, Any]:
    """Get the interface data for a specific node type.

    Pure data extraction - no logic.

    Args:
        node_type: The node type to look up
        registry_data: Registry data dictionary

    Returns:
        Interface dict or empty dict if not found
    """
    if node_type in registry_data:
        return cast(dict[str, Any], registry_data[node_type].get("interface", {}))
    return {}


def get_node_outputs(node_type: str, registry_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Get list of outputs a node writes to shared store.

    Pure data extraction - no validation.

    Args:
        node_type: The node type to look up
        registry_data: Registry data dictionary

    Returns:
        List of output dicts or empty list if not found
    """
    interface = get_node_interface(node_type, registry_data)
    return cast(list[dict[str, Any]], interface.get("outputs", []))


def get_node_inputs(node_type: str, registry_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Get list of inputs a node reads from shared store.

    Pure data extraction - no validation.

    Args:
        node_type: The node type to look up
        registry_data: Registry data dictionary

    Returns:
        List of input dicts or empty list if not found
    """
    interface = get_node_interface(node_type, registry_data)
    return cast(list[dict[str, Any]], interface.get("inputs", []))
