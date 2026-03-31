"""Integration tests for conditional branching in workflows.

Tests end-to-end: IR dict -> compile -> run, and markdown -> parse -> compile -> run.
"""

import textwrap

import pytest

from pflow.core.exceptions import MaxNodeVisitsError
from pflow.core.markdown_parser import parse_markdown
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from tests.shared.registry_utils import ensure_test_registry


def _md(text: str) -> str:
    """Dedent a markdown string and ensure trailing newline."""
    return textwrap.dedent(text).strip() + "\n"


def compile_and_run_ir(ir: dict, shared: dict | None = None) -> dict:
    """Compile IR dict to workflow and run it via WorkflowEngine."""
    registry = ensure_test_registry()
    workflow = compile_workflow(ir, registry)
    shared = shared or {}
    shared.update(workflow.resolved_defaults)
    engine = WorkflowEngine()
    engine.run(workflow, shared)
    return shared


def parse_compile_and_run(markdown: str, shared: dict | None = None) -> dict:
    """Parse markdown, compile to flow, and run it."""
    result = parse_markdown(markdown)
    return compile_and_run_ir(result.ir, shared)


# ---------------------------------------------------------------------------
# Helpers for checking whether a node ran
# ---------------------------------------------------------------------------


def _node_ran(shared: dict, node_id: str) -> bool:
    """Check if a node was executed by looking at completed_nodes."""
    return node_id in shared.get("__execution__", {}).get("completed_nodes", [])


# ===========================================================================
# TestCodeDynamicRouting — IR-based tests for code node `next` variable
# ===========================================================================


class TestCodeDynamicRouting:
    """Test that code nodes can dynamically route to named branches via next."""

    def test_code_routes_to_named_branch(self) -> None:
        """When code sets next='fast-path', only the fast-path branch runs."""
        ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {
                        "code": 'next: str = "fast-path"\nresult: str = "routed"',
                    },
                },
                {
                    "id": "fast-path",
                    "type": "echo",
                    "params": {"message": "fast"},
                },
                {
                    "id": "slow-path",
                    "type": "echo",
                    "params": {"message": "slow"},
                },
            ],
            "edges": [
                {"from": "router", "to": "fast-path", "action": "fast-path"},
                {"from": "router", "to": "slow-path", "action": "slow-path"},
                {"from": "router", "to": "fast-path", "action": "default"},
            ],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "fast-path")
        assert not _node_ran(shared, "slow-path")
        assert shared["router"]["result"] == "routed"

    def test_code_default_when_next_not_set(self) -> None:
        """When code does not set next, routing follows the default edge."""
        ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {
                        "code": 'result: str = "done"',
                    },
                },
                {
                    "id": "default-target",
                    "type": "echo",
                    "params": {"message": "reached"},
                },
            ],
            "edges": [
                {"from": "router", "to": "default-target"},
            ],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "default-target")
        assert shared["default-target"]["echo"] == "reached"

    def test_code_skip_ahead(self) -> None:
        """When code sets next='save', intermediate nodes are skipped."""
        ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {
                        "code": 'next: str = "save"\nresult: str = "skipped"',
                    },
                },
                {
                    "id": "transform",
                    "type": "echo",
                    "params": {"message": "transform"},
                },
                {
                    "id": "save",
                    "type": "echo",
                    "params": {"message": "saved"},
                },
            ],
            "edges": [
                {"from": "router", "to": "transform", "action": "default"},
                {"from": "router", "to": "save", "action": "save"},
                {"from": "transform", "to": "save"},
            ],
        }

        shared = compile_and_run_ir(ir)

        assert not _node_ran(shared, "transform")
        assert _node_ran(shared, "save")
        assert shared["save"]["echo"] == "saved"


# ===========================================================================
# TestErrorRouting — IR-based tests for on-error edge routing
# ===========================================================================


class TestErrorRouting:
    """Test that error edges route execution to handler nodes."""

    def test_on_error_routes_to_handler(self) -> None:
        """When a code node fails, the error edge routes to the handler."""
        ir = {
            "nodes": [
                {
                    "id": "failer",
                    "type": "code",
                    "params": {
                        "code": "result: int = 1 // 0",  # ZeroDivisionError
                    },
                },
                {
                    "id": "handler",
                    "type": "echo",
                    "params": {"message": "handled"},
                },
            ],
            "edges": [
                {"from": "failer", "to": "handler", "action": "error"},
            ],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "handler")
        assert shared["handler"]["echo"] == "handled"
        # The failer node should have an error recorded
        assert "error" in shared["failer"]

    def test_on_error_not_triggered_on_success(self) -> None:
        """When a code node succeeds, the error edge is NOT taken."""
        ir = {
            "nodes": [
                {
                    "id": "succeeder",
                    "type": "code",
                    "params": {
                        "code": 'result: str = "ok"',
                    },
                },
                {
                    "id": "handler",
                    "type": "echo",
                    "params": {"message": "should not run"},
                },
            ],
            "edges": [
                {"from": "succeeder", "to": "handler", "action": "error"},
            ],
        }

        # PocketFlow warns when action "default" has no matching edge — expected
        # since this IR only has an "error" edge, and the node succeeds.
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "succeeder")
        assert not _node_ran(shared, "handler")
        assert shared["succeeder"]["result"] == "ok"


