"""Constants, configuration, context object, and pure utility functions for mermaid generation."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

logger = logging.getLogger("pflow.core.workflow.mermaid")

# ---------------------------------------------------------------------------
# Shape mapping: node_type -> (open_bracket, close_bracket, css_class)
# ---------------------------------------------------------------------------

_SHAPE_MAP: dict[str, tuple[str, str, str]] = {
    "llm": ("([", "])", "llm"),
    "shell": ("[[", "]]", "shell"),
    "write-file": ("[(", ")]", "writefile"),
    "code": ("[", "]", "code"),
    "workflow": ("(", ")", "workflow"),
}

# Batch item label extraction
_LABEL_KEYS = ("name", "label", "focus", "lens")
_SKIP_KEYS = ("workflow", "prompt", "command", "model")

# Reserved workflow params (not child inputs)
_RESERVED_PARAMS = {"workflow", "storage_mode", "type"}

# Style declarations
_CLASSDEF_STYLES: dict[str, str] = {
    "code": "fill:#D5E8D4,stroke:#82B366,color:#000",
    "llm": "fill:#E8D5F5,stroke:#7B2D8E,color:#000",
    "shell": "fill:#DAE8FC,stroke:#6C8EBF,color:#000",
    "mcp": "fill:#FFE6CC,stroke:#D79B00,color:#000",
    "writefile": "fill:#F8CECC,stroke:#B85450,color:#000",
    "workflow": "fill:#FFF2CC,stroke:#D6B656,color:#000",
    "decision": "fill:#F5F5F5,stroke:#666666,color:#000",
    "input": "fill:#F5F5F5,stroke:#666666,stroke-dasharray:5 5,color:#000",
    "output": "fill:#E8E8E8,stroke:#666666,color:#000",
}

# Regex patterns
_SOURCE_NODE_FIELD_RE = re.compile(r"(?:^|[\s{?])([a-zA-Z0-9_-]+)\.([a-zA-Z0-9_-]+)")
_PARAM_REF_RE = re.compile(r"\$\{([a-zA-Z0-9_-]+)(?:\.|\})")

# Workflow types eligible for sub-workflow expansion
_WORKFLOW_TYPES = {"workflow", "pflow.runtime.workflow_executor"}

# Subgraph nesting opacity: linear ramp, each depth level gets 7% more opaque
_SUBGRAPH_OPACITIES = [0.07, 0.14, 0.21, 0.28]


# ---------------------------------------------------------------------------
# Configuration and context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MermaidConfig:
    """Immutable configuration for a single generate_mermaid call."""

    resolve_child: Optional[Callable[[dict[str, Any], Optional[Path]], Optional[SubWorkflowResult]]]
    max_depth: int
    direction: str
    descriptions: bool


class MermaidContext:
    """Mutable rendering state for one workflow level.

    Shared across all recursion levels: ``lines`` and ``seen`` are the same
    object reference.  Per-level state (routing maps, indent, prefix) is fresh
    for each ``_render_workflow`` call.
    """

    def __init__(
        self,
        config: MermaidConfig,
        lines: list[str],
        seen: set[str],
        prefix: str = "",
        current_depth: int = 0,
        suppress_io: bool = False,
        base_path: Optional[Path] = None,
    ) -> None:
        # Immutable config
        self.config = config

        # Shared across all recursion levels (same object reference)
        self.lines = lines
        self.seen = seen

        # Per-level identity
        self.prefix = prefix
        self.current_depth = current_depth
        self.indent = "    " * (current_depth + 1)
        self.suppress_io = suppress_io
        self.base_path = base_path

        # Per-level routing state (fresh for each _render_workflow call)
        self.fork_join_map: dict[str, list[str]] = {}
        self.outgoing_routes: dict[str, dict[str, str]] = {}
        self.has_expanded_outputs: set[str] = set()
        self.incoming_map: dict[str, dict[str, str]] = {}
        self.data_flow_targets: set[str] = set()

        # Per-level IR-derived state (set by _render_workflow after creation)
        self.decision_nodes: set[str] = set()
        self.parent_inputs: dict[str, Any] = {}
        self.sibling_node_ids: set[str] = set()

    def child(
        self,
        prefix: str,
        suppress_io: bool = False,
        base_path: Optional[Path] = None,
    ) -> "MermaidContext":
        """Create a child context for recursive sub-workflow rendering."""
        return MermaidContext(
            config=self.config,
            lines=self.lines,  # shared reference
            seen=self.seen,  # shared reference
            prefix=prefix,
            current_depth=self.current_depth + 1,
            suppress_io=suppress_io,
            base_path=base_path if base_path is not None else self.base_path,
        )


# ---------------------------------------------------------------------------
# Pure utility functions
# ---------------------------------------------------------------------------


def _to_mermaid_id(node_id: str) -> str:
    """Convert a pflow node ID to a valid Mermaid node ID.

    Returns the ID unchanged — hyphens and underscores are both valid
    in Mermaid's bracket syntax (``id["label"]``), so no sanitization
    is needed. Replacing hyphens with underscores would cause ID
    collisions between ``foo-bar`` and ``foo_bar``.
    """
    return node_id


def _escape_label(text: str) -> str:
    """Escape special characters for Mermaid node and edge labels."""
    return text.replace('"', "&quot;").replace("|", "&#124;")


def _get_node_shape(node_type: str, is_decision: bool) -> tuple[str, str, str]:
    """Return (open_bracket, close_bracket, css_class) for a node's Mermaid shape.

    Decision nodes always get diamond shape regardless of type.
    MCP nodes (type starts with "mcp") get hexagon shape.
    """
    if is_decision:
        return ("{", "}", "decision")
    if node_type.startswith("mcp"):
        return ("{{", "}}", "mcp")
    return _SHAPE_MAP.get(node_type, ("[", "]", "code"))


def _format_node_type(node_type: str) -> str:
    """Format node type for display in labels.

    MCP types are long (``mcp-klavis-youtube-get_youtube_video_transcript``).
    Format as ``mcp:<br/>klavis-youtube-get_youtube_video_transcript`` for readability.
    """
    if node_type.startswith("mcp-"):
        return f"mcp:<br/>{node_type[4:]}"
    return node_type


def _format_label(
    node_id: str,
    node_type: str,
    descriptions: bool,
    purpose: str,
    batch_suffix: str = "",
) -> str:
    """Format the full display label for a node.

    The batch suffix (e.g., ``(parallel x|sources|)``) is appended AFTER
    escaping because it contains ``|`` delimiters that must be preserved
    in ``@{ shape: procs }`` labels.
    """
    display_type = _format_node_type(node_type)
    label = f"{node_id} ({display_type})"
    if descriptions and purpose:
        label += f"<br/>{_first_sentence(purpose)}"
    label = _escape_label(label)
    if batch_suffix:
        label += f"<br/>{batch_suffix}"
    return label


def _first_sentence(text: str) -> str:
    """Extract first sentence from a purpose string, stripped of markdown formatting."""
    # Strip bold and italic markdown
    clean = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    clean = re.sub(r"\*(.+?)\*", r"\1", clean)
    # Find first sentence
    match = re.match(r"([^.!?]+[.!?])", clean)
    if match:
        return match.group(1)[:80]
    return clean[:80]


def _classdef_to_style(css_class: str) -> str:
    """Return inline style properties for a classDef name.

    Used for nodes that can't use ``:::classDef`` syntax (e.g., ``@{ shape: procs }``).
    """
    return _CLASSDEF_STYLES.get(css_class, _CLASSDEF_STYLES["code"])


def _subgraph_style(mermaid_id: str, depth: int) -> str:
    """Return a Mermaid style directive for subgraph nesting depth.

    Uses a neutral gray with increasing ``fill-opacity`` so nesting is
    visible on both light and dark themes.
    """
    opacity = _SUBGRAPH_OPACITIES[min(depth, len(_SUBGRAPH_OPACITIES) - 1)]
    return f"style {mermaid_id} fill:#808080,fill-opacity:{opacity},stroke:#999"


def _get_item_label(item: Any, index: int) -> str:
    """Extract a meaningful short label from a batch item dict."""
    if not isinstance(item, dict):
        return f"#{index + 1}"
    # Try priority keys
    for key in _LABEL_KEYS:
        val = item.get(key)
        if isinstance(val, str):
            return val
    # Fallback: first short string value not in skip keys
    for key, val in item.items():
        if key in _SKIP_KEYS:
            continue
        if isinstance(val, str) and len(val) <= 30:
            return val
    return f"#{index + 1}"


def _dynamic_batch_label(batch: Optional[dict[str, Any]]) -> str:
    """Return a batch suffix string like ' (parallel x|sources|)' for dynamic batch.

    Extracts the source variable name from the template ref (first segment
    of ``${ref.field}``), e.g. ``${sources}`` -> ``sources``,
    ``${zip-concepts-with-briefs.result}`` -> ``zip-concepts-with-briefs``.
    """
    if not batch or not isinstance(batch.get("items"), str):
        return ""
    items_ref = batch["items"]
    # Extract first segment from ${ref.field...}
    match = _PARAM_REF_RE.search(items_ref)
    source_name = match.group(1) if match else "N"
    parallel_prefix = "parallel " if batch.get("parallel", False) else ""
    return f" ({parallel_prefix}x|{source_name}|)"


def _refs_input(value: str, input_name: str) -> bool:
    """Check if a string value references a top-level input by name."""
    return f"${{{input_name}}}" in value or f"${{{input_name}." in value


def _collect_param_refs(params: dict[str, Any]) -> list[str]:
    """Collect all string values from params, including one level of nested dicts.

    Code nodes store declared inputs at ``params.inputs`` (a nested dict),
    so we recurse one level to find those refs too.
    """
    refs: list[str] = []
    for value in params.values():
        if isinstance(value, str):
            refs.append(value)
        elif isinstance(value, dict):
            refs.extend(v for v in value.values() if isinstance(v, str))
    return refs


def _render_classdefs(ctx: MermaidContext) -> None:
    """Add classDef color declarations at the top of the graph."""
    for name, style in _CLASSDEF_STYLES.items():
        ctx.lines.append(f"    classDef {name} {style}")
