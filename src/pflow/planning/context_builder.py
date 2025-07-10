"""Context builder for LLM-based workflow planning.

This module transforms node registry metadata into LLM-optimized markdown
documentation that enables natural language workflow composition.
"""

import importlib
import logging
from typing import Any

from pflow.registry.metadata_extractor import PflowMetadataExtractor

logger = logging.getLogger(__name__)


def build_context(registry_metadata: dict[str, dict[str, Any]]) -> str:
    """Build LLM-friendly context from registry metadata.

    Args:
        registry_metadata: Dict mapping node types to metadata dicts
                          (as returned by Registry.load())

    Returns:
        Formatted markdown string describing available nodes
    """
    # Phase 1: Node collection and filtering
    extractor = PflowMetadataExtractor()
    processed_nodes = {}
    skipped_count = 0

    for node_type, node_info in registry_metadata.items():
        # Skip test nodes
        file_path = node_info.get("file_path", "")
        if "test" in file_path.lower():
            logger.debug(f"context: Skipping test node: {node_type}")
            skipped_count += 1
            continue

        # Phase 2: Import and metadata extraction
        try:
            # Import the node class using module path and class name
            module_path = node_info.get("module")
            class_name = node_info.get("class_name")

            if not module_path or not class_name:
                logger.warning(f"context: Missing module or class_name for node '{node_type}'")
                skipped_count += 1
                continue

            module = importlib.import_module(module_path)
            node_class = getattr(module, class_name)

            # Extract metadata
            metadata = extractor.extract_metadata(node_class)

            # Store successful extraction
            processed_nodes[node_type] = {
                "description": metadata.get("description", "No description"),
                "inputs": metadata.get("inputs", []),
                "outputs": metadata.get("outputs", []),
                "params": metadata.get("params", []),
                "actions": metadata.get("actions", []),
                "registry_info": node_info,
            }

        except Exception as e:
            logger.warning(f"context: Failed to process node '{node_type}': {e}")
            skipped_count += 1
            continue

    # Phase 3: Group by category
    categories = _group_nodes_by_category(processed_nodes)

    # Phase 4: Format as markdown
    markdown_sections = []

    for category, nodes in sorted(categories.items()):
        markdown_sections.append(f"## {category}\n")

        for node_type in sorted(nodes):
            node_data = processed_nodes[node_type]
            section = _format_node_section(node_type, node_data)
            markdown_sections.append(section)

    # Log summary
    total_nodes = len(registry_metadata)
    processed_count = len(processed_nodes)
    logger.info(f"context: Processed {processed_count}/{total_nodes} nodes ({skipped_count} skipped)")

    output = "\n".join(markdown_sections)
    output_size = len(output)
    if output_size > 10000:  # 10KB warning threshold
        logger.warning(f"context: Large output size: {output_size} bytes")

    return output


def _group_nodes_by_category(nodes: dict[str, dict]) -> dict[str, list[str]]:
    """Group nodes by category based on simple pattern matching."""
    categories: dict[str, list[str]] = {}

    for node_type in nodes:
        # Simple pattern matching for categories
        if "file" in node_type or "read" in node_type or "write" in node_type:
            category = "File Operations"
        elif "llm" in node_type or "ai" in node_type:
            category = "AI/LLM Operations"
        elif "git" in node_type or "github" in node_type or "gitlab" in node_type:
            category = "Git Operations"
        elif "http" in node_type or "api" in node_type:
            category = "HTTP/API Operations"
        else:
            category = "General Operations"

        if category not in categories:
            categories[category] = []
        categories[category].append(node_type)

    return categories


def _format_node_section(node_type: str, node_data: dict) -> str:
    """Format a single node's information as markdown."""
    lines = [f"### {node_type}"]
    lines.append(node_data["description"])
    lines.append("")

    # Format inputs
    inputs = node_data["inputs"]
    if inputs:
        formatted_inputs = []
        for inp in inputs:
            # Check if optional (this would need to be enhanced based on actual metadata)
            formatted_inputs.append(f"`{inp}`")
        lines.append(f"**Inputs**: {', '.join(formatted_inputs)}")
    else:
        lines.append("**Inputs**: none")

    # Format outputs with actions
    outputs = node_data["outputs"]
    actions = node_data["actions"]
    if outputs:
        formatted_outputs = []
        for i, out in enumerate(outputs):
            # Map outputs to actions if possible
            if i < len(actions) and actions[i] != "default":
                formatted_outputs.append(f"`{out}` ({actions[i]})")
            else:
                formatted_outputs.append(f"`{out}`")
        lines.append(f"**Outputs**: {', '.join(formatted_outputs)}")
    else:
        lines.append("**Outputs**: none")

    # Format exclusive parameters (params not in inputs)
    params = node_data["params"]
    inputs_set = set(inputs)
    exclusive_params = [p for p in params if p not in inputs_set]

    if exclusive_params:
        formatted_params = [f"`{p}`" for p in exclusive_params]
        lines.append(f"**Parameters**: {', '.join(formatted_params)}")
    else:
        lines.append("**Parameters**: none")

    lines.append("")  # Empty line between nodes
    return "\n".join(lines)
