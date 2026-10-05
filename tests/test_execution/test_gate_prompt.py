"""Unit tests for the TTY gate resolver (Task 125 Phase 3 — execution/gate_prompt.py).

The resolver is the ONE builder every surface uses (CLI interactive, MCP non-TTY,
parallel-batch worker via ``allow_prompt=False``). These tests pin its contract:
auto-approve is approval-only and thread-config-independent; prompting requires
stdin+stderr TTY (NOT stdout — Decision 14); every no-prompt path raises the
payload-carrying ``GateNotInteractiveError``; Ctrl-C (click Abort) becomes
``KeyboardInterrupt`` so the engine never archives it as a node failure.
"""

from __future__ import annotations

from typing import Any

import click
import pytest

from pflow.core.exceptions import GateNotInteractiveError
from pflow.core.gate import GateRequest, GateResolution
from pflow.execution.gate_prompt import build_gate_resolver, can_prompt


class _FakeOC:
    """Duck-typed OutputController: just the fields/seam the resolver reads."""

    def __init__(
        self, *, stdin_tty: bool = True, stdout_tty: bool = False, stderr_tty: bool = True, print_flag: bool = False
    ):
        self.stdin_tty = stdin_tty
        self.stdout_tty = stdout_tty
        self.stderr_tty = stderr_tty
        self.print_flag = print_flag
        self.prompt_preparations = 0

    def prepare_for_prompt(self) -> None:
        self.prompt_preparations += 1


def _approval(node_id: str = "notify", **preview: Any) -> GateRequest:
    return GateRequest(
        node_id=node_id, node_type="ShellNode", kind="action_approval", preview=preview or {"command": "echo hi"}
    )


def _escalation(**kwargs: Any) -> GateRequest:
    return GateRequest(node_id="agent-step", node_type="AgentNode", kind="decision_escalation", **kwargs)


class TestCanPrompt:
    def test_requires_stdin_and_stderr_tty_but_not_stdout(self):
        # Decision 14: `pflow wf | jq` (stdout piped) at a real terminal must still gate.
        assert can_prompt(_FakeOC(stdin_tty=True, stderr_tty=True, stdout_tty=False)) is True

    def test_false_without_controller_or_under_print_flag_or_non_tty(self):
        assert can_prompt(None) is False
        assert can_prompt(_FakeOC(print_flag=True)) is False
        assert can_prompt(_FakeOC(stdin_tty=False)) is False
        assert can_prompt(_FakeOC(stderr_tty=False)) is False


class TestAutoApprove:
    def test_flag_approves_named_approval_gate_without_prompting(self):
        resolver = build_gate_resolver(frozenset({"notify"}), None)
        resolution = resolver(_approval("notify"))
        assert resolution == GateResolution(approved=True, resolved_via="flag")

    def test_flag_works_with_prompting_disallowed(self):
        # The parallel-batch worker path: allow_prompt=False must not disable the flag.
        resolver = build_gate_resolver(frozenset({"notify"}), None)
        resolution = resolver(_approval("notify"), allow_prompt=False)
        assert resolution.approved is True and resolution.resolved_via == "flag"

    def test_flag_never_resolves_an_escalation(self):
        # You cannot pre-answer an unknown question.
        resolver = build_gate_resolver(frozenset({"agent-step"}), None)
        with pytest.raises(GateNotInteractiveError):
            resolver(_escalation(question="which schema?"))

    def test_unlisted_gate_without_tty_raises_with_payload(self):
        resolver = build_gate_resolver(frozenset({"other"}), None)
        with pytest.raises(GateNotInteractiveError) as exc_info:
            resolver(_approval("notify"))
        assert exc_info.value.request.node_id == "notify"
        assert exc_info.value.parallel_batch is False

    def test_allow_prompt_false_is_the_only_source_of_parallel_batch(self):
        resolver = build_gate_resolver(frozenset(), _FakeOC())
        with pytest.raises(GateNotInteractiveError) as exc_info:
            resolver(_approval(), allow_prompt=False)
        assert exc_info.value.parallel_batch is True

    def test_flag_echo_suppressed_on_worker_thread_with_real_output_controller(self, capsys):
        # Code-review fix: the auto-approve visibility echo must NOT touch a real
        # (unbuffered) OutputController when called with allow_prompt=False — that
        # combination means this call is running on a parallel-batch WORKER
        # thread, where the per-worker progress buffer (not the real controller)
        # is the only concurrency-safe channel. Previously this test gap existed
        # because the only prior coverage used output_controller=None (the echo
        # early-returns regardless) or a RecordingResolver test double (never
        # touches build_gate_resolver's real echo at all).
        oc = _FakeOC()
        resolver = build_gate_resolver(frozenset({"notify"}), oc)
        resolution = resolver(_approval("notify"), allow_prompt=False)
        assert resolution == GateResolution(approved=True, resolved_via="flag")
        assert oc.prompt_preparations == 0, "must not touch the real OutputController from a worker thread"
        assert capsys.readouterr().err == ""

    def test_flag_echo_still_fires_on_main_thread(self, capsys):
        oc = _FakeOC()
        resolver = build_gate_resolver(frozenset({"notify"}), oc)
        resolver(_approval("notify"), allow_prompt=True)
        assert oc.prompt_preparations == 1
        assert "pre-approved via --auto-approve=notify" in capsys.readouterr().err