# ===========================================================================
# TestLoopExecution — IR-based tests for loop guard
# ===========================================================================


class TestLoopExecution:
    """Test loop guard and loop-with-exit-condition behavior."""

    def test_loop_guard_raises_at_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When a node always loops back to itself, MaxNodeVisitsError is raised."""
        # Lower the limit to keep the test fast
        monkeypatch.setattr("pflow.runtime.engine.instrumentation.MAX_NODE_VISITS", 5)

        ir = {
            "nodes": [
                {
                    "id": "looper",
                    "type": "code",
                    "params": {
                        "code": 'next: str = "looper"\nresult: int = 0',
                    },
                },
            ],
            "edges": [
                {"from": "looper", "to": "looper", "action": "looper"},
            ],
        }

        with pytest.raises(MaxNodeVisitsError, match="looper"):
            compile_and_run_ir(ir)

    def test_loop_with_exit_condition(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A two-node loop that runs N times then exits.

        Uses worker + checker pattern because a single node can't reference
        its own previous output through templates (NamespacedSharedStore
        excludes self-namespace from keys to prevent recursion).

        Critical: without cache invalidation for revisited nodes, both
        nodes would be cached after the first iteration and return stale
        actions forever — never reaching the exit condition.
        """
        monkeypatch.setattr("pflow.runtime.engine.instrumentation.MAX_NODE_VISITS", 20)

        ir = {
            "nodes": [
                {
                    "id": "worker",
                    "type": "code",
                    "params": {
                        "code": ("prev: str\nresult: str = str(int(prev) + 1)\n"),
                        "inputs": {"prev": "${checker.result}"},
                    },
                },
                {
                    "id": "checker",
                    "type": "code",
                    "params": {
                        "code": (
                            "count: str\n"
                            "result: str = count\n"
                            "if int(count) >= 3:\n"
                            "    next: str = 'done'\n"
                            "else:\n"
                            "    next: str = 'worker'\n"
                        ),
                        "inputs": {"count": "${worker.result}"},
                    },
                },
                {
                    "id": "done",
                    "type": "echo",
                    "params": {"message": "finished"},
                },
            ],
            "edges": [
                {"from": "worker", "to": "checker", "action": "default"},
                {"from": "checker", "to": "worker", "action": "worker"},
                {"from": "checker", "to": "done", "action": "done"},
                {"from": "checker", "to": "done", "action": "default"},
            ],
        }

        # Pre-seed checker result so worker's ${checker.result} resolves on first run
        shared = compile_and_run_ir(ir, shared={"checker": {"result": "0"}})

        # The loop should run 3 iterations: worker(1)→checker(1)→worker(2)→checker(2)→worker(3)→checker(3)→done
        assert _node_ran(shared, "done")
        assert shared["done"]["echo"] == "finished"
        # Worker's final result should be "3" (incremented 3 times: 0→1, 1→2, 2→3)
        assert shared["worker"]["result"] == "3"
        # Each node should have been visited 3 times
        assert shared["__execution__"]["node_visit_counts"]["worker"] == 3
        assert shared["__execution__"]["node_visit_counts"]["checker"] == 3


# ===========================================================================
# TestNextEnd — IR-based test for next=end termination
# ===========================================================================


class TestNextEnd:
    """Test that flows terminate when no successor matches."""

    def test_no_edge_terminates_flow(self) -> None:
        """When a node has no outgoing edge for its action, the flow ends."""
        ir = {
            "nodes": [
                {
                    "id": "stopper",
                    "type": "code",
                    "params": {
                        "code": 'result: str = "stopped"',
                    },
                },
                {
                    "id": "after-stopper",
                    "type": "echo",
                    "params": {"message": "should not run"},
                },
            ],
            # No edge from stopper to after-stopper — flow ends after stopper
            "edges": [],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "stopper")
        assert not _node_ran(shared, "after-stopper")


# ===========================================================================
# TestFullPipeline — Markdown -> parse -> compile -> run
# ===========================================================================


