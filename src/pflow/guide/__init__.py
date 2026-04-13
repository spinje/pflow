"""Guide content composition for the pflow CLI."""

from __future__ import annotations

from pathlib import Path

GUIDE_DIR = Path(__file__).parent

# Node types that don't map 1:1 to guide topic names.
_NODE_TYPE_TO_TOPIC: dict[str, str] = {
    "read-file": "file",
    "write-file": "file",
    "workflow": "sub-workflows",
}

# Guide topic → registry node type(s) for dynamic interface injection.
# Topics not listed here get static content only (e.g., mcp — user-specific tools).
_TOPIC_TO_NODE_TYPES: dict[str, list[str]] = {
    "http": ["http"],
    "llm": ["llm"],
    "code": ["code"],
    "shell": ["shell"],
    "file": ["read-file", "write-file"],
}


class GuideError(Exception):
    """Raised when guide topic resolution fails."""


def render_entry_content() -> str:
    """Return the shared entry content for ``pflow --help`` and ``pflow guide``."""
    entry_path = GUIDE_DIR / "entry.md"
    try:
        if entry_path.exists():
            content = entry_path.read_text(encoding="utf-8")
            if content.strip():
                return content
    except (OSError, UnicodeDecodeError):
        pass
    return _placeholder_entry_content()


def compose_guide(args: list[str]) -> str:
    """Compose guide content from topic names and/or workflow references.

    Each arg is either a topic name (``http``, ``core``, ``batch``),
    a workflow file path (contains ``/`` or ends ``.pflow.md``),
    or a saved workflow name.  Workflow references are parsed and
    topics auto-detected from the IR.

    Returns the composed markdown content with ``---`` separators.
    Raises :class:`GuideError` on unknown topics or bad workflow refs.
    """
    if not args:
        return render_entry_content()

    topics: list[str] = []
    seen: set[str] = set()

    for arg in args:
        detected = _resolve_arg(arg)
        for topic in detected:
            if topic not in seen:
                topics.append(topic)
                seen.add(topic)

    parts: list[str] = []
    for topic in topics:
        path = _resolve_topic_path(topic)
        if path is None:
            available = ", ".join(list_topics())
            raise GuideError(
                f"Unknown topic '{topic}'. Available topics: {available}.\nRun `pflow guide` for the full menu."
            )
        content = path.read_text(encoding="utf-8").rstrip()

        # Append dynamic interface for node topics
        interface = _get_node_interface(topic)
        if interface:
            content = content + "\n\n---\n\n" + interface

        parts.append(content)

    return "\n\n---\n\n".join(parts) + "\n"


def list_topics() -> list[str]:
    """Return all available guide topic names (sorted, core first)."""
    topics: list[str] = []
    if (GUIDE_DIR / "core.md").exists():
        topics.append("core")
    for subdir in ("nodes", "features"):
        d = GUIDE_DIR / subdir
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                topics.append(f.stem)
    return topics


def detect_topics_from_ir(ir: dict) -> list[str]:
    """Detect guide topics from a parsed workflow IR.

    Walks nodes and edges to determine which guide topics are relevant.
    Only returns topics that have corresponding guide files.
    """
    topics: set[str] = set()
    available = set(list_topics())

    for node in ir.get("nodes", []):
        node_type = node.get("type", "")

        # Map node type to guide topic
        topic = _NODE_TYPE_TO_TOPIC.get(node_type)
        if topic is None and node_type.startswith("mcp-"):
            topic = "mcp"
        if topic is None:
            topic = node_type

        if topic in available:
            topics.add(topic)

        # Batch detection (batch is at node top-level, not in params)
        if node.get("batch") is not None:
            topics.add("batch")

    # Branching detection via non-default edge actions
    for edge in ir.get("edges", []):
        action = edge.get("action", "default")
        if action != "default":
            topics.add("branching")
            break

    return sorted(topics)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_arg(arg: str) -> list[str]:
    """Resolve a CLI arg to one or more topic names."""
    # File path heuristic: contains / or ends with .pflow.md
    if "/" in arg or arg.endswith(".pflow.md"):
        return _topics_from_workflow_file(arg)

    # Known topic name (wins over saved workflow names)
    if _resolve_topic_path(arg) is not None:
        return [arg]

    # Saved workflow name
    ir = _try_load_saved_workflow(arg)
    if ir is not None:
        return detect_topics_from_ir(ir)

    # Unknown — return as-is so compose_guide raises a clear error
    return [arg]


def _resolve_topic_path(topic: str) -> Path | None:
    """Find the markdown file for a topic name, or None."""
    if topic == "core":
        path = GUIDE_DIR / "core.md"
        return path if path.exists() else None

    for subdir in ("nodes", "features"):
        path = GUIDE_DIR / subdir / f"{topic}.md"
        if path.exists():
            return path

    return None


