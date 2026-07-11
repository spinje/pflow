"""Task 125 — approval gates + escalation: engine seam behavior.

Covers the two ``_execute_node`` hook points (pre-exec approval, post-exec
escalation), the gate-exception boundary exemptions (engine / WorkflowExecutor /
batch retry), the parallel-batch prompt guard, and the cache interactions. The
resolver here is always a test fake implementing the ``core/gate.py`` contract —
the real TTY resolver is Phase 3 (CLI) work.
"""

from __future__ import annotations

from typing import Any

import pytest

from pflow.core.exceptions import GateDenied, GateNotInteractiveError, GateResolverError, PflowError
from pflow.core.gate import GateRequest, GateResolution
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.engine.gate import detect_escalation


class RecordingResolver:
    """Fake resolver: records every request, answers from a script."""

    def __init__(
        self,
        *,
        approved: bool = True,
        chosen: str | None = None,
        notes: str | None = None,
        auto_approve: frozenset[str] = frozenset(),
    ):
        self.approved = approved
        self.chosen = chosen
        self.notes = notes
        self.auto_approve = auto_approve
        self.calls: list[tuple[GateRequest, bool]] = []

    def __call__(self, request: GateRequest, *, allow_prompt: bool) -> GateResolution:
        self.calls.append((request, allow_prompt))
        if request.node_id in self.auto_approve:
            return GateResolution(approved=True, resolved_via="flag")
        if not allow_prompt:
            raise GateNotInteractiveError(request, parallel_batch=True)
        return GateResolution(approved=self.approved, resolved_via="prompt", chosen=self.chosen, notes=self.notes)


def _shell_ir(*, approval_on_b: bool = True) -> dict[str, Any]:
    nodes = [
        {"id": "a", "type": "shell", "params": {"command": "echo hello"}},
        {"id": "b", "type": "shell", "params": {"command": "echo from-${a.stdout}"}},
    ]
    if approval_on_b:
        nodes[1]["approval"] = "required"
    return {"ir_version": "0.1.0", "nodes": nodes, "edges": [{"from": "a", "to": "b"}]}


def _run(ir: dict[str, Any], shared: dict[str, Any]) -> str:
    compiled = compile_workflow(ir, Registry())
    return WorkflowEngine().run(compiled, shared)


