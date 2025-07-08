"""
Metadata extractor for pflow nodes.

This module provides functionality to extract structured metadata from node
docstrings at runtime. It validates node classes and parses their documentation
to extract interface information.
"""

import inspect
import logging
import re
from typing import Any

import pocketflow

# Set up module logger
logger = logging.getLogger(__name__)


class PflowMetadataExtractor:
    """Extract metadata from pflow node classes."""

    # Regex patterns for Interface parsing
    INTERFACE_PATTERN = r"Interface:\s*\n((?:[ \t]*-[^\n]+(?:\n(?![ \t]*-)[ \t]+[^\n]+)*\n?)*)"
    INTERFACE_ITEM_PATTERN = r"-\s*(\w+):\s*([^\n]*(?:\n(?![ \t]*-)[ \t]+[^\n]+)*)"
    SHARED_KEY_PATTERN = r'shared\["([^"]+)"\]'
    ACTIONS_PATTERN = r"(\w+)(?:\s*\([^)]+\))?"

    def extract_metadata(self, node_class: type) -> dict[str, Any]:
        """
        Extract metadata from a node class.

        Args:
            node_class: A class that should inherit from pocketflow.BaseNode

        Returns:
            Dictionary containing:
                - description: First line of docstring or 'No description'
                - inputs: List of input keys (empty for subtask 7.1)
                - outputs: List of output keys (empty for subtask 7.1)
                - params: List of parameter names (empty for subtask 7.1)
                - actions: List of action names (empty for subtask 7.1)

        Raises:
            ValueError: If node_class is not a valid node class
        """
        logger.debug(
            "Starting metadata extraction",
            extra={
                "phase": "init",
                "node_class": node_class.__name__ if hasattr(node_class, "__name__") else str(node_class),
            },
        )

        # Phase 1: Validate input type
        if not inspect.isclass(node_class):
            logger.error(
                "Invalid node class type", extra={"phase": "validation", "class_type": type(node_class).__name__}
            )
            raise ValueError(f"metadata_extractor: Expected a class, got {type(node_class).__name__}")

        # Phase 2: Validate node inheritance
        try:
            if not issubclass(node_class, pocketflow.BaseNode):
                logger.error(
                    "Class does not inherit from BaseNode",
                    extra={"phase": "validation", "class_name": node_class.__name__},
                )
                raise ValueError(  # noqa: TRY004
                    f"metadata_extractor: Class {node_class.__name__} does not inherit from pocketflow.BaseNode"
                )
        except TypeError as e:
            # issubclass can raise TypeError for non-class arguments
            logger.exception("Invalid class type for issubclass", extra={"phase": "validation", "error": str(e)})
            raise ValueError(f"metadata_extractor: Invalid class type for {node_class}") from e

        logger.debug("Node class validated", extra={"phase": "validation", "class_name": node_class.__name__})

        # Phase 3: Extract description
        docstring = inspect.getdoc(node_class)
        logger.debug(
            "Docstring extracted",
            extra={
                "phase": "docstring_parsing",
                "has_docstring": bool(docstring),
                "docstring_length": len(docstring) if docstring else 0,
            },
        )

        description = self._extract_description(docstring)

        # Phase 4: Parse Interface section
        interface_data = self._parse_interface_section(docstring)

        logger.debug(
            "Interface data extracted",
            extra={
                "phase": "interface_extraction",
                "sections_found": list(interface_data.keys()),
                "input_count": len(interface_data.get("inputs", [])),
                "output_count": len(interface_data.get("outputs", [])),
                "param_count": len(interface_data.get("params", [])),
                "action_count": len(interface_data.get("actions", [])),
            },
        )

        # Return complete metadata structure
        result = {
            "description": description,
            "inputs": interface_data.get("inputs", []),
            "outputs": interface_data.get("outputs", []),
            "params": interface_data.get("params", []),
            "actions": interface_data.get("actions", []),
        }

        logger.info(
            "Metadata extraction complete",
            extra={"phase": "complete", "node_class": node_class.__name__, "metadata_keys": list(result.keys())},
        )

        return result

    def _extract_description(self, docstring: str | None) -> str:
        """
        Extract the first line of the docstring as description.

        Args:
            docstring: The raw docstring or None

        Returns:
            First non-empty line of docstring or 'No description'
        """
        if not docstring:
            return "No description"

        # Split into lines and find first non-empty line
        lines = docstring.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line:
                return line

        return "No description"

    def _parse_interface_section(self, docstring: str | None) -> dict[str, list[str]]:
        """
        Parse the Interface section of a docstring.

        Args:
            docstring: The raw docstring or None

        Returns:
            Dictionary with inputs, outputs, params, and actions lists
        """
        if not docstring:
            logger.debug("No docstring provided for Interface parsing", extra={"phase": "interface_extraction"})
            return {"inputs": [], "outputs": [], "params": [], "actions": []}

        # Extract the Interface section
        interface_match = re.search(self.INTERFACE_PATTERN, docstring)
        if not interface_match:
            logger.debug("No Interface section found", extra={"phase": "interface_extraction"})
            return {"inputs": [], "outputs": [], "params": [], "actions": []}

        interface_content = interface_match.group(1)

        # Parse each component
        result: dict[str, list[str]] = {"inputs": [], "outputs": [], "params": [], "actions": []}

        # Find all items in the Interface section
        for match in re.finditer(self.INTERFACE_ITEM_PATTERN, interface_content):
            item_type = match.group(1).lower()
            item_content = match.group(2)

            if item_type == "reads":
                result["inputs"] = self._extract_shared_keys(item_content)
            elif item_type == "writes":
                result["outputs"] = self._extract_shared_keys(item_content)
            elif item_type == "params":
                result["params"] = self._extract_params(item_content)
            elif item_type == "actions":
                result["actions"] = self._extract_actions(item_content)

        return result

    def _extract_shared_keys(self, content: str) -> list[str]:
        """
        Extract shared store keys from a Reads or Writes line.

        Args:
            content: The content after "Reads:" or "Writes:"

        Returns:
            List of key names found in shared["key"] patterns
        """
        keys = re.findall(self.SHARED_KEY_PATTERN, content)
        return keys

    def _extract_params(self, content: str) -> list[str]:
        """
        Extract parameter names from a Params line.

        Args:
            content: The content after "Params:"

        Returns:
            List of parameter names
        """
        # Remove the "as fallbacks" note if present
        content = re.sub(r"\s*\(as fallbacks[^)]*\)", "", content)

        # Split by comma and clean up
        params = []
        for param in content.split(","):
            param = param.strip()
            if param:
                # Extract just the parameter name (before any parentheses)
                # This handles cases like "param_name (default: value)"
                match = re.match(r"(\w+)", param)
                if match:
                    params.append(match.group(1))

        return params

    def _extract_actions(self, content: str) -> list[str]:
        """
        Extract action names from an Actions line.

        Args:
            content: The content after "Actions:"

        Returns:
            List of action names (without descriptions)
        """
        actions = []
        # Split by comma first to handle multiple actions
        for part in content.split(","):
            part = part.strip()
            if part:
                # Extract just the action name (before any parentheses)
                match = re.match(self.ACTIONS_PATTERN, part)
                if match:
                    action_name = match.group(1)
                    if action_name:
                        actions.append(action_name)

        return actions
