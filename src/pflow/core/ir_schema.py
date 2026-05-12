"""JSON Schema definitions for pflow workflow intermediate representation (IR).

This module provides the schema and validation functions for workflow IR,
which is the standardized format for representing workflows before they
are compiled to CompiledWorkflow objects for execution by WorkflowEngine.

The IR format is designed to be:
- Human-readable and editable
- Validated before execution
- Extensible for future features
- Compatible with template variables (${variable} syntax)

Design Decisions:
- **'type' vs 'registry_id'**: We use 'type' for node identification to keep
  the MVP simple. This may evolve to 'registry_id' in future versions.
- **Nodes as array**: Nodes are stored as an array with 'id' fields rather
  than a dictionary to preserve order and simplify duplicate detection.
- **Optional start_node**: If not specified, execution begins with the first
  node in the array, following the principle of least surprise.
- **Action-based routing**: Edges support an 'action' field for conditional
  flow control, inspired by pocketflow's execution model.

Example usage:
    >>> from pflow.core import validate_ir
    >>>
    >>> # Valid minimal IR
    >>> ir = {
    ...     "ir_version": "0.1.0",
    ...     "nodes": [
    ...         {"id": "n1", "type": "read-file", "params": {"file_path": "input.txt"}}
    ...     ]
    ... }
    >>> validate_ir(ir)  # No exception raised
    >>>
    >>> # IR with edges and template variables
    >>> pipeline = {
    ...     "ir_version": "0.1.0",
    ...     "nodes": [
    ...         {"id": "read", "type": "read-file", "params": {"file_path": "${input_file}"}},
    ...         {"id": "proc", "type": "transform", "params": {"format": "json"}},
    ...         {"id": "save", "type": "write-file", "params": {"file_path": "${output_file}"}}
    ...     ],
    ...     "edges": [
    ...         {"from": "read", "to": "proc"},
    ...         {"from": "proc", "to": "save"}
    ...     ]
    ... }
    >>> validate_ir(pipeline)  # Template variables are valid strings
    >>>
    >>> # Invalid IR (missing required field)
    >>> bad_ir = {"nodes": [{"id": "n1"}]}
    >>> try:
    ...     validate_ir(bad_ir)
    >>> except ValidationError as e:
    ...     print(e)  # "Validation error at root: 'ir_version' is required"

Common Validation Errors:
- Missing 'ir_version': Every IR must specify its version
- Empty nodes array: At least one node is required
- Duplicate node IDs: Each node must have a unique identifier
- Invalid edge references: All 'from' and 'to' must reference existing nodes
- Wrong types: Ensure strings for IDs, objects for params, etc.

For comprehensive examples, see the examples/ directory.
"""

import json
from typing import Any, Union

import jsonschema
from jsonschema import Draft7Validator
from jsonschema import ValidationError as JsonSchemaValidationError

from pflow.core.exceptions import SchemaValidationError as ValidationError
from pflow.core.types import CANONICAL_TYPES

