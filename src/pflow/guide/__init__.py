"""Guide content composition for the pflow CLI."""

from __future__ import annotations

from pathlib import Path

GUIDE_DIR = Path(__file__).parent
PROMPT_CACHING_TOPIC = "prompt-caching"

# Topic output gets the read-completeness header + end-marker only when it's
# large enough that a calling tool might truncate it. Small fetches (a single
# small topic) are not truncated in practice, so framing them is pure overhead.
# 20KB sits above every single small topic and below `core` and all multi-topic
# output — the failure class where an agent silently misses a whole section.
# Tunable risk dial: lower = safer against aggressive truncators, higher = less
# overhead on mid-size output.
_FRAME_THRESHOLD_BYTES = 20_000

# Backward-compatible topic aliases. Keep aliases out of auto-detection and
# menu text so generated guide pointers use the clearest public topic name.
_TOPIC_ALIASES: dict[str, str] = {
    "caching": PROMPT_CACHING_TOPIC,
}

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
    "claude-code": ["claude-code"],
    "code": ["code"],
    "shell": ["shell"],
    "file": ["read-file", "write-file", "copy-file", "move-file", "delete-file"],
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
            canonical_topic = _canonical_topic(topic)
            if canonical_topic not in seen:
                topics.append(canonical_topic)
                seen.add(canonical_topic)

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

    body = "\n\n---\n\n".join(parts)
    if len(body) < _FRAME_THRESHOLD_BYTES:
        return body + "\n"
    return _frame_topics(body, len(topics))


def _frame_topics(body: str, n: int) -> str:
    """Frame composed topic content with a read-completeness header and end-marker.

    Only called for output large enough to risk truncation (see
    ``_FRAME_THRESHOLD_BYTES``). The header goes at the very top because calling
    tools that truncate large output keep the *start* and drop the *end* — a
    trailing reminder would be in the region that gets cut. It tells the agent that
    a preview means the tool has preserved the full text elsewhere (file/pagination)
    to be read there rather than re-fetched, and points at the end-marker as the
    completeness check. The marker's absence proves the output was truncated.

    ``marker`` is computed once so the header's claim and the trailing line cannot
    drift on pluralization.
    """
    sections = "section" if n == 1 else "sections"
    marker = f"⟨END OF GUIDE — {n} {sections}⟩"
    header = (
        f"> **{n} guide {sections} below, split by `---`. Read each to the END before building** "
        "— they're condensed, so skimming means wrong format rules.\n"
        "> Output is long: if you see only a **preview**, the full text is preserved elsewhere "
        "(a file your tool names, or pagination) — open and read it there. "
        "Don't build from the preview, and don't re-run this command.\n"
        f"> Done only when you reach the last line `{marker}` — if you're not there, you haven't read it all."
    )
    return f"{header}\n\n{body}\n\n---\n\n{marker}\n"


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


def _node_topics(node: dict, available: set[str]) -> set[str]:
    """Guide topics implied by a single node (type + top-level feature blocks)."""
    topics: set[str] = set()
    node_type = node.get("type", "")

    topic = _NODE_TYPE_TO_TOPIC.get(node_type)
    if topic is None and node_type.startswith("mcp-"):
        topic = "mcp"
    if topic is None:
        topic = node_type
    if topic in available:
        topics.add(topic)

    if node.get("batch") is not None:  # batch is at node top-level, not in params
        topics.add("batch")
    if node.get("loop") is not None:
        topics.add("loop")
    if node.get("retry") is not None:
        topics.add("error-handling")
    # Caching: per-node opt-in. Presence (not truthiness) — ``prewarm: false`` is
    # still engaging with the feature and should surface the guide.
    if node.get("prompt_cache") is not None or node.get("prewarm") is not None:
        topics.add(PROMPT_CACHING_TOPIC)
    return topics


def detect_topics_from_ir(ir: dict) -> list[str]:
    """Detect guide topics from a parsed workflow IR.

    Walks nodes and edges to determine which guide topics are relevant.
    Only returns topics that have corresponding guide files. Does not walk
    into sub-workflow files; see ``_topics_from_workflow_file`` for tree walking.
    """
    topics: set[str] = set()
    available = set(list_topics())

    for node in ir.get("nodes") or []:
        topics |= _node_topics(node, available)

    # Caching detection: top-level ``## Cache`` block.
    if ir.get("cache") is not None:
        topics.add(PROMPT_CACHING_TOPIC)

    # Branching / error-handling detection via non-default edge actions
    for edge in ir.get("edges") or []:
        action = edge.get("action", "default")
        if action == "error":
            topics.add("error-handling")
        elif action != "default":
            topics.add("branching")

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
        return [_canonical_topic(arg)]

    # Saved workflow name — route through the file walker so sub-workflows
    # are walked the same way as for an explicit file path.
    saved_path = _try_get_saved_workflow_path(arg)
    if saved_path is not None:
        return _topics_from_workflow_file(saved_path)

    # Unknown — return as-is so compose_guide raises a clear error
    return [arg]


