"""Integration tests for branch convergence using optional inputs.

When conditional branches converge at a code node, inputs annotated as
``Optional[T]`` or ``T | None`` receive ``None`` when their source node
didn't execute (branch not taken). Non-optional inputs still error.
"""

import textwrap
from typing import Any

import pytest

from pflow.core.markdown_parser import parse_markdown
from pflow.runtime.compiler import compile_ir_to_flow
from tests.shared.registry_utils import ensure_test_registry


def _md(text: str) -> str:
    """Dedent a markdown string and ensure trailing newline."""
    return textwrap.dedent(text).strip() + "\n"


def compile_and_run_ir(
    ir: dict,
    shared: dict | None = None,
    *,
    initial_params: dict[str, Any] | None = None,
) -> dict:
    """Compile IR dict to flow and run it."""
    registry = ensure_test_registry()
    flow = compile_ir_to_flow(ir, registry, initial_params=initial_params)
    shared = shared or {}
    flow.run(shared)
    return shared


def parse_compile_and_run(
    markdown: str,
    shared: dict | None = None,
    *,
    initial_params: dict[str, Any] | None = None,
) -> dict:
    """Parse markdown, compile to flow, and run it."""
    result = parse_markdown(markdown)
    return compile_and_run_ir(result.ir, shared, initial_params=initial_params)


def _node_ran(shared: dict, node_id: str) -> bool:
    """Check if a node was executed by looking at completed_nodes."""
    return node_id in shared.get("__execution__", {}).get("completed_nodes", [])


# ---------------------------------------------------------------------------
# IR for the standard branch convergence pattern
# ---------------------------------------------------------------------------


def _make_convergence_ir(
    merge_code: str,
    *,
    route_to_low: bool = True,
    merge_inputs: dict[str, str] | None = None,
) -> dict:
    """Build IR for a router -> two branches -> merge convergence pattern.

    Args:
        merge_code: Python code for the merge node.
        route_to_low: If True, the router sends to branch-low; otherwise branch-high.
        merge_inputs: Override for merge node inputs dict. Defaults to
            referencing both branch stdout fields.

    Returns:
        IR dict ready for ``compile_and_run_ir``.
    """
    if merge_inputs is None:
        merge_inputs = {
            "high": "${branch-high.stdout}",
            "low": "${branch-low.stdout}",
        }

    if route_to_low:
        route_code = 'result: str = "low"\nnext: str = "branch-low"'
    else:
        route_code = 'result: str = "high"\nnext: str = "branch-high"'

    return {
        "nodes": [
            {
                "id": "route",
                "type": "code",
                "params": {
                    "code": route_code,
                },
            },
            {
                "id": "branch-high",
                "type": "shell",
                "params": {"command": "echo HIGH-VALUE"},
            },
            {
                "id": "branch-low",
                "type": "shell",
                "params": {"command": "echo LOW-VALUE"},
            },
            {
                "id": "merge",
                "type": "code",
                "params": {
                    "inputs": merge_inputs,
                    "code": merge_code,
                },
            },
        ],
        "edges": [
            {"from": "route", "to": "branch-high", "action": "branch-high"},
            {"from": "route", "to": "branch-low", "action": "branch-low"},
            {"from": "branch-high", "to": "merge", "action": "default"},
            {"from": "branch-low", "to": "merge", "action": "default"},
        ],
    }


# ===========================================================================
# TestBranchConvergenceIR — IR-based tests
# ===========================================================================


