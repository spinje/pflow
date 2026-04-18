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

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import MarkdownParseError
from pflow.core.suggestion_utils import find_similar_items

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
    warnings: list[Diagnostic] = field(default_factory=list)


# --- Internal types ---

# Node ID regex: starts with lowercase letter, then lowercase/digits/hyphens/underscores
_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

# YAML 1.1 boolean values (matching PyYAML's yaml.safe_load behavior)
_YAML_BOOL_TRUE = frozenset({
    "true",
    "True",
    "TRUE",
    "yes",
    "Yes",
    "YES",
    "on",
    "On",
    "ON",
})
_YAML_BOOL_FALSE = frozenset({
    "false",
    "False",
    "FALSE",
    "no",
    "No",
    "NO",
    "off",
    "Off",
    "OFF",
})
_YAML_NULL = frozenset({"null", "Null", "NULL", "~"})

# Regex for single-line YAML item: "- key: value" with optional leading whitespace
_YAML_ITEM_RE = re.compile(r"^\s*-\s+(\S+?):\s*(.*)$")

# Regex for numeric values — matches integers and floats (with required dot for floats).
# Must NOT match "inf", "nan", "infinity" etc. (Python's float() accepts these but YAML
# treats them as strings). More permissive than PyYAML for scientific notation: "1.5e10"
# is coerced to float here (PyYAML keeps it as string because YAML 1.1 requires an
# explicit exponent sign like "1.5e+10"). "1e5" (no dot) stays string in both.
_NUMERIC_INT_RE = re.compile(r"^[+-]?\d+$")
_NUMERIC_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?$")

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
    # Content params that benefit from code block escape
    "system": "system",
    "system_prompt": "system_prompt",
    "url": "url",
    "content": "content",
    "body": "body",
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


_KNOWN_SECTIONS: set[_SectionType] = {
    _SectionType.INPUTS,
    _SectionType.STEPS,
    _SectionType.OUTPUTS,
}

_SECTION_DISPLAY_NAMES: dict[_SectionType, str] = {
    _SectionType.INPUTS: "Inputs",
    _SectionType.STEPS: "Steps",
    _SectionType.OUTPUTS: "Outputs",
}

