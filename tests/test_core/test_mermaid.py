"""Tests for mermaid flowchart generation from workflow IR."""

from pathlib import Path
from typing import Any, Optional

from pflow.core.workflow.mermaid import (
    _deduplicate_edges,
    _detect_decision_nodes,
    _find_terminal_nodes,
    _first_sentence,
    _get_item_label,
    generate_mermaid,
)
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ir(
    nodes: list[dict[str, Any]],
    edges: Optional[list[dict[str, Any]]] = None,
    inputs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build a minimal workflow IR dict."""
    ir: dict[str, Any] = {"nodes": nodes}
    if edges is not None:
        ir["edges"] = edges
    if inputs is not None:
        ir["inputs"] = inputs
    return ir


def _node(node_id: str, node_type: str = "shell", **kwargs: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"id": node_id, "type": node_type}
    d.update(kwargs)
    return d


# ---------------------------------------------------------------------------
# 1. Simple pipeline
# ---------------------------------------------------------------------------


def test_simple_pipeline() -> None:
    """Linear A -> B -> C produces graph LR with --> edges."""
    ir = _ir(
        nodes=[_node("a"), _node("b"), _node("c")],
        edges=[
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
        ],
    )
    out = generate_mermaid(ir)
    lines = out.strip().splitlines()

    assert lines[0] == "graph LR"
    # Node declarations (shell -> subroutine shape)
    assert any('a[["a (shell)"]]:::shell' in line for line in lines)
    assert any('b[["b (shell)"]]:::shell' in line for line in lines)
    assert any('c[["c (shell)"]]:::shell' in line for line in lines)
    # Edges
    assert any("a --> b" in line for line in lines)
    assert any("b --> c" in line for line in lines)


# ---------------------------------------------------------------------------
# 2. Conditional branching
# ---------------------------------------------------------------------------


def test_conditional_branching() -> None:
    """Named action edges get labels; error edges get dashed style."""
    ir = _ir(
        nodes=[_node("check"), _node("pass"), _node("fail"), _node("handle")],
        edges=[
            {"from": "check", "to": "pass", "action": "yes"},
            {"from": "check", "to": "fail", "action": "no"},
            {"from": "check", "to": "handle", "action": "error"},
        ],
    )
    out = generate_mermaid(ir)

    assert "check -->|yes| pass" in out
    assert "check -->|no| fail" in out
    assert "check -.->|error| handle" in out


# ---------------------------------------------------------------------------
# 3. Direction TD
# ---------------------------------------------------------------------------


def test_direction_td() -> None:
    """direction='TD' produces graph TD header."""
    ir = _ir(nodes=[_node("x")])
    out = generate_mermaid(ir, direction="TD")
    assert out.startswith("graph TD\n")


# ---------------------------------------------------------------------------
# 4. No edges
# ---------------------------------------------------------------------------


def test_no_edges() -> None:
    """Single-node workflow with no edges produces just the node declaration."""
    ir = _ir(nodes=[_node("solo", "http")])
    out = generate_mermaid(ir)

    # http type falls back to code shape (rectangle)
    assert 'solo["solo (http)"]:::code' in out


# ---------------------------------------------------------------------------
# 5. Sub-workflow expansion
# ---------------------------------------------------------------------------


def test_sub_workflow_expansion() -> None:
    """type=workflow node renders as subgraph with child nodes inside."""
    child_ir = _ir(
        nodes=[_node("inner_a"), _node("inner_b")],
        edges=[{"from": "inner_a", "to": "inner_b"}],
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            _node("start"),
            {"id": "sub", "type": "workflow", "params": {"workflow": "child"}},
            _node("finish"),
        ],
        edges=[
            {"from": "start", "to": "sub"},
            {"from": "sub", "to": "finish"},
        ],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)
    lines = out.strip().splitlines()

    # Subgraph opening and closing
    assert any("subgraph sub" in line for line in lines)
    assert any("end" in line for line in lines)
    # Child nodes are namespaced with prefix (shell -> subroutine)
    assert any('sub__inner_a[["inner_a (shell)"]]:::shell' in line for line in lines)
    assert any('sub__inner_b[["inner_b (shell)"]]:::shell' in line for line in lines)
    # Child edge is namespaced
    assert any("sub__inner_a --> sub__inner_b" in line for line in lines)
    # Parent edges use parent-level IDs
    assert any("start --> sub" in line for line in lines)
    assert any("sub --> finish" in line for line in lines)


# ---------------------------------------------------------------------------
# 6. Depth zero no expansion
# ---------------------------------------------------------------------------


def test_depth_zero_no_expansion() -> None:
    """max_depth=0 renders workflow nodes as regular opaque nodes."""
    called = False

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        nonlocal called
        called = True
        return SubWorkflowResult(ir=_ir(nodes=[_node("x")]), path=None, warnings=())

    ir = _ir(
        nodes=[{"id": "sub", "type": "workflow", "params": {"workflow": "child"}}],
    )
    out = generate_mermaid(ir, resolve_child=resolver, max_depth=0)

    assert not called, "resolver should not be called when max_depth=0"
    # workflow -> rounded rectangle shape
    assert 'sub("sub (workflow)"):::workflow' in out
    assert "subgraph sub" not in out


# ---------------------------------------------------------------------------
# 7. Depth limit
# ---------------------------------------------------------------------------


def test_depth_limit() -> None:
    """Grandchild workflows beyond max_depth render as opaque nodes."""
    grandchild_ir = _ir(nodes=[_node("deep")])
    child_ir = _ir(
        nodes=[
            {"id": "nested", "type": "workflow", "params": {"workflow": "grandchild"}},
        ],
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        wf = params.get("workflow", "")
        if wf == "child":
            return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())
        if wf == "grandchild":
            return SubWorkflowResult(ir=grandchild_ir, path=Path("/fake/grandchild.pflow.md"), warnings=())
        return None

    parent_ir = _ir(
        nodes=[{"id": "sub", "type": "workflow", "params": {"workflow": "child"}}],
    )
    # max_depth=1 means only one level of expansion
    out = generate_mermaid(parent_ir, resolve_child=resolver, max_depth=1)

    # Child expands as subgraph
    assert "subgraph sub" in out
    # Grandchild is opaque (rendered as a regular node, not a subgraph)
    assert 'sub__nested("nested (workflow)"):::workflow' in out
    assert "subgraph sub__nested" not in out


# ---------------------------------------------------------------------------
# 8. Node ID sanitization
# ---------------------------------------------------------------------------


def test_node_id_sanitization() -> None:
    """Hyphens in node IDs are preserved -- no collision between foo-bar and foo_bar."""
    ir = _ir(
        nodes=[_node("read-file"), _node("write-file", "write-file")],
        edges=[{"from": "read-file", "to": "write-file"}],
    )
    out = generate_mermaid(ir)

    # Mermaid IDs preserve hyphens (bracket syntax handles them fine)
    assert "read-file" in out
    assert "write-file" in out
    # Labels also preserve original ID text
    assert "read-file (shell)" in out
    assert "write-file (write-file)" in out
    # Edges use original IDs
    assert "read-file --> write-file" in out


def test_hyphen_underscore_no_collision() -> None:
    """Distinct node IDs with hyphens vs underscores don't collide."""
    ir = _ir(
        nodes=[_node("foo-bar"), _node("foo_bar")],
        edges=[{"from": "foo-bar", "to": "foo_bar"}],
    )
    out = generate_mermaid(ir)

    # Both IDs should appear as distinct nodes with shell shape
    assert 'foo-bar[["foo-bar (shell)"]]:::shell' in out
    assert 'foo_bar[["foo_bar (shell)"]]:::shell' in out
    # Edge goes between distinct nodes, not a self-edge
    assert "foo-bar --> foo_bar" in out


# ---------------------------------------------------------------------------
# 9. Cycle detection
# ---------------------------------------------------------------------------


def test_cycle_detection() -> None:
    """Circular sub-workflow refs don't cause infinite recursion."""
    # Both "a" and "b" resolve to the same path, creating a cycle
    shared_path = Path("/fake/shared.pflow.md")
    call_count = 0

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        nonlocal call_count
        call_count += 1
        # Every workflow node resolves to the same path with another
        # workflow node inside, creating an infinite cycle
        return SubWorkflowResult(
            ir=_ir(
                nodes=[
                    {"id": "recurse", "type": "workflow", "params": {"workflow": "x"}},
                ],
            ),
            path=shared_path,
            warnings=(),
        )

    ir = _ir(
        nodes=[{"id": "entry", "type": "workflow", "params": {"workflow": "x"}}],
    )
    # Should not hang or raise
    out = generate_mermaid(ir, resolve_child=resolver, max_depth=10)

    # The first resolution succeeds but the second hit of the same path
    # is detected as a cycle and skipped
    assert "subgraph entry" in out
    # The recursive child renders as opaque because the path was already seen
    assert 'entry__recurse("recurse (workflow)"):::workflow' in out
    assert "subgraph entry__recurse" not in out


# ---------------------------------------------------------------------------
# 9b. Sibling nodes referencing same child both expand
# ---------------------------------------------------------------------------


def test_sibling_same_child_both_expand() -> None:
    """Two sibling nodes referencing the same child workflow both expand."""
    child_ir = _ir(nodes=[{"id": "inner", "type": "shell", "params": {}}])
    shared_path = Path("/fake/child.pflow.md")

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=shared_path, warnings=())

    ir = _ir(
        nodes=[
            {"id": "first", "type": "workflow", "params": {"workflow": "child"}},
            {"id": "second", "type": "workflow", "params": {"workflow": "child"}},
        ],
        edges=[{"from": "first", "to": "second"}],
    )
    out = generate_mermaid(ir, resolve_child=resolver, max_depth=1)

    # Both siblings should expand into subgraphs
    assert "subgraph first" in out
    assert "subgraph second" in out
    assert "first__inner" in out
    assert "second__inner" in out


