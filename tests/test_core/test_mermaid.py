"""Tests for mermaid flowchart generation from workflow IR."""

from pathlib import Path
from typing import Any, Optional

from pflow.core.workflow.mermaid import generate_mermaid
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ir(
    nodes: list[dict[str, Any]],
    edges: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Build a minimal workflow IR dict."""
    ir: dict[str, Any] = {"nodes": nodes}
    if edges is not None:
        ir["edges"] = edges
    return ir


def _node(node_id: str, node_type: str = "shell") -> dict[str, Any]:
    return {"id": node_id, "type": node_type}


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
    # Node declarations
    assert '    a["a (shell)"]' in lines
    assert '    b["b (shell)"]' in lines
    assert '    c["c (shell)"]' in lines
    # Edges
    assert "    a --> b" in lines
    assert "    b --> c" in lines


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
    lines = out.strip().splitlines()

    assert lines[0] == "graph LR"
    assert '    solo["solo (http)"]' in lines
    assert len(lines) == 2  # header + one node, no edges


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
    # Child nodes are namespaced with prefix
    assert any('sub__inner_a["inner_a (shell)"]' in line for line in lines)
    assert any('sub__inner_b["inner_b (shell)"]' in line for line in lines)
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
    assert '    sub["sub (workflow)"]' in out
    assert "subgraph" not in out


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
    assert 'sub__nested["nested (workflow)"]' in out
    assert "subgraph sub__nested" not in out


# ---------------------------------------------------------------------------
# 8. Node ID sanitization
# ---------------------------------------------------------------------------


def test_node_id_sanitization() -> None:
    """Hyphens in node IDs are preserved — no collision between foo-bar and foo_bar."""
    ir = _ir(
        nodes=[_node("read-file"), _node("write-file")],
        edges=[{"from": "read-file", "to": "write-file"}],
    )
    out = generate_mermaid(ir)

    # Mermaid IDs preserve hyphens (bracket syntax handles them fine)
    assert "read-file" in out
    assert "write-file" in out
    # Labels also preserve original ID text
    assert "read-file (shell)" in out
    assert "write-file (shell)" in out
    # Edges use original IDs
    assert "read-file --> write-file" in out


def test_hyphen_underscore_no_collision() -> None:
    """Distinct node IDs with hyphens vs underscores don't collide."""
    ir = _ir(
        nodes=[_node("foo-bar"), _node("foo_bar")],
        edges=[{"from": "foo-bar", "to": "foo_bar"}],
    )
    out = generate_mermaid(ir)

    # Both IDs should appear as distinct nodes
    assert 'foo-bar["foo-bar (shell)"]' in out
    assert 'foo_bar["foo_bar (shell)"]' in out
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
    assert 'entry__recurse["recurse (workflow)"]' in out
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

    assert '    broken["broken (workflow)"]' in out
    assert "subgraph" not in out


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

    assert '    sub["sub (workflow)"]' in out
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
