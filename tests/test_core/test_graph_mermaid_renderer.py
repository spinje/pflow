"""Tests for rendering GraphModel to Mermaid."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from pflow.core.workflow.graph import LoopSpec, build_graph, render_mermaid
from pflow.core.workflow.graph.renderers.mermaid import _get_item_label, _loop_label
from pflow.core.workflow.mermaid import generate_mermaid
from pflow.core.workflow.sub_workflow_resolver import SubWorkflowResult, resolve_sub_workflow
from pflow.execution.workflow_resolver import resolve_workflow

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"

# Tokens that DEFINE (introduce) a mermaid id. A given id must be introduced at most
# once; defining it twice — same shape OR different — collapses two logical nodes into
# one in the rendered diagram.
_DEF_RE = re.compile(r"^([A-Za-z0-9_\-]+)((?:@\{|\[\(|\(\[|\[\[|\[/|\{\{|\[|\(|\{).*)$")
_SUBGRAPH_RE = re.compile(r"^subgraph\s+([A-Za-z0-9_\-]+)\s")


def _id_definitions(mermaid: str) -> dict[str, list[str]]:
    """Map each flat id to every definition (shape token) it is rendered with.

    Counts occurrences (not distinct shapes) so a same-shape duplicate — two shell
    nodes that flatten to one id — is still detected as a collision.
    """
    defs: dict[str, list[str]] = {}
    for raw in mermaid.splitlines():
        line = raw.strip()
        sub = _SUBGRAPH_RE.match(line)
        if sub:
            defs.setdefault(sub.group(1), []).append("<subgraph>")
            continue
        if line.startswith(("style ", "classDef ", "graph ")) or "-->" in line or "-.->" in line:
            continue
        node = _DEF_RE.match(line)
        if node:
            defs.setdefault(node.group(1), []).append(node.group(2).split('"')[0])
    return defs


def _assert_no_collisions(mermaid: str) -> None:
    collisions = {nid: shapes for nid, shapes in _id_definitions(mermaid).items() if len(shapes) > 1}
    assert not collisions, f"Mermaid id(s) defined more than once (collision): {collisions}\n{mermaid}"


def _assert_valid_mermaid(mermaid: str) -> None:
    """Assert the rendered diagram is structurally valid, independent of its exact text.

    Goldens freeze the exact string — including a broken one if a bug is introduced and
    the golden regenerated. This checks the *properties* a golden can't: no leaked
    template refs, balanced subgraph/end nesting, and no id defined twice (collision).
    """
    assert "${" not in mermaid, f"Template ref leaked into Mermaid label:\n{mermaid}"
    depth = 0
    for raw in mermaid.splitlines():
        stripped = raw.strip()
        if stripped.startswith("subgraph "):
            depth += 1
        elif stripped == "end":
            depth -= 1
            assert depth >= 0, f"Unbalanced 'end' (closes a subgraph that was never opened):\n{mermaid}"
    assert depth == 0, f"Unbalanced subgraphs (depth={depth}):\n{mermaid}"
    _assert_no_collisions(mermaid)


def _child_resolver(children: dict[str, dict[str, Any]]):
    def resolver(params: dict[str, Any], base: Path | None) -> SubWorkflowResult | None:
        ref = params.get("workflow")
        ir = children.get(ref)
        return SubWorkflowResult(ir=ir, path=Path(f"/fake/{ref}"), warnings=()) if ir is not None else None

    return resolver


def _render_public(workflow_path: Path, *, direction: str, descriptions: bool) -> str:
    """Render through the public ``generate_mermaid`` entry point (the shim → build → render path)."""
    resolved = resolve_workflow(str(workflow_path))
    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    return generate_mermaid(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        source_file=Path(resolved.file_path) if resolved.file_path else None,
        max_depth=5,
        direction=direction,
        descriptions=descriptions,
    )


@pytest.mark.parametrize(
    "workflow_rel,direction",
    [
        ("core/conditional-branching.pflow.md", "LR"),  # branching + next:end sink
        ("core/error-handling.pflow.md", "LR"),  # on-error + next:end, no decision
        ("nested/document-processor.pflow.md", "LR"),  # nested sub-workflow
        ("batch-test-parallel.pflow.md", "LR"),  # batch fan-out
        ("nested/deep-research/deep-research.pflow.md", "TD"),  # deep nesting, top-down
        ("nested/deep-research/deep-research.pflow.md", "LR"),
        ("core/stateful-loop-tournament.pflow.md", "LR"),  # loop on a sub-workflow host
        ("agent-orchestration/plan-to-code/run-from-plan.pflow.md", "TD"),  # Task 163 harness: deep + loop + batch
        ("agent-orchestration/parallel-planner-review/orchestrate.pflow.md", "LR"),  # ${...} in a description
        ("real-workflows/generate-changelog/workflow.pflow.md", "LR"),  # large real workflow
    ],
)
def test_public_mermaid_output_is_structurally_valid(workflow_rel: str, direction: str) -> None:
    # descriptions=True is the stricter case: labels carry description prose, where a
    # ${...} ref could leak. Rendered via the public generate_mermaid path.
    mermaid = _render_public(EXAMPLES_DIR / workflow_rel, direction=direction, descriptions=True)
    _assert_valid_mermaid(mermaid)


def test_item_label_extraction() -> None:
    assert _get_item_label({"focus": "emotional"}, 0) == "emotional"
    assert _get_item_label({"lens": "heart"}, 0) == "heart"
    assert _get_item_label({"name": "test"}, 0) == "test"
    assert _get_item_label({"label": "my-label"}, 0) == "my-label"
    assert _get_item_label({"workflow": "./foo.pflow.md", "role": "critic"}, 0) == "critic"
    assert _get_item_label("plain-string", 0) == "#1"
    assert _get_item_label(42, 2) == "#3"


def test_loop_label_formats_loop_spec() -> None:
    assert _loop_label(LoopSpec("while", "${run-rounds.more}", 10, {}), "run-rounds") == "<br/>⟳ while more · ≤ 10"
    assert _loop_label(LoopSpec("until", "${check.done}", None, {}), "check") == "<br/>⟳ until done"
    assert (
        _loop_label(
            LoopSpec(
                "while",
                "${review-round.result.continue}",
                "${max_review_rounds}",
                {},
            ),
            "review-round",
        )
        == "<br/>⟳ while result.continue · ≤ max_review_rounds"
    )
    assert (
        _loop_label(
            LoopSpec("while", "${r.more}", 10, {"contenders": "${r.survivors}"}),
            "r",
        )
        == "<br/>⟳ while more · ≤ 10 · carry contenders"
    )
    assert _loop_label(LoopSpec("while", "${r.go}", None, {}), "r") == "<br/>⟳ while go"
    assert _loop_label(LoopSpec("while", "${other.flag}", None, {}), "r") == "<br/>⟳ while other.flag"
    assert _loop_label(LoopSpec("while", "${r.go}", True, {}), "r") == "<br/>⟳ while go"


def test_loop_label_escapes_special_chars() -> None:
    label = _loop_label(LoopSpec("while", "${r.go}", None, {"a|b": "${r.x}"}), "r")

    assert "|" not in label.split("<br/>")[1]
    assert "&#124;" in label


# ── Flat-id collision resolution (Task 155 renderer hardening) ────────────────


def test_node_name_colliding_with_sink_id_is_disambiguated() -> None:
    """An authored node literally named ``pflow_end`` must not collide with the sink."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "classify", "type": "code", "purpose": "route the input"},
            {"id": "pflow_end", "type": "shell", "purpose": "a node named like the sink"},
            {"id": "other", "type": "shell", "purpose": "the other branch"},
        ],
        "edges": [
            {"from": "classify", "to": "pflow_end", "action": "pflow_end"},
            {"from": "classify", "to": "other", "action": "other"},
        ],
    }
    mermaid = render_mermaid(build_graph(ir))
    _assert_no_collisions(mermaid)
    # The synthetic sink keeps `pflow_end`; the authored node is suffixed.
    assert 'pflow_end(("end"))' in mermaid
    assert "pflow_end_2" in mermaid


