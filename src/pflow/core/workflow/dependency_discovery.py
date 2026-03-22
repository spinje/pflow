"""Dependency discovery for workflow bundling.

Scans workflow IR to find all file dependencies (sub-workflows,
prompts, scripts, batch configs) that must be co-located with
the workflow for it to work as a self-contained bundle.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from pflow.core.file_resolver import FILE_RESOLVABLE_PARAMS, is_file_reference, is_workflow_file_reference
from pflow.core.markdown_parser import parse_markdown

logger = logging.getLogger(__name__)


@dataclass
class Dependency:
    """A file dependency discovered in a workflow."""

    relative_path: str  # Path as written in the workflow (e.g., "./prompts/foo.md")
    absolute_path: Path  # Resolved absolute path on disk
    source_node_id: str  # Node that references this file
    source_param: str  # Param name (e.g., "prompt", "workflow", "batch")
    dep_type: str  # "file_ref" or "sub_workflow"


def discover_dependencies(
    ir_dict: dict[str, Any],
    base_dir: Path,
    seen: Optional[set[str]] = None,
) -> list[Dependency]:
    """Recursively discover all file dependencies of a workflow.

    Scans the IR for four types of file references:
    1. Sub-workflow file references (- workflow: ./sub.pflow.md)
    2. File references in node params (- prompt: ./prompts/foo.md)
    3. Batch config files (- batch: ./reviews.yaml)
    4. File references inside batch items

    Sub-workflows referenced by name (not file path) are NOT included —
    they are shared dependencies that should be saved independently.

    Args:
        ir_dict: Workflow IR dict (raw, before file resolution)
        base_dir: Directory to resolve relative paths from
        seen: Set of resolved absolute path strings for cycle detection

    Returns:
        Flat list of all discovered dependencies (including recursive ones)

    Raises:
        FileNotFoundError: If a referenced file doesn't exist
        ValueError: If a circular dependency is detected
    """
    if seen is None:
        seen = set()

    deps: list[Dependency] = []

    for node in ir_dict.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id", "unknown")
        params = node.get("params", {})
        if not isinstance(params, dict):
            continue

        _collect_sub_workflow_deps(params, base_dir, node_id, seen, deps)
        _collect_param_deps(params, base_dir, node_id, deps)
        _collect_batch_deps(node, base_dir, node_id, deps)

    return deps


def _collect_sub_workflow_deps(
    params: dict[str, Any],
    base_dir: Path,
    node_id: str,
    seen: set[str],
    deps: list[Dependency],
) -> None:
    """Detect and recurse into sub-workflow file references."""
    workflow_ref = params.get("workflow")
    if not isinstance(workflow_ref, str) or not is_workflow_file_reference(workflow_ref):
        return

    resolved = (base_dir / workflow_ref).resolve()
    resolved_str = str(resolved)

    if resolved_str in seen:
        logger.warning(f"Skipping circular dependency: {workflow_ref} (node '{node_id}')")
        return

    _require_file_exists(resolved, workflow_ref, node_id, "workflow", base_dir)
    seen.add(resolved_str)
    deps.append(
        Dependency(
            relative_path=workflow_ref,
            absolute_path=resolved,
            source_node_id=node_id,
            source_param="workflow",
            dep_type="sub_workflow",
        )
    )
    # Recurse into sub-workflow to find its dependencies
    try:
        child_content = resolved.read_text(encoding="utf-8")
        child_result = parse_markdown(child_content)
        child_deps = discover_dependencies(child_result.ir, resolved.parent, seen)
        deps.extend(child_deps)
    except Exception as e:
        if isinstance(e, (FileNotFoundError, ValueError)):
            raise
        logger.warning(f"Failed to parse sub-workflow {workflow_ref}: {e}")


def _collect_param_deps(
    params: dict[str, Any],
    base_dir: Path,
    node_id: str,
    deps: list[Dependency],
) -> None:
    """Collect file references from node params."""
    for key, value in params.items():
        if key == "workflow":  # Handled by _collect_sub_workflow_deps
            continue
        if key not in FILE_RESOLVABLE_PARAMS:
            continue
        if not is_file_reference(value):
            continue
        resolved = (base_dir / value).resolve()
        _require_file_exists(resolved, value, node_id, key, base_dir)
        deps.append(
            Dependency(
                relative_path=value,
                absolute_path=resolved,
                source_node_id=node_id,
                source_param=key,
                dep_type="file_ref",
            )
        )


def _collect_batch_deps(
    node: dict[str, Any],
    base_dir: Path,
    node_id: str,
    deps: list[Dependency],
) -> None:
    """Collect file references from batch config (file or inline items)."""
    batch = node.get("batch")

    # Batch is a string file reference (entire config in external file)
    if isinstance(batch, str) and is_file_reference(batch):
        resolved = (base_dir / batch).resolve()
        _require_file_exists(resolved, batch, node_id, "batch", base_dir)
        deps.append(
            Dependency(
                relative_path=batch,
                absolute_path=resolved,
                source_node_id=node_id,
                source_param="batch",
                dep_type="file_ref",
            )
        )
        # Parse batch YAML to find file refs in items
        try:
            batch_content = resolved.read_text(encoding="utf-8")
            batch_data = yaml.safe_load(batch_content)
            if isinstance(batch_data, dict):
                _collect_batch_item_deps(batch_data, base_dir, node_id, base_dir, deps)
        except yaml.YAMLError:
            logger.warning(f"Failed to parse batch YAML {batch} in node '{node_id}'")
        return

    # Batch is a dict with inline items
    if isinstance(batch, dict):
        _collect_batch_item_deps(batch, base_dir, node_id, base_dir, deps)


def _collect_batch_item_deps(
    batch_data: dict[str, Any],
    workflow_base_dir: Path,
    node_id: str,
    file_base_dir: Path,
    deps: list[Dependency],
) -> None:
    """Scan batch items for file references."""
    items = batch_data.get("items")
    if not isinstance(items, list):
        return
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if key not in FILE_RESOLVABLE_PARAMS:
                continue
            if not is_file_reference(value):
                continue
            resolved = (file_base_dir / value).resolve()
            _require_file_exists(resolved, value, node_id, f"batch.items[{i}].{key}", workflow_base_dir)
            deps.append(
                Dependency(
                    relative_path=value,
                    absolute_path=resolved,
                    source_node_id=node_id,
                    source_param=f"batch.items[{i}].{key}",
                    dep_type="file_ref",
                )
            )


def _require_file_exists(resolved: Path, original_ref: str, node_id: str, param_name: str, base_dir: Path) -> None:
    """Raise FileNotFoundError if the resolved file doesn't exist."""
    if not resolved.is_file():
        raise FileNotFoundError(
            f"File reference in node '{node_id}', param '{param_name}' not found: {original_ref}\n"
            f"  Resolved to: {resolved}\n"
            f"  Relative to: {base_dir}"
        )