_SECTION_SYNTAX_HINTS: dict[_SectionType, str] = {
    _SectionType.INPUTS: (
        "Inputs must use ### heading syntax:\n\n"
        "    ### input-name\n\n"
        "    Description of the input.\n\n"
        "    - type: string\n"
        "    - required: true"
    ),
    _SectionType.STEPS: (
        "Steps must use ### heading syntax:\n\n"
        "    ### step-name\n\n"
        "    Description of what this step does.\n\n"
        "    - type: shell\n\n"
        "    ```shell command\n"
        '    echo "hello"\n'
        "    ```"
    ),
    _SectionType.OUTPUTS: (
        "Outputs must use ### heading syntax:\n\n"
        "    ### output-name\n\n"
        "    Description of the output.\n\n"
        "    - value: ${step-name.output}"
    ),
}


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
    yaml_item_lines: list[int] = field(default_factory=list)  # Parallel: source line of each item's first '- '
    yaml_item_keys: list[str] = field(default_factory=list)  # Parallel to yaml_items: parsed top-level key
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
    warnings: list[Diagnostic] = []
    orphaned_lines: dict[_SectionType, list[int]] = {}
    seen_sections: dict[_SectionType, int] = {}  # section_type → first line number

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
    yaml_current_item_start_line = 0
    yaml_indent_level = 0  # The column where content after '- ' starts
    steps_section_found = False

    def _flush_yaml_item() -> None:
        """Flush the current YAML item to the current entity."""
        nonlocal in_yaml_continuation, yaml_current_item_lines, yaml_current_item_start_line
        if yaml_current_item_lines and current_entity is not None:
            current_entity.yaml_items.append("\n".join(yaml_current_item_lines))
            current_entity.yaml_item_lines.append(yaml_current_item_start_line)
        yaml_current_item_lines = []
        yaml_current_item_start_line = 0
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
                    elif current_section in _KNOWN_SECTIONS:
                        orphaned_lines.setdefault(current_section, []).extend([code_fence_line, line_num])
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
            if current_section in _KNOWN_SECTIONS and current_section in seen_sections:
                raise MarkdownParseError(
                    f"Duplicate '## {_SECTION_DISPLAY_NAMES[current_section]}' section.",
                    line=line_num,
                    suggestion=f"Merge with the existing '## {_SECTION_DISPLAY_NAMES[current_section]}' section at line {seen_sections[current_section]}.",
                )
            if current_section in _KNOWN_SECTIONS:
                seen_sections[current_section] = line_num
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
                yaml_current_item_start_line = line_num
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

        # --- Orphaned content in known sections ---
        if current_section in _KNOWN_SECTIONS and stripped:
            orphaned_lines.setdefault(current_section, []).append(line_num)

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

    # Check for orphaned content in known sections
    for section_type, line_nums in orphaned_lines.items():
        section_name = _SECTION_DISPLAY_NAMES[section_type]
        entity_count = sum(1 for e in entities if e.section_type == section_type)
        first_line = min(line_nums)
        last_line = max(line_nums)

        line_ref = f"line {first_line}" if first_line == last_line else f"lines {first_line}-{last_line}"

        if entity_count == 0:
            raise MarkdownParseError(
                f"'{section_name}' section has content but no {section_name.lower()} were parsed ({line_ref}).",
                line=first_line,
                suggestion=_SECTION_SYNTAX_HINTS[section_type],
            )
        else:
            warnings.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    message=(
                        f"Unparsed content in '{section_name}' section ({line_ref}). "
                        "Content before the first ### heading is not captured."
                    ),
                    suggestions=["Move content under a ### heading, or remove it."],
                    source="parser",
                )
            )

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

    # Build nodes with routing metadata
    nodes: list[dict[str, Any]] = []
    routing_metadata: dict[str, dict[str, Any]] = {}
    for entity in step_entities:
        node, routing = _build_node_dict(entity)
        nodes.append(node)
        if routing:
            routing_metadata[entity.id] = routing
    ir["nodes"] = nodes

    # Collect AST-detected routing targets from python code blocks
    ast_routing_targets: dict[str, list[str]] = {}
    ast_has_dynamic: set[str] = set()
    for entity in step_entities:
        for block in entity.code_blocks:
            if block.param_name == "code":
                code_targets, has_dynamic = _extract_next_targets_from_code(block.content)
                if code_targets:
                    ast_routing_targets[entity.id] = code_targets
                if has_dynamic:
                    ast_has_dynamic.add(entity.id)

    # Build edges with routing
    ir["edges"] = _build_edges(nodes, routing_metadata, ast_routing_targets)

    # Validate routing targets
    node_id_set = {n["id"] for n in nodes}
    if "end" in node_id_set:
        raise MarkdownParseError(
            "'end' is a reserved keyword and cannot be used as a node ID",
            suggestion="Rename the node to something else (e.g., 'finish', 'done')",
        )
    _validate_routing_targets(ir["edges"], node_id_set)

    # Validate branch target routing (prevents silent fall-through)
    heading_lines = {e.id: e.heading_line for e in step_entities}
    _validate_branch_target_routing(ir["edges"], routing_metadata, ast_has_dynamic, heading_lines)

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


def _resolve_section(section_name: str, line_num: int) -> tuple[_SectionType, bool, Diagnostic | None]:
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
        warning = Diagnostic(
            severity=Severity.WARNING,
            message=f"Line {line_num}: '## {section_name}' looks like a typo for '## {expected}'.",
            suggestions=[f"Rename to '## {expected}'."],
            source="parser",
        )
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


def _enhance_yaml_error(exc: yaml.YAMLError, entity: _Entity) -> MarkdownParseError:
    """Turn a raw YAML error into an actionable MarkdownParseError.

    Detects the common case where a parameter value contains an unquoted
    ```: ```(colon + space), which YAML misinterprets as a nested mapping.
    """
    exc_str = str(exc)
    if "mapping values are not allowed here" in exc_str:
        # Find the offending line from the YAML items
        offending_line = _find_colon_offending_line(entity.yaml_items)
        if offending_line:
            key, value = offending_line
            quoted = f'- {key}: "{value}"'
            return MarkdownParseError(
                f"YAML parse error in '{entity.id}' parameters.",
                line=entity.heading_line,
                suggestion=(
                    f'The value contains ": " (colon + space), which YAML '
                    f"interprets as a key-value separator.\n"
                    f"Fix: wrap the value in quotes:\n"
                    f"    {quoted}"
                ),
            )
    return MarkdownParseError(
        f"YAML syntax error in parameters for '{entity.id}': {exc}",
        line=entity.heading_line,
    )