class TestBranchConvergenceIR:
    """Test branch convergence with optional inputs using IR dicts."""

    def test_optional_input_receives_none_for_skipped_branch(self) -> None:
        """When only branch-low runs, merge gets high=None, low='LOW-VALUE...'."""
        merge_code = 'high: str | None\nlow: str | None\nresult: str = high or low or "nothing"'
        ir = _make_convergence_ir(merge_code, route_to_low=True)

        shared = compile_and_run_ir(ir)

        # Only the low branch should have run
        assert _node_ran(shared, "route")
        assert not _node_ran(shared, "branch-high")
        assert _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        # Merge result should contain the low branch output
        assert "LOW-VALUE" in shared["merge"]["result"]

    def test_non_optional_input_still_errors(self) -> None:
        """When merge uses non-optional 'high: str', unresolved template errors."""
        merge_code = 'high: str\nlow: str | None\nresult: str = high or low or "nothing"'
        ir = _make_convergence_ir(merge_code, route_to_low=True)

        with pytest.raises(ValueError, match="Unresolved variables"):
            compile_and_run_ir(ir)

    def test_typo_in_field_still_errors_despite_optional(self) -> None:
        """A typo in the template path errors even when the input is optional.

        When the source node DID execute but the referenced field doesn't exist,
        the template validator catches the typo at compile time. This verifies
        that optional annotations do NOT suppress typo detection.
        """
        merge_code = 'high: str | None\nlow: str | None\nresult: str = high or low or "nothing"'
        # Typo: 'stddout' instead of 'stdout' -- branch-high DID run in
        # the high-value path, but the field doesn't exist
        ir = _make_convergence_ir(
            merge_code,
            route_to_low=False,  # branch-high runs
            merge_inputs={
                "high": "${branch-high.stddout}",  # typo
                "low": "${branch-low.stdout}",
            },
        )

        # The typo is caught at template validation time (compile stage),
        # not at runtime -- the error message references the wrong field name
        with pytest.raises(ValueError, match=r"does not output.*stddout"):
            compile_and_run_ir(ir)


# ===========================================================================
# TestBranchConvergenceMarkdown — Full markdown pipeline tests
# ===========================================================================

_CONVERGENCE_WORKFLOW_MD = _md("""\
    # Branch Convergence Workflow

    Route to high or low branch, then merge results.

    ## Inputs

    - value: int

    ## Steps

    ### route

    Route based on input value.

    - type: code
    - inputs: { value: "${value}" }

    ```python code
    value: int

    if value > 10:
        result: str = "high"
        next: str = "branch-high"
    else:
        result: str = "low"
        next: str = "branch-low"
    ```

    ### branch-high

    Process high values.

    - type: shell
    - next: merge

    ```shell command
    echo HIGH-BRANCH-RESULT
    ```

    ### branch-low

    Process low values.

    - type: shell
    - next: merge

    ```shell command
    echo LOW-BRANCH-RESULT
    ```

    ### merge

    Merge branch results using optional inputs.

    - type: code
    - inputs: { high: "${branch-high.stdout}", low: "${branch-low.stdout}" }
    - next: end

    ```python code
    high: str | None
    low: str | None
    result: str = high.strip() if high else low.strip() if low else "nothing"
    ```
""")


class TestBranchConvergenceMarkdown:
    """Test branch convergence with optional inputs using markdown workflows."""

    def test_full_markdown_convergence_low_branch(self) -> None:
        """With value=5, only the low branch runs; merge gets high=None."""
        shared = parse_compile_and_run(
            _CONVERGENCE_WORKFLOW_MD,
            initial_params={"value": 5},
        )

        assert _node_ran(shared, "route")
        assert not _node_ran(shared, "branch-high")
        assert _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        assert "LOW-BRANCH-RESULT" in shared["merge"]["result"]

    def test_full_markdown_convergence_high_branch(self) -> None:
        """With value=15, only the high branch runs; merge gets low=None."""
        shared = parse_compile_and_run(
            _CONVERGENCE_WORKFLOW_MD,
            initial_params={"value": 15},
        )

        assert _node_ran(shared, "route")
        assert _node_ran(shared, "branch-high")
        assert not _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        assert "HIGH-BRANCH-RESULT" in shared["merge"]["result"]

    def test_optional_str_annotation_also_works(self) -> None:
        """Optional[str] annotation works the same as str | None."""
        markdown = _md("""\
            # Optional Annotation Workflow

            Test Optional[str] syntax for branch convergence.

            ## Inputs

            - value: int

            ## Steps

            ### route

            Route based on input value.

            - type: code
            - inputs: { value: "${value}" }

            ```python code
            value: int

            if value > 10:
                result: str = "high"
                next: str = "branch-high"
            else:
                result: str = "low"
                next: str = "branch-low"
            ```

            ### branch-high

            Process high values.

            - type: shell
            - next: merge

            ```shell command
            echo HIGH-OPT
            ```

            ### branch-low

            Process low values.

            - type: shell
            - next: merge

            ```shell command
            echo LOW-OPT
            ```

            ### merge

            Merge using Optional[str] annotations.

            - type: code
            - inputs: { high: "${branch-high.stdout}", low: "${branch-low.stdout}" }
            - next: end

            ```python code
            from typing import Optional
            high: Optional[str]
            low: Optional[str]
            result: str = high.strip() if high else low.strip() if low else "nothing"
            ```
        """)

        shared = parse_compile_and_run(
            markdown,
            initial_params={"value": 5},
        )

        assert _node_ran(shared, "route")
        assert not _node_ran(shared, "branch-high")
        assert _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        assert "LOW-OPT" in shared["merge"]["result"]