# ---------------------------------------------------------------------------
# 10. Resolve failure degrades gracefully
# ---------------------------------------------------------------------------


def test_resolve_failure_degrades_gracefully() -> None:
    """Resolver that raises renders the node as an opaque regular node."""

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        raise FileNotFoundError("workflow not found")

    ir = _ir(
        nodes=[{"id": "broken", "type": "workflow", "params": {"workflow": "missing"}}],
    )
    out = generate_mermaid(ir, resolve_child=resolver, max_depth=1)

    assert 'broken("broken (workflow)"):::workflow' in out
    assert "subgraph broken" not in out


# ---------------------------------------------------------------------------
# 11. No resolver skips expansion
# ---------------------------------------------------------------------------


def test_no_resolver_skips_expansion() -> None:
    """resolve_child=None renders all workflow nodes as opaque."""
    ir = _ir(
        nodes=[
            {"id": "sub", "type": "workflow", "params": {"workflow": "child"}},
        ],
    )
    out = generate_mermaid(ir, resolve_child=None)

    assert 'sub("sub (workflow)"):::workflow' in out
    assert "subgraph" not in out


# ---------------------------------------------------------------------------
# 12. Default and no-action edges
# ---------------------------------------------------------------------------


def test_default_and_no_action_edges() -> None:
    """Both action='default' and missing action render as plain arrows."""
    ir = _ir(
        nodes=[_node("a"), _node("b"), _node("c")],
        edges=[
            {"from": "a", "to": "b", "action": "default"},
            {"from": "b", "to": "c"},  # no action key
        ],
    )
    out = generate_mermaid(ir)

    # Both should produce plain --> arrows, no labels
    assert "a --> b" in out
    assert "b --> c" in out
    # No label syntax on these edges
    assert "-->|" not in out
    assert "-.->" not in out