def _find_colon_offending_line(
    yaml_items: list[str],
) -> tuple[str, str] | None:
    """Find a ``- key: value`` line where value contains `: `.

    Returns ``(key, value)`` or ``None``.

    Note: With raw string parsing for single-line items, this function primarily
    applies to multi-line YAML error diagnostics. Single-line colon-space values
    no longer go through ``yaml.safe_load()`` and thus never trigger YAML errors.
    """
    for item in yaml_items:
        # Each item starts with "- key: value" (possibly multiline)
        first_line = item.split("\n", 1)[0]
        m = re.match(r"^-\s+(\S+?):\s+(.+)$", first_line)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        # Value contains an additional ": " and isn't already quoted
        if ": " in value and not (value.startswith('"') and value.endswith('"')):
            return key, value
    return None


# Escape sequences for YAML double-quoted strings.
# Must handle at minimum: \\ \" \n (generated by tests/shared/markdown_utils.py)
_YAML_DOUBLE_QUOTE_ESCAPES: dict[str, str] = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "/": "/",
    " ": " ",
}


def _unescape_yaml_double_quoted(s: str) -> str:
    """Process escape sequences in a YAML double-quoted string value."""
    result: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            next_char = s[i + 1]
            if next_char in _YAML_DOUBLE_QUOTE_ESCAPES:
                result.append(_YAML_DOUBLE_QUOTE_ESCAPES[next_char])
                i += 2
                continue
        result.append(s[i])
        i += 1
    return "".join(result)


def _coerce_numeric(value: str) -> int | float | None:
    """Try to coerce a string to int or float. Returns None if not numeric."""
    if _NUMERIC_INT_RE.match(value):
        try:
            return int(value)
        except ValueError:
            pass
    if _NUMERIC_FLOAT_RE.match(value):
        try:
            return float(value)
        except ValueError:
            pass
    return None


def _coerce_yaml_scalar(value: str) -> Any:
    """Coerce a raw string value to a Python scalar using YAML-like rules.

    Handles: quoted strings, null, booleans, integers, floats, flow-style YAML.
    Plain string values are returned as-is — no structural YAML parsing
    (no colon-space splitting, no # comment stripping).

    Note: intentionally diverges from PyYAML for edge cases (octal ``012``,
    scientific notation ``1.5e10``, dates, hex, sexagesimal). See the
    Known Type Divergences table in the implementation plan for details.

    Raises:
        ValueError: For unterminated quoted strings.
        yaml.YAMLError: For malformed flow-style YAML (``{...}``, ``[...]``).
    """
    # Empty value (bare "- key:" with no value) → None
    if not value:
        return None

    # Double-quoted string → strip quotes, process escape sequences
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return _unescape_yaml_double_quoted(value[1:-1])

    # Single-quoted string → strip quotes, only '' → ' escaping
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")

    # Unmatched opening quote — almost certainly a missing closing quote
    if value[0] in ('"', "'"):
        quote_type = "double" if value[0] == '"' else "single"
        raise ValueError(f"Unterminated {quote_type}-quoted string: {value}")

    # Flow-style YAML mapping or sequence → parse with yaml.safe_load
    # Let yaml.YAMLError propagate — caller converts to MarkdownParseError
    if value.startswith(("{", "[")):
        return yaml.safe_load(value)

    # Null
    if value in _YAML_NULL:
        return None

    # Booleans
    if value in _YAML_BOOL_TRUE:
        return True
    if value in _YAML_BOOL_FALSE:
        return False

    # Numeric (int or float)
    numeric = _coerce_numeric(value)
    if numeric is not None:
        return numeric

    # Everything else: raw string
    return value


