"""External file reference resolution for workflow IR.

Detects file path references in node parameters, reads the files,
and substitutes their content into the IR before compilation.
This enables prompts, code, batch configs, etc. to live in
external files while being validated identically to inline content.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Extensions that trigger file reference detection
FILE_REFERENCE_EXTENSIONS = frozenset({
    ".md",
    ".txt",
    ".py",
    ".sh",
    ".yaml",
    ".yml",
    ".json",
})

# Params where file content is YAML-parsed, not raw text.
# Matches the is_yaml_config distinction in markdown_parser.py:489-501
YAML_PARSED_PARAMS = frozenset({"batch", "output_schema", "headers"})

# Only these params can be resolved as file references.
# These are the params that correspond to code block tags in the markdown parser
# (see markdown_parser.py _CODE_BLOCK_TAG_TO_PARAM). Other params like 'file_path',
# 'workflow', 'url', etc. contain path/URL VALUES, not content to inline.
# Note: "batch" is handled separately in _resolve_batch_file_references(), not here.
FILE_RESOLVABLE_PARAMS = frozenset({
    "command",
    "code",
    "prompt",
    "source",
    "stdin",
    "headers",
    "output_schema",
})


def is_file_reference(value: Any) -> bool:
    """Detect whether a parameter value is a file path reference.

    A value is treated as a file reference if it:
    - Is a non-empty string without newlines, spaces, or template variables
    - Starts with './' or '../' (always matches regardless of extension), OR
    - Contains '/' and ends with a recognized file extension

    Args:
        value: The parameter value to check

    Returns:
        True if the value looks like a file path reference
    """
    if not isinstance(value, str) or not value:
        return False

    # Template variables are never file references
    if "${" in value:
        return False

    # Multi-line strings are never file paths
    if "\n" in value:
        return False

    # Strings with spaces are commands or prose, not file paths
    if " " in value:
        return False

    # URLs are never file references
    if "://" in value:
        return False

    # Explicit relative paths
    if value.startswith("./") or value.startswith("../"):
        return True

    # Path with recognized extension
    if "/" in value:
        suffix = Path(value).suffix.lower()
        if suffix in FILE_REFERENCE_EXTENSIONS:
            return True

    return False


def resolve_file_references(ir_dict: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """Resolve file references in workflow IR, modifying it in place.

    Walks all node params and batch items. When a value matches the
    file reference heuristic and the file exists, reads the file and
    substitutes its content. For YAML params (batch, output_schema,
    headers), the file content is parsed with yaml.safe_load().

    Args:
        ir_dict: The workflow IR dict (modified in place)
        base_dir: Directory to resolve relative paths from
                  (typically the workflow file's parent directory)

    Returns:
        The same ir_dict (for chaining convenience)

    Raises:
        FileNotFoundError: If a detected file reference doesn't exist
        yaml.YAMLError: If a YAML file fails to parse
    """
    for node in ir_dict.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "unknown")

        # A. Resolve file references in node params
        params = node.get("params", {})
        if not isinstance(params, dict):
            continue
        for key, value in list(params.items()):
            if key not in FILE_RESOLVABLE_PARAMS:
                continue
            if is_file_reference(value):
                content = _read_file(value, base_dir, node_id, key)
                if key in YAML_PARSED_PARAMS:
                    params[key] = yaml.safe_load(content)
                else:
                    params[key] = content
                node.setdefault("_source_files", {})[key] = value
                logger.debug(f"Resolved file reference: node '{node_id}', param '{key}' <- {value}")

        # B. Resolve file references in batch config
        batch = node.get("batch")
        if batch is not None:
            _resolve_batch_file_references(node, batch, base_dir, node_id)

    return ir_dict


def _resolve_batch_file_references(
    node: dict[str, Any],
    batch: Any,
    base_dir: Path,
    node_id: str,
) -> None:
    """Resolve file references in batch config.

    Handles two cases:
    - Batch is a string file reference (entire config in external file)
    - Batch is a dict with inline items containing file references
    """
    # B1. Batch is a string — entire config in external file
    if isinstance(batch, str) and is_file_reference(batch):
        original_value = batch
        content = _read_file(batch, base_dir, node_id, "batch")
        node["batch"] = yaml.safe_load(content)
        node.setdefault("_source_files", {})["batch"] = original_value
        logger.debug(f"Resolved file reference: node '{node_id}', batch <- {original_value}")
        batch = node["batch"]  # Update local var for B2 fall-through

    # B2. Batch is a dict with inline items — check for file refs in items
    if isinstance(batch, dict):
        items = batch.get("items")
        if isinstance(items, list):
            for i, item in enumerate(items):
                if isinstance(item, dict):
                    for key, value in list(item.items()):
                        if key not in FILE_RESOLVABLE_PARAMS:
                            continue
                        if is_file_reference(value):
                            content = _read_file(value, base_dir, node_id, f"batch.items[{i}].{key}")
                            if key in YAML_PARSED_PARAMS:
                                item[key] = yaml.safe_load(content)
                            else:
                                item[key] = content
                            provenance_key = f"batch.items[{i}].{key}"
                            node.setdefault("_source_files", {})[provenance_key] = value
                            logger.debug(f"Resolved file reference: node '{node_id}', {provenance_key} <- {value}")


def _read_file(
    file_ref: str,
    base_dir: Path,
    node_id: str,
    param_name: str,
) -> str:
    """Read a file reference, resolving relative to base_dir.

    Args:
        file_ref: The relative file path from the workflow
        base_dir: Directory to resolve relative paths from
        node_id: Node ID for error messages
        param_name: Parameter name for error messages

    Returns:
        File content as string

    Raises:
        FileNotFoundError: If file doesn't exist
    """
    resolved_path = (base_dir / file_ref).resolve()

    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"File reference in node '{node_id}', param '{param_name}' not found: {file_ref}\n"
            f"  Resolved to: {resolved_path}\n"
            f"  Relative to: {base_dir}"
        )

    return resolved_path.read_text(encoding="utf-8")


def has_file_references(ir_dict: dict[str, Any]) -> list[str]:
    """Scan IR for file references without resolving them.

    Returns a list of file reference strings found (empty if none).
    Useful for detecting file references in inline workflows where
    there's no file path context for resolution.
    """
    found: list[str] = []
    for node in ir_dict.get("nodes", []):
        if not isinstance(node, dict):
            continue
        _collect_param_file_refs(node.get("params", {}), found)
        _collect_batch_file_refs(node.get("batch"), found)
    return found


def _collect_param_file_refs(params: Any, found: list[str]) -> None:
    """Collect file references from node params."""
    if not isinstance(params, dict):
        return
    for key, value in params.items():
        if key in FILE_RESOLVABLE_PARAMS and is_file_reference(value):
            found.append(value)


def _collect_batch_file_refs(batch: Any, found: list[str]) -> None:
    """Collect file references from batch config."""
    if isinstance(batch, str) and is_file_reference(batch):
        found.append(batch)
    if isinstance(batch, dict):
        items = batch.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    _collect_param_file_refs(item, found)


def get_base_dir(initial_params: dict[str, Any]) -> Path:
    """Derive base directory for file resolution from initial params.

    Uses _pflow_workflow_file if available, otherwise falls back to CWD.

    Args:
        initial_params: The initial params dict (may contain _pflow_workflow_file)

    Returns:
        Path to use as base directory for resolving relative file references
    """
    workflow_file = initial_params.get("_pflow_workflow_file")
    if workflow_file:
        return Path(workflow_file).parent
    return Path.cwd()
