"""Regression tests for GH #454: stray ``--flag`` tokens after a workflow name.

Before the fix, ``pflow wf.pflow.md --scenario fail-mid`` silently dropped the
``--scenario`` token (it has no ``=``) and ran with defaults — exit 0, no
warning. For an agent-first CLI that is the worst failure class: a green run on
the wrong inputs. The run command now rejects any stray leading-dash token with
a tailored "use key=value" error, while leaving the ``--help`` passthrough, the
``key=value`` form, and pflow's own flags untouched.

The guard lives in ``pflow.cli.commands.run._validate_workflow_flags`` (called
before workflow resolution) and inspects the post-Click ``workflow`` tuple.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.commands.run import _PFLOW_FLAGS, _suggest_key_value, _validate_workflow_flags, run
from pflow.cli.main import main
from pflow.core.user_errors import UserFriendlyError
from tests.shared.markdown_utils import write_workflow_file

_WF_IR = {
    "inputs": {
        "scenario": {
            "type": "string",
            "required": False,
            "default": "happy",
            "description": "The scenario to run.",
        }
    },
    "nodes": [
        {
            "id": "echo",
            "type": "shell",
            "purpose": "Echo the scenario value back out.",
            "params": {"command": 'echo "scenario=${scenario}"'},
        }
    ],
}


@pytest.fixture
def workflow_file(tmp_path: Path) -> Path:
    """A minimal valid workflow declaring one optional input ``scenario``."""
    path = tmp_path / "wf454.pflow.md"
    write_workflow_file(_WF_IR, path, title="WF 454", description="Unknown-flag test workflow.")
    return path


class TestValidateWorkflowFlagsGuard:
    """Unit coverage of the guard's decision logic (no workflow file needed)."""

    def test_unknown_long_flag_rejected_with_key_value_suggestion(self):
        """The headline bug: ``--scenario fail-mid`` must raise, not vanish, and
        the suggestion must teach the canonical ``scenario=fail-mid`` form."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", "--scenario", "fail-mid"))
        err = exc_info.value
        assert err.title == "Unknown option '--scenario'"
        assert "key=value" in err.explanation
        assert any("scenario=fail-mid" in s for s in err.suggestions)
        # Inputs are listed via per-workflow --help using the concrete name.
        assert any("pflow wf.pflow.md --help" in s for s in err.suggestions)
        assert not any("describe" in s for s in err.suggestions)

    def test_spaced_workflow_path_is_quoted_in_suggestions(self):
        """Commands emitted for spaced paths must remain copy-pasteable."""
        target = "./draft files/wf.pflow.md"

        with pytest.raises(UserFriendlyError) as misplaced:
            _validate_workflow_flags((target, "--verbose"))
        assert misplaced.value.suggestions == [f"pflow --verbose '{target}'"]

        with pytest.raises(UserFriendlyError) as unknown:
            _validate_workflow_flags((target, "--scenario"))
        assert any(f"pflow '{target}' --help" in suggestion for suggestion in unknown.value.suggestions)

    def test_unknown_flag_pairs_its_following_value(self):
        """An unknown flag pairs with the token that follows it for the hint."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", "--nonsense-flag", "xyz"))
        assert any("nonsense-flag=xyz" in s for s in exc_info.value.suggestions)

    def test_unknown_flag_without_value_suggests_placeholder(self):
        """A trailing flag with no value falls back to ``key=<value>``."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", "--scenario"))
        assert any("scenario=<value>" in s for s in exc_info.value.suggestions)

    def test_forgot_workflow_name_first_token_is_dash(self):
        """When the name is omitted entirely, ``workflow[0]`` is itself a dash
        token — it must still be caught, not treated as a workflow name."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("--scenario", "x"))
        assert exc_info.value.title == "Unknown option '--scenario'"

    @pytest.mark.parametrize("flag", ["--verbose", "-v"])
    def test_misplaced_pflow_flag_says_move_before(self, flag):
        """A real pflow flag in the wrong place keeps the precise "move it
        before the workflow" message — distinct from the unknown-option path.
        The suggestion is a concrete, runnable command (flag before the name),
        never the removed natural-language form (``pflow --verbose "..."``)."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", flag))
        err = exc_info.value
        assert err.title == "CLI flags must come BEFORE the workflow"
        assert flag in err.explanation
        assert err.suggestions == [f"pflow {flag} wf.pflow.md"]
        # Guard against re-introducing the stale natural-language suggestion.
        assert all('"' not in s for s in err.suggestions)

    def test_short_help_flag_points_to_double_dash_help(self):
        """``-h`` (currently unwired) is rejected loudly with a pointer to the
        real ``--help`` rather than a nonsensical ``h=<value>`` suggestion. The
        pointer is concrete (uses the typed name) and uses ``--help``, which
        accepts file paths (unlike ``pflow describe``)."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", "-h"))
        err = exc_info.value
        assert err.title == "Unknown option '-h'"
        assert "--help" in err.explanation
        assert err.suggestions == ["pflow wf.pflow.md --help"]

    def test_first_unknown_flag_reported_when_several(self):
        """Only the first stray token is surfaced; fixing it re-runs to the next."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", "--foo", "a", "--bar", "b"))
        assert exc_info.value.title == "Unknown option '--foo'"

    def test_misplaced_pflow_flag_wins_over_unknown_flag(self):
        """When a misplaced pflow flag AND an unknown flag are both present, the
        pflow-flag diagnosis surfaces first — it's the more confident call. The
        unknown flag re-surfaces on the next run. Pins the precedence so a future
        refactor can't silently flip it."""
        with pytest.raises(UserFriendlyError) as exc_info:
            _validate_workflow_flags(("wf.pflow.md", "--scenario", "x", "--verbose"))
        assert exc_info.value.title == "CLI flags must come BEFORE the workflow"

    def test_pflow_flags_mirrors_run_command_options(self):
        """`_PFLOW_FLAGS` must list every run-command option (plus the group-level
        flags that land in the workflow tuple when misplaced) so the "move it
        before the workflow" message stays precise instead of degrading to the
        generic "Unknown option" path.

        This is primarily a consistency/documentation invariant: declared run
        options are consumed by Click regardless of position (`allow_interspersed_args`),
        so they rarely reach the guard — drift mostly costs the wrong suggestion in
        the degenerate `-- <flag>` case. Limitation: `group_flags` is hardcoded, so
        a NEWLY added group-level flag won't be auto-detected here.
        """
        declared = {opt for p in run.params for opt in getattr(p, "opts", []) + getattr(p, "secondary_opts", [])}
        run_flags = {f for f in declared if f.startswith("-") and f != "--help"}
        group_flags = {"--verbose", "-v"}
        missing = (run_flags | group_flags) - _PFLOW_FLAGS
        assert not missing, f"_PFLOW_FLAGS drifted from run options; missing: {missing}"

    @pytest.mark.parametrize(
        "workflow",
        [
            (),
            ("wf.pflow.md",),
            ("wf.pflow.md", "scenario=fail-mid"),
            ("my-workflow", "scenario=fail-mid"),
            ("wf.pflow.md", "--help"),
            ("wf.pflow.md", "--help", "scenario=x"),
            # Standalone --help is consumed at the group level and normally never
            # reaches this guard; included so the whitelist is pinned even if that
            # routing ever changes.
            ("--help",),
        ],
    )
    def test_valid_invocations_do_not_raise(self, workflow):
        """Names, ``key=value`` params, and ``--help`` must all pass cleanly."""
        assert _validate_workflow_flags(workflow) is None

    def test_equals_dash_form_left_to_downstream_validator(self):
        """``--scenario=fail-mid`` has an ``=`` and is intentionally NOT caught
        here — it already fails loudly via the undeclared-input validator
        ("Unknown input '--scenario', did you mean 'scenario'?"). Keeping the
        guard scoped to the dash-WITHOUT-``=`` form avoids changing that path."""
        assert _validate_workflow_flags(("wf.pflow.md", "--scenario=fail-mid")) is None