def _parse_multiline_yaml_item(item: str, entity: _Entity, merged: dict[str, Any]) -> str | None:
    """Parse a multi-line YAML item and merge results into ``merged``."""
    try:
        parsed = yaml.safe_load(item)
    except yaml.YAMLError as exc:
        raise _enhance_yaml_error(exc, entity) from exc

    if parsed is None:
        return None
    if isinstance(parsed, list):
        first_key: str | None = None
        for entry in parsed:
            if not isinstance(entry, dict):
                raise MarkdownParseError(
                    f"'{entry}' is not a valid parameter. Use * for documentation bullets.",
                    line=entity.heading_line,
                    suggestion=(
                        "Parameters must be key: value pairs:\n"
                        "    - type: shell\n"
                        "    - timeout: 30\n\n"
                        "For notes, use * instead of -:\n"
                        "    * This is a documentation note"
                    ),
                )
            merged.update(entry)
            if first_key is None and entry:
                first_key = str(next(iter(entry.keys())))
        return first_key
    elif isinstance(parsed, dict):
        merged.update(parsed)
        return str(next(iter(parsed.keys()))) if parsed else None
    else:
        raise MarkdownParseError(
            f"'{parsed}' is not a valid parameter. Use * for documentation bullets.",
            line=entity.heading_line,
        )


def _parse_yaml_items(entity: _Entity) -> dict[str, Any]:
    """Parse collected YAML items into a merged dict.

    Single-line items (``- key: value``) are parsed as raw strings with
    YAML-compatible scalar coercion (booleans, numbers, null, quoted strings,
    flow-style collections). This avoids YAML structural parsing issues
    (colon-space in values, ``#`` treated as comments).

    Multi-line items (with indented continuations) are YAML-parsed individually
    since they contain structured data (dicts, nested values).

    Raises:
        MarkdownParseError: On YAML syntax errors or non-dict items.
    """
    if not entity.yaml_items:
        return {}

    merged: dict[str, Any] = {}
    entity.yaml_item_keys = []

    for item in entity.yaml_items:
        if "\n" in item:
            key = _parse_multiline_yaml_item(item, entity, merged)
            entity.yaml_item_keys.append(key or "")
        else:
            # Single-line item: raw string extraction with scalar coercion
            m = _YAML_ITEM_RE.match(item)
            if m:
                try:
                    key = m.group(1)
                    merged[key] = _coerce_yaml_scalar(m.group(2))
                    entity.yaml_item_keys.append(key)
                except yaml.YAMLError as exc:
                    raise _enhance_yaml_error(exc, entity) from exc
                except ValueError as exc:
                    raise MarkdownParseError(
                        f"Parameter parse error in '{entity.id}': {exc}",
                        line=entity.heading_line,
                        suggestion="Add the missing closing quote.",
                    ) from exc
            else:
                content = re.sub(r"^\s*-\s*", "", item).strip()
                raise MarkdownParseError(
                    f"'{content}' is not a valid parameter. Use * for documentation bullets.",
                    line=entity.heading_line,
                    suggestion=(
                        "Parameters must be key: value pairs:\n"
                        "    - type: shell\n"
                        "    - timeout: 30\n\n"
                        "For notes, use * instead of -:\n"
                        "    * This is a documentation note"
                    ),
                )

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


def _parse_next_targets(value: str) -> list[str]:
    """Parse next field value into target list.

    Handles: "node-id" (single), "end" (terminal), "a, b, c" (routing list).
    """
    if "," in str(value):
        return [t.strip() for t in str(value).split(",") if t.strip()]
    return [str(value).strip()]