class TestApprovalGate:
    def test_approved_gate_continues_and_previews_resolved_params(self):
        resolver = RecordingResolver(approved=True)
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        action = _run(_shell_ir(), shared)
        assert action == "default"
        assert "from-hello" in shared["b"]["stdout"]
        ((request, allow_prompt),) = resolver.calls
        assert request.kind == "action_approval"
        assert request.node_id == "b"
        assert allow_prompt is True
        # The preview shows the RESOLVED template value, not `${a.stdout}`.
        assert request.preview["command"] == "echo from-hello"

    def test_denied_gate_stops_cleanly_before_exec(self, tmp_path):
        marker = tmp_path / "ran.txt"
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo ok"}},
                {"id": "b", "type": "shell", "params": {"command": f"touch {marker}"}, "approval": "required"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }
        shared: dict[str, Any] = {"__gate_resolver__": RecordingResolver(approved=False)}
        with pytest.raises(GateDenied) as exc_info:
            _run(ir, shared)
        # The gated node NEVER ran: no side effect, no namespace, no failure record.
        assert not marker.exists()
        assert "b" not in shared
        assert not shared.get("__failures__")
        assert shared["__execution__"]["failed_node"] is None
        assert exc_info.value.request.node_id == "b"
        assert exc_info.value.retriable is False

    def test_no_resolver_fails_loudly_with_payload(self):
        shared: dict[str, Any] = {}
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _run(_shell_ir(), shared)
        diag = exc_info.value.to_diagnostics()[0]
        # The agent-actionable contract: cause + payload + ask-your-human + scoped flag.
        assert "non-interactive" in diag.message
        assert diag.context["gate"]["node_id"] == "b"
        assert diag.context["gate"]["preview"]["command"] == "echo from-hello"
        assert any("ask your human" in s for s in diag.suggestions)
        assert any("--auto-approve=b" in s for s in diag.suggestions)
        assert not shared.get("__failures__")

    def test_secretlike_preview_values_masked_in_diagnostic_only(self):
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call",
                    "type": "shell",
                    "params": {"command": "echo x", "api_key": "sk-super-secret"},
                    "approval": "required",
                }
            ],
            "edges": [],
        }
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _run(ir, {})
        diag = exc_info.value.to_diagnostics()[0]
        assert diag.context["gate"]["preview"]["api_key"] == "<REDACTED>"
        # The in-memory payload itself stays unmasked (trace-consistent).
        assert exc_info.value.request.preview["api_key"] == "sk-super-secret"

    def test_secret_nested_in_dict_value_masked_in_diagnostic(self):
        # Code-review fix: mask_sensitive_value only checks the TOP-LEVEL key —
        # a secret nested inside a dict value (e.g. `headers:` on an http node)
        # must not reach the MCP/JSON-visible diagnostic unmasked.
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call",
                    "type": "shell",
                    "params": {"command": "echo x", "headers": {"Authorization": "Bearer sk-super-secret"}},
                    "approval": "required",
                }
            ],
            "edges": [],
        }
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _run(ir, {})
        diag = exc_info.value.to_diagnostics()[0]
        assert diag.context["gate"]["preview"]["headers"]["Authorization"] == "<REDACTED>"
        # The in-memory payload itself stays unmasked (trace-consistent).
        assert exc_info.value.request.preview["headers"]["Authorization"] == "Bearer sk-super-secret"

    def test_long_nonsecret_nested_value_intact_in_diagnostic(self):
        # PR #554 review warning: sanitize_parameters cut long non-secret nested
        # values to ~20 chars in the MCP/JSON-visible diagnostic — the agent must
        # be able to show its human the FULL action (approving blind defeats the
        # gate). Masking is mask-only; the diagnostic never truncates.
        body = "b" * 150
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call",
                    "type": "shell",
                    "params": {"command": "echo x", "json": {"body": body, "token": "sk-super-secret"}},
                    "approval": "required",
                }
            ],
            "edges": [],
        }
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _run(ir, {})
        preview = exc_info.value.to_diagnostics()[0].context["gate"]["preview"]
        assert preview["json"]["body"] == body  # full value, no "...<truncated>" cut
        assert "sk-super-secret" not in str(preview)  # nested secret still redacted

    def test_cached_node_never_gates(self, tmp_path, monkeypatch):
        from pathlib import Path

        from pflow.runtime.cache import MemoizationCache

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "g",
                    "type": "shell",
                    "params": {"command": "echo gated"},
                    "approval": "required",
                    "cache": True,
                }
            ],
            "edges": [],
        }
        resolver = RecordingResolver(approved=True)
        shared1: dict[str, Any] = {"__gate_resolver__": resolver, "__memoization_cache__": MemoizationCache()}
        _run(ir, shared1)
        assert len(resolver.calls) == 1
        # Second run hits the memo cache — nothing is about to happen, so no gate.
        shared2: dict[str, Any] = {"__gate_resolver__": resolver, "__memoization_cache__": MemoizationCache()}
        _run(ir, shared2)
        assert shared2["__cache_hits__"] == ["g"]
        assert len(resolver.calls) == 1

    def test_gate_on_loop_node_prompts_every_iteration(self):
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "tick",
                    "type": "code",
                    "params": {
                        "code": "i: int\nresult: dict = {'go': int(i) < 2}",
                        "inputs": {"i": "${__iteration__}"},
                    },
                    "approval": "required",
                    "loop": {"while": "${tick.result.go}", "max_iterations": 5},
                }
            ],
            "edges": [],
        }
        resolver = RecordingResolver(approved=True)
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        _run(ir, shared)
        # while goes falsy on iteration 2 → two executions → two prompts.
        assert len(resolver.calls) == 2

    def test_broken_resolver_return_type_is_loud(self):
        shared: dict[str, Any] = {"__gate_resolver__": lambda request, *, allow_prompt: "yes"}
        with pytest.raises(GateResolverError, match="broken resolver installation"):
            _run(_shell_ir(), shared)