# ---------------------------------------------------------------------------
# 13. Label escaping
# ---------------------------------------------------------------------------


def test_label_escaping() -> None:
    """Quotes in node types are escaped for mermaid labels."""
    ir = _ir(
        nodes=[{"id": "x", "type": 'say "hello"'}],
    )
    out = generate_mermaid(ir)

    # Double quotes must be escaped as &quot; inside the label
    assert "&quot;hello&quot;" in out
    # The label is enclosed in double quotes, so raw " would break mermaid
    assert 'say "hello"' not in out


# ===========================================================================
# Phase 1: Edge preprocessing
# ===========================================================================


def test_duplicate_edge_suppression() -> None:
    """Document-order edge is suppressed when a named action edge exists for same pair."""
    edges = [
        {"from": "a", "to": "b"},  # document-order (no action key)
        {"from": "a", "to": "b", "action": "go"},  # named action
    ]
    ir = _ir(
        nodes=[_node("a", "code"), _node("b", "code")],
        edges=edges,
    )
    out = generate_mermaid(ir)

    # Only the named edge should appear
    assert "-->|go|" in out
    # Should NOT have a duplicate plain --> for the same pair
    plain_edges = [line for line in out.splitlines() if "a --> b" in line and "-->|" not in line]
    assert len(plain_edges) == 0


def test_decision_node_diamond_shape() -> None:
    """Node with 2+ named action edges renders as diamond shape."""
    ir = _ir(
        nodes=[_node("check", "code"), _node("x", "code"), _node("y", "code")],
        edges=[
            {"from": "check", "to": "x", "action": "yes"},
            {"from": "check", "to": "y", "action": "no"},
        ],
    )
    out = generate_mermaid(ir)

    # Decision node renders with diamond braces
    assert 'check{"check (code)"}:::decision' in out


def test_error_edge_not_decision() -> None:
    """Node with one named action + one error edge is NOT a decision."""
    ir = _ir(
        nodes=[_node("a", "code"), _node("b", "code"), _node("err", "code")],
        edges=[
            {"from": "a", "to": "b", "action": "go"},
            {"from": "a", "to": "err", "action": "error"},
        ],
    )
    out = generate_mermaid(ir)

    # Should NOT be a diamond — only 1 non-error named action
    assert 'a["a (code)"]:::code' in out
    assert "{" not in out.split("a[")[0].split("\n")[-1]  # no diamond for 'a'


# ===========================================================================
# Phase 2: Node shape mapping
# ===========================================================================


def test_llm_node_stadium_shape() -> None:
    """LLM node renders with stadium (([...])) brackets."""
    ir = _ir(nodes=[_node("gen", "llm")])
    out = generate_mermaid(ir)
    assert 'gen(["gen (llm)"]):::llm' in out


def test_shell_node_subroutine_shape() -> None:
    """Shell node renders with subroutine ([[...]]) brackets."""
    ir = _ir(nodes=[_node("run", "shell")])
    out = generate_mermaid(ir)
    assert 'run[["run (shell)"]]:::shell' in out


def test_mcp_node_hexagon_shape() -> None:
    """MCP node renders with hexagon ({{...}}) brackets."""
    ir = _ir(nodes=[_node("fetch", "mcp-server-tool")])
    out = generate_mermaid(ir)
    assert 'fetch{{"fetch (mcp:<br/>server-tool)"}}:::mcp' in out


def test_mcp_type_line_break() -> None:
    """MCP node type gets formatted with line break for readability."""
    ir = _ir(nodes=[_node("f", "mcp-klavis-youtube-get_transcript")])
    out = generate_mermaid(ir)
    assert "mcp:<br/>klavis-youtube-get_transcript" in out


def test_code_node_default_rectangle() -> None:
    """Code node renders with default rectangle [...] brackets."""
    ir = _ir(nodes=[_node("proc", "code")])
    out = generate_mermaid(ir)
    assert 'proc["proc (code)"]:::code' in out


def test_write_file_cylinder_shape() -> None:
    """write-file node renders with cylinder ([(...) ]) brackets."""
    ir = _ir(nodes=[_node("save", "write-file")])
    out = generate_mermaid(ir)
    assert 'save[("save (write-file)")]:::writefile' in out


def test_classdefs_present() -> None:
    """Output contains classDef declarations for all node types."""
    ir = _ir(nodes=[_node("x")])
    out = generate_mermaid(ir)
    assert "classDef llm" in out
    assert "classDef code" in out
    assert "classDef shell" in out
    assert "classDef mcp" in out
    assert "classDef writefile" in out
    assert "classDef workflow" in out
    assert "classDef decision" in out
    assert "classDef input" in out


# ===========================================================================
# Phase 3: Batch rendering
# ===========================================================================


def test_batch_inline_small_fork_join() -> None:
    """Node with <=4 inline batch items renders as fork/join with all items named."""
    ir = _ir(
        nodes=[
            {
                "id": "review",
                "type": "llm",
                "batch": {
                    "items": [{"focus": "a"}, {"focus": "b"}, {"focus": "c"}],
                    "parallel": True,
                },
            },
        ],
    )
    out = generate_mermaid(ir)

    # Subgraph with parallel label
    assert "parallel x3" in out
    assert "subgraph review" in out
    # All 3 item nodes present
    assert "a (llm)" in out
    assert "b (llm)" in out
    assert "c (llm)" in out


def test_batch_inline_large_ellipsis() -> None:
    """Node with >4 inline batch items shows 2 items + ellipsis."""
    items = [{"focus": f"item{i}"} for i in range(6)]
    ir = _ir(
        nodes=[
            {
                "id": "analyze",
                "type": "llm",
                "batch": {"items": items, "parallel": True},
            },
        ],
    )
    out = generate_mermaid(ir)

    # Subgraph present with count
    assert "x6" in out
    # Only first 2 items shown
    assert "item0 (llm)" in out
    assert "item1 (llm)" in out
    # Items 2-5 not shown individually
    assert "item2" not in out
    # Ellipsis node present
    assert "... x6" in out


