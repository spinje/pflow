"""
Metadata extractor for pflow nodes.

This module provides functionality to extract structured metadata from node
docstrings at runtime. It validates node classes and parses their documentation
to extract interface information.
"""

import inspect
import logging
import re
from typing import Any, cast

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

        # Transform to consistent rich format
        result = {
            "description": description,
            "inputs": self._normalize_to_rich_format(interface_data.get("inputs", [])),
            "outputs": self._normalize_to_rich_format(interface_data.get("outputs", [])),
            "params": self._normalize_to_rich_format(interface_data.get("params", [])),
            "actions": interface_data.get("actions", []),  # Actions remain as simple list
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

    def _process_interface_item(
        self, item_type: str, item_content: str, result: dict[str, list[str] | list[dict[str, Any]]]
    ) -> None:
        """
        Process a single interface item (reads/writes/params).

        Args:
            item_type: The type of item ("reads", "writes", or "params")
            item_content: The content after the item type
            result: The result dictionary to update
        """
        # Map item types to result keys
        type_map = {"reads": "inputs", "writes": "outputs", "params": "params"}

        result_key = type_map[item_type]
        new_items = self._extract_interface_component(item_content, result_key)

        if isinstance(result[result_key], list) and isinstance(new_items, list):
            if all(isinstance(item, dict) for item in new_items):
                # Enhanced format - extend the list
                # Use cast to help mypy understand the types
                cast(list[dict[str, Any]], result[result_key]).extend(cast(list[dict[str, Any]], new_items))
            else:
                # Simple format strings - extend the list
                # Use cast to help mypy understand the types
                cast(list[str], result[result_key]).extend(cast(list[str], new_items))
        else:
            result[result_key] = new_items

    def _parse_interface_section(self, docstring: str | None) -> dict[str, list[str] | list[dict[str, Any]]]:
        """
        Parse the Interface section of a docstring.

        Args:
            docstring: The raw docstring or None

        Returns:
            Dictionary with inputs, outputs, params, and actions lists.
            For enhanced format, inputs/outputs/params contain dicts with key, type, description.
            For simple format, they contain strings (backward compatible).
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
        result: dict[str, list[str] | list[dict[str, Any]]] = {"inputs": [], "outputs": [], "params": [], "actions": []}

        # Find all items in the Interface section
        for match in re.finditer(self.INTERFACE_ITEM_PATTERN, interface_content):
            item_type = match.group(1).lower()
            item_content = match.group(2)

            if item_type in ["reads", "writes", "params"]:
                self._process_interface_item(item_type, item_content, result)
            elif item_type == "actions":
                result["actions"] = self._extract_actions(item_content)

        # Now handle structure parsing for enhanced format
        # Parse the interface content line by line for structures
        if any(
            isinstance(item, dict) and item.get("_has_structure")
            for component in [result["inputs"], result["outputs"]]
            for item in component
        ):
            lines = interface_content.split("\n")
            self._parse_all_structures(lines, result)

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

    def _detect_interface_format(self, content: str, component_type: str) -> bool:
        """
        Detect if the content uses enhanced format with type annotations.

        Args:
            content: The content after "Reads:", "Writes:", or "Params:"
            component_type: Type of component ("inputs", "outputs", or "params")

        Returns:
            True if enhanced format detected, False for simple format
        """
        if component_type in ("inputs", "outputs"):
            # Check for colon after shared["key"]
            # Pattern: shared["key"]: type
            if re.search(r'shared\["[^"]+"\]\s*:', content):
                logger.debug(
                    "Enhanced format detected for shared keys",
                    extra={"phase": "format_detection", "component": component_type},
                )
                return True
        elif component_type == "params":
            # Check for colon after param name BUT NOT within parentheses
            # Pattern: param_name: type (not "default: 10" within parens)
            # First remove parenthetical content to avoid false positives
            content_no_parens = re.sub(r"\([^)]+\)", "", content)
            if re.search(r"\b\w+\s*:\s*\w+", content_no_parens):
                logger.debug(
                    "Enhanced format detected for params",
                    extra={"phase": "format_detection", "component": component_type},
                )
                return True

        logger.debug("Simple format detected", extra={"phase": "format_detection", "component": component_type})
        return False

    def _extract_interface_component(self, content: str, component_type: str) -> list[dict[str, Any]] | list[str]:
        """
        Extract interface component with format detection.

        Args:
            content: The content after component declaration
            component_type: Type of component ("inputs", "outputs", or "params")

        Returns:
            List of dicts for enhanced format or list of strings for simple format
        """
        # Detect format
        is_enhanced = self._detect_interface_format(content, component_type)

        if not is_enhanced:
            # Use existing extractors for backward compatibility
            if component_type in ("inputs", "outputs"):
                return self._extract_shared_keys(content)
            else:  # params
                return self._extract_params(content)

        # Enhanced format parsing
        if component_type in ("inputs", "outputs"):
            return self._extract_enhanced_shared_keys(content)
        else:  # params
            return self._extract_enhanced_params(content)

    def _extract_enhanced_shared_keys(self, content: str) -> list[dict[str, Any]]:
        """
        Extract shared store keys with type annotations and descriptions.

        Args:
            content: The content after "Reads:" or "Writes:" in enhanced format

        Returns:
            List of dicts with key, type, description, and optional structure
        """
        results = []

        # First check if there's a shared comment at the end of the line
        shared_comment = ""
        comment_match = re.search(r"#\s*([^\n]+)$", content)
        if comment_match:
            # Check if this is a shared comment (comes after multiple items)
            # by seeing if there are commas before the comment
            before_comment = content[: comment_match.start()].strip()
            if "," in before_comment:
                shared_comment = comment_match.group(1).strip()
                # Remove the shared comment for easier parsing
                content = before_comment

        # Split by comma only when followed by shared["..."] pattern
        # This preserves commas inside descriptions
        segments = re.split(r",\s*(?=shared\[)", content)
        segments = [seg.strip() for seg in segments if seg.strip()]

        for _i, segment in enumerate(segments):
            if not segment:
                continue

            # Pattern for item with optional individual comment: shared["key"]: type  # description
            item_pattern = r'shared\["([^"]+)"\]\s*:\s*([^\s#]+)(?:\s*#\s*(.*))?'
            match = re.match(item_pattern, segment)

            if match:
                key = match.group(1)
                type_str = match.group(2).strip()
                # Individual comment if present, otherwise use shared comment
                individual_comment = match.group(3).strip() if match.group(3) else ""
                description = individual_comment if individual_comment else shared_comment

                result = {"key": key, "type": type_str, "description": description}

                # Check if this is a complex type that might have structure
                if type_str in ("dict", "list", "list[dict]"):
                    # Mark that structure follows, will be parsed separately
                    result["_has_structure"] = True

                results.append(result)

                logger.debug(
                    f"Extracted enhanced key: {key}",
                    extra={
                        "phase": "enhanced_extraction",
                        "key": key,
                        "type": type_str,
                        "has_description": bool(description),
                    },
                )
            else:
                logger.warning(
                    f"Failed to parse enhanced format segment: {segment}",
                    extra={"phase": "enhanced_extraction", "segment": segment},
                )

        # If no results from enhanced format, fall back
        if not results:
            logger.warning(
                "Enhanced format detected but parsing failed, falling back",
                extra={"phase": "enhanced_extraction", "content_preview": content[:50]},
            )
            # Convert simple keys to enhanced format with defaults
            simple_keys = self._extract_shared_keys(content)
            return [{"key": k, "type": "any", "description": ""} for k in simple_keys]

        return results

    def _extract_enhanced_params(self, content: str) -> list[dict[str, Any]]:
        """
        Extract parameters with type annotations and descriptions.

        Args:
            content: The content after "Params:" in enhanced format

        Returns:
            List of dicts with key, type, and description
        """
        results = []

        # Pattern: param_name: type  # description
        # Split params properly first, then parse each one
        param_segments = re.split(r",\s*(?=\w+\s*:)", content)

        for segment in param_segments:
            segment = segment.strip()
            if not segment:
                continue

            # Now parse each param: name: type  # description
            param_pattern = r"(\w+)\s*:\s*([^#\n]+)(?:\s*#\s*(.*))?$"
            match = re.match(param_pattern, segment)

            if match:
                key = match.group(1)
                type_str = match.group(2).strip()
                description = match.group(3).strip() if match.group(3) else ""

                results.append({"key": key, "type": type_str, "description": description})

                logger.debug(
                    f"Extracted enhanced param: {key}",
                    extra={
                        "phase": "enhanced_extraction",
                        "key": key,
                        "type": type_str,
                        "has_description": bool(description),
                    },
                )

        # If no results from enhanced format, fall back
        if not results:
            logger.warning(
                "Enhanced param format detected but parsing failed, falling back",
                extra={"phase": "enhanced_extraction", "content_preview": content[:50]},
            )
            # Convert simple params to enhanced format with defaults
            simple_params = self._extract_params(content)
            return [{"key": p, "type": "any", "description": ""} for p in simple_params]

        return results

    def _normalize_to_rich_format(self, items: list[str] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Normalize items to consistent rich format.

        Args:
            items: List of strings (simple format) or dicts (already rich format)

        Returns:
            List of dicts with key, type, and description
        """
        if not items:
            return []

        # Check if already in rich format
        if isinstance(items[0], dict):
            # Type narrowing: if first item is dict, all items are dicts
            return items  # type: ignore[return-value]

        # Convert simple strings to rich format with defaults
        return [{"key": item, "type": "any", "description": ""} for item in items]

    def _get_indentation(self, line: str) -> int:
        """Get the indentation level of a line."""
        return len(line) - len(line.lstrip())

    def _parse_all_structures(self, lines: list[str], result: dict[str, list[Any]]) -> None:
        """
        Parse all structures in the interface content after main parsing.

        Args:
            lines: All lines from the interface section
            result: The parsed interface result to update with structures
        """
        # Look for each component that might have structures
        for component_name in ["inputs", "outputs"]:
            items = result.get(component_name, [])
            if not isinstance(items, list) or not items:
                continue

            for item in items:
                if not isinstance(item, dict) or not item.get("_has_structure"):
                    continue

                # Find the line that declares this item
                key = item["key"]
                type_str = item["type"]

                # Look for the declaration line
                for i, line in enumerate(lines):
                    if f'shared["{key}"]' in line and f": {type_str}" in line and i + 1 < len(lines):
                        next_line = lines[i + 1]
                        if self._get_indentation(next_line) > self._get_indentation(line):
                            # Has structure definition
                            structure, _ = self._parse_structure(lines, i + 1)
                            if structure:
                                item["structure"] = structure
                            break

                # Clean up the marker
                item.pop("_has_structure", None)

    def _parse_structure(self, lines: list[str], start_idx: int) -> tuple[dict[str, Any], int]:
        """
        Parse indentation-based structure starting at start_idx.

        Args:
            lines: All lines to parse
            start_idx: Starting line index

        Returns:
            Tuple of (structure_dict, next_line_idx)
        """
        structure = {}
        base_indent = None
        idx = start_idx

        while idx < len(lines):
            line = lines[idx]

            # Skip empty lines
            if not line.strip():
                idx += 1
                continue

            current_indent = self._get_indentation(line)

            # Initialize base indentation
            if base_indent is None:
                base_indent = current_indent

            # If we've returned to or gone below base indentation, we're done
            if current_indent < base_indent:
                break

            # If we're at base indentation, parse this field
            if current_indent == base_indent:
                # Parse field line: "- field: type  # description"
                field_match = re.match(r"\s*-\s*(\w+)\s*:\s*([^#\n]+)(?:\s*#\s*(.*))?", line)
                if field_match:
                    field_name = field_match.group(1)
                    field_type = field_match.group(2).strip()
                    field_desc = field_match.group(3).strip() if field_match.group(3) else ""

                    field_info = {"type": field_type, "description": field_desc}

                    # Check if this field has nested structure
                    if field_type in ("dict", "list", "list[dict]") and idx + 1 < len(lines):
                        next_line = lines[idx + 1]
                        if self._get_indentation(next_line) > current_indent:
                            nested_structure, new_idx = self._parse_structure(lines, idx + 1)
                            if nested_structure:
                                field_info["structure"] = nested_structure
                                idx = new_idx - 1  # Will be incremented below

                    structure[field_name] = field_info

                else:
                    # If we can't parse the line, log warning but continue
                    logger.warning(
                        f"Failed to parse structure line: {line}", extra={"phase": "structure_parsing", "line": line}
                    )

            idx += 1

        return structure, idx