class TestGateResolverFailure:
    """A resolver bug is gate-scoped control flow, never a node failure.

    Without the GateResolverError exemption, an unexpected resolver exception
    falls to the engine's generic except arm — which at the POST-exec escalation
    seam records a duplicate error event and archives the node's genuinely
    successful output into __failures__.
    """

    @staticmethod
    def _crashing_resolver(request: GateRequest, *, allow_prompt: bool) -> GateResolution:
        raise RuntimeError("resolver bug")

    def test_resolver_crash_at_approval_gate_is_gate_scoped(self):
        shared: dict[str, Any] = {"__gate_resolver__": self._crashing_resolver}
        with pytest.raises(GateResolverError, match="RuntimeError: resolver bug"):
            _run(_shell_ir(), shared)
        # The gated node never ran and was NOT archived as a node failure.
        assert "b" not in shared
        assert "b" not in shared.get("__failures__", {})

    def test_resolver_crash_at_escalation_keeps_node_success_record(self):
        shared: dict[str, Any] = {"__gate_resolver__": self._crashing_resolver}
        with pytest.raises(GateResolverError, match="RuntimeError: resolver bug"):
            _run(_code_ir(ESCALATION_CODE), shared)
        # The node's honest success record stands: output in place, no failure archive.
        assert shared["agent"]["result"]["work"] == "partial"
        assert "agent" not in shared.get("__failures__", {})


ESCALATION_CODE = (
    "result: dict = {'escalation': {'question': 'Merge configs?', "
    "'options': [{'label': 'merge', 'description': 'one file'}, "
    "{'label': 'split', 'description': 'per env'}], "
    "'recommendation': 'split'}, 'work': 'partial'}"
)


def _code_ir(code: str, node_id: str = "agent", **extra: Any) -> dict[str, Any]:
    node = {"id": node_id, "type": "code", "params": {"code": code}, **extra}
    return {"ir_version": "0.1.0", "nodes": [node], "edges": []}