def test_batch_dynamic_label() -> None:
    """Node with dynamic batch items uses procs shape with source variable name."""
    ir = _ir(
        nodes=[
            {
                "id": "process",
                "type": "llm",
                "batch": {"items": "${sources}", "parallel": True},
            },
        ],
    )
    out = generate_mermaid(ir)

    # Uses procs (stacked rectangles) shape with actual variable name
    assert "shape: procs" in out
    assert "x|sources|" in out
    assert "parallel" in out


def test_batch_fork_join_edge_rerouting() -> None:
    """Edges to/from a fork/join batch node fan out to/from individual items."""
    ir = _ir(
        nodes=[
            _node("a", "code"),
            {
                "id": "batch_node",
                "type": "llm",
                "batch": {
                    "items": [{"focus": "x"}, {"focus": "y"}],
                    "parallel": True,
                },
            },
            _node("c", "code"),
        ],
        edges=[
            {"from": "a", "to": "batch_node"},
            {"from": "batch_node", "to": "c"},
        ],
    )
    out = generate_mermaid(ir)
    output_lines = out.splitlines()

    # Edges should fan out from a to each item
    a_to_x = any("a" in line and "batch_node__x" in line and "-->" in line for line in output_lines)
    a_to_y = any("a" in line and "batch_node__y" in line and "-->" in line for line in output_lines)
    assert a_to_x, "Expected edge from a to batch_node__x"
    assert a_to_y, "Expected edge from a to batch_node__y"

    # Edges should fan in from each item to c
    x_to_c = any("batch_node__x" in line and "c" in line and "-->" in line for line in output_lines)
    y_to_c = any("batch_node__y" in line and "c" in line and "-->" in line for line in output_lines)
    assert x_to_c, "Expected edge from batch_node__x to c"
    assert y_to_c, "Expected edge from batch_node__y to c"


def test_batch_workflow_dynamic_subgraph_label() -> None:
    """Workflow node with dynamic batch that expands shows batch info in subgraph label."""
    child_ir = _ir(nodes=[_node("inner", "llm")])

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    ir = _ir(
        nodes=[
            {
                "id": "worker",
                "type": "workflow",
                "params": {"workflow": "child"},
                "batch": {"items": "${data}", "parallel": True},
            },
        ],
    )
    out = generate_mermaid(ir, resolve_child=resolver)

    # Subgraph label should contain parallel with source variable name
    assert "parallel x|data|" in out
    # Internal node still rendered
    assert "inner (llm)" in out


def test_item_label_extraction() -> None:
    """_get_item_label extracts labels from various dict formats."""
    assert _get_item_label({"focus": "emotional"}, 0) == "emotional"
    assert _get_item_label({"lens": "heart"}, 0) == "heart"
    assert _get_item_label({"name": "test"}, 0) == "test"
    assert _get_item_label({"label": "my-label"}, 0) == "my-label"
    # Fallback: first short string not in skip keys
    assert _get_item_label({"workflow": "./foo.pflow.md", "role": "critic"}, 0) == "critic"
    # Non-dict
    assert _get_item_label("plain-string", 0) == "#1"
    assert _get_item_label(42, 2) == "#3"


def test_batch_item_workflow_expansion() -> None:
    """Batch items with literal workflow paths are expanded as subgraphs."""
    child_ir = _ir(nodes=[_node("review-step", "llm")])

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/review.pflow.md"), warnings=())

    ir = _ir(
        nodes=[
            {
                "id": "reviews",
                "type": "workflow",
                "batch": {
                    "items": [
                        {"focus": "quality", "workflow": "./review-quality.pflow.md"},
                        {"focus": "style", "workflow": "./review-style.pflow.md"},
                    ],
                    "parallel": True,
                },
            },
        ],
    )
    out = generate_mermaid(ir, resolve_child=resolver, max_depth=2)

    # Each item should expand as a subgraph, not an opaque node
    assert "subgraph reviews__quality" in out
    assert "subgraph reviews__style" in out
    # Internal nodes visible
    assert "review-step (llm)" in out


def test_batch_item_template_workflow_not_expanded() -> None:
    """Batch items with template workflow refs render as opaque nodes."""
    ir = _ir(
        nodes=[
            {
                "id": "reviews",
                "type": "workflow",
                "batch": {
                    "items": [
                        {"focus": "quality", "workflow": "${some.ref}"},
                    ],
                    "parallel": False,
                },
            },
        ],
    )
    out = generate_mermaid(ir)

    # Should NOT expand (template ref), render as opaque
    assert "subgraph reviews__quality" not in out
    assert 'reviews__quality("quality (workflow)"):::workflow' in out


# ===========================================================================
# Phase 4: Terminal end nodes
# ===========================================================================


def test_end_node_in_branching_workflow() -> None:
    """Branching workflow with terminal nodes gets (("end")) marker."""
    ir = _ir(
        nodes=[
            _node("check", "code"),
            _node("path_a", "code"),
            _node("path_b", "code"),
        ],
        edges=[
            {"from": "check", "to": "path_a", "action": "yes"},
            {"from": "check", "to": "path_b", "action": "no"},
        ],
    )
    out = generate_mermaid(ir)

    assert '(("end"))' in out
    # Terminal nodes connected to end
    assert "path_a --> " in out
    assert "path_b --> " in out


def test_no_end_node_in_linear_pipeline() -> None:
    """Simple linear pipeline has no end marker."""
    ir = _ir(
        nodes=[_node("a"), _node("b"), _node("c")],
        edges=[
            {"from": "a", "to": "b"},
            {"from": "b", "to": "c"},
        ],
    )
    out = generate_mermaid(ir)

    assert '(("end"))' not in out