def _resolve_topic_path(topic: str) -> Path | None:
    """Find the markdown file for a topic name, or None."""
    topic = _canonical_topic(topic)
    if topic == "core":
        path = GUIDE_DIR / "core.md"
        return path if path.exists() else None

    for subdir in ("nodes", "features"):
        path = GUIDE_DIR / subdir / f"{topic}.md"
        if path.exists():
            return path

    return None


def _canonical_topic(topic: str) -> str:
    """Return the preferred topic name for a user-supplied topic or alias."""
    return _TOPIC_ALIASES.get(topic, topic)


def _topics_from_workflow_file(path_str: str) -> list[str]:
    """Parse a workflow file and detect topics from its IR + sub-workflows.

    Root parse errors raise :class:`GuideError`; descendant parse / load
    errors fail-soft with a stderr warning so a broken sub-workflow doesn't
    block the parent's guide.
    """
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
    except MarkdownParseError as e:
        raise GuideError(
            f"Failed to parse workflow {path_str}: {e}\nUse explicit topics instead: `pflow guide <topics...>`"
        ) from e

    topics = _collect_topics(result.ir, base=path.parent, seen={str(path.resolve())})
    if not topics:
        raise GuideError(
            f"No guide topics detected in {path_str} "
            f"(workflow has no recognizable node types).\n"
            f"Use explicit topics instead: `pflow guide <topics...>`"
        )
    return sorted(topics)


def _collect_topics(ir: dict, *, base: Path, seen: set[str]) -> set[str]:
    """Walk an IR and its sub-workflows, accumulating topics.

    Fails-soft on broken descendants and on cycles: emits a stderr warning
    and continues so the parent's topic detection isn't silently truncated.
    """
    import click

    from pflow.core.exceptions import WorkflowNotFoundError
    from pflow.core.markdown_parser import MarkdownParseError
    from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow

    topics = set(detect_topics_from_ir(ir))
    for node in ir.get("nodes") or []:
        if node.get("type") != "workflow":
            continue
        try:
            child = resolve_sub_workflow(node.get("params") or {}, base_path=base)
        except (FileNotFoundError, ValueError, MarkdownParseError, WorkflowNotFoundError) as e:
            click.echo(
                f"Warning: skipped sub-workflow during topic detection ({node.get('id', '?')}): {e}",
                err=True,
            )
            continue
        if child is None or child.path is None:
            continue
        resolved = str(child.path.resolve())
        if resolved in seen:
            click.echo(
                f"Warning: cycle detected during topic detection at {resolved}",
                err=True,
            )
            continue
        seen.add(resolved)
        topics |= _collect_topics(child.ir, base=child.path.parent, seen=seen)
    return topics


def _try_get_saved_workflow_path(name: str) -> str | None:
    """Resolve a saved workflow name to its on-disk entry-point path.

    Returns None when the workflow doesn't exist (so callers fall through
    to the unknown-topic error path).  Raises :class:`GuideError` when the
    workflow exists but failed to load — preserving the rich validation-
    error path from ``WorkflowManager.load_ir``.
    """
    try:
        from pflow.core.exceptions import WorkflowNotFoundError
        from pflow.core.workflow.manager import WorkflowManager

        wm = WorkflowManager()
        wm.load_ir(name)  # validate existence + integrity (raises on load failure)
        return wm.get_path(name)
    except WorkflowNotFoundError:
        return None
    except Exception as e:
        # Preserve structured diagnostics — WorkflowValidationError carries
        # validation_errors (task 153 shape), str(e) is just the summary.
        from pflow.core.exceptions import WorkflowValidationError

        detail = str(e)
        if isinstance(e, WorkflowValidationError) and e.validation_errors:
            from pflow.core.diagnostic_render import format_diagnostic

            rendered = "\n".join(format_diagnostic(d) for d in e.validation_errors)
            detail = f"{e.summary}\n{rendered}"
        raise GuideError(
            f"Saved workflow '{name}' failed to load: {detail}\nUse explicit topics instead: `pflow guide <topics...>`"
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
        import logging

        logging.getLogger(__name__).debug("Failed to load registry for guide topic %s", topic, exc_info=True)
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
pflow runs workflows — sequences of nodes (http, shell, llm, claude-code, code, file, mcp) \
that pass data via `${...}` templates.

Quick start:
  pflow <workflow-file>       Run a workflow file
  pflow <saved-name>          Run a saved workflow
  pflow list                  List saved workflows
  pflow find "description"    Search workflows by intent (LLM-powered)
  pflow guide                 Learn how to build workflows
  pflow mcp list              List available MCP tools

Use 'pflow <command> --help' for details on any command.
"""