# ===========================================================================
# TestBranchConvergenceCoalesce — Coalesce operator in shell nodes
# ===========================================================================


def _make_coalesce_ir(route_to_low: bool = True) -> dict:
    """Build IR for branch convergence using ?? coalesce (no merge code node)."""
    if route_to_low:
        route_code = 'result: str = "low"\nnext: str = "branch-low"'
    else:
        route_code = 'result: str = "high"\nnext: str = "branch-high"'

    return {
        "nodes": [
            {
                "id": "route",
                "type": "code",
                "params": {"code": route_code},
            },
            {
                "id": "branch-high",
                "type": "shell",
                "params": {"command": "echo HIGH-VALUE"},
            },
            {
                "id": "branch-low",
                "type": "shell",
                "params": {"command": "echo LOW-VALUE"},
            },
            {
                "id": "use-result",
                "type": "shell",
                "params": {"command": "echo Result: ${branch-high.stdout ?? branch-low.stdout}"},
            },
        ],
        "edges": [
            {"from": "route", "to": "branch-high", "action": "branch-high"},
            {"from": "route", "to": "branch-low", "action": "branch-low"},
            {"from": "branch-high", "to": "use-result", "action": "default"},
            {"from": "branch-low", "to": "use-result", "action": "default"},
        ],
    }


class TestBranchConvergenceCoalesce:
    """Test branch convergence using ?? coalesce in shell nodes (no merge code node)."""

    def test_shell_node_coalesce_low_branch(self) -> None:
        """When low branch runs, coalesce picks branch-low.stdout."""
        ir = _make_coalesce_ir(route_to_low=True)
        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "route")
        assert not _node_ran(shared, "branch-high")
        assert _node_ran(shared, "branch-low")
        assert _node_ran(shared, "use-result")

        assert "LOW-VALUE" in shared["use-result"]["stdout"]

    def test_shell_node_coalesce_high_branch(self) -> None:
        """When high branch runs, coalesce picks branch-high.stdout."""
        ir = _make_coalesce_ir(route_to_low=False)
        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "route")
        assert _node_ran(shared, "branch-high")
        assert not _node_ran(shared, "branch-low")
        assert _node_ran(shared, "use-result")

        assert "HIGH-VALUE" in shared["use-result"]["stdout"]


# ===========================================================================
# TestCoalesceInWorkflowOutputs — Coalesce in ## Outputs source declarations
# ===========================================================================


class TestCoalesceInWorkflowOutputs:
    """Test coalesce in workflow output source declarations (full compile+execute).

    This tests the complete chain: compiler monkey-patches flow.run →
    populate_declared_outputs → resolve_output_source → resolve_template.
    The output resolver previously bypassed resolve_template, silently
    dropping coalesced outputs.
    """

    def test_coalesced_output_resolves_to_executed_branch(self) -> None:
        """Workflow output with ?? resolves to whichever branch ran."""
        ir = _make_coalesce_ir(route_to_low=True)
        ir["outputs"] = {
            "content": {"source": "${branch-low.stdout ?? branch-high.stdout}"},
        }

        shared = compile_and_run_ir(ir)

        assert "content" in shared, "Coalesced output was not populated"
        assert "LOW-VALUE" in shared["content"]

    def test_coalesced_output_other_branch(self) -> None:
        """Same test, opposite branch — ensures both directions work."""
        ir = _make_coalesce_ir(route_to_low=False)
        ir["outputs"] = {
            "content": {"source": "${branch-high.stdout ?? branch-low.stdout}"},
        }

        shared = compile_and_run_ir(ir)

        assert "content" in shared, "Coalesced output was not populated"
        assert "HIGH-VALUE" in shared["content"]