class TestEscalation:
    def test_dict_marker_pauses_and_decision_lands_in_marker(self):
        resolver = RecordingResolver(chosen="split", notes="keep env overrides")
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        action = _run(_code_ir(ESCALATION_CODE), shared)
        assert action == "default"
        ((request, _),) = resolver.calls
        assert request.kind == "decision_escalation"
        assert request.question == "Merge configs?"
        assert [o["label"] for o in request.options] == ["merge", "split"]
        assert request.recommendation == "split"
        assert shared["agent"]["result"]["escalation"]["decision"] == {
            "chosen": "split",
            "notes": "keep env overrides",
        }
        # The rest of the node's work product is untouched.
        assert shared["agent"]["result"]["work"] == "partial"

    def test_decided_marker_never_reprompts(self):
        decided = "result: dict = {'escalation': {'question': 'q', 'decision': {'chosen': 'a', 'notes': None}}}"
        resolver = RecordingResolver()
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        _run(_code_ir(decided), shared)
        assert resolver.calls == []

    def test_string_marker_pauses_with_string_as_question(self):
        resolver = RecordingResolver(chosen="postgres")
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        _run(_code_ir("result: dict = {'escalation': 'which db?'}"), shared)
        ((request, _),) = resolver.calls
        assert request.question == "which db?"
        assert shared["agent"]["result"]["escalation"] == {
            "question": "which db?",
            "decision": {"chosen": "postgres", "notes": None},
        }

    @pytest.mark.parametrize(
        "code",
        [
            "result: dict = {'escalation': {}}",  # empty dict — clearly intended, unusable
            "result: dict = {'escalation': 42}",  # unusable shape
            "result: dict = {'escalation': True}",  # unusable shape
        ],
    )
    def test_malformed_marker_warns_and_does_not_pause(self, code):
        resolver = RecordingResolver()
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        _run(_code_ir(code), shared)
        assert resolver.calls == []
        warning = shared["__warnings__"]["agent"]
        assert "did NOT pause" in warning.message

    @pytest.mark.parametrize(
        "code",
        [
            "result: dict = {'no_escalation': 1}",
            "result: dict = {'escalation': None}",
            "result: dict = {'escalation': False}",
            "result: str = 'plain prose without the keyword'",
        ],
    )
    def test_absent_or_falsy_marker_never_pauses_or_warns(self, code):
        resolver = RecordingResolver()
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        _run(_code_ir(code), shared)
        assert resolver.calls == []
        assert "agent" not in shared.get("__warnings__", {})

    def test_schema_softfail_string_result_mentioning_escalation_warns(self):
        # detect_escalation unit path: a claude-code schema soft-failure leaves a
        # raw string result + _schema_error in the namespace.
        shared = {
            "agent": {
                "result": "I think we need an escalation here: the plan conflicts with the data model",
                "_schema_error": "output did not match schema",
            },
            "__warnings__": {},
        }
        assert detect_escalation(shared, "agent") is None
        assert "swallowed" in shared["__warnings__"]["agent"].message

    def test_noninteractive_escalation_keeps_success_record(self):
        shared: dict[str, Any] = {}
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _run(_code_ir(ESCALATION_CODE), shared)
        # The node genuinely succeeded — its record stands; nothing is archived.
        assert shared["agent"]["result"]["work"] == "partial"
        assert not shared.get("__failures__")
        diag = exc_info.value.to_diagnostics()[0]
        assert any("cannot be pre-approved" in s for s in diag.suggestions)

    def test_escalating_result_is_never_cached(self, tmp_path, monkeypatch):
        from pathlib import Path

        from pflow.runtime.cache import MemoizationCache

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ir = _code_ir(ESCALATION_CODE, cache=True)
        resolver = RecordingResolver(chosen="split")
        shared1: dict[str, Any] = {"__gate_resolver__": resolver, "__memoization_cache__": MemoizationCache()}
        _run(ir, shared1)
        # Not in-process-completed, not memo-cached: a fresh run re-executes and re-escalates.
        assert "agent" not in shared1["__execution__"]["completed_nodes"]
        shared2: dict[str, Any] = {"__gate_resolver__": resolver, "__memoization_cache__": MemoizationCache()}
        _run(ir, shared2)
        assert shared2.get("__cache_hits__", []) == []
        assert len(resolver.calls) == 2

    def test_non_escalating_result_still_caches(self, tmp_path, monkeypatch):
        from pathlib import Path

        from pflow.runtime.cache import MemoizationCache

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        ir = _code_ir("result: dict = {'work': 'done'}", cache=True)
        shared1: dict[str, Any] = {"__memoization_cache__": MemoizationCache()}
        _run(ir, shared1)
        assert "agent" in shared1["__execution__"]["completed_nodes"]
        shared2: dict[str, Any] = {"__memoization_cache__": MemoizationCache()}
        _run(ir, shared2)
        assert shared2["__cache_hits__"] == ["agent"]


class TestEscalationContinueSemantics:
    """The escalation CONTINUE mechanism — the reason escalation exists.

    Pins the two timing claims the whole design rests on: the human's decision is
    written to the store BEFORE the walk's loop-re-entry check evaluates `while:`,
    and BEFORE iteration 2's carry resolution reads it. If either ordering broke,
    escalation would pause correctly but the answer would never reach the work.
    """

    def test_escalation_decision_feeds_loop_carry_reentry(self):
        code = (
            "answer: str\n"
            "needs_human = answer == 'none'\n"
            "result: dict = (\n"
            "    {'escalation': {'question': 'which layout?'}, 'go': True}\n"
            "    if needs_human\n"
            "    else {'go': False, 'used': answer}\n"
            ")\n"
        )
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "agent",
                    "type": "code",
                    "params": {"code": code, "inputs": {"answer": "none"}},
                    "loop": {
                        "while": "${agent.result.go}",
                        "max_iterations": 5,
                        "carry": {"answer": "${agent.result.escalation.decision.chosen}"},
                    },
                }
            ],
            "edges": [],
        }
        resolver = RecordingResolver(chosen="split")
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        action = _run(ir, shared)
        assert action == "default"
        # Iteration 1 escalated exactly once; iteration 2 got the human's answer via
        # carry and finished the work with it.
        assert len(resolver.calls) == 1
        assert shared["agent"]["result"] == {"go": False, "used": "split"}
        assert shared["__execution__"]["node_visit_counts"]["agent"] == 2