class TestApprovalAnswer:
    """Resume's single-use ``approval_answer`` — `pflow resume <id> --approve yes|no` (Task 171, #615)."""

    def test_yes_answers_exactly_one_occurrence(self, capsys):
        # A looping gate's next iteration is a new action — the answer must not
        # become a standing approval for the id (it pauses again, Task 179).
        resolver = build_gate_resolver(frozenset(), _FakeOC(stdin_tty=False), approval_answer=("notify", True))
        assert resolver(_approval("notify")) == GateResolution(approved=True, resolved_via="flag")
        assert "Gate 'notify' approved via --approve yes" in capsys.readouterr().err
        with pytest.raises(GateNotInteractiveError):
            resolver(_approval("notify"))

    def test_no_denies_via_flag_without_prompting(self):
        resolver = build_gate_resolver(frozenset(), None, approval_answer=("notify", False))
        resolution = resolver(_approval("notify"), allow_prompt=False)
        assert resolution == GateResolution(approved=False, resolved_via="flag")

    def test_answer_checked_before_auto_approve(self):
        # Backstop only — the CLI rejects `--approve no --auto-approve <same>` up
        # front. A silent approve here would run a step the human explicitly denied.
        resolver = build_gate_resolver(frozenset({"notify"}), _FakeOC(), approval_answer=("notify", False))
        assert resolver(_approval("notify")).approved is False

    def test_auto_approve_covers_occurrences_after_the_answer(self, capsys):
        # `--approve yes --auto-approve <id>`: the answer resolves the paused gate,
        # the flag every later iteration.
        resolver = build_gate_resolver(frozenset({"notify"}), _FakeOC(), approval_answer=("notify", True))
        assert resolver(_approval("notify")).approved is True
        assert resolver(_approval("notify")).approved is True
        err = capsys.readouterr().err
        assert "approved via --approve yes" in err
        assert "pre-approved via --auto-approve=notify" in err

    def test_answer_never_touches_escalations(self):
        # You cannot pre-answer a question; an answered id on an escalation still
        # raises the non-interactive error (no controller to prompt through).
        resolver = build_gate_resolver(frozenset(), None, approval_answer=("agent-step", True))
        with pytest.raises(GateNotInteractiveError):
            resolver(_escalation(question="a or b?"))

    def test_answer_ignores_other_gates_and_is_not_consumed_by_them(self):
        resolver = build_gate_resolver(frozenset({"other"}), None, approval_answer=("notify", False))
        assert resolver(_approval("other"), allow_prompt=False).approved is True
        assert resolver(_approval("notify"), allow_prompt=False).approved is False


