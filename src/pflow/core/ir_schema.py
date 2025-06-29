"""JSON Schema definitions for pflow workflow intermediate representation (IR).

This module provides the schema and validation functions for workflow IR,
which is the standardized format for representing workflows before they
are compiled to executable pocketflow.Flow objects.

Example usage:
    >>> from pflow.core import validate_ir
    >>>
    >>> # Valid minimal IR
    >>> ir = {
    ...     "ir_version": "0.1.0",
    ...     "nodes": [
    ...         {"id": "n1", "type": "read-file", "params": {"path": "input.txt"}}
    ...     ]
    ... }
    >>> validate_ir(ir)  # No exception raised
    >>>
    >>> # Invalid IR (missing required field)
    >>> bad_ir = {"nodes": [{"id": "n1"}]}
    >>> try:
    ...     validate_ir(bad_ir)
    >>> except ValidationError as e:
    ...     print(e)  # "Validation error at root: 'ir_version' is required"
"""

import json
from typing import Any, Union

import jsonschema
from jsonschema import Draft7Validator
from jsonschema import ValidationError as JsonSchemaValidationError


class ValidationError(Exception):
    """Custom validation error with helpful messages and field paths."""

    def __init__(self, message: str, path: str = "", suggestion: str = ""):
        """Initialize validation error.

        Args:
            message: The validation error message
            path: The path to the invalid field (e.g., "nodes[0].type")
            suggestion: Optional suggestion for fixing the error
        """
        self.message = message
        self.path = path
        self.suggestion = suggestion

        full_message = "Validation error"
        if path:
            full_message += f" at {path}"
        full_message += f": {message}"
        if suggestion:
            full_message += f"\n{suggestion}"

        super().__init__(full_message)


# JSON Schema for workflow IR (minimal MVP version)
FLOW_IR_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "ir_version": {
            "type": "string",
            "pattern": "^\\d+\\.\\d+\\.\\d+$",
            "description": "Semantic version of the IR format",
        },
        "nodes": {
            "type": "array",
            "description": "Array of nodes in the workflow",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Unique identifier for the node"},
                    "type": {"type": "string", "description": "Node type that maps to registry"},
                    "params": {
                        "type": "object",
                        "description": "Parameters for node behavior",
                        "additionalProperties": True,
                    },
                },
                "required": ["id", "type"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "edges": {
            "type": "array",
            "description": "Array of edges connecting nodes",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string", "description": "Source node ID"},
                    "to": {"type": "string", "description": "Target node ID"},
                    "action": {
                        "type": "string",
                        "description": "Action string for conditional routing",
                        "default": "default",
                    },
                },
                "required": ["from", "to"],
                "additionalProperties": False,
            },
            "default": [],
        },
        "start_node": {
            "type": "string",
            "description": "ID of the first node to execute (defaults to first node if not specified)",
        },
        "mappings": {
            "type": "object",
            "description": "Optional proxy mappings for NodeAwareSharedStore",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "input_mappings": {"type": "object", "additionalProperties": {"type": "string"}},
                    "output_mappings": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "default": {},
        },
    },
    "required": ["ir_version", "nodes"],
    "additionalProperties": False,
}


def _format_path(path: list) -> str:
    """Format a jsonschema path into a readable string.

    Args:
        path: List of path components from jsonschema

    Returns:
        Formatted path string like "nodes[0].type"
    """
    formatted = ""
    for i, component in enumerate(path):
        if isinstance(component, int):
            formatted += f"[{component}]"
        else:
            if i > 0 and not formatted.endswith("]"):
                formatted += "."
            formatted += str(component)
    return formatted or "root"


def _get_suggestion(error: JsonSchemaValidationError) -> str:
    """Get a helpful suggestion based on the validation error.

    Args:
        error: The jsonschema validation error

    Returns:
        Suggestion string for fixing the error
    """
    if error.validator == "required":
        # Extract field name from message like "'field_name' is a required property"
        match = error.message.split("'")
        if len(match) >= 2:
            field_name = match[1]
            return f"Add the required field '{field_name}'"
        return "Add the missing required field"
    elif error.validator == "type":
        expected = error.validator_value
        actual = type(error.instance).__name__
        return f"Change type from '{actual}' to '{expected}'"
    elif error.validator == "pattern":
        if "ir_version" in str(error.absolute_path):
            return "Use semantic versioning format, e.g., '0.1.0'"
    elif error.validator == "additionalProperties":
        return "Remove unknown properties or check field names"
    elif error.validator == "minItems":
        return "Add at least one node to the workflow"

    return ""


def validate_ir(data: Union[dict[str, Any], str]) -> None:
    """Validate workflow IR against the schema.

    Args:
        data: The IR data to validate (dict or JSON string)

    Raises:
        ValidationError: If the IR is invalid
        ValueError: If JSON parsing fails
    """
    # Parse JSON string if needed
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e  # noqa: TRY003

    # Create validator
    validator = Draft7Validator(FLOW_IR_SCHEMA)

    # Check if schema is valid first (development safety)
    try:
        validator.check_schema(FLOW_IR_SCHEMA)
    except jsonschema.SchemaError as e:
        raise RuntimeError(f"Schema definition error: {e}") from e  # noqa: TRY003

    # Validate the data
    errors = list(validator.iter_errors(data))
    if not errors:
        # Additional custom validations
        _validate_node_references(data)
        _validate_duplicate_node_ids(data)
        return

    # Format the first error with helpful message
    error = errors[0]
    path = _format_path(list(error.absolute_path))
    suggestion = _get_suggestion(error)

    raise ValidationError(message=error.message, path=path, suggestion=suggestion)


def _validate_node_references(data: dict[str, Any]) -> None:
    """Validate that all edge references point to existing nodes.

    Args:
        data: The validated IR data

    Raises:
        ValidationError: If edge references non-existent nodes
    """
    if "edges" not in data or not data["edges"]:
        return

    node_ids = {node["id"] for node in data["nodes"]}

    for i, edge in enumerate(data["edges"]):
        if edge["from"] not in node_ids:
            raise ValidationError(
                message=f"Edge references non-existent node '{edge['from']}'",
                path=f"edges[{i}].from",
                suggestion=f"Change to one of: {sorted(node_ids)}",
            )
        if edge["to"] not in node_ids:
            raise ValidationError(
                message=f"Edge references non-existent node '{edge['to']}'",
                path=f"edges[{i}].to",
                suggestion=f"Change to one of: {sorted(node_ids)}",
            )


def _validate_duplicate_node_ids(data: dict[str, Any]) -> None:
    """Validate that all node IDs are unique.

    Args:
        data: The validated IR data

    Raises:
        ValidationError: If duplicate node IDs exist
    """
    seen = set()
    for i, node in enumerate(data["nodes"]):
        node_id = node["id"]
        if node_id in seen:
            raise ValidationError(
                message=f"Duplicate node ID '{node_id}'",
                path=f"nodes[{i}].id",
                suggestion="Use unique IDs for each node",
            )
        seen.add(node_id)