class TestFullPipeline:
    """End-to-end tests: markdown source -> parse -> compile -> run."""

    def test_pipeline_code_classification(self) -> None:
        """A code node dynamically routes via next in a full markdown pipeline."""
        markdown = _md("""\
            # Classification Workflow

            Classify and route.

            ## Steps

            ### classifier

            Classify the input and route to the appropriate branch.

            - type: code

            ```python code
            next: str = "positive"
            result: str = "classified"
            ```

            ### positive

            Handle positive classification.

            - type: echo
            - message: positive-result
            - next: end

            ### negative

            Handle negative classification.

            - type: echo
            - message: negative-result
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "classifier")
        assert _node_ran(shared, "positive")
        assert not _node_ran(shared, "negative")
        assert shared["positive"]["echo"] == "positive-result"

    def test_pipeline_error_routing(self) -> None:
        """A failing code node routes to the error handler via on-error in markdown."""
        markdown = _md("""\
            # Error Routing Workflow

            Test error routing.

            ## Steps

            ### risky

            A step that will fail.

            - type: code
            - on-error: handler

            ```python code
            result: int = 1 // 0
            ```

            ### handler

            Handle errors from the risky step.

            - type: echo
            - message: error-handled
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "handler")
        assert shared["handler"]["echo"] == "error-handled"
        assert "error" in shared["risky"]

    def test_pipeline_next_end(self) -> None:
        """A node with '- next: end' terminates the flow early."""
        markdown = _md("""\
            # Early Termination Workflow

            Stop after the first step.

            ## Steps

            ### stopper

            This step terminates the workflow.

            - type: code
            - next: end

            ```python code
            result: str = "done"
            ```

            ### unreachable

            This step should never run.

            - type: echo
            - message: should-not-run
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "stopper")
        assert not _node_ran(shared, "unreachable")
        assert shared["stopper"]["result"] == "done"

    def test_pipeline_validated_branching_with_upstream_refs(self) -> None:
        """Branch targets referencing upstream data pass validation (not just execution).

        This catches the regression where named edges were excluded from
        topological sort, causing branch targets to be ordered before the
        router and failing template validation.
        """
        markdown = _md("""\
            # Validated Branching

            Branch targets reference upstream data — must pass validation.

            ## Steps

            ### router

            Classify and route based on input.

            - type: code

            ```python code
            result: str = "routed-value"
            next: str = "branch-a"
            ```

            ### branch-a

            Process with upstream data reference.

            - type: code
            - inputs: { upstream: "${router.result}" }
            - next: done

            ```python code
            upstream: str
            result: str = f"processed-{upstream}"
            ```

            ### branch-b

            Alternative processing with upstream data reference.

            - type: code
            - inputs: { upstream: "${router.result}" }
            - next: done

            ```python code
            upstream: str
            result: str = f"alt-{upstream}"
            ```

            ### done

            Final step.

            - type: echo
            - message: complete
        """)

        # validate=True exercises the full validation pipeline including
        # data flow ordering — would fail if branch targets are mis-ordered
        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "router")
        assert _node_ran(shared, "branch-a")
        assert not _node_ran(shared, "branch-b")
        assert _node_ran(shared, "done")

    def test_pipeline_template_resolution_in_branch_targets(self) -> None:
        """Shell commands in branch targets correctly resolve ${router.result} templates.

        This is the most common real-world branching pattern: a code node
        routes to shell nodes that reference upstream data via templates.
        Tests template resolution + namespace isolation + branching together.
        """
        markdown = _md("""\
            # Template Branch Test

            Route to shell nodes that use upstream templates.

            ## Steps

            ### router

            Classify and route based on input.

            - type: code

            ```python code
            result: str = "premium"
            next: str = "premium-path"
            ```

            ### standard-path

            Standard processing with upstream template reference.

            - type: shell
            - next: end

            ```shell command
            echo "Standard: ${router.result}"
            ```

            ### premium-path

            Premium processing with upstream template reference.

            - type: shell
            - next: end

            ```shell command
            echo "Premium: ${router.result}"
            ```
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "router")
        assert _node_ran(shared, "premium-path")
        assert not _node_ran(shared, "standard-path")
        # Template ${router.result} resolved to "premium" inside the branch target
        assert shared["premium-path"]["stdout"].strip() == "Premium: premium"

    def test_pipeline_error_handler_with_convergence(self) -> None:
        """Error handler with '- next: done' converges back to main flow."""
        markdown = _md("""\
            # Error Convergence

            Error handler converges to a shared final step.

            ## Steps

            ### risky

            A step that will fail.

            - type: code
            - on-error: handler

            ```python code
            result: int = 1 // 0
            ```

            ### handler

            Handle errors, then continue to done.

            - type: echo
            - message: handled
            - next: done

            ### done

            Final step (convergence point).

            - type: echo
            - message: complete
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "handler")
        assert _node_ran(shared, "done")
        assert shared["done"]["echo"] == "complete"

    def test_pipeline_branch_targets_at_bottom(self) -> None:
        """Pattern B layout: main flow on top, branch targets at bottom."""
        markdown = _md("""\
            # Bottom Branch Layout

            Main flow first, branch targets at the bottom.

            ## Steps

            ### fetch

            Fetch data.

            - type: echo
            - message: fetched

            ### process

            Process data, route if needed.

            - type: code

            ```python code
            result: str = "processed"
            next: str = "special-handler"
            ```

            ### finish

            End of main flow.

            - type: echo
            - message: finished
            - next: end

            ### special-handler

            Special processing branch.

            - type: echo
            - message: special
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "process")
        assert _node_ran(shared, "special-handler")
        assert not _node_ran(shared, "finish")
        assert shared["special-handler"]["echo"] == "special"