# ===========================================================================
# TestCoalesceWithOptionalInputs — Interaction between Phase 1 and Phase 2
# ===========================================================================


def _make_coalesce_optional_ir(*, route_to: str) -> dict:
    """Build IR for testing coalesce + optional input interaction.

    Phase 1 (optional input injection) replaces unresolved optional input
    templates with None when the source node didn't execute.
    Phase 2 (coalesce operator) resolves templates by trying operands
    left-to-right.

    These features were designed independently. This IR exercises both:
    - The merge node uses coalesce (``??``) inside an optional input
    - Depending on ``route_to``, zero or one branch executes

    Args:
        route_to: "branch-high", "branch-low", or "skip-both".
    """
    if route_to == "branch-high":
        route_code = 'result: str = "high"\nnext: str = "branch-high"'
    elif route_to == "branch-low":
        route_code = 'result: str = "low"\nnext: str = "branch-low"'
    else:
        # Skip both branches — go directly to merge
        route_code = 'result: str = "skip"\nnext: str = "merge"'

    return {
        "nodes": [
            {
                "id": "route",
                "type": "code",
                "params": {"code": route_code},
            },
            {
                "id": "branch-high",
                "type": "shell",
                "params": {"command": "echo HIGH-VALUE"},
            },
            {
                "id": "branch-low",
                "type": "shell",
                "params": {"command": "echo LOW-VALUE"},
            },
            {
                "id": "merge",
                "type": "code",
                "params": {
                    "inputs": {
                        "branch_value": "${branch-high.stdout ?? branch-low.stdout}",
                    },
                    "code": 'branch_value: str | None\nresult: str = branch_value.strip() if branch_value else "NONE-INJECTED"',
                },
            },
        ],
        "edges": [
            {"from": "route", "to": "branch-high", "action": "branch-high"},
            {"from": "route", "to": "branch-low", "action": "branch-low"},
            {"from": "route", "to": "merge", "action": "merge"},
            {"from": "branch-high", "to": "merge", "action": "default"},
            {"from": "branch-low", "to": "merge", "action": "default"},
        ],
    }


class TestCoalesceWithOptionalInputs:
    """Test interaction between Phase 1 (optional input injection) and Phase 2 (coalesce).

    Phase 1 injects None for optional inputs whose source nodes didn't execute.
    Phase 2 resolves ``${a ?? b}`` by trying operands left-to-right, skipping
    absent roots.

    These features work correctly together because:
    1. ``_all_variables_from_absent_nodes`` requires ALL roots to be absent —
       with coalesce, usually only ONE root is absent, so injection is skipped.
    2. The ``input_value != input_template`` guard skips injection when coalesce
       already resolved the value to a concrete string.

    But this correctness is accidental (no explicit design coordination), so
    these tests serve as guardrails to catch regressions.
    """

    def test_coalesce_in_optional_input_resolves_correctly(self) -> None:
        """When one branch runs, coalesce resolves to that branch's output.

        The optional input injection must NOT interfere — the coalesce
        already resolved the template to a concrete value, so the
        ``input_value != input_template`` guard should prevent injection.
        """
        # Route to branch-high: coalesce picks branch-high.stdout
        ir = _make_coalesce_optional_ir(route_to="branch-high")
        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "route")
        assert _node_ran(shared, "branch-high")
        assert not _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        # Coalesce resolved to branch-high.stdout — injection did not fire
        assert "HIGH-VALUE" in shared["merge"]["result"]

        # Also verify the opposite direction
        ir = _make_coalesce_optional_ir(route_to="branch-low")
        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "route")
        assert not _node_ran(shared, "branch-high")
        assert _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        assert "LOW-VALUE" in shared["merge"]["result"]

    def test_coalesce_in_optional_input_both_absent_gets_none(self) -> None:
        """When neither branch runs, coalesce fails and injection sets None.

        The router skips both branches (routes directly to merge). The
        coalesce template ``${branch-high.stdout ?? branch-low.stdout}``
        cannot resolve because both roots are absent. The template stays
        unchanged, then ``_all_variables_from_absent_nodes`` detects that
        ALL roots are absent and injects None for the optional input.
        """
        ir = _make_coalesce_optional_ir(route_to="skip-both")
        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "route")
        assert not _node_ran(shared, "branch-high")
        assert not _node_ran(shared, "branch-low")
        assert _node_ran(shared, "merge")

        # Both branches absent → coalesce unresolved → injection sets None →
        # code node sees branch_value=None → result = "NONE-INJECTED"
        assert shared["merge"]["result"] == "NONE-INJECTED"