class TestPromptFlows:
    def test_approval_yes_and_no(self, monkeypatch):
        oc = _FakeOC()
        resolver = build_gate_resolver(frozenset(), oc)
        for answer, approved in ((True, True), (False, False)):
            monkeypatch.setattr(click, "confirm", lambda *a, _answer=answer, **k: _answer)
            resolution = resolver(_approval())
            assert resolution.approved is approved
            assert resolution.resolved_via == "prompt"
        assert oc.prompt_preparations == 2, "prompt must close the open progress partial line first"

    def test_escalation_numbered_choice_maps_to_option_label(self, monkeypatch):
        monkeypatch.setattr(click, "prompt", lambda *a, **k: "2")
        resolver = build_gate_resolver(frozenset(), _FakeOC())
        request = _escalation(
            question="one config file or per-env?",
            options=({"label": "merge", "description": "simpler"}, {"label": "per-env", "tradeoffs": "more files"}),
            recommendation="per-env",
        )
        resolution = resolver(request)
        assert resolution == GateResolution(approved=True, resolved_via="prompt", chosen="per-env")

    def test_escalation_free_text_becomes_chosen(self, monkeypatch):
        monkeypatch.setattr(click, "prompt", lambda *a, **k: "  keep both, gate on env var  ")
        resolver = build_gate_resolver(frozenset(), _FakeOC())
        resolution = resolver(_escalation(question="?", options=({"label": "a"},)))
        assert resolution.chosen == "keep both, gate on env var"

    def test_escalation_unicode_numeric_answer_is_free_text_not_a_crash(self, monkeypatch):
        # "²".isdigit() is True but int("²") raises ValueError — the guard uses
        # isdecimal() so a stray unicode-numeric answer folds as free text (mirrors
        # resume_source._map_choose_answer's durable --choose rule).
        monkeypatch.setattr(click, "prompt", lambda *a, **k: "²")
        resolver = build_gate_resolver(frozenset(), _FakeOC())
        resolution = resolver(_escalation(question="?", options=({"label": "a"},)))
        assert resolution.chosen == "²"

    def test_out_of_range_number_is_free_text_not_crash(self, monkeypatch):
        monkeypatch.setattr(click, "prompt", lambda *a, **k: "9")
        resolver = build_gate_resolver(frozenset(), _FakeOC())
        resolution = resolver(_escalation(question="?", options=({"label": "a"},)))
        assert resolution.chosen == "9"

    def test_ctrl_c_abort_becomes_keyboard_interrupt(self, monkeypatch):
        # click.Abort is an Exception subclass — if it escaped as-is, the engine's
        # generic except arm would archive the gate as a node failure.
        def _abort(*a: Any, **k: Any) -> bool:
            raise click.exceptions.Abort()

        monkeypatch.setattr(click, "confirm", _abort)
        resolver = build_gate_resolver(frozenset(), _FakeOC())
        with pytest.raises(KeyboardInterrupt):
            resolver(_approval())


class TestPreviewRendering:
    def _rendered(self, request: GateRequest, monkeypatch, capsys) -> str:
        monkeypatch.setattr(click, "confirm", lambda *a, **k: True)
        build_gate_resolver(frozenset(), _FakeOC())(request)
        return capsys.readouterr().err

    def test_secret_values_masked_long_values_truncated_newlines_escaped(self, monkeypatch, capsys):
        rendered = self._rendered(
            _approval(api_key="sk-super-secret", body="line1\nline2", note="x" * 500),
            monkeypatch,
            capsys,
        )
        assert "sk-super-secret" not in rendered
        assert "line1\\nline2" in rendered
        assert "… (500 chars)" in rendered
        assert "Approval required: notify (ShellNode)" in rendered

    def test_non_string_values_render_as_compact_json(self, monkeypatch, capsys):
        rendered = self._rendered(_approval(payload={"a": 1, "b": [True, None]}), monkeypatch, capsys)
        assert '{"a": 1, "b": [true, null]}' in rendered

    def test_nested_secret_in_dict_value_is_redacted(self, monkeypatch, capsys):
        # Code-review fix: mask_sensitive_value only checks the top-level key —
        # a secret nested inside a dict/list value (headers on an http node,
        # inputs on a sub-workflow) must not render verbatim.
        rendered = self._rendered(
            _approval(headers={"Authorization": "Bearer sk-super-secret", "Accept": "application/json"}),
            monkeypatch,
            capsys,
        )
        assert "sk-super-secret" not in rendered
        assert "<REDACTED>" in rendered
        assert "application/json" in rendered  # non-secret nested value survives

    def test_long_nonsecret_nested_value_survives_to_display_budget(self, monkeypatch, capsys):
        # PR #554 review warning: routing preview values through
        # sanitize_parameters cut long NON-secret nested strings to ~20 chars —
        # blinding the approver. Masking must not truncate; only the renderer's
        # 200-char display budget applies.
        body = "b" * 150
        rendered = self._rendered(
            _approval(json={"body": body, "token": "sk-super-secret"}),
            monkeypatch,
            capsys,
        )
        assert body in rendered  # full 150-char value visible (under the 200 budget)
        assert "<truncated>" not in rendered
        assert "sk-super-secret" not in rendered  # nested secret still redacted

    def test_nested_secret_in_list_of_dicts_is_redacted(self, monkeypatch, capsys):
        rendered = self._rendered(
            _approval(inputs=[{"api_key": "sk-live-abc123"}, {"name": "safe"}]),
            monkeypatch,
            capsys,
        )
        assert "sk-live-abc123" not in rendered
        assert "safe" in rendered

    def test_escalation_renders_options_with_recommendation_marker(self, monkeypatch, capsys):
        monkeypatch.setattr(click, "prompt", lambda *a, **k: "1")
        build_gate_resolver(frozenset(), _FakeOC())(
            _escalation(
                question="merge configs?",
                options=(
                    {"label": "merge", "description": "simpler", "tradeoffs": "breaks overrides"},
                    {"label": "split"},
                ),
                recommendation="split",
            )
        )
        rendered = capsys.readouterr().err
        assert "Escalation from agent-step" in rendered
        assert "merge configs?" in rendered
        assert "1. merge — simpler — breaks overrides" in rendered
        assert "2. split (rec)" in rendered