class TestRunnerBoundary:
    """End-to-end through WorkflowRunner (tests/CLAUDE.md pitfall #20: engine-level
    tests can pass while the real pipeline breaks).

    Pins the production behavior for a gated run with no resolver installed
    (any caller not passing ``gate_resolver`` — e.g. a bare library caller): the
    run fails as a result (never a propagated exception — the CLI's trace finalize
    depends on a non-None result), the payload-carrying gate diagnostic survives
    runner conversion intact, and it is JSON-serializable end to end (the MCP/JSON
    formatters serialize it verbatim). The denied half (Phase 3) maps GateDenied →
    ``WorkflowStatus.DENIED``, pinned below.
    """

    def test_noninteractive_gate_through_runner_keeps_payload_diagnostics(self):
        import json as _json

        from pflow.execution import WorkflowRunner
        from pflow.execution.result import RunnerConfig

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo hello"}},
                {
                    "id": "b",
                    "type": "shell",
                    "params": {"command": "echo from-${a.stdout}"},
                    "approval": "required",
                },
            ],
            "edges": [{"from": "a", "to": "b"}],
        }
        result = WorkflowRunner().run(ir, {}, config=RunnerConfig(trace_enabled=False))
        assert result.success is False
        gate_diags = [d for d in result.diagnostics if (d.context or {}).get("category") == "gate"]
        assert gate_diags, f"gate diagnostic lost in runner conversion: {result.diagnostics}"
        diag = gate_diags[0]
        # The operating agent must see WHAT was about to happen — resolved, not raw.
        assert diag.context["gate"]["preview"]["command"] == "echo from-hello"
        assert any("ask your human" in s for s in (diag.suggestions or []))
        _json.dumps(diag.to_dict())  # must survive the JSON/MCP serialization path
        # Upstream work is preserved and the gated node never ran / never "failed".
        assert "hello" in result.shared_after["a"]["stdout"]
        assert "b" not in result.shared_after
        assert not result.shared_after.get("__failures__")

    def test_denied_gate_through_runner_yields_denied_status_not_failed(self):
        """Phase 3 (Decision 5): a human's "no" is WorkflowStatus.DENIED — a clean
        stop the CLI maps to exit 3 — never FAILED, never a __failures__ entry."""
        from pflow.core.gate import GateResolution
        from pflow.core.workflow.status import WorkflowStatus
        from pflow.execution import WorkflowRunner
        from pflow.execution.result import RunnerConfig

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "shell", "params": {"command": "echo hello"}},
                {"id": "b", "type": "shell", "params": {"command": "echo boom"}, "approval": "required"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }

        def deny(request, *, allow_prompt=True):
            return GateResolution(approved=False, resolved_via="prompt")

        result = WorkflowRunner().run(ir, {}, config=RunnerConfig(trace_enabled=False), gate_resolver=deny)
        assert result.success is False
        assert result.status is WorkflowStatus.DENIED
        # The gated node never ran, nothing broke, upstream survives.
        assert "b" not in result.shared_after
        assert not result.shared_after.get("__failures__")
        assert "hello" in result.shared_after["a"]["stdout"]
        # The denial diagnostic carries the gate payload for the JSON/MCP surfaces.
        gate_diags = [d for d in result.diagnostics if (d.context or {}).get("category") == "gate"]
        assert gate_diags and gate_diags[0].node_id == "b"

    def test_approving_resolver_installed_via_runner_reaches_nested_engines(self, tmp_path):
        """The gate_resolver kwarg mirrors progress_callback: __gate_resolver__ is
        propagated into sub-workflow child engines, so a CHILD gate prompts/approves
        through the SAME resolver with zero WorkflowExecutor plumbing."""
        from pflow.core.gate import GateResolution
        from pflow.execution import WorkflowRunner
        from pflow.execution.result import RunnerConfig

        child_path = tmp_path / "child.pflow.md"
        child_path.write_text(
            "# Child\n\nChild with a gated step.\n\n## Steps\n\n"
            "### gated-child\n\nDo the child action.\n\n"
            "- type: shell\n"
            "- command: echo child-ran\n"
            "- approval: required\n",
            encoding="utf-8",
        )
        parent = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": str(child_path)}}],
            "edges": [],
        }
        seen: list[str] = []

        def approve(request, *, allow_prompt=True):
            seen.append(request.node_id)
            return GateResolution(approved=True, resolved_via="prompt")

        result = WorkflowRunner().run(parent, {}, config=RunnerConfig(trace_enabled=False), gate_resolver=approve)
        assert result.success, f"child-gated run failed: {[d.message for d in result.diagnostics]}"
        assert seen == ["gated-child"]