# ===========================================================================
# TestOutputResolutionErrors — Non-coalesce output sources referencing
# non-executed branches must error instead of silently dropping.
# ===========================================================================


class TestOutputResolutionErrors:
    """Test that unresolvable non-coalesce output sources raise errors."""

    def test_non_coalesce_output_errors_on_unexecuted_branch(self) -> None:
        """Output source without ?? referencing non-executed branch raises error."""
        from pflow.core.user_errors import OutputResolutionError

        ir = _make_coalesce_ir(route_to_low=True)
        # Non-coalesce source pointing to branch that didn't execute
        ir["outputs"] = {
            "content": {"source": "${branch-high.stdout}"},
        }

        with pytest.raises(OutputResolutionError, match="branch-high.*did not execute"):
            compile_and_run_ir(ir)

    def test_coalesce_output_resolves_on_unexecuted_branch(self) -> None:
        """Output source WITH ?? resolves when one branch didn't execute."""
        ir = _make_coalesce_ir(route_to_low=True)
        ir["outputs"] = {
            "content": {"source": "${branch-low.stdout ?? branch-high.stdout}"},
        }
        shared = compile_and_run_ir(ir)
        assert "content" in shared
        assert "LOW-VALUE" in shared["content"]

    def test_nested_workflow_output_error_propagates_to_parent(self, tmp_path: Any) -> None:
        """OutputResolutionError in child workflow surfaces in parent with diagnosis.

        Full chain: parent flow → WorkflowExecutor.exec() → child flow.run() →
        run_with_hooks() → populate_declared_outputs() raises OutputResolutionError →
        WorkflowExecutor.exec() catches → post() writes error to parent shared store.

        This is the primary motivating scenario: a parent workflow should see the
        child's specific diagnosis ("node X did not execute"), not a generic
        "unresolved variable" error pointing at the parent.
        """

        # Write child workflow as .pflow.md file — routes to branch-b,
        # but output references branch-a (which won't execute)
        child_md = _md("""\
            # Child With Bad Output

            A child workflow that routes to branch-b but declares an output
            referencing branch-a without coalesce.

            ## Steps

            ### route

            Route to branch-b always.

            - type: code

            ```python code
            result: str = "going-b"
            next: str = "branch-b"
            ```

            ### branch-a

            Will not execute.

            - type: shell
            - next: end

            ```shell command
            echo "from A"
            ```

            ### branch-b

            Will execute.

            - type: shell
            - next: end

            ```shell command
            echo "from B"
            ```

            ## Outputs

            ### content

            References branch-a without ?? — should error.

            - source: ${branch-a.stdout}
        """)
        child_path = tmp_path / "child.pflow.md"
        child_path.write_text(child_md)

        # Parent: references child by file path
        parent_ir = {
            "nodes": [
                {
                    "id": "child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path)},
                },
            ],
            "edges": [],
        }

        shared = compile_and_run_ir(parent_ir)

        # Child failed — error written to parent's shared store under child namespace
        assert "child" in shared
        error = shared["child"].get("error", "")
        assert "branch-a" in error, f"Expected 'branch-a' in error, got: {error}"
        assert "did not execute" in error, f"Expected 'did not execute' in error, got: {error}"