def _topics_from_workflow_file(path_str: str) -> list[str]:
    """Parse a workflow file and detect topics from its IR."""
    from pflow.core.markdown_parser import MarkdownParseError, parse_markdown

    path = Path(path_str)
    if not path.exists():
        raise GuideError(
            f"Workflow file not found: {path_str}\n"
            f"To see saved workflows: `pflow list`\n"
            f"To see guide topics: `pflow guide`"
        )

    try:
        result = parse_markdown(path.read_text(encoding="utf-8"))
        topics = detect_topics_from_ir(result.ir)
        if not topics:
            raise GuideError(
                f"No guide topics detected in {path_str} "
                f"(workflow has no recognizable node types).\n"
                f"Use explicit topics instead: `pflow guide <topics...>`"
            )
        return topics
    except MarkdownParseError as e:
        raise GuideError(
            f"Failed to parse workflow {path_str}: {e}\nUse explicit topics instead: `pflow guide <topics...>`"
        ) from e


def _try_load_saved_workflow(name: str) -> dict | None:
    """Try to load a saved workflow's IR.

    Returns None only when the workflow doesn't exist.
    Raises :class:`GuideError` when the workflow exists but is broken.
    """
    try:
        from pflow.core.exceptions import WorkflowNotFoundError
        from pflow.core.workflow.manager import WorkflowManager

        wm = WorkflowManager()
        return wm.load_ir(name)
    except WorkflowNotFoundError:
        return None
    except Exception as e:
        raise GuideError(
            f"Saved workflow '{name}' failed to load: {e}\nUse explicit topics instead: `pflow guide <topics...>`"
        ) from e


def _get_node_interface(topic: str) -> str | None:
    """Load dynamic interface from registry for a node topic.

    Returns formatted Parameters + Outputs markdown, or None if the topic
    has no registry mapping (e.g., mcp, features, core).
    """
    node_types = _TOPIC_TO_NODE_TYPES.get(topic)
    if not node_types:
        return None

    try:
        from pflow.registry.registry import Registry

        registry = Registry()
        metadata = registry.load()
    except Exception:
        return None

    multi = len(node_types) > 1
    sections: list[str] = []
    for node_type in node_types:
        if node_type not in metadata:
            continue
        interface = metadata[node_type].get("interface", {})
        section = _format_interface(node_type, interface, multi)
        if section:
            sections.append(section)

    return "\n\n".join(sections) if sections else None


def _format_interface(node_type: str, interface: dict, show_node_heading: bool) -> str:
    """Format Parameters and Outputs sections from registry interface data.

    When *show_node_heading* is True (multi-node topics like ``file``),
    each node type gets its own ``###`` heading.  Otherwise, just
    ``### Parameters`` and ``### Outputs`` headings are used.
    """
    lines: list[str] = []

    if show_node_heading:
        desc = interface.get("description", "")
        lines.append(f"### {node_type}")
        if desc:
            lines.append(desc)
        lines.append("")

    # Merge inputs + params, filter out extractor artifacts
    all_params = [
        p for p in list(interface.get("inputs", [])) + list(interface.get("params", [])) if p.get("key") != "default"
    ]
    if all_params:
        if show_node_heading:
            lines.append("**Parameters**:")
        else:
            lines.append("### Parameters")
            lines.append("")
        for p in all_params:
            lines.append(_format_param_line(p))
        lines.append("")

    # Outputs (filter artifacts and internal keys)
    outputs = [
        o for o in interface.get("outputs", []) if o.get("key") != "default" and not o.get("key", "").startswith("_")
    ]
    if outputs:
        if show_node_heading:
            lines.append("**Outputs**:")
        else:
            lines.append("### Outputs")
            lines.append("")
        for o in outputs:
            key = o.get("key", "")
            otype = o.get("type", "")
            desc = o.get("description", "")
            line = f"- `{key}: {otype}`"
            if desc:
                line += f" - {desc}"
            lines.append(line)

    return "\n".join(lines).rstrip()


def _format_param_line(param: dict) -> str:
    """Format a single parameter as a markdown list item."""
    key = param.get("key", "")
    ptype = param.get("type", "")
    desc = param.get("description", "")
    # Clean up descriptions that got truncated by the extractor bug
    # e.g., "Variable name to value mapping (optional" → add closing paren
    if desc.endswith("(optional"):
        desc += ")"
    line = f"- `{key}: {ptype}`"
    if desc:
        line += f" - {desc}"
    return line


def _placeholder_entry_content() -> str:
    return """\
pflow runs workflows — sequences of nodes (http, shell, llm, code, file, mcp) \
that chain together through a shared data store.

Quick start:
  pflow <workflow-file>       Run a workflow file
  pflow <saved-name>          Run a saved workflow
  pflow list                  List saved workflows
  pflow find "description"    Search workflows by intent (LLM-powered)
  pflow guide                 Learn how to build workflows
  pflow mcp list              List available MCP tools

Use 'pflow <command> --help' for details on any command.
"""