def test_error_only_node_is_terminal() -> None:
    """Node with only an error edge outgoing is terminal for the success path."""
    ir = _ir(
        nodes=[
            _node("check", "code"),
            _node("ok", "code"),
            _node("risky", "code"),
            _node("fallback", "code"),
        ],
        edges=[
            {"from": "check", "to": "ok", "action": "yes"},
            {"from": "check", "to": "risky", "action": "no"},
            {"from": "risky", "to": "fallback", "action": "error"},
        ],
    )
    generate_mermaid(ir)  # ensure no errors

    # risky has only an error edge, so it's terminal for success path
    terminals = _find_terminal_nodes(
        [_node("check"), _node("ok"), _node("risky"), _node("fallback")],
        [
            {"from": "check", "to": "ok", "action": "yes"},
            {"from": "check", "to": "risky", "action": "no"},
            {"from": "risky", "to": "fallback", "action": "error"},
        ],
    )
    assert "risky" in terminals
    assert "ok" in terminals
    assert "fallback" in terminals


# ===========================================================================
# Phase 5: Input nodes
# ===========================================================================


def test_inputs_rendered_as_parallelogram() -> None:
    """IR with inputs renders parallelogram nodes connected to consuming node."""
    ir = _ir(
        nodes=[{"id": "process", "type": "code", "params": {"value": "${name}"}}],
        inputs={"name": {"type": "string", "required": True}},
    )
    out = generate_mermaid(ir)

    assert '[/"name (string, required)"/]' in out
    assert ":::input" in out
    assert "input_name --> process" in out


def test_no_inputs_section_when_empty() -> None:
    """IR with no inputs key produces no parallelogram nodes."""
    ir = _ir(nodes=[_node("x")])
    out = generate_mermaid(ir)

    assert "[/" not in out


# ===========================================================================
# Phase 6: Sub-workflow IO and data-flow edges
# ===========================================================================