def test_node_name_colliding_with_input_wrapper_is_disambiguated() -> None:
    """Nodes named like the input node id (``input_x``) or wrapper (``workflow-inputs``)."""
    ir = {
        "ir_version": "0.1.0",
        "inputs": {"seed": {"type": "string", "required": True}},
        "nodes": [
            {"id": "workflow-inputs", "type": "shell", "purpose": "collides with the wrapper id"},
            {"id": "input_seed", "type": "shell", "purpose": "collides with the input node id"},
        ],
    }
    mermaid = render_mermaid(build_graph(ir))
    _assert_no_collisions(mermaid)


def test_node_name_colliding_with_nested_child_flat_id_is_disambiguated() -> None:
    """Top-level node ``a__b`` must not collide with child ``b`` under sub-workflow ``a``."""
    child = {
        "ir_version": "0.1.0",
        "inputs": {"x": {"type": "string"}},
        "nodes": [{"id": "b", "type": "shell", "purpose": "child node b"}],
        "outputs": {"out": {"source": "${b.stdout}"}},
    }
    parent = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "a", "type": "workflow", "params": {"workflow": "child", "inputs": {"x": "hi"}}},
            {"id": "a__b", "type": "code", "purpose": "top node colliding with a's child b"},
        ],
    }
    mermaid = render_mermaid(build_graph(parent, resolve_child=_child_resolver({"child": child}), max_depth=2))
    _assert_no_collisions(mermaid)


def test_node_name_colliding_with_deep_level_sink_is_disambiguated() -> None:
    """A shallow node must not squat on a deeper level's synthetic sink id (ordering hole)."""
    leaf = {
        "ir_version": "0.1.0",
        "inputs": {"v": {"type": "string"}},
        "nodes": [{"id": "gate", "type": "shell", "purpose": "terminate", "_routes_to_end": True}],
        "outputs": {"r": {"source": "${gate.stdout}"}},
    }
    mid = {
        "ir_version": "0.1.0",
        "inputs": {"v": {"type": "string"}},
        "nodes": [{"id": "c", "type": "workflow", "params": {"workflow": "leaf", "inputs": {"v": "${v}"}}}],
        "outputs": {"r": {"source": "${c.r}"}},
    }
    top = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "w", "type": "workflow", "params": {"workflow": "mid", "inputs": {"v": "hi"}}},
            {"id": "w__c__pflow_end", "type": "shell", "purpose": "name matches the deep sink id"},
        ],
    }
    mermaid = render_mermaid(build_graph(top, resolve_child=_child_resolver({"mid": mid, "leaf": leaf}), max_depth=5))
    _assert_no_collisions(mermaid)


def test_template_refs_in_descriptions_do_not_leak_into_labels() -> None:
    """A ${...} ref inside a node description must not leak into the rendered label."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "step",
                "type": "llm",
                "purpose": "Caps iterations at `${max_iterations}` to bound the loop.",
            }
        ],
    }
    mermaid = render_mermaid(build_graph(ir), descriptions=True)
    assert "${" not in mermaid
    assert "max_iterations" in mermaid  # inner ref text is preserved, just de-braced