def _extract_next_targets_from_code(code: str) -> tuple[list[str], bool]:
    """Extract literal 'next' assignment targets from Python code via AST.

    Finds ``next: str = "node-id"`` (AnnAssign) and ``next = "node-id"`` (Assign).
    Only extracts string literals. Dynamic values are tracked separately.

    Returns:
        Tuple of (literal_targets, has_dynamic). has_dynamic is True when any
        assignment to ``next`` uses a non-literal value (e.g. ``next = variable``).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return [], False

    targets: list[str] = []
    has_dynamic = False
    for node in ast.walk(tree):
        # Annotated assignment: next: str = "literal" or next: str = variable
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "next"
            and node.value is not None
        ) or (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "next"
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                targets.append(node.value.value)
            else:
                has_dynamic = True

    seen: set[str] = set()
    unique: list[str] = []
    for t in targets:
        # "end" is a special keyword for flow termination, not a node reference
        if t not in seen and t != "end":
            seen.add(t)
            unique.append(t)
    return unique, has_dynamic


def _build_edges(
    nodes: list[dict[str, Any]],
    routing_metadata: dict[str, dict[str, Any]],
    ast_routing_targets: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Build edge list from node order, routing metadata, and AST targets.

    Rules:
    - next: end -> no outgoing edge (terminal keyword, filtered from targets)
    - next: node-id -> edge with action "default" (overrides document order)
    - next: a, b, c -> edges with action = target node ID
    - No next -> document-order edge to next node (no action field)
    - on-error: node-id -> edge with action "error"
    - AST next = "literal" -> edge with action = literal string
    """
    edges: list[dict[str, Any]] = []

    for i, node in enumerate(nodes):
        node_id = node["id"]
        routing = routing_metadata.get(node_id, {})
        next_value = routing.get("next")
        on_error_target = routing.get("on_error")
        code_targets = ast_routing_targets.get(node_id, [])

        # Default / next edges
        if next_value is not None:
            targets = _parse_next_targets(str(next_value))
            real_targets = [t for t in targets if t != "end"]
            if not real_targets:
                pass  # Terminal: "end" only, no outgoing edge
            elif len(real_targets) == 1:
                edges.append({"from": node_id, "to": real_targets[0], "action": "default"})
            else:
                # Multi-target: all get named edges, first also gets default
                for target in real_targets:
                    edges.append({"from": node_id, "to": target, "action": target})
                edges.append({"from": node_id, "to": real_targets[0], "action": "default"})
        else:
            # Document-order default edge
            if i < len(nodes) - 1:
                edges.append({"from": node_id, "to": nodes[i + 1]["id"]})

        # Error edge
        if on_error_target:
            edges.append({"from": node_id, "to": str(on_error_target), "action": "error"})

        # AST-detected routing edges (skip duplicates already covered)
        existing_actions = {(e["from"], e.get("action")) for e in edges}
        for target in code_targets:
            if (node_id, target) not in existing_actions:
                edges.append({"from": node_id, "to": target, "action": target})

    return edges


def _validate_routing_targets(
    edges: list[dict[str, Any]],
    node_ids: set[str],
) -> None:
    """Validate all edge targets reference existing node IDs."""
    for edge in edges:
        target = edge["to"]
        source = edge["from"]
        if target not in node_ids:
            similar = find_similar_items(target, sorted(node_ids), method="fuzzy", cutoff=0.4)
            if similar:
                suggestion = f"Did you mean: {', '.join(similar)}?"
            else:
                suggestion = f"Available nodes: {', '.join(sorted(node_ids))}"
            raise MarkdownParseError(f"Node '{source}' references unknown target '{target}'. {suggestion}")


def _validate_dynamic_next_declarations(
    routing_metadata: dict[str, dict[str, Any]],
    ast_has_dynamic: set[str],
) -> None:
    """Check that code nodes with dynamic ``next`` have ``- next:`` declarations."""
    for node_id in sorted(ast_has_dynamic):
        routing = routing_metadata.get(node_id, {})
        if "next" not in routing:
            raise MarkdownParseError(
                f"Node '{node_id}' uses dynamic routing (next = <expression>) but has no "
                f"'- next:' declaration. Routing targets must be declared so pflow can "
                f"create the edges that PocketFlow needs to follow at runtime.\n\n"
                f"Fix: Add '- next:' listing all possible routing targets:\n\n"
                f"    ### {node_id}\n"
                f"    - type: code\n"
                f"    - next: target-a, target-b\n\n"
                f"Without '- next:', the flow will silently stop when code sets next at runtime.",
                see_also=["branching"],
            )


def _build_branch_target_routers(
    edges: list[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, dict[str, list[str]]]]:
    """Build branch-target router maps.

    Returns two parallel structures:
    - ``branch_target_routers``: target_id → set of router source node IDs.
    - ``router_actions``: target_id → source_id → list of action values
      (preserves routing mechanism per (router, target) pair, used for
      annotating error messages with e.g. ``(on-error)``).

    A "branch target" is any node reached via an edge with action not in
    ``{None, "default"}``.
    """
    branch_target_routers: dict[str, set[str]] = {}
    router_actions: dict[str, dict[str, list[str]]] = {}
    for edge in edges:
        action = edge.get("action")
        if action is not None and action != "default":
            target = edge["to"]
            source = edge["from"]
            branch_target_routers.setdefault(target, set()).add(source)
            router_actions.setdefault(target, {}).setdefault(source, []).append(action)
    return branch_target_routers, router_actions