def test_subworkflow_outputs_replace_end_node() -> None:
    """Sub-workflow with outputs renders output nodes instead of end."""
    child_ir = _ir(
        nodes=[_node("check", "code"), _node("a", "code"), _node("b", "code")],
        edges=[
            {"from": "check", "to": "a", "action": "yes"},
            {"from": "check", "to": "b", "action": "no"},
        ],
    )
    child_ir["outputs"] = {"result": {"source": "${a.stdout ?? b.stdout}"}}

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[{"id": "sub", "type": "workflow", "params": {"workflow": "child"}}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Output node should appear instead of end
    assert "result" in out
    assert ":::output" in out
    # No end node
    assert '(("end"))' not in out
    # Terminal nodes connect to output
    assert "sub__a --> " in out
    assert "sub__b --> " in out


def test_subworkflow_inputs_rendered_inside() -> None:
    """Sub-workflow inputs are rendered as parallelogram nodes inside the subgraph."""
    child_ir = _ir(
        nodes=[_node("process", "llm")],
        inputs={"text": {"type": "string"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[{"id": "sub", "type": "workflow", "params": {"workflow": "child"}}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Input parallelogram inside subgraph
    assert 'in_text[/"text (string)"/]' in out
    # Connected to first node
    assert "in_text --> " in out


def test_subworkflow_linear_outputs_connected() -> None:
    """Linear sub-workflow (no branching) still connects last node to outputs."""
    child_ir = _ir(
        nodes=[_node("step1", "llm"), _node("step2", "code")],
        edges=[{"from": "step1", "to": "step2"}],
    )
    child_ir["outputs"] = {"analysis": {"source": "${step2.result}"}}

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[{"id": "sub", "type": "workflow", "params": {"workflow": "child"}}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Output node rendered
    assert "analysis" in out
    assert ":::output" in out
    # Last node connected to output (not floating)
    assert "sub__step2 --> " in out
    # No end node
    assert '(("end"))' not in out


def test_data_flow_edges_from_params() -> None:
    """Template refs in ``params["inputs"]`` generate per-input data-flow edges.

    Regression for GH #283: child-input bindings live inside a nested
    ``inputs:`` dict (canonical form post-task-153).  The edge generator
    must descend into that dict — iterating top-level params misses every
    binding.
    """
    child_ir = _ir(
        nodes=[_node("process", "code")],
        inputs={"data": {"type": "string"}, "config": {"type": "object"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            _node("producer", "llm"),
            {
                "id": "consumer",
                "type": "workflow",
                "params": {
                    "workflow": "child",
                    "inputs": {
                        "data": "${producer.response}",
                        "config": "${my_input}",
                    },
                },
            },
        ],
        edges=[{"from": "producer", "to": "consumer"}],
        inputs={"my_input": {"type": "object"}},
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Data-flow edge: producer → consumer's data input
    assert "producer --> consumer__in_data" in out
    # Data-flow edge: parent input → consumer's config input — exactly once.
    # At depth 0, _connect_top_level_inputs emits this edge.  The data-flow
    # generator must skip top-level input refs to avoid double emission.
    assert out.count("input_my_input --> consumer__in_config") == 1, (
        f"Double-emit: depth-0 input ref should be skipped by data-flow generator "
        f"(output contains {out.count('input_my_input --> consumer__in_config')} copies)"
    )
    # Structural edge routes through outputs (consumer has none, so subgraph box)
    assert "producer --> consumer" in out


def test_structural_edge_not_suppressed_when_subwf_inputs_are_only_from_parent() -> None:
    """Structural edge survives when sub-workflow inputs come only from workflow inputs.

    Regression test: data_flow_targets was populated unconditionally when a
    sub-workflow had child inputs, even when _generate_data_flow_edges produced
    zero edges (all refs resolved to parent inputs, which are skipped at depth 0).
    This suppressed the structural edge, making the preceding node a dead end.
    """
    child_ir = _ir(
        nodes=[_node("inner", "llm")],
        inputs={"config": {"type": "string"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    # prepare → subwf, but subwf's only input references a workflow input (not prepare)
    parent_ir = _ir(
        nodes=[
            _node("prepare", "code"),
            {
                "id": "subwf",
                "type": "workflow",
                "params": {
                    "workflow": "child",
                    "inputs": {"config": "${my_setting}"},
                },
            },
        ],
        edges=[{"from": "prepare", "to": "subwf"}],
        inputs={"my_setting": {"type": "string"}},
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Structural edge prepare → subwf must survive (not suppressed)
    assert "prepare --> subwf" in out


def test_data_flow_skips_item_refs() -> None:
    """Batch item refs (${item.*}) don't generate data-flow edges."""
    child_ir = _ir(
        nodes=[_node("step", "llm")],
        inputs={"text": {"type": "string"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            {
                "id": "batch_wf",
                "type": "workflow",
                "params": {
                    "workflow": "child",
                    "inputs": {"text": "${item.content}"},
                },
                "batch": {"items": "${sources}", "parallel": True},
            },
        ],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # No data-flow edge FROM an external node TO in_text (item refs are skipped)
    data_flow_to_input = [
        line for line in out.splitlines() if "in_text" in line and "-->" in line and "in_text -->" not in line
    ]
    assert len(data_flow_to_input) == 0, f"Unexpected data-flow edges: {data_flow_to_input}"


def test_top_level_outputs_rendered() -> None:
    """Top-level workflow with outputs renders output wrapper at the bottom."""
    ir = _ir(
        nodes=[_node("a", "code"), _node("b", "code")],
        edges=[
            {"from": "a", "to": "b", "action": "go"},
            {"from": "a", "to": "b", "action": "stop"},
        ],
    )
    ir["outputs"] = {"result": {"source": "${b.stdout}"}}
    out = generate_mermaid(ir)

    # Top-level outputs rendered in a wrapper subgraph
    assert "workflow-outputs" in out
    assert ":::output" in out
    assert "out_result" in out
    # Producing node connected to output
    assert "b --> out_result" in out
    # No end node when outputs exist
    assert '(("end"))' not in out


# ===========================================================================
# Phase 7: --descriptions flag
# ===========================================================================


def test_descriptions_flag_on() -> None:
    """With descriptions=True, node purpose appears in label."""
    ir = _ir(
        nodes=[
            _node("gen", "llm", purpose="This is the first sentence. And more detail."),
        ],
    )
    out = generate_mermaid(ir, descriptions=True)

    assert "<br/>This is the first sentence." in out


def test_descriptions_flag_off() -> None:
    """With descriptions=False (default), no purpose in label."""
    ir = _ir(
        nodes=[
            _node("gen", "llm", purpose="This is the first sentence. And more detail."),
        ],
    )
    out = generate_mermaid(ir, descriptions=False)

    assert "<br/>This is the first sentence." not in out


def test_descriptions_on_subgraph() -> None:
    """With descriptions=True, sub-workflow subgraph label includes purpose."""
    child_ir = _ir(nodes=[_node("inner", "code")])

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            {
                "id": "sub",
                "type": "workflow",
                "params": {"workflow": "child"},
                "purpose": "Fetches content from multiple sources. More details here.",
            },
        ],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver, descriptions=True)

    assert "Fetches content from multiple sources." in out

    # Without descriptions, purpose should not appear in subgraph label
    out_no_desc = generate_mermaid(parent_ir, resolve_child=resolver, descriptions=False)
    assert "Fetches content from multiple sources." not in out_no_desc


def test_first_sentence_extraction() -> None:
    """_first_sentence extracts first sentence and strips markdown."""
    assert _first_sentence("Hello world. More text.") == "Hello world."
    assert _first_sentence("**Bold** start. Rest.") == "Bold start."
    assert _first_sentence("No period here") == "No period here"
    assert _first_sentence("A" * 100 + ".") == "A" * 80


# ===========================================================================
# Phase 8: Back-edge test
# ===========================================================================


def test_back_edge_renders() -> None:
    """Back-edge (b -> a) renders without error."""
    ir = _ir(
        nodes=[_node("a"), _node("b")],
        edges=[
            {"from": "a", "to": "b"},
            {"from": "b", "to": "a"},
        ],
    )
    out = generate_mermaid(ir)

    assert "b --> a" in out
    assert "a --> b" in out


# ===========================================================================
# Unit tests for internal functions
# ===========================================================================


def test_deduplicate_edges_preserves_error() -> None:
    """Error edges are never suppressed by deduplication."""
    edges = [
        {"from": "a", "to": "b"},
        {"from": "a", "to": "b", "action": "go"},
        {"from": "a", "to": "c", "action": "error"},
    ]
    result = _deduplicate_edges(edges)
    actions = [e.get("action") for e in result]
    assert "go" in actions
    assert "error" in actions
    # Document-order edge for a->b should be suppressed
    assert sum(1 for e in result if e["from"] == "a" and e["to"] == "b") == 1


def test_detect_decision_nodes_ignores_default() -> None:
    """action='default' edges don't count toward decision detection."""
    edges = [
        {"from": "a", "to": "b", "action": "default"},
        {"from": "a", "to": "c", "action": "go"},
    ]
    decisions = _detect_decision_nodes(edges)
    assert "a" not in decisions  # only 1 non-default named action


# ===========================================================================
# High-value regression tests
# ===========================================================================


def test_nested_subworkflow_output_routes_through_child_output() -> None:
    """When an outer sub-workflow's output references an inner sub-workflow's
    output, the edge must route through the inner sub-workflow's specific
    output node — not the inner subgraph box.

    This tests the two-map cascade in _connect_sources_to_output: the child
    outgoing map (from the inner sub-workflow) must be checked BEFORE the
    parent outgoing map. If the order is wrong, the edge goes to the
    subgraph box instead of the output node.
    """
    # Inner sub-workflow: has an output "winning"
    inner_ir = _ir(
        nodes=[_node("pick", "llm")],
    )
    inner_ir["outputs"] = {"winning": {"source": "${pick.response}"}}

    # Outer sub-workflow: contains "inner" and references its output
    outer_ir = _ir(
        nodes=[
            _node("prep", "code"),
            {"id": "inner", "type": "workflow", "params": {"workflow": "inner.pflow.md"}},
        ],
        edges=[{"from": "prep", "to": "inner"}],
    )
    outer_ir["outputs"] = {"result": {"source": "${inner.winning}"}}

    call_count = 0

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        nonlocal call_count
        wf = params.get("workflow", "")
        if "inner" in wf:
            call_count += 1
            return SubWorkflowResult(ir=inner_ir, path=Path(f"/fake/inner{call_count}.pflow.md"), warnings=())
        if "outer" in wf:
            return SubWorkflowResult(ir=outer_ir, path=Path("/fake/outer.pflow.md"), warnings=())
        return None

    parent_ir = _ir(
        nodes=[{"id": "outer", "type": "workflow", "params": {"workflow": "outer.pflow.md"}}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver, max_depth=3)

    # The outer output "result" must connect through inner's output node,
    # not through the inner subgraph box
    lines = out.strip().splitlines()
    result_edges = [line for line in lines if "out_result" in line and "-->" in line]
    assert any("out_winning" in edge for edge in result_edges), (
        f"Outer output 'result' should route through inner's 'out_winning' node, "
        f"but edges to out_result are: {result_edges}"
    )


def test_suppression_without_replacement_keeps_structural_edge() -> None:
    """When data-flow targets suppress a structural edge but names don't match,
    the structural edge must survive as fallback — not silently disconnect.

    This catches the most dangerous failure mode: nodes becoming floating
    because suppression fired without a replacement data-flow edge.
    """
    # Child A has output "result", child B has input "data" (names DON'T match)
    child_a_ir = _ir(
        nodes=[_node("inner_a", "code")],
        inputs={"x": {"type": "string"}},
    )
    child_a_ir["outputs"] = {"result": {"source": "${inner_a.stdout}"}}
    child_b_ir = _ir(
        nodes=[_node("inner_b", "code")],
        inputs={"data": {"type": "string"}},  # "data" != "result" — no name match
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        wf = params.get("workflow", "")
        if wf == "a.pflow.md":
            return SubWorkflowResult(ir=child_a_ir, path=Path("/fake/a.pflow.md"), warnings=())
        if wf == "b.pflow.md":
            return SubWorkflowResult(ir=child_b_ir, path=Path("/fake/b.pflow.md"), warnings=())
        return None

    parent_ir = _ir(
        nodes=[
            {
                "id": "sub-a",
                "type": "workflow",
                "params": {"workflow": "a.pflow.md", "inputs": {"x": "val"}},
            },
            {
                "id": "sub-b",
                "type": "workflow",
                "params": {"workflow": "b.pflow.md", "inputs": {"data": "${sub-a.result}"}},
            },
        ],
        edges=[{"from": "sub-a", "to": "sub-b"}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # sub-a's output "result" should exist
    assert "out_result" in out
    # sub-b's input "data" should exist
    assert "in_data" in out
    # A connection from sub-a to sub-b MUST exist (either through output or direct).
    # The worst bug is: suppression fires, no replacement, nodes disconnect.
    lines = out.strip().splitlines()
    a_to_b_edges = [line for line in lines if "sub-a" in line and "sub-b" in line]
    assert len(a_to_b_edges) > 0, "sub-a must connect to sub-b — no silent disconnection"


def test_external_io_does_not_duplicate_with_internal_io() -> None:
    """An expanded sub-workflow must have external IO from parent OR internal IO,
    never both. Duplicate IO nodes cause edges to connect to the wrong copy.
    """
    child_ir = _ir(
        nodes=[_node("step", "code")],
        inputs={"val": {"type": "string"}},
    )
    child_ir["outputs"] = {"out": {"source": "${step.stdout}"}}

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            {
                "id": "sub",
                "type": "workflow",
                "params": {"workflow": "child", "inputs": {"val": "x"}},
            },
        ],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Count input nodes — should be exactly 1 (external), not 2 (external + internal)
    input_nodes = [line for line in out.splitlines() if "in_val" in line and ":::" in line]
    assert len(input_nodes) == 1, f"Expected 1 input node, got {len(input_nodes)}: {input_nodes}"

    # Count output nodes — should be exactly 1 (external), not 2
    output_nodes = [line for line in out.splitlines() if "out_out" in line and ":::" in line]
    assert len(output_nodes) == 1, f"Expected 1 output node, got {len(output_nodes)}: {output_nodes}"

    # No end node — external outputs replace them
    assert '(("end"))' not in out


def test_top_level_input_connects_to_actual_consumer() -> None:
    """Top-level input connects to the node that references it, not blindly
    to the first node. Catches regression to old 'all inputs → first node'.
    """
    ir = _ir(
        nodes=[
            _node("step1", "code"),
            _node("step2", "code"),
            {"id": "step3", "type": "code", "params": {"config": "${settings}"}},
        ],
        edges=[
            {"from": "step1", "to": "step2"},
            {"from": "step2", "to": "step3"},
        ],
        inputs={"settings": {"type": "string", "required": False}},
    )
    out = generate_mermaid(ir)

    # Should connect to step3 (which references ${settings}), NOT step1
    assert "input_settings --> step3" in out
    assert "input_settings --> step1" not in out
    assert "input_settings --> step2" not in out


# ===========================================================================
# GH #283 regression tests (canonical ``inputs:`` dict form)
# ===========================================================================


def test_opaque_template_inputs_fall_through_gracefully() -> None:
    """Heterogeneous-batch ``inputs: ${item.inputs}`` (whole-dict template) does not crash.

    When the ``inputs`` value is a template string rather than a dict, static
    analysis cannot enumerate per-input bindings — runtime resolves them per
    item.  The data-flow edge generator must skip this case without error.
    """
    child_ir = _ir(
        nodes=[_node("step", "code")],
        inputs={"x": {"type": "string"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            {
                "id": "consumer",
                "type": "workflow",
                "params": {
                    "workflow": "child",
                    "inputs": "${item.inputs}",  # opaque whole-dict template
                },
                "batch": {"items": "${sources}", "parallel": False},
            },
        ],
    )
    # Must not raise
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Input node is still rendered (parallelogram) — opaque template doesn't
    # prevent child input declaration
    assert "consumer__in_x[/" in out, "child input node must be rendered"

    # But no data-flow edge INTO consumer__in_x from an external node —
    # we can't statically enumerate which parent value feeds which child input.
    external_to_input = [
        line
        for line in out.splitlines()
        if "--> consumer__in_x" in line and "consumer-in" not in line  # skip wrapper → input edge
    ]
    assert external_to_input == [], f"Unexpected data-flow edges: {external_to_input}"


def test_batch_data_flow_with_inputs_dict() -> None:
    """Heterogeneous batch with per-item inputs in ``params["inputs"]`` dict.

    Regression for GH #283 batch variant.  Parent-param refs in the nested
    ``inputs:`` dict must emit edges to each expanded item's input node.
    """
    child_ir = _ir(
        nodes=[_node("review", "llm")],
        inputs={"summary": {"type": "string"}, "aspect": {"type": "string"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/review.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            _node("combine", "code"),
            {
                "id": "reviews",
                "type": "workflow",
                "params": {
                    "workflow": "${item.workflow}",
                    "inputs": {
                        "summary": "${combine.result}",
                        "aspect": "${item.aspect}",
                    },
                },
                "batch": {
                    "items": [
                        {"aspect": "accuracy", "workflow": "/fake/review.pflow.md"},
                        {"aspect": "clarity", "workflow": "/fake/review.pflow.md"},
                    ],
                    "parallel": True,
                },
            },
        ],
        edges=[{"from": "combine", "to": "reviews"}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Per-item data-flow edge from combine → each item's summary input
    assert "combine --> reviews__accuracy__in_summary" in out
    assert "combine --> reviews__clarity__in_summary" in out
    # aspect is ${item.*} — no external data-flow edge for it
    assert "combine --> reviews__accuracy__in_aspect" not in out


def test_coalesce_in_data_flow_binding() -> None:
    """Coalesce expressions in data-flow bindings emit edges for both operands.

    Coalesce (``??``) is a general-purpose template operator — valid in any
    template context, not just output sources.  ``refs_in`` must capture
    every ref inside ``${...}`` blocks, including both sides of ``??``.
    A regression where only the first operand is extracted would silently
    drop half the data-flow edges.
    """
    child_ir = _ir(
        nodes=[_node("step", "code")],
        inputs={"val": {"type": "string"}},
    )

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            _node("primary", "llm"),
            _node("fallback", "llm"),
            {
                "id": "consumer",
                "type": "workflow",
                "params": {
                    "workflow": "child",
                    "inputs": {"val": "${primary.response ?? fallback.response}"},
                },
            },
        ],
        edges=[{"from": "primary", "to": "consumer"}, {"from": "fallback", "to": "consumer"}],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Both operands of the coalesce must feed the consumer's val input
    assert "primary --> consumer__in_val" in out, "first coalesce operand missing"
    assert "fallback --> consumer__in_val" in out, "second coalesce operand missing"


# ===========================================================================
# GH #263 regression tests (output sources referencing workflow inputs)
# ===========================================================================


def test_output_source_from_declared_input() -> None:
    """Output ``source: ${data.field}`` where ``data`` is a declared input.

    Regression for GH #263: previously silently dropped (``_connect_sources_to_output``
    only recognized node IDs as source roots).  The output node rendered
    disconnected — no incoming edge from the input parallelogram.
    """
    ir = _ir(
        nodes=[_node("process", "shell")],
        inputs={"data": {"type": "object"}},
    )
    ir["outputs"] = {"result": {"source": "${data.field}"}}

    out = generate_mermaid(ir)

    assert "input_data --> out_result" in out


def test_output_source_from_bare_input_ref() -> None:
    """Output ``source: ${data}`` (no field) also resolves to the input.

    Regression for GH #263: the old regex ``_SOURCE_NODE_FIELD_RE`` required
    ``name.field`` form, so bare input refs didn't match at all and the
    output silently disconnected.
    """
    ir = _ir(
        nodes=[_node("process", "shell")],
        inputs={"data": {"type": "string"}},
    )
    ir["outputs"] = {"result": {"source": "${data}"}}

    out = generate_mermaid(ir)

    assert "input_data --> out_result" in out


def test_output_source_from_input_in_subworkflow() -> None:
    """Sub-workflow output referencing its declared input also resolves.

    The input at sub-workflow scope uses the ``{prefix}in_{name}`` convention
    rather than top-level ``input_{name}``.  The fix must construct the right
    ID at each scope.
    """
    child_ir = _ir(
        nodes=[_node("passthrough", "code")],
        inputs={"data": {"type": "string"}},
    )
    child_ir["outputs"] = {"echo": {"source": "${data}"}}

    def resolver(params: dict[str, Any], base: Optional[Path]) -> Optional[SubWorkflowResult]:
        return SubWorkflowResult(ir=child_ir, path=Path("/fake/child.pflow.md"), warnings=())

    parent_ir = _ir(
        nodes=[
            {
                "id": "sub",
                "type": "workflow",
                "params": {"workflow": "child", "inputs": {"data": "val"}},
            },
        ],
    )
    out = generate_mermaid(parent_ir, resolve_child=resolver)

    # Within the sub-workflow scope, the input-root ref resolves to the
    # sub-workflow's input wrapper, not a top-level ``input_*`` node.
    assert "sub__in_data --> sub__out_echo" in out
