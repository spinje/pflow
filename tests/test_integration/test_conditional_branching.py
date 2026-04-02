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
                    "type": "shell",
                    "params": {"command": "printf '%s' fast"},
                },
                {
                    "id": "slow-path",
                    "type": "shell",
                    "params": {"command": "printf '%s' slow"},
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
                    "type": "shell",
                    "params": {"command": "printf '%s' reached"},
                },
            ],
            "edges": [
                {"from": "router", "to": "default-target"},
            ],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "default-target")
        assert shared["default-target"]["stdout"] == "reached"

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
                    "type": "shell",
                    "params": {"command": "printf '%s' transform"},
                },
                {
                    "id": "save",
                    "type": "shell",
                    "params": {"command": "printf '%s' saved"},
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
        assert shared["save"]["stdout"] == "saved"


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
                    "type": "shell",
                    "params": {"command": "printf '%s' handled"},
                },
            ],
            "edges": [
                {"from": "failer", "to": "handler", "action": "error"},
            ],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "handler")
        assert shared["handler"]["stdout"] == "handled"
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
                    "type": "shell",
                    "params": {"command": "printf '%s' 'should not run'"},
                },
            ],
            "edges": [
                {"from": "succeeder", "to": "handler", "action": "error"},
            ],
        }

        # Node succeeds — only error edges exist, so this is clean termination
        # (no forward path, not a routing failure).
        shared = compile_and_run_ir(ir)

        assert not _node_ran(shared, "handler")  # Error edge NOT taken
        assert shared["succeeder"]["result"] == "ok"  # Node DID execute
        assert shared["__execution__"]["failed_node"] is None  # Clean termination


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
                    "type": "shell",
                    "params": {"command": "printf '%s' finished"},
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
        assert shared["done"]["stdout"] == "finished"
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
                    "type": "shell",
                    "params": {"command": "printf '%s' 'should not run'"},
                },
            ],
            # No edge from stopper to after-stopper — flow ends after stopper
            "edges": [],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "stopper")
        assert not _node_ran(shared, "after-stopper")

    def test_end_action_terminates_cleanly(self) -> None:
        """Code node returning next='end' terminates without warning."""
        ir = {
            "nodes": [
                {
                    "id": "decider",
                    "type": "code",
                    "params": {
                        "code": 'next: str = "end"\nresult: str = "decided"',
                    },
                },
                {
                    "id": "after-decider",
                    "type": "shell",
                    "params": {"command": "printf '%s' 'should not run'"},
                },
            ],
            # Edge exists so curr.successors is non-empty — tests "end" bypass
            "edges": [{"from": "decider", "to": "after-decider", "action": "default"}],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "decider")
        assert not _node_ran(shared, "after-decider")
        assert shared.get("__warnings__", {}) == {}
        assert shared["__execution__"]["failed_node"] is None

    def test_unmatched_action_sets_failed_node(self) -> None:
        """Code node returning unrecognized action marks workflow as failed."""
        ir = {
            "nodes": [
                {
                    "id": "bad-router",
                    "type": "code",
                    "params": {
                        "code": 'next: str = "nonexistent"\nresult: str = "routed"',
                    },
                },
                {
                    "id": "fallback",
                    "type": "shell",
                    "params": {"command": "printf '%s' fallback"},
                },
            ],
            "edges": [{"from": "bad-router", "to": "fallback", "action": "default"}],
        }

        shared = compile_and_run_ir(ir)

        assert shared["__execution__"]["failed_node"] == "bad-router"
        assert "bad-router" in shared.get("__warnings__", {})
        assert 'next: str = "end"' in shared["__warnings__"]["bad-router"]

    def test_unmatched_action_not_in_completed_nodes(self) -> None:
        """Routing failure rolls back success bookkeeping — node must not appear completed."""
        ir = {
            "nodes": [
                {
                    "id": "bad-router",
                    "type": "code",
                    "params": {
                        "code": 'next: str = "nonexistent"\nresult: str = "routed"',
                    },
                },
                {
                    "id": "fallback",
                    "type": "shell",
                    "params": {"command": "printf '%s' fallback"},
                },
            ],
            "edges": [{"from": "bad-router", "to": "fallback", "action": "default"}],
        }

        shared = compile_and_run_ir(ir)

        exec_state = shared["__execution__"]
        assert exec_state["failed_node"] == "bad-router"
        assert "bad-router" not in exec_state["completed_nodes"]
        assert "bad-router" not in exec_state.get("node_actions", {})
        assert "bad-router" not in exec_state.get("node_hashes", {})

    def test_error_only_successors_terminate_on_success(self) -> None:
        """Node with only 'error' edges terminates cleanly on success.

        When a node's only successor is an error edge, success means 'done' —
        there is no forward path. This is the IR-level equivalent of
        '- next: end' + '- on-error: handler'.
        """
        ir = {
            "nodes": [
                {
                    "id": "primary",
                    "type": "shell",
                    "params": {"command": "printf '%s' ok"},
                },
                {
                    "id": "handler",
                    "type": "shell",
                    "params": {"command": "printf '%s' handled"},
                },
            ],
            # Only an error edge — no default successor
            "edges": [{"from": "primary", "to": "handler", "action": "error"}],
        }

        shared = compile_and_run_ir(ir)

        assert _node_ran(shared, "primary")
        assert not _node_ran(shared, "handler")
        assert shared["primary"]["stdout"] == "ok"
        assert shared.get("__warnings__", {}) == {}
        assert shared["__execution__"]["failed_node"] is None


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

            - type: shell
            - command: printf '%s' positive-result
            - next: end

            ### negative

            Handle negative classification.

            - type: shell
            - command: printf '%s' negative-result
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "classifier")
        assert _node_ran(shared, "positive")
        assert not _node_ran(shared, "negative")
        assert shared["positive"]["stdout"] == "positive-result"

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

            - type: shell
            - command: printf '%s' error-handled
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "handler")
        assert shared["handler"]["stdout"] == "error-handled"
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

            - type: shell
            - command: printf '%s' should-not-run
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "stopper")
        assert not _node_ran(shared, "unreachable")
        assert shared["stopper"]["result"] == "done"

    def test_pipeline_next_end_with_on_error(self) -> None:
        """A node with both '- next: end' and '- on-error:' terminates on success.

        Regression test: the engine previously treated the error-only successor
        map as a routing failure because 'default' was absent. The correct
        behavior is to recognize that no forward (non-error) path means
        intentional termination.
        """
        markdown = _md("""\
            # Fallback Chain

            Primary fetch with fallback on error.

            ## Steps

            ### primary

            Try the primary path. On success, stop. On error, fall back.

            - type: shell
            - command: printf '%s' primary-ok
            - on-error: fallback
            - next: end

            ### fallback

            Fallback path if primary fails.

            - type: shell
            - command: printf '%s' fallback-ok
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "primary")
        assert not _node_ran(shared, "fallback")
        assert shared["primary"]["stdout"] == "primary-ok"
        assert shared.get("__warnings__", {}) == {}
        assert shared["__execution__"]["failed_node"] is None

    def test_pipeline_next_end_with_on_error_takes_fallback(self) -> None:
        """When the primary node fails, on-error routes to the fallback."""
        markdown = _md("""\
            # Fallback Chain — Error Path

            Primary fails, fallback runs.

            ## Steps

            ### primary

            A step that will fail.

            - type: code
            - on-error: fallback
            - next: end

            ```python code
            result: int = 1 // 0
            ```

            ### fallback

            Fallback path runs on error.

            - type: shell
            - command: printf '%s' fallback-ok
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "fallback")
        assert shared["fallback"]["stdout"] == "fallback-ok"

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

            - type: shell
            - command: printf '%s' complete
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

            - type: shell
            - command: printf '%s' handled
            - next: done

            ### done

            Final step (convergence point).

            - type: shell
            - command: printf '%s' complete
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "handler")
        assert _node_ran(shared, "done")
        assert shared["done"]["stdout"] == "complete"

    def test_pipeline_branch_targets_at_bottom(self) -> None:
        """Pattern B layout: main flow on top, branch targets at bottom."""
        markdown = _md("""\
            # Bottom Branch Layout

            Main flow first, branch targets at the bottom.

            ## Steps

            ### fetch

            Fetch data.

            - type: shell
            - command: printf '%s' fetched

            ### process

            Process data, route if needed.

            - type: code

            ```python code
            result: str = "processed"
            next: str = "special-handler"
            ```

            ### finish

            End of main flow.

            - type: shell
            - command: printf '%s' finished
            - next: end

            ### special-handler

            Special processing branch.

            - type: shell
            - command: printf '%s' special
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "process")
        assert _node_ran(shared, "special-handler")
        assert not _node_ran(shared, "finish")
        assert shared["special-handler"]["stdout"] == "special"

    def test_pipeline_code_end_branch_no_warning(self) -> None:
        """Code node with conditional next='end' produces no warning."""
        markdown = _md("""\
            # Conditional End Workflow

            Skip email if address is empty.

            ## Steps

            ### checker

            Check whether to continue or stop.

            - type: code
            - next: sender, end

            ```python code
            if True:
                next: str = "end"
            else:
                next: str = "sender"
            result: str = "checked"
            ```

            ### sender

            Send the email.

            - type: shell
            - command: printf '%s' email-sent
            - next: end
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "checker")
        assert not _node_ran(shared, "sender")
        assert shared.get("__warnings__", {}) == {}
        assert shared["__execution__"]["failed_node"] is None

    def test_sub_workflow_end_does_not_leak_to_parent(self) -> None:
        """Inner workflow terminating via 'end' must not stop the parent."""
        markdown = _md("""\
            # Parent Workflow

            Outer workflow continues after sub-workflow ends early.

            ## Steps

            ### run-inner

            Sub-workflow that terminates via end.

            - type: workflow
            - workflow_ir:
                nodes:
                  - id: inner-decider
                    type: code
                    params:
                      code: |
                        next: str = "end"
                        result: str = "inner done"
                  - id: inner-after
                    type: shell
                    params:
                      command: printf '%s' should-not-run
                edges:
                  - from: inner-decider
                    to: inner-after

            ### outer-after

            This must still run.

            - type: shell
            - command: printf '%s' outer-continued
        """)

        shared = parse_compile_and_run(markdown)

        assert _node_ran(shared, "run-inner")
        assert _node_ran(shared, "outer-after")
        assert shared["outer-after"]["stdout"] == "outer-continued"
        assert shared.get("__warnings__", {}) == {}