class TestBatchInteractions:
    def _batch_escalation_ir(self, *, decided: bool = False) -> dict[str, Any]:
        decision = ", 'decision': {'chosen': 'x'}" if decided else ""
        code = f"item: str\nresult: dict = {{'escalation': {{'question': 'item asks: ' + str(item){decision}}}}}"
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "worker",
                    "type": "code",
                    "params": {"code": code, "inputs": {"item": "${item}"}},
                    "batch": {"items": "${items}", "as": "item"},
                }
            ],
            "edges": [],
        }

    def test_undecided_escalation_in_batch_item_fails_loudly_with_context(self):
        shared: dict[str, Any] = {"items": ["alpha", "beta"], "__gate_resolver__": RecordingResolver()}
        with pytest.raises(PflowError) as exc_info:
            _run(self._batch_escalation_ir(), shared)
        message = str(exc_info.value)
        assert "batch item 1 of 2" in message
        assert "item asks: alpha" in message
        assert "outside the batch" in message

    def test_batch_escalation_reports_original_item_index_when_earlier_item_failed(self):
        # `results` holds successes only — with item 1 (alpha) failing, the
        # escalating item 2 (beta) sits at results[0]. The error must still
        # name it "batch item 2 of 2", not "1 of 2".
        code = (
            "item: str\n"
            "if item == 'alpha':\n"
            "    raise ValueError('boom')\n"
            "result: dict = {'escalation': {'question': 'item asks: ' + str(item)}}"
        )
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "worker",
                    "type": "code",
                    "params": {"code": code, "inputs": {"item": "${item}"}},
                    "batch": {"items": "${items}", "as": "item", "error_handling": "continue"},
                }
            ],
            "edges": [],
        }
        shared: dict[str, Any] = {"items": ["alpha", "beta"], "__gate_resolver__": RecordingResolver()}
        with pytest.raises(PflowError) as exc_info:
            _run(ir, shared)
        message = str(exc_info.value)
        assert "batch item 2 of 2" in message
        assert "item asks: beta" in message

    def test_decided_escalation_in_batch_item_is_skipped(self):
        shared: dict[str, Any] = {"items": ["alpha"], "__gate_resolver__": RecordingResolver()}
        action = _run(self._batch_escalation_ir(decided=True), shared)
        assert action == "default"

    def test_approval_gate_before_batch_previews_and_batch_runs(self):
        # Decision 1's recommended shape: gate the step BEFORE the batch.
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "confirm", "type": "shell", "params": {"command": "echo go"}, "approval": "required"},
                {
                    "id": "fan",
                    "type": "code",
                    "params": {"code": "item: int\nresult: str = str(item)", "inputs": {"item": "${item}"}},
                    "batch": {"items": "${items}", "as": "item"},
                },
            ],
            "edges": [{"from": "confirm", "to": "fan"}],
        }
        resolver = RecordingResolver(approved=True)
        shared: dict[str, Any] = {"items": [1, 2, 3], "__gate_resolver__": resolver}
        _run(ir, shared)
        assert len(resolver.calls) == 1
        assert shared["fan"]["count"] == 3