def _format_router_list(
    routers: set[str],
    target_id: str,
    router_actions: dict[str, dict[str, list[str]]],
) -> str:
    """Format a router list with ``(on-error)`` annotation where unambiguous.

    A router is annotated ``(on-error)`` only when all of its actions for this
    target are ``"error"``. Mixed mechanisms are left unannotated — the edge
    schema cannot distinguish dynamic-python routing from static multi-target
    literal routing, so we only surface the distinction that IS reliable.
    """
    actions_for_target = router_actions.get(target_id, {})
    parts = []
    for r in sorted(routers):
        actions = actions_for_target.get(r, [])
        # `actions and` is load-bearing: without it, `all(... for [])` is
        # vacuously True, so any missing (router, target) pair would
        # silently annotate as (on-error). Today both maps are populated
        # in lockstep by `_build_branch_target_routers`; this guard
        # protects against drift.
        if actions and all(a == "error" for a in actions):
            parts.append(f"'{r}' (on-error)")
        else:
            parts.append(f"'{r}'")
    return ", ".join(parts)


def _infer_convergence_candidate(
    edges: list[dict[str, Any]],
    branch_target_routers: dict[str, set[str]],
    source: str,
) -> str | None:
    """Infer a likely convergence node that a fall-through source should route to.

    A convergence node is one that multiple branch targets explicitly route
    into via ``- next:`` (edge with ``action="default"``). Returns the candidate
    with the most branch-target voters, or ``None`` when evidence is weak
    (fewer than 2 voters). Conservative by design: false negatives are fine,
    false positives would mislead the user worse than the current behavior.

    The threshold is 2 because a single vote is indistinguishable from
    incidental coincidence — any branch target with a ``- next:`` declaration
    produces one vote for its target, so a single voter is the baseline, not
    evidence of convergence. Raising the threshold beyond 2 makes inference
    rarer; lowering it to 1 crosses from inference into guessing.
    """
    votes: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("action") == "default" and edge["from"] in branch_target_routers:
            votes.setdefault(edge["to"], set()).add(edge["from"])

    candidates = [
        (len(voters), cid)
        for cid, voters in votes.items()
        if cid not in branch_target_routers and cid != source and len(voters) >= 2
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (-c[0], c[1]))
    return candidates[0][1]


def _validate_branch_targets_have_next(
    edges: list[dict[str, Any]],
    routing_metadata: dict[str, dict[str, Any]],
    branch_target_routers: dict[str, set[str]],
    router_actions: dict[str, dict[str, list[str]]],
    heading_lines: dict[str, int],
) -> None:
    """Check that branch targets have explicit ``- next:`` directives."""
    doc_order_targets: dict[str, str] = {}
    for edge in edges:
        if "action" not in edge:
            doc_order_targets[edge["from"]] = edge["to"]

    for target_id in sorted(branch_target_routers):
        routers = branch_target_routers[target_id]
        routing = routing_metadata.get(target_id, {})
        if "next" in routing:
            continue

        router_list = _format_router_list(routers, target_id, router_actions)
        doc_successor = doc_order_targets.get(target_id)
        # Only suggest the successor as a continuation if it's not itself a
        # branch target. Suggesting a branch target as a "next step" creates
        # a cascade: applying the fix produces a new missing-`- next:` error
        # on the successor, and iterated suggestions can form runtime cycles.
        # Symmetric with `_infer_convergence_candidate`'s filter.
        suggest_successor = doc_successor if doc_successor and doc_successor not in branch_target_routers else None

        if doc_successor:
            context = (
                f"Without it, execution would fall through to '{doc_successor}' "
                f"via document order — pflow rejects this to prevent silent routing bugs."
            )
        else:
            context = "Branch targets must declare their exit explicitly to prevent silent routing bugs."

        if suggest_successor:
            fix_body = (
                f"Fix — add '- next:' to '### {target_id}'. "
                f"Either continue to the next step:\n\n"
                f"    - next: {suggest_successor}\n\n"
                f"Or terminate the branch:\n\n"
                f"    - next: end"
            )
        else:
            fix_body = f"Fix — add an explicit terminator to '### {target_id}':\n\n    - next: end"

        raise MarkdownParseError(
            f"Node '{target_id}' is a routing target of {router_list} but has no "
            f"'- next:' directive. {context}\n\n{fix_body}",
            line=heading_lines.get(target_id),
            see_also=["branching"],
        )