class TestSuggestKeyValue:
    """Unit coverage of the ``key=value`` suggestion builder."""

    @pytest.mark.parametrize(
        ("flag", "workflow", "expected"),
        [
            ("--scenario", ("wf.pflow.md", "--scenario", "fail-mid"), "scenario=fail-mid"),
            ("--nonsense-flag", ("--nonsense-flag", "xyz"), "nonsense-flag=xyz"),
            ("--scenario", ("wf.pflow.md", "--scenario"), "scenario=<value>"),
            ("--scenario", ("wf.pflow.md", "--scenario", "--other"), "scenario=<value>"),
            ("--scenario", ("wf.pflow.md", "--scenario", "k=v"), "scenario=<value>"),
        ],
    )
    def test_suggestion(self, flag, workflow, expected):
        assert _suggest_key_value(flag, workflow) == expected


class TestUnknownFlagCLI:
    """End-to-end coverage through the real CLI surface (CliRunner)."""

    def test_stray_flag_no_longer_silently_dropped(self, workflow_file):
        """The exact repro from #454: exit 1 (was 0) with an actionable error."""
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, [str(workflow_file), "--scenario", "fail-mid"])
        assert result.exit_code == 1
        assert "Unknown option '--scenario'" in result.stderr
        assert "scenario=fail-mid" in result.stderr

    def test_workflow_help_still_works(self, workflow_file):
        """Regression pin: ``--help`` is whitelisted and reaches per-workflow
        help instead of being rejected by the guard."""
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, [str(workflow_file), "--help"])
        assert result.exit_code == 0
        assert "Inputs:" in result.output
        assert "scenario" in result.output

    def test_misplaced_verbose_flag_after_workflow(self, workflow_file):
        """``--verbose`` (a group flag) lands in the tuple and keeps its
        tailored "must come BEFORE" message end-to-end."""
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, [str(workflow_file), "--verbose"])
        assert result.exit_code == 1
        assert "CLI flags must come BEFORE the workflow" in result.stderr
        assert "--verbose" in result.stderr

    def test_key_value_param_not_rejected(self, workflow_file):
        """No false positive: a legitimate ``key=value`` param validates fine."""
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--validate-only", str(workflow_file), "scenario=fail-mid"])
        assert result.exit_code == 0, result.stderr

    def test_json_mode_error_is_parseable(self, workflow_file):
        """Agent surface: in JSON mode the rejection is a parseable error
        object on stdout with exit 1 (not a silent success)."""
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--output-format", "json", str(workflow_file), "--scenario", "fail-mid"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["success"] is False
        assert payload["error"] == "Unknown option '--scenario'"
        assert any("scenario=fail-mid" in s for s in payload["errors"][0]["suggestions"])