class TestSubWorkflowBoundary:
    def _child_workflow(self, tmp_path, *, gated_command: str = "echo child-action") -> str:
        child = tmp_path / "child.pflow.md"
        child.write_text(
            "# Child\n\nChild with a gated step.\n\n## Steps\n\n"
            "### gated-step\n\nDo the child action.\n\n"
            "- type: shell\n"
            f"- command: {gated_command}\n"
            "- approval: required\n",
            encoding="utf-8",
        )
        return str(child)

    def _parent_ir(self, child_path: str, **node_extra: Any) -> dict[str, Any]:
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "sub", "type": "workflow", "params": {"workflow": child_path}, **node_extra}],
            "edges": [],
        }

    def test_gate_inside_subworkflow_prompts_via_propagated_resolver(self, tmp_path):
        resolver = RecordingResolver(approved=True)
        shared: dict[str, Any] = {"__gate_resolver__": resolver}
        action = _run(self._parent_ir(self._child_workflow(tmp_path)), shared)
        assert action == "default"
        ((request, _),) = resolver.calls
        assert request.node_id == "gated-step"

    def test_denial_inside_subworkflow_crosses_boundary_unconverted(self, tmp_path):
        shared: dict[str, Any] = {"__gate_resolver__": RecordingResolver(approved=False)}
        with pytest.raises(GateDenied):
            _run(self._parent_ir(self._child_workflow(tmp_path)), shared)
        assert not shared.get("__failures__")

    def test_denial_is_not_routable_via_error_action_continue(self, tmp_path):
        # Decision 5/11: a workflow must not "handle" a human's no.
        ir = self._parent_ir(self._child_workflow(tmp_path))
        ir["nodes"][0]["params"]["error_action"] = "continue"
        shared: dict[str, Any] = {"__gate_resolver__": RecordingResolver(approved=False)}
        with pytest.raises(GateDenied):
            _run(ir, shared)

    def test_denial_in_sequential_batch_item_stops_run_without_retry_reprompt(self, tmp_path):
        child_path = self._child_workflow(tmp_path)
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "workflow",
                    "params": {"workflow": child_path},
                    "batch": {"items": "${items}", "as": "item", "max_retries": 3},
                }
            ],
            "edges": [],
        }
        resolver = RecordingResolver(approved=False)
        shared: dict[str, Any] = {"items": [1, 2, 3], "__gate_resolver__": resolver}
        with pytest.raises(GateDenied):
            _run(ir, shared)
        # retriable=False: the batch retry loop must NOT re-prompt a human who said no,
        # and later items must not prompt either.
        assert len(resolver.calls) == 1

    def test_parallel_batch_gate_cannot_prompt_but_flag_approval_works(self, tmp_path):
        child_path = self._child_workflow(tmp_path)

        def batch_ir() -> dict[str, Any]:
            return {
                "ir_version": "0.1.0",
                "nodes": [
                    {
                        "id": "sub",
                        "type": "workflow",
                        "params": {"workflow": child_path},
                        "batch": {"items": "${items}", "as": "item", "parallel": True, "error_handling": "continue"},
                    }
                ],
                "edges": [],
            }

        # Without a pre-approval: the worker cannot prompt → loud, truthful error.
        resolver = RecordingResolver(approved=True)
        shared: dict[str, Any] = {"items": [1], "__gate_resolver__": resolver}
        with pytest.raises(GateNotInteractiveError) as exc_info:
            _run(batch_ir(), shared)
        assert exc_info.value.parallel_batch is True
        ((_request, allow_prompt),) = resolver.calls
        assert allow_prompt is False

        # With the gate pre-approved (flag lookup is thread-safe): the batch runs.
        approver = RecordingResolver(auto_approve=frozenset({"gated-step"}))
        shared2: dict[str, Any] = {"items": [1, 2], "__gate_resolver__": approver}
        action = _run(batch_ir(), shared2)
        assert action == "default"
        assert shared2["sub"]["success_count"] == 2