def _validate_no_fallthrough_into_branch_targets(
    edges: list[dict[str, Any]],
    branch_target_routers: dict[str, set[str]],
    router_actions: dict[str, dict[str, list[str]]],
    heading_lines: dict[str, int],
) -> None:
    """Check that non-router nodes don't fall through into branch targets."""
    for edge in edges:
        if "action" not in edge:  # Document-order edge
            target = edge["to"]
            source = edge["from"]
            if target in branch_target_routers:
                routers = branch_target_routers[target]
                if source not in routers:
                    router_list = _format_router_list(routers, target, router_actions)
                    convergence = _infer_convergence_candidate(edges, branch_target_routers, source)

                    if convergence:
                        fix_body = (
                            f"Fix — add '- next:' to '### {source}'. "
                            f"Either continue past the branch section to the convergence point "
                            f"(inferred: '{convergence}' is where other branch targets route):\n\n"
                            f"    - next: {convergence}\n\n"
                            f"Or terminate the flow:\n\n"
                            f"    - next: end"
                        )
                    else:
                        fix_body = f"Fix — add an explicit '- next:' to '### {source}':\n\n    - next: end"

                    raise MarkdownParseError(
                        f"Node '{source}' flows into '{target}' via document order, but "
                        f"'{target}' is a routing target of {router_list}. Main flow nodes "
                        f"must not silently fall through into branch targets.\n\n"
                        f"{fix_body}",
                        line=heading_lines.get(source),
                        see_also=["branching"],
                    )


def _validate_branch_target_routing(
    edges: list[dict[str, Any]],
    routing_metadata: dict[str, dict[str, Any]],
    ast_has_dynamic: set[str],
    heading_lines: dict[str, int],
) -> None:
    """Validate that branch targets have explicit routing to prevent fall-through.

    Three checks:
    1. Dynamic ``next`` in code without ``- next:`` declaration on the node.
    2. Branch targets (nodes reached via named action edges) without ``- next:``.
    3. Non-router nodes that fall through into branch targets via document order.

    Raises:
        MarkdownParseError: On the first violation found.
    """
    _validate_dynamic_next_declarations(routing_metadata, ast_has_dynamic)

    branch_target_routers, router_actions = _build_branch_target_routers(edges)
    if not branch_target_routers:
        return  # No branch targets — nothing to validate

    _validate_branch_targets_have_next(edges, routing_metadata, branch_target_routers, router_actions, heading_lines)
    _validate_no_fallthrough_into_branch_targets(edges, branch_target_routers, router_actions, heading_lines)


def _build_node_dict(entity: _Entity) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a node dict and routing metadata from an entity.

    Routes: type -> top-level, batch -> top-level, prose -> purpose,
    next/on-error -> routing metadata, everything else -> params.

    Returns:
        Tuple of (node_dict, routing_dict). Routing dict may contain
        "next" and/or "on_error" keys.
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

    # Extract cache (goes to top-level, not params)
    if "cache" in all_params:
        node["cache"] = all_params.pop("cache")

    # Extract routing metadata (not stored in params)
    routing: dict[str, Any] = {}
    if "next" in all_params:
        routing["next"] = all_params.pop("next")
    if "on-error" in all_params:
        routing["on_error"] = all_params.pop("on-error")

    # Purpose from prose
    prose = _get_prose(entity)
    if prose:
        node["purpose"] = prose

    _route_code_blocks_to_node(entity, node, all_params)

    if all_params:
        node["params"] = all_params

    return node, routing


def _build_output_dict(entity: _Entity) -> dict[str, Any]:
    """Build an output definition dict from an entity.

    Outputs get flat dicts (no params wrapper).
    Valid fields: description, type, source, stdout.
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

    # Track source line for `source:` (used by template errors)
    if "source" in params:
        for idx, key in enumerate(entity.yaml_item_keys):
            if key == "source" and idx < len(entity.yaml_item_lines):
                result["_source_line"] = entity.yaml_item_lines[idx]
                break

    # Code blocks — source goes directly to output
    for block in entity.code_blocks:
        if block.param_name == "source":
            result["source"] = block.content
            result["_source_line"] = block.start_line + 1
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