class TestPausedGateRendering:
    """Task 171 — format_gate_lines / format_resume_answer_command: the pause
    surfaces render the SAME content shape as the blocking prompt, from the
    GateRequest.to_dict() payload (what the trace trailer carries)."""

    def test_loop_gate_leads_with_its_iteration(self):
        """Task 179: one rule serves every pause surface (CLI stderr, MCP ``Gate:`` block,
        the answer-required error) — a loop step's gate leads with ``Loop iteration N``."""
        from dataclasses import replace

        from pflow.execution.gate_prompt import format_gate_lines

        approval = replace(_approval(command="deploy"), iteration=2).to_dict()
        assert format_gate_lines(approval)[:2] == ["Loop iteration 2", "command:  deploy"]
        escalation = replace(_escalation(question="which?"), iteration=3).to_dict()
        assert format_gate_lines(escalation)[:2] == ["Loop iteration 3", "which?"]
        # A non-loop gate (iteration None) has no such line.
        assert format_gate_lines(_approval(command="deploy").to_dict()) == ["command:  deploy"]

    def test_approval_lines_mask_secrets(self):
        from pflow.execution.gate_prompt import format_gate_lines

        payload = _approval(command="deploy", api_key="sk-live-abc").to_dict()
        lines = format_gate_lines(payload)
        text = "\n".join(lines)
        assert "deploy" in text
        assert "<REDACTED>" in text
        assert "sk-live-abc" not in text

    def test_escalation_lines_match_prompt_option_rendering(self):
        from pflow.execution.gate_prompt import format_gate_lines

        payload = _escalation(
            question="merge configs?",
            options=(
                {"label": "merge", "description": "simpler", "tradeoffs": "breaks overrides"},
                {"label": "split"},
            ),
            recommendation="split",
        ).to_dict()
        lines = format_gate_lines(payload)
        # The exact label extraction the blocking prompt uses — `--choose N`
        # maps numbers to precisely what is shown here.
        assert lines[0] == "merge configs?"
        assert lines[1] == "1. merge — simpler — breaks overrides"
        assert lines[2] == "2. split (rec)"

    def test_resume_answer_command_pairs_verb_with_kind(self):
        from pflow.execution.gate_prompt import format_resume_answer_command

        approval = format_resume_answer_command("tok-1", _approval().to_dict())
        assert approval == "pflow resume tok-1 --approve yes|no"
        escalation = format_resume_answer_command("tok-2", _escalation(question="q?").to_dict())
        assert escalation == 'pflow resume tok-2 --choose "<answer or option number>"'


class TestLoopIterationInPromptHeaders:
    """Task 179: the blocking prompt and the flag echo render their own header from the
    live request — a loop step's names the iteration, a non-loop step's does not."""

    def test_approval_prompt_and_flag_echo_name_the_iteration(self, monkeypatch, capsys):
        from dataclasses import replace

        monkeypatch.setattr(click, "confirm", lambda *a, **k: True)
        build_gate_resolver(frozenset(), _FakeOC())(replace(_approval(), iteration=2))
        build_gate_resolver(frozenset({"notify"}), _FakeOC())(replace(_approval(), iteration=3))
        build_gate_resolver(frozenset(), _FakeOC())(_approval())
        err = capsys.readouterr().err
        assert "Approval required: notify (ShellNode) — iteration 2" in err
        assert "Gate 'notify' — iteration 3 pre-approved via --auto-approve=notify" in err
        assert "Approval required: notify (ShellNode)\n" in err  # the non-loop header, no suffix

    def test_escalation_prompt_names_the_iteration(self, monkeypatch, capsys):
        from dataclasses import replace

        monkeypatch.setattr(click, "prompt", lambda *a, **k: "x")
        build_gate_resolver(frozenset(), _FakeOC())(replace(_escalation(question="q?"), iteration=2))
        assert "Escalation from agent-step — iteration 2:" in capsys.readouterr().err
