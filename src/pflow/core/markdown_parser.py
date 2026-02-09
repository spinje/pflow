"""Markdown workflow parser for .pflow.md files.

Parses markdown workflow documents into the same IR dict shape that
JSON workflows produce. Uses a custom line-by-line state machine —
no markdown library dependency. Only depends on PyYAML for YAML
fragment parsing and ast for Python code validation.

The parser front-loads structural validation with markdown line numbers
so that downstream jsonschema validation (in validate_ir) becomes a
safety net that rarely triggers.

Design: format-specification.md (27 decisions)
Implementation: implementation-plan.md (Phase 1.1)
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import yaml

# --- Exceptions ---


class MarkdownParseError(ValueError):
    """Error raised when markdown workflow content cannot be parsed.

    Extends ValueError so existing ``except ValueError`` catches still work.

    Attributes:
        line: Source line number where the error occurred (1-based).
        suggestion: Optional human-readable fix suggestion.
    """

    def __init__(
        self,
        message: str,
        line: int | None = None,
        suggestion: str | None = None,
    ):
        self.line = line
        self.suggestion = suggestion
        prefix = f"Line {line}: " if line else ""
        full = f"{prefix}{message}"
        if suggestion:
            full += f"\n\n{suggestion}"
        super().__init__(full)


# --- Result dataclass ---


@dataclass
class MarkdownParseResult:
    """Result of parsing a .pflow.md file.

    Attributes:
        ir: The workflow IR dict (same shape as json.load produced).
        title: H1 heading text (None if no H1).
        description: H1 prose between ``#`` and first ``##`` (None if empty).
        metadata: Frontmatter dict (None for authored files without frontmatter).
        source: Original markdown content (for save operations that preserve
            the author's formatting).
    """

    ir: dict[str, Any]
    title: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    source: str = ""
    warnings: list[str] = field(default_factory=list)


# --- Internal types ---

# Node ID regex: starts with lowercase letter, then lowercase/digits/hyphens/underscores
_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# Code block tag mapping: last word → param name
# Preceding word(s) are language hints for editor highlighting (ignored by parser)
_CODE_BLOCK_TAG_TO_PARAM: dict[str, str] = {
    "command": "command",
    "code": "code",
    "prompt": "prompt",
    "source": "source",
    "batch": "batch",
    "stdin": "stdin",
    "headers": "headers",
    "output_schema": "output_schema",
}

# Near-miss section names that should produce warnings
_NEAR_MISS_SECTIONS: dict[str, str] = {
    "input": "Inputs",
    "output": "Outputs",
    "step": "Steps",
}


class _SectionType(Enum):
    NONE = auto()
    INPUTS = auto()
    STEPS = auto()
    OUTPUTS = auto()
    UNKNOWN = auto()


@dataclass
class _CodeBlock:
    """A collected code block within an entity."""

    tag: str  # The info string (e.g. "shell command", "yaml batch")
    param_name: str  # Extracted param name (e.g. "command", "batch")
    content: str
    start_line: int
    is_yaml_config: bool = False  # True for yaml batch, yaml stdin, etc.


@dataclass
class _Entity:
    """A collected ### entity (input, node, or output)."""

    id: str
    heading_line: int
    prose_parts: list[str] = field(default_factory=list)
    yaml_items: list[str] = field(default_factory=list)  # Raw YAML item strings
    code_blocks: list[_CodeBlock] = field(default_factory=list)
    section_type: _SectionType = _SectionType.NONE


# --- Main parser ---


def parse_markdown(content: str) -> MarkdownParseResult:  # noqa: C901
    """Parse a .pflow.md workflow file into an IR dict.

    Args:
        content: Raw markdown content of the workflow file.

    Returns:
        MarkdownParseResult with the parsed IR, title, description,
        optional frontmatter metadata, and original source content.

    Raises:
        MarkdownParseError: If the content has structural or syntax errors.
    """
    result = MarkdownParseResult(ir={}, source=content)
    warnings: list[str] = []

    lines = content.splitlines()
    total_lines = len(lines)

    # --- Phase 1: Extract frontmatter ---
    body_start = 0
    if lines and lines[0].rstrip() == "---":
        closing = _find_frontmatter_close(lines)
        if closing is not None:
            fm_text = "\n".join(lines[1:closing])
            try:
                fm_data = yaml.safe_load(fm_text)
            except yaml.YAMLError as exc:
                raise MarkdownParseError(
                    f"Invalid YAML in frontmatter: {exc}",
                    line=1,
                ) from exc
            if isinstance(fm_data, dict):
                result.metadata = fm_data
            body_start = closing + 1

    # --- Phase 2: Line-by-line state machine ---
    current_section: _SectionType = _SectionType.NONE
    h1_found = False
    h1_prose_parts: list[str] = []
    entities: list[_Entity] = []
    current_entity: _Entity | None = None
    in_code_block = False
    code_fence_pattern = ""  # The fence string that opened the block
    code_fence_line = 0
    code_block_tag = ""
    code_block_lines: list[str] = []
    # YAML continuation tracking
    in_yaml_continuation = False
    yaml_current_item_lines: list[str] = []
    yaml_indent_level = 0  # The column where content after '- ' starts
    steps_section_found = False

    def _flush_yaml_item() -> None:
        """Flush the current YAML item to the current entity."""
        nonlocal in_yaml_continuation, yaml_current_item_lines
        if yaml_current_item_lines and current_entity is not None:
            current_entity.yaml_items.append("\n".join(yaml_current_item_lines))
        yaml_current_item_lines = []
        in_yaml_continuation = False

    for line_idx in range(body_start, total_lines):
        line = lines[line_idx]
        line_num = line_idx + 1  # 1-based

        # --- Code fence boundaries (highest priority) ---
        if _is_code_fence(line):
            if in_code_block:
                if _is_closing_fence(line, code_fence_pattern):
                    block_content = "\n".join(code_block_lines)
                    if current_entity is not None:
                        _append_code_block(current_entity, code_block_tag, block_content, code_fence_line)
                    in_code_block = False
                    code_block_lines = []
                    continue
                else:
                    code_block_lines.append(line)
                    continue
            else:
                _flush_yaml_item()
                stripped = line.strip()
                fence_match = re.match(r"^(`{3,}|~{3,})", stripped)
                if fence_match:
                    code_fence_pattern = fence_match.group(1)
                    code_block_tag = stripped[len(code_fence_pattern) :].strip()
                    code_fence_line = line_num
                    in_code_block = True
                    code_block_lines = []
                    continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # --- Headings ---
        stripped = line.strip()

        # H1
        if stripped.startswith("# ") and not stripped.startswith("## "):
            _flush_yaml_item()
            if not h1_found:
                h1_found = True
                result.title = stripped[2:].strip()
                current_entity = None
            continue

        # H2 — section boundary
        if stripped.startswith("## ") and not stripped.startswith("### "):
            _flush_yaml_item()
            current_entity = None
            section_name = stripped[3:].strip()
            current_section, is_steps, warning = _resolve_section(section_name, line_num)
            if is_steps:
                steps_section_found = True
            if warning:
                warnings.append(warning)
            continue

        # H3 — entity
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            _flush_yaml_item()
            entity_id = stripped[4:].strip()
            # Validate ID format
            if not _NODE_ID_RE.match(entity_id):
                raise MarkdownParseError(
                    f"Invalid entity ID '{entity_id}'.",
                    line=line_num,
                    suggestion=(
                        "IDs must start with a lowercase letter and contain only "
                        "lowercase letters, digits, hyphens, and underscores.\n"
                        f"Pattern: {_NODE_ID_RE.pattern}"
                    ),
                )
            # Check for duplicate IDs within the same section type
            for existing in entities:
                if existing.id == entity_id and existing.section_type == current_section:
                    raise MarkdownParseError(
                        f"Duplicate entity ID '{entity_id}'.",
                        line=line_num,
                        suggestion=f"An entity with ID '{entity_id}' was already defined at line {existing.heading_line}.",
                    )
            current_entity = _Entity(
                id=entity_id,
                heading_line=line_num,
                section_type=current_section,
            )
            entities.append(current_entity)
            continue

        # --- Inside an entity: YAML params, prose ---
        if current_entity is not None:
            # YAML continuation tracking
            if in_yaml_continuation:
                # Check if this line is a continuation (indented beyond the - level)
                if line and line.strip() != "":
                    # Calculate leading whitespace
                    content_start = len(line) - len(line.lstrip())
                    if content_start >= yaml_indent_level:
                        yaml_current_item_lines.append(line)
                        continue
                # Not a continuation — flush and fall through
                _flush_yaml_item()

            # New YAML item: line starts with "- " (with optional leading whitespace)
            yaml_match = re.match(r"^(\s*)- (.+)$", line)
            if yaml_match:
                _flush_yaml_item()
                leading_spaces = len(yaml_match.group(1))
                yaml_current_item_lines = [line.rstrip()]
                # The continuation indent level is the column after "- "
                yaml_indent_level = leading_spaces + 2
                in_yaml_continuation = True
                continue

            # Blank line
            if stripped == "":
                _flush_yaml_item()
                continue

            # Prose line
            _flush_yaml_item()
            current_entity.prose_parts.append(stripped)
            continue

        # --- H1 prose (between # and first ##) ---
        if h1_found and current_section == _SectionType.NONE:
            if stripped:
                h1_prose_parts.append(stripped)
            continue

    # --- End of file ---
    _flush_yaml_item()

    # Check for unclosed code block
    if in_code_block:
        raise MarkdownParseError(
            "Unclosed code block.",
            line=code_fence_line,
            suggestion=f"Add a closing fence ({code_fence_pattern}) to match the opening fence at line {code_fence_line}.",
        )

    # Set workflow description from H1 prose
    if h1_prose_parts:
        result.description = "\n\n".join(_join_prose_paragraphs(h1_prose_parts))

    # --- Phase 3: Validate structure ---
    if not steps_section_found:
        raise MarkdownParseError(
            "Missing '## Steps' section.",
            suggestion=(
                "Every workflow needs a Steps section with at least one node:\n\n"
                "    ## Steps\n\n"
                "    ### my-node\n\n"
                "    Description of what this node does.\n\n"
                "    - type: shell"
            ),
        )

    step_entities = [e for e in entities if e.section_type == _SectionType.STEPS]
    if not step_entities:
        raise MarkdownParseError(
            "The '## Steps' section has no nodes.",
            suggestion=(
                "Add at least one node with a ### heading:\n\n"
                "    ## Steps\n\n"
                "    ### my-node\n\n"
                "    Description of what this node does.\n\n"
                "    - type: shell"
            ),
        )

    # --- Phase 4: Build IR ---
    ir: dict[str, Any] = {}

    # Build inputs
    input_entities = [e for e in entities if e.section_type == _SectionType.INPUTS]
    if input_entities:
        ir["inputs"] = {}
        for entity in input_entities:
            ir["inputs"][entity.id] = _build_input_dict(entity)

    # Build nodes
    nodes: list[dict[str, Any]] = []
    for entity in step_entities:
        nodes.append(_build_node_dict(entity))
    ir["nodes"] = nodes

    # Build edges from document order
    if len(nodes) > 1:
        ir["edges"] = [{"from": nodes[i]["id"], "to": nodes[i + 1]["id"]} for i in range(len(nodes) - 1)]
    else:
        ir["edges"] = []

    # Build outputs
    output_entities = [e for e in entities if e.section_type == _SectionType.OUTPUTS]
    if output_entities:
        ir["outputs"] = {}
        for entity in output_entities:
            ir["outputs"][entity.id] = _build_output_dict(entity)

    result.ir = ir

    if warnings:
        result.warnings = warnings

    return result


# --- Internal helpers ---


def _find_frontmatter_close(lines: list[str]) -> int | None:
    """Find the closing ``---`` line index for frontmatter.

    Starts searching from line index 1 (line after opening ``---``).
    Returns the line index of the closing ``---``, or None if not found.
    """
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return i
    return None


def _is_code_fence(line: str) -> bool:
    """Check if a line is a code fence (``` or ~~~, 3+ chars)."""
    stripped = line.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _extract_param_name(tag: str) -> str:
    """Extract the parameter name from a code block info string.

    The last word is the param name. Preceding words are language hints.
    Single word serves as both language and param.
    """
    parts = tag.strip().split()
    if not parts:
        return ""
    return parts[-1]


def _resolve_section(section_name: str, line_num: int) -> tuple[_SectionType, bool, str | None]:
    """Resolve an H2 section name to a section type.

    Returns (section_type, is_steps, optional_warning).
    """
    section_lower = section_name.lower()
    if section_lower == "inputs":
        return _SectionType.INPUTS, False, None
    if section_lower == "steps":
        return _SectionType.STEPS, True, None
    if section_lower == "outputs":
        return _SectionType.OUTPUTS, False, None
    # Unknown section — check for near-miss
    warning = None
    if section_lower in _NEAR_MISS_SECTIONS:
        expected = _NEAR_MISS_SECTIONS[section_lower]
        warning = f"Line {line_num}: '## {section_name}' looks like a typo — did you mean '## {expected}'?"
    return _SectionType.UNKNOWN, False, warning


def _is_closing_fence(line: str, opening_pattern: str) -> bool:
    """Check if a line closes a code block opened with ``opening_pattern``."""
    stripped = line.strip()
    fence_char = opening_pattern[0]
    fence_len = len(opening_pattern)
    return stripped == fence_char * len(stripped) and len(stripped) >= fence_len and stripped[0] == fence_char


def _append_code_block(entity: _Entity, tag: str, content: str, start_line: int) -> None:
    """Append a parsed code block to an entity."""
    if tag:
        param_name = _extract_param_name(tag)
        tag_parts = tag.strip().split()
        is_yaml = len(tag_parts) > 1 and tag_parts[0].lower() == "yaml"
        entity.code_blocks.append(
            _CodeBlock(
                tag=tag,
                param_name=param_name,
                content=content,
                start_line=start_line,
                is_yaml_config=is_yaml,
            )
        )
    else:
        entity.code_blocks.append(_CodeBlock(tag="", param_name="", content=content, start_line=start_line))


def _join_prose_paragraphs(parts: list[str]) -> list[str]:
    """Group consecutive prose lines into paragraphs.

    Consecutive non-blank lines are joined with ``\\n``.
    Returns a list of paragraph strings.
    """
    if not parts:
        return []
    paragraphs: list[str] = []
    current: list[str] = []
    for part in parts:
        current.append(part)
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def _parse_yaml_items(entity: _Entity) -> dict[str, Any]:
    """Parse collected YAML items into a merged dict.

    Each item is a ``- key: value`` string (possibly with indented continuations).
    They are joined and parsed as a YAML sequence, then merged into a single dict.

    Raises:
        MarkdownParseError: On YAML syntax errors or non-dict items.
    """
    if not entity.yaml_items:
        return {}

    # Join all items into a single YAML document
    yaml_text = "\n".join(entity.yaml_items)

    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise MarkdownParseError(
            f"YAML syntax error in parameters for '{entity.id}': {exc}",
            line=entity.heading_line,
        ) from exc

    if parsed is None:
        return {}

    if not isinstance(parsed, list):
        raise MarkdownParseError(
            f"Parameters for '{entity.id}' did not parse as a list of key-value pairs.",
            line=entity.heading_line,
        )

    # Validate each item is a dict and merge
    merged: dict[str, Any] = {}
    for item in parsed:
        if not isinstance(item, dict):
            raise MarkdownParseError(
                f"'{item}' is not a valid parameter. Use * for documentation bullets.",
                line=entity.heading_line,
                suggestion=(
                    "Parameters must be key: value pairs:\n"
                    "    - type: shell\n"
                    "    - timeout: 30\n\n"
                    "For notes, use * instead of -:\n"
                    "    * This is a documentation note"
                ),
            )
        merged.update(item)

    return merged


def _validate_code_blocks(entity: _Entity) -> None:
    """Validate code blocks within an entity.

    Checks:
    - No bare code blocks (missing info string)
    - No duplicate param names from code blocks
    - Python code syntax (ast.parse)
    - YAML config syntax (yaml.safe_load)
    """
    seen_params: dict[str, int] = {}  # param_name → start_line

    for block in entity.code_blocks:
        # Bare code block check
        if not block.tag:
            # Check for nested backticks pattern: tagged block followed by bare block
            preceding_tagged = [b for b in entity.code_blocks if b.tag and b.start_line < block.start_line]
            if preceding_tagged:
                last = preceding_tagged[-1]
                raise MarkdownParseError(
                    f"Code block has no tag (likely caused by nested ``` "
                    f"in the `{last.tag}` block at line {last.start_line}).",
                    line=block.start_line,
                    suggestion=(
                        f"An inner ``` closes the outer block early, making this line\n"
                        "look like a new code block.\n\n"
                        f"Fix: Use 4+ backticks for the outer fence:\n"
                        f"    ````{last.tag}\n"
                        "    content with ``` inside\n"
                        "    ````"
                    ),
                )
            raise MarkdownParseError(
                "Code block has no tag.",
                line=block.start_line,
                suggestion=(
                    "Add a tag to identify what this code block contains:\n"
                    "    ```shell command\n"
                    "    ```prompt\n"
                    "    ```python code\n"
                    "    ```yaml batch\n\n"
                    "Tip: To include ``` inside a code block, use 4+ backticks\n"
                    "or tildes for the outer fence."
                ),
            )

        # Duplicate param check
        if block.param_name in seen_params:
            raise MarkdownParseError(
                f"Duplicate code block for '{block.param_name}'.",
                line=block.start_line,
                suggestion=(
                    f"A '{block.param_name}' code block was already defined at "
                    f"line {seen_params[block.param_name]}. Each parameter can only "
                    "have one code block."
                ),
            )
        seen_params[block.param_name] = block.start_line

        # Python syntax validation
        tag_parts = block.tag.strip().split()
        lang = tag_parts[0].lower() if tag_parts else ""
        if lang == "python" or block.param_name == "code":
            try:
                ast.parse(block.content)
            except SyntaxError as exc:
                # Calculate the actual line in the markdown file
                offset_line = block.start_line + (exc.lineno or 0)
                raise MarkdownParseError(
                    f"Python syntax error in code block: {exc.msg}",
                    line=offset_line,
                    suggestion=f"Fix the Python syntax in the code block starting at line {block.start_line}.",
                ) from exc

        # YAML config validation
        if block.is_yaml_config:
            try:
                yaml.safe_load(block.content)
            except yaml.YAMLError as exc:
                raise MarkdownParseError(
                    f"YAML syntax error in '{block.tag}' block: {exc}",
                    line=block.start_line,
                ) from exc


def _build_input_dict(entity: _Entity) -> dict[str, Any]:
    """Build an input definition dict from an entity.

    Inputs get flat dicts (no params wrapper).
    Valid fields: description, required, type, default, stdin.
    """
    _validate_description(entity)
    _validate_code_blocks(entity)

    result: dict[str, Any] = {}

    # Description from prose
    prose = _get_prose(entity)
    if prose:
        result["description"] = prose

    # Parse YAML params — flat, directly into result
    params = _parse_yaml_items(entity)
    result.update(params)

    # Code blocks in inputs — handle source-like blocks
    for block in entity.code_blocks:
        if block.param_name:
            result[block.param_name] = block.content

    return result


def _check_param_code_block_conflicts(entity: _Entity, all_params: dict[str, Any]) -> None:
    """Check for params defined both inline and as code blocks."""
    code_param_names = {b.param_name for b in entity.code_blocks if b.param_name}
    for param_name in code_param_names:
        if param_name in all_params:
            block = next(b for b in entity.code_blocks if b.param_name == param_name)
            raise MarkdownParseError(
                f"Parameter '{param_name}' is defined both inline and as a code block.",
                line=block.start_line,
                suggestion=(
                    f"Remove either the inline '- {param_name}: ...' or the "
                    f"code block. Each parameter should be defined only once."
                ),
            )


def _route_code_blocks_to_node(entity: _Entity, node: dict[str, Any], params: dict[str, Any]) -> None:
    """Route code blocks to top-level node fields or params dict."""
    for block in entity.code_blocks:
        if block.param_name == "batch":
            if block.is_yaml_config:
                node["batch"] = yaml.safe_load(block.content)
            else:
                node["batch"] = block.content
        elif block.param_name:
            if block.is_yaml_config:
                params[block.param_name] = yaml.safe_load(block.content)
            else:
                params[block.param_name] = block.content
                # Carry source line so runtime errors can reference the .pflow.md file.
                # Content starts on the line after the opening fence.
                source_lines = node.setdefault("_source_lines", {})
                source_lines[block.param_name] = block.start_line + 1


def _build_node_dict(entity: _Entity) -> dict[str, Any]:
    """Build a node dict from an entity.

    Routes: type → top-level, batch → top-level, prose → purpose,
    everything else → params.
    """
    _validate_description(entity)
    _validate_code_blocks(entity)

    node: dict[str, Any] = {"id": entity.id}
    all_params = _parse_yaml_items(entity)

    _check_param_code_block_conflicts(entity, all_params)

    # Extract type (required, goes to top-level)
    if "type" in all_params:
        node["type"] = all_params.pop("type")
    else:
        raise MarkdownParseError(
            f"Node '{entity.id}' is missing a 'type' parameter.",
            line=entity.heading_line,
            suggestion=(
                "Every node needs a type:\n\n"
                f"    ### {entity.id}\n\n"
                "    Description of what this node does.\n\n"
                "    - type: shell"
            ),
        )

    # Extract batch (goes to top-level, not params)
    if "batch" in all_params:
        node["batch"] = all_params.pop("batch")

    # Purpose from prose
    prose = _get_prose(entity)
    if prose:
        node["purpose"] = prose

    _route_code_blocks_to_node(entity, node, all_params)

    if all_params:
        node["params"] = all_params

    return node


def _build_output_dict(entity: _Entity) -> dict[str, Any]:
    """Build an output definition dict from an entity.

    Outputs get flat dicts (no params wrapper).
    Valid fields: description, type, source.
    """
    _validate_description(entity)
    _validate_code_blocks(entity)

    result: dict[str, Any] = {}

    # Description from prose
    prose = _get_prose(entity)
    if prose:
        result["description"] = prose

    # Parse YAML params — flat
    params = _parse_yaml_items(entity)
    result.update(params)

    # Code blocks — source goes directly to output
    for block in entity.code_blocks:
        if block.param_name == "source":
            result["source"] = block.content
        elif block.param_name:
            result[block.param_name] = block.content

    return result


def _validate_description(entity: _Entity) -> None:
    """Validate that an entity has a prose description."""
    if not entity.prose_parts:
        raise MarkdownParseError(
            f"Entity '{entity.id}' (line {entity.heading_line}) is missing a description.",
            line=entity.heading_line,
            suggestion=(
                "Add a text paragraph between the heading and the parameters:\n\n"
                f"    ### {entity.id}\n\n"
                "    Description of what this entity does and why.\n\n"
                "    - type: shell"
            ),
        )


def _get_prose(entity: _Entity) -> str | None:
    """Get joined prose text from an entity's prose parts."""
    if not entity.prose_parts:
        return None
    # Join all prose parts. Parts that were separated by blank lines
    # or params/code blocks are joined with \n\n. Consecutive lines with \n.
    # Since we collect one stripped line per prose_parts entry, and blank lines
    # cause a flush, consecutive lines are separate entries.
    return "\n".join(entity.prose_parts)