# JSON Schema for batch configuration on nodes
# Enables sequential or parallel processing of multiple items through a single node
BATCH_CONFIG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Configuration for batch processing of multiple items",
    "properties": {
        "items": {
            "oneOf": [
                {
                    "type": "string",
                    "pattern": r"^\$\{.+\}$",
                    "description": "Template reference to array (e.g., '${node.files}')",
                },
                {
                    "type": "array",
                    "minItems": 1,
                    "description": "Inline array of items (can contain templates)",
                },
            ],
            "description": "Items to process: template reference OR inline array",
        },
        "as": {
            "type": "string",
            "pattern": r"^[a-zA-Z_][a-zA-Z0-9_]*$",
            "default": "item",
            "description": "Variable name for current item in templates (default: 'item')",
        },
        "error_handling": {
            "type": "string",
            "enum": ["fail_fast", "continue"],
            "default": "fail_fast",
            "description": "How to handle per-item errors: 'fail_fast' stops on first error, 'continue' processes all items",
        },
        # Phase 2: Parallel execution configuration
        "parallel": {
            "type": "boolean",
            "default": False,
            "description": "Enable concurrent execution of items (default: sequential)",
        },
        "max_concurrent": {
            "type": "integer",
            "minimum": 1,
            "maximum": 100,
            "default": 10,
            "description": "Maximum concurrent workers when parallel=true (default: 10)",
        },
        "max_retries": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "default": 1,
            "description": "Maximum retry attempts per item (default: 1, no retry)",
        },
        "retry_wait": {
            "type": "number",
            "minimum": 0,
            "default": 0,
            "description": "Seconds to wait between retries (default: 0)",
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}


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
                    "purpose": {
                        "type": "string",
                        "description": "Human-readable description of what this node does in the workflow",
                    },
                    "params": {
                        "type": "object",
                        "description": "Parameters for node behavior",
                        "additionalProperties": True,
                    },
                    "batch": BATCH_CONFIG_SCHEMA,
                    "_source_lines": {
                        "type": "object",
                        "description": "Markdown source line offsets for code block params (injected by parser)",
                        "additionalProperties": {"type": "integer"},
                    },
                    "_source_files": {
                        "type": "object",
                        "description": "Maps param names to source file paths (injected by file resolver)",
                        "additionalProperties": {"type": "string"},
                    },
                    "cache": {
                        "type": "boolean",
                        "description": "Whether to cache this node's output across runs (default: true)",
                    },
                    "prompt_cache": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Per-node LLM-provider prompt-cache subset (Task 159). List of bare cache "
                            "chunk identifiers from the workflow-level ## Cache block, in declaration order. "
                            "Independent of the `cache: bool` memoization field."
                        ),
                    },
                    "prewarm": {
                        "type": "boolean",
                        "description": (
                            "Per-node opt-in for batch prewarming (Task 159). When true on a batch LLM node, "
                            "pflow serializes the first call (cache write) before fanning out the remainder "
                            "as cache reads."
                        ),
                    },
                    "_source_line": {
                        "type": "integer",
                        "description": (
                            "1-based line number of the ``### node-id`` heading in the source .pflow.md file "
                            "(injected by parser). Used for cross-workflow boundary attribution and diagnostic "
                            "rendering. Always populated on parser-produced nodes; legacy / programmatic IRs may "
                            "omit it."
                        ),
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
        "inputs": {
            "type": "object",
            "description": "Declared workflow input parameters with their schemas",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Human-readable description"},
                    "required": {"type": "boolean", "default": True, "description": "Whether input is required"},
                    "type": {
                        "type": "string",
                        "enum": list(CANONICAL_TYPES),
                        "description": f"Data type: one of {', '.join(CANONICAL_TYPES)}",
                    },
                    "default": {"description": "Default value if not provided"},
                    "stdin": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether this input receives piped stdin data",
                    },
                },
                "additionalProperties": False,
            },
            "default": {},
        },
        "outputs": {
            "type": "object",
            "description": "Declared workflow outputs that will be written to shared store",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Human-readable description"},
                    "type": {
                        "type": "string",
                        "enum": list(CANONICAL_TYPES),
                        "description": f"Data type: one of {', '.join(CANONICAL_TYPES)}",
                    },
                    "source": {
                        "type": "string",
                        "description": "Template expression specifying where to get the output value from (e.g., '${node_id.output_key}')",
                    },
                    "stdout": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether this output streams to process stdout in text mode (only one output per workflow may set this)",
                    },
                    "_source_line": {
                        "type": "integer",
                        "description": "Markdown source line for the output source declaration (internal parser metadata)",
                    },
                },
                "additionalProperties": False,
            },
            "default": {},
        },
        "cache": {
            "type": "object",
            "description": (
                "Workflow-level prompt-cache declaration (Task 159). Carries an optional `ttl` "
                "and an ordered list of cache chunks. Per-node `prompt_cache:` lists reference "
                "subsets of these items by name; semantic validation lives in core/workflow/data_flow.py."
            ),
            "properties": {
                "ttl": {
                    "type": "string",
                    "pattern": r"^(([1-9]|[1-5][0-9]|60)m|1h)$",
                    "description": (
                        "Cache TTL: 1m through 60m, or 1h as an alias for 60m. "
                        "Omit for pflow's default 5m behavior. Provider validation "
                        "rejects unsupported minute-level TTLs."
                    ),
                },
                "items": {
                    "type": "array",
                    "description": "Cache chunks in declaration order. Each chunk is `[prose-before-${var}][${var}]`.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Chunk identifier (the ${var} content verbatim)"},
                            "var": {"type": "string", "description": "Template path inside ${...} (== name)"},
                            "prose_before": {
                                "type": "string",
                                "description": "Prose appearing before the ${var} (rendered into the cacheable system prefix)",
                            },
                            "_source_line": {
                                "type": "integer",
                                "description": "Markdown source line of the chunk (parser metadata)",
                            },
                        },
                        "required": ["name", "var", "prose_before"],
                        "additionalProperties": False,
                    },
                },
                "_source_line": {
                    "type": "integer",
                    "description": "Markdown source line of the ## Cache section header (parser metadata)",
                },
            },
            "required": ["items"],
            "additionalProperties": False,
        },
        "enable_namespacing": {
            "type": "boolean",
            "description": "Enable automatic namespacing to prevent output collisions between nodes",
            "default": True,
        },
        "template_resolution_mode": {
            "type": "string",
            "enum": ["strict", "permissive"],
            "description": (
                "Template resolution error behavior. "
                "strict: fail immediately on unresolved templates (recommended for production). "
                "permissive: warn and continue with unresolved templates (useful for debugging)."
            ),
            "default": "strict",
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
            if i > 0:
                formatted += "."
            formatted += str(component)
    return formatted or "root"


def _get_output_suggestion(error: JsonSchemaValidationError, path_str: str) -> str:
    """Get a helpful suggestion for output-specific validation errors.

    Args:
        error: The jsonschema validation error
        path_str: The formatted path string for context

    Returns:
        Suggestion string for fixing the output-related error
    """
    # Case 1: Additional properties (wrong field names like 'value', 'from')
    if error.validator == "additionalProperties":
        # Extract which field was unexpected
        unexpected_field = None
        if hasattr(error, "message"):
            import re

            match = re.search(r"'([^']+)' was unexpected", error.message)
            if match:
                unexpected_field = match.group(1)

        # Build helpful message
        lines = ["Output definitions can only have: description, type, source, stdout (all optional)"]

        # Suggest replacement for common mistakes
        if unexpected_field == "value":
            lines.append("\nDid you mean 'source' instead of 'value'?")
        elif unexpected_field == "from":
            lines.append("\nDid you mean 'source' instead of 'from'?")
        elif unexpected_field:
            lines.append(f"\nUnknown field: '{unexpected_field}'")

        # Show correct example
        lines.extend([
            "\nExample:",
            "  ### story",
            "",
            "  The generated story.",
            "",
            "  - type: string",
            "  - source: ${generate_story.response}",
        ])

        return "\n".join(lines)

    # Case 2: Wrong type (string instead of object)
    if error.validator == "type" and "object" in str(error.validator_value):
        return (
            "Each output must be a section with parameters, not a plain string.\n\n"
            "Wrong: - source: ${generate_story.response}  (as a top-level value)\n"
            "Right:\n"
            "  ### story\n\n"
            "  The generated story.\n\n"
            "  - source: ${generate_story.response}"
        )

    return ""


def _suggest_for_invalid_type(offending: Any) -> tuple[str, dict[str, Any]]:
    """Return an actionable suggestion and structured context for invalid S1 types."""
    from pflow.core.types import TypeSpec, TypeVocabularyError

    # YAML `- type: null` parses to Python None — map to the 'null' string so
    # TypeSpec.parse produces the actionable "Use 'any' if the value may be None"
    # suggestion instead of the generic fallback.
    if offending is None:
        offending = "null"

    if not isinstance(offending, str):
        text = f"Type must be one of: {', '.join(CANONICAL_TYPES)}"
        return text, {
            "available_fields": list(CANONICAL_TYPES),
            "available_fields_label": "types",
        }

    try:
        TypeSpec.parse(offending)
    except TypeVocabularyError as exc:
        context: dict[str, Any] = {
            "available_fields": exc.available_fields,
            "available_fields_label": exc.available_fields_label,
        }
        if exc.similar_names:
            context["similar_names"] = exc.similar_names
        if exc.suggestions_list:
            context["suggestions_list"] = exc.suggestions_list
        return str(exc), context

    return (
        f"Type must be one of: {', '.join(CANONICAL_TYPES)}",
        {
            "available_fields": list(CANONICAL_TYPES),
            "available_fields_label": "types",
        },
    )


def _get_suggestion(error: JsonSchemaValidationError) -> tuple[str, dict[str, Any]]:
    """Get a helpful suggestion based on the validation error.

    Args:
        error: The jsonschema validation error

    Returns:
        Tuple of suggestion string and structured context kwargs
    """
    path_list = list(error.absolute_path)
    path_str = str(error.absolute_path)

    # Type-vocabulary errors: any failure at `inputs.<name>.type` or `outputs.<name>.type`
    # — covers invalid strings (validator='enum', e.g. 'str') AND non-string values
    # (validator='type', e.g. `- type: null` which YAML parses to Python None).
    # List-based path check avoids matching `nodes[N].type` via substring.
    is_type_vocab_path = len(path_list) >= 3 and path_list[0] in ("inputs", "outputs") and path_list[-1] == "type"
    if is_type_vocab_path:
        return _suggest_for_invalid_type(error.instance)

    # OUTPUT-SPECIFIC ERROR HANDLING (non-type fields: additionalProperties, shape)
    if "outputs" in path_str:
        return _get_output_suggestion(error, path_str), {}

    # GENERAL ERROR HANDLING (existing cases)
    if error.validator == "required":
        # Extract field name from message like "'field_name' is a required property"
        match = error.message.split("'")
        if len(match) >= 2:
            field_name = match[1]
            return f"Add the required field '{field_name}'", {}
        return "Add the missing required field", {}
    elif error.validator == "type":
        expected = error.validator_value
        actual = type(error.instance).__name__
        return f"Change type from '{actual}' to '{expected}'", {}
    elif error.validator == "pattern":
        if "ir_version" in path_str:
            return "Use semantic versioning format, e.g., '0.1.0'", {}
    elif error.validator == "additionalProperties":
        return "Remove unknown properties or check field names", {}
    elif error.validator == "minItems":
        return "Add at least one node to the workflow", {}

    return "", {}


def validate_ir(data: Union[dict[str, Any], str]) -> None:
    """Validate workflow IR against the schema.

    This function performs both structural validation (via JSON Schema) and
    business logic validation (node references, duplicate IDs). It accepts
    either a dictionary or a JSON string.

    Args:
        data: The IR data to validate (dict or JSON string)

    Raises:
        ValidationError: If the IR is invalid with details about the error
        ValueError: If JSON parsing fails

    Examples:
        >>> # Valid IR passes silently
        >>> validate_ir({"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test"}]})

        >>> # Missing required field
        >>> try:
        ...     validate_ir({"nodes": []})
        ... except ValidationError as e:
        ...     print(e.path)    # "root"
        ...     print(e.message) # "'ir_version' is a required property"

        >>> # Invalid node reference
        >>> try:
        ...     validate_ir({
        ...         "ir_version": "0.1.0",
        ...         "nodes": [{"id": "n1", "type": "test"}],
        ...         "edges": [{"from": "n1", "to": "n2"}]
        ...     })
        ... except ValidationError as e:
        ...     print(e.path)    # "edges[0].to"
        ...     print("n2" in e.message)  # True

        >>> # JSON string input
        >>> validate_ir('{"ir_version": "0.1.0", "nodes": [{"id": "n1", "type": "test"}]}')
    """
    # Parse JSON string if needed
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid workflow data: {e}") from e

    # Create validator
    validator = Draft7Validator(FLOW_IR_SCHEMA)

    # Check if schema is valid first (development safety)
    try:
        validator.check_schema(FLOW_IR_SCHEMA)
    except jsonschema.SchemaError as e:
        raise RuntimeError(f"Schema definition error: {e}") from e

    # Validate the data
    errors = list(validator.iter_errors(data))
    if not errors:
        # Additional custom validations
        if isinstance(data, dict):
            _validate_node_references(data)
            _validate_duplicate_node_ids(data)
        return

    # Format the first error with helpful message
    error = errors[0]
    path = _format_path(list(error.absolute_path))
    suggestion, context_kwargs = _get_suggestion(error)

    raise ValidationError(
        message=error.message,
        path=path,
        suggestion=suggestion,
        **context_kwargs,
    )


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


def normalize_ir(workflow_ir: dict[str, Any]) -> dict[str, Any]:
    """Normalize workflow IR by adding missing boilerplate fields.

    This function adds required fields that are often omitted by agent-generated
    workflows to reduce friction. It modifies the workflow IR in-place and
    returns it for convenience.

    Fields added:
    - ir_version: "0.1.0" if missing
    - edges: [] if missing (and no 'flow' field present)
    - Normalizes node "parameters" to "params" (backward compatibility)

    Args:
        workflow_ir: Workflow IR dictionary (modified in-place)

    Returns:
        The same workflow_ir dict (for chaining convenience).

    Example:
        >>> ir = {"nodes": [{"id": "n1", "type": "test"}]}
        >>> result = normalize_ir(ir)
        >>> result["ir_version"]
        '0.1.0'
        >>> result["edges"]
        []
        >>> result is ir
        True
    """
    if "ir_version" not in workflow_ir:
        workflow_ir["ir_version"] = "0.1.0"
    if "edges" not in workflow_ir and "flow" not in workflow_ir:
        workflow_ir["edges"] = []

    # Normalize node parameters: "parameters" → "params"
    # This provides backward compatibility and reduces friction for agents
    if "nodes" in workflow_ir and isinstance(workflow_ir["nodes"], list):
        for node in workflow_ir["nodes"]:
            if "parameters" in node and "params" not in node:
                node["params"] = node.pop("parameters")

    return workflow_ir
