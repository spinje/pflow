"""Tests for direct execution helper functions in CLI."""

from types import SimpleNamespace

import click
import click.testing

from pflow.cli.param_parsing import infer_type, parse_workflow_params
from pflow.cli.workflow_errors import _display_text_error_details
from pflow.cli.workflow_output import _display_execution_summary, _format_cost_summary_lines
from pflow.cli.workflow_resolution import is_likely_workflow_name
from pflow.core.diagnostic import Diagnostic, Severity


class TestInferType:
    """Test type inference from string values."""

    def test_boolean_true(self):
        """Test that 'true' variants are converted to boolean True."""
        assert infer_type("true") is True
        assert infer_type("True") is True
        assert infer_type("TRUE") is True

    def test_boolean_false(self):
        """Test that 'false' variants are converted to boolean False."""
        assert infer_type("false") is False
        assert infer_type("False") is False
        assert infer_type("FALSE") is False

    def test_integer(self):
        """Test integer detection."""
        assert infer_type("42") == 42
        assert infer_type("0") == 0
        assert infer_type("-10") == -10
        assert isinstance(infer_type("42"), int)

    def test_float(self):
        """Test float detection."""
        assert infer_type("3.14") == 3.14
        assert infer_type("-2.5") == -2.5
        assert infer_type("1e5") == 100000.0
        assert isinstance(infer_type("3.14"), float)

    def test_json_array(self):
        """Test JSON array parsing."""
        assert infer_type('["a", "b", "c"]') == ["a", "b", "c"]
        assert infer_type("[1, 2, 3]") == [1, 2, 3]
        assert infer_type("[]") == []

    def test_json_object(self):
        """Test JSON object parsing."""
        assert infer_type('{"key": "value"}') == {"key": "value"}
        assert infer_type('{"num": 42}') == {"num": 42}
        assert infer_type("{}") == {}

    def test_string_default(self):
        """Test that non-special strings remain strings."""
        assert infer_type("hello") == "hello"
        assert infer_type("data.csv") == "data.csv"
        assert infer_type("/path/to/file") == "/path/to/file"
        assert infer_type("true-but-not-boolean") == "true-but-not-boolean"

    def test_invalid_json_stays_string(self):
        """Test that invalid JSON stays as string."""
        assert infer_type("[invalid") == "[invalid"
        assert infer_type("{bad json}") == "{bad json}"


class TestParseWorkflowParams:
    """Test parameter parsing from command arguments."""

    def test_single_param(self):
        """Test parsing a single parameter."""
        result = parse_workflow_params(("input_file=data.csv",))
        assert result == {"input_file": "data.csv"}

    def test_multiple_params(self):
        """Test parsing multiple parameters."""
        args = ("input_file=data.csv", "output_dir=results/", "limit=100")
        result = parse_workflow_params(args)
        assert result == {
            "input_file": "data.csv",
            "output_dir": "results/",
            "limit": 100,  # Note: inferred as int
        }

    def test_no_params(self):
        """Test with no parameters."""
        assert parse_workflow_params(()) == {}
        assert parse_workflow_params(("no-equals-sign",)) == {}

    def test_type_inference_in_params(self):
        """Test that type inference works in parameter parsing."""
        args = ("verbose=true", "count=42", "ratio=3.14", "items=[1,2,3]", 'config={"key":"value"}')
        result = parse_workflow_params(args)
        assert result["verbose"] is True
        assert result["count"] == 42
        assert result["ratio"] == 3.14
        assert result["items"] == [1, 2, 3]
        assert result["config"] == {"key": "value"}

    def test_empty_value(self):
        """Test parameter with empty value."""
        result = parse_workflow_params(("key=",))
        assert result == {"key": ""}

    def test_multiple_equals_signs(self):
        """Test parameter value containing equals sign."""
        result = parse_workflow_params(("expression=a=b+c",))
        assert result == {"expression": "a=b+c"}


class TestIsLikelyWorkflowName:
    """Test workflow name detection heuristics."""

    def test_with_parameters(self):
        """Test that args with parameters are detected as workflow names."""
        assert is_likely_workflow_name("my-workflow", ("input=data.csv", "output=result"))
        assert is_likely_workflow_name("analyzer", ("file=test.txt",))
        # But not if it's CLI syntax with =>
        assert not is_likely_workflow_name("node1", ("=>", "node2"))
        assert not is_likely_workflow_name("read-file", ("--path=data.txt", "=>", "process"))

    def test_kebab_case(self):
        """Test that kebab-case names are detected."""
        assert is_likely_workflow_name("my-analyzer", ())
        assert is_likely_workflow_name("generate-report", ())
        assert is_likely_workflow_name("test-workflow-name", ())
        # But not if followed by CLI syntax
        assert not is_likely_workflow_name("read-file", ("=>", "process"))

    def test_natural_language(self):
        """Test that natural language is not detected as workflow name."""
        assert not is_likely_workflow_name("analyze the data", ())
        assert not is_likely_workflow_name("create a report from csv", ())
        assert not is_likely_workflow_name("process this file", ())

    def test_excluded_starters(self):
        """Test that common command starters are excluded."""
        # Single words without params are not treated as workflow names anymore
        assert not is_likely_workflow_name("analyze", ())
        assert not is_likely_workflow_name("create", ())
        assert not is_likely_workflow_name("generate", ())
        assert not is_likely_workflow_name("process", ())

    def test_single_word_workflow(self):
        """Test single word that could be workflow name."""
        # Single words without kebab-case or params are NOT workflow names
        assert not is_likely_workflow_name("myworkflow", ())
        assert not is_likely_workflow_name("reporter", ())
        assert not is_likely_workflow_name("analyze", ())
        # But they are if they have params
        assert is_likely_workflow_name("myworkflow", ("input=data.csv",))
        assert is_likely_workflow_name("reporter", ("format=pdf",))

    def test_edge_cases(self):
        """Test edge cases."""
        # Empty string
        assert not is_likely_workflow_name("", ())
        # Very long string without spaces (unlikely workflow name)
        long_name = "a" * 60
        assert not is_likely_workflow_name(long_name, ())
        # With spaces never a workflow name
        assert not is_likely_workflow_name("has spaces", ("param=value",))

    def test_help_flag_handling(self):
        """Test that --help flag is allowed with workflow names."""
        # --help is special-cased to allow showing workflow help
        assert is_likely_workflow_name("my-workflow", ("--help",))
        assert is_likely_workflow_name("read-file", ("--help",))
        assert is_likely_workflow_name("test-workflow-name", ("--help",))

        # Other flags still indicate natural language
        assert not is_likely_workflow_name("my-workflow", ("--verbose",))
        assert not is_likely_workflow_name("my-workflow", ("--force",))

        # --help with other arguments
        assert is_likely_workflow_name("my-workflow", ("--help", "param=value"))


class TestDisplayCostSummary:
    """Tests for _format_cost_summary_lines pricing warning display."""

    @staticmethod
    def _make_formatted_result(
        pricing_available: bool = True,
        unavailable_models: list[dict[str, object]] | None = None,
        partial_cost_usd: float | None = None,
        unavailable_models_unnamed_count: int = 0,
        total_calls: int = 0,
        tokens_total: int = 15,
    ) -> dict:
        """Build a synthetic formatted result for cost-display tests.

        ``unavailable_models`` uses the F#17-deferred shape
        ``list[{name, calls}]`` consumed by the helper-normalizer in
        ``cli/workflow_output.py::_format_cost_summary_lines``.

        The cost line reads ``metrics.workflow.tokens_total`` (production keeps
        it equal to ``metrics.total.tokens_total`` — both summed from the same
        llm_calls). ``tokens_input``/``tokens_output`` are unread display filler.
        """
        total: dict = {
            "tokens_input": 10,
            "tokens_output": 5,
            "tokens_total": tokens_total,
            "total_calls": total_calls,
            "cost_usd": None,
        }
        if not pricing_available:
            total["pricing_available"] = False
            total["unavailable_models"] = unavailable_models or []
            total["unavailable_models_unnamed_count"] = unavailable_models_unnamed_count
            if partial_cost_usd is not None:
                total["partial_cost_usd"] = partial_cost_usd
        return {"metrics": {"total": total, "workflow": {"tokens_total": tokens_total}}}

    def test_unknown_model_shows_warning(self) -> None:
        """When LiteLLM has no pricing for the model, show warning with model name."""
        result = self._make_formatted_result(
            pricing_available=False,
            unavailable_models=[{"name": "my-custom-model", "calls": 4}],
            total_calls=4,
        )
        out = "\n".join(_format_cost_summary_lines(None, result))
        assert "Cost unavailable" in out
        # F#17 deferred: per-model call count in parenthetical
        assert "my-custom-model (4 calls)" in out
        # F#17 deferred: total LLM calls sibling line (3-space indent)
        assert "   Total LLM calls: 4" in out

    def test_partial_cost_shows_partial_with_models(self) -> None:
        """When some models have pricing, show partial cost."""
        result = self._make_formatted_result(
            pricing_available=False,
            unavailable_models=[{"name": "unknown-model", "calls": 1}],
            partial_cost_usd=0.03,
            total_calls=2,
        )
        out = "\n".join(_format_cost_summary_lines(None, result))
        assert "$0.0300+" in out
        assert "unknown-model (1 call)" in out
        assert "   Total LLM calls: 2" in out

    def test_known_model_shows_normal_cost(self) -> None:
        """When pricing is available, show normal cost."""
        result = self._make_formatted_result(total_calls=3)
        out = "\n".join(_format_cost_summary_lines(0.05, result))
        assert "$0.0500" in out
        assert "unavailable" not in out.lower()
        # F#17 deferred: priced multi-call line carries the call count
        assert "3 calls" in out

    def test_priced_cost_line_shows_token_count(self) -> None:
        """The priced cost line surfaces the cache-inclusive total-token count.

        Regression guard: the code read the wrong key (``total_tokens``) while
        MetricsCollector emits ``tokens_total``, so this detail silently rendered
        as 0 (never shown) for every run. The fixture now uses the production key.
        """
        result = self._make_formatted_result(total_calls=2, tokens_total=28000)
        out = "\n".join(_format_cost_summary_lines(0.05, result))
        assert "28,000 tokens" in out

    def test_priced_cost_line_token_count_over_one_million_uses_separators(self) -> None:
        """Token counts ≥ 1M render with thousands separators, no overflow or
        abbreviation — matching the trace-report summary convention."""
        result = self._make_formatted_result(total_calls=9, tokens_total=2137122)
        out = "\n".join(_format_cost_summary_lines(0.05, result))
        assert "2,137,122 tokens" in out

    def test_known_model_singular_call_uses_singular_noun(self) -> None:
        """F#17 wording lock: single LLM call renders as ``1 call``."""
        result = self._make_formatted_result(total_calls=1)
        out = "\n".join(_format_cost_summary_lines(0.05, result))
        assert "$0.0500" in out
        assert "1 call" in out
        assert "1 calls" not in out

    def test_zero_cost_shows_nothing(self) -> None:
        """When cost is zero, produce no lines."""
        result = self._make_formatted_result()
        assert _format_cost_summary_lines(0.0, result) == []

    def test_total_llm_calls_suppressed_when_zero(self) -> None:
        """Honest unmeasurable: workflows with no LLM calls must NOT show
        ``Total LLM calls: 0``."""
        result = self._make_formatted_result(total_calls=0)
        out = "\n".join(_format_cost_summary_lines(0.05, result))
        # Cost line shows but no sibling line for zero calls.
        assert "$0.0500" in out
        assert "Total LLM calls" not in out

    def test_unnamed_only_shows_count_not_unknown(self) -> None:
        """Regression: genuinely-unrecorded calls render as a clear count
        rather than the opaque literal ``"unknown"``."""
        result = self._make_formatted_result(
            pricing_available=False,
            unavailable_models=[],
            unavailable_models_unnamed_count=3,
            total_calls=3,
        )
        out = "\n".join(_format_cost_summary_lines(None, result))
        assert "3 calls without recorded model" in out
        assert "unknown" not in out
        assert "   Total LLM calls: 3" in out

    def test_named_plus_unnamed_shows_both(self) -> None:
        """A mix surfaces both real model names and the unnamed-count
        tally in the rendered phrase."""
        result = self._make_formatted_result(
            pricing_available=False,
            unavailable_models=[{"name": "my-custom-model", "calls": 3}],
            unavailable_models_unnamed_count=2,
            partial_cost_usd=0.01,
            total_calls=5,
        )
        out = "\n".join(_format_cost_summary_lines(None, result))
        # Locked wording from F#17 deferred spec
        assert "my-custom-model (3 calls); 2 calls without recorded model" in out
        assert "   Total LLM calls: 5" in out


class TestDisplayExecutionSummaryAdvisories:
    """CLI default summary splits INFO advisories from WARNING-severity
    diagnostics (``cli/workflow_output.py::_display_execution_summary``).

    Guards the CLI half of the empty-batch advisory fix: an INFO advisory must
    render under 'Advisories' with a clean '✓ Workflow completed' header, while
    a real WARNING still degrades the header under 'Warnings'.
    """

    @staticmethod
    def _formatted() -> dict:
        """Minimal synthetic shape mirroring format_execution_success output."""
        return {
            "duration_ms": 100,
            "total_cost_usd": None,
            "status": "success",
            "workflow": {"name": "wf", "action": "unsaved"},
            "execution": {"steps": [], "cache_hits": 0, "nodes_executed": 1},
        }

    def test_info_advisory_renders_under_advisories_not_warnings(self) -> None:
        formatted = self._formatted()
        advisory = Diagnostic(
            severity=Severity.INFO,
            message="Batch 'consume' ran with 0 items (input list was empty).",
            node_id="consume",
            source="runtime",
        )

        @click.command()
        def cmd() -> None:
            _display_execution_summary(formatted, verbose=False, warning_diagnostics=[advisory])

        cli_result = click.testing.CliRunner().invoke(cmd)
        assert cli_result.exit_code == 0, cli_result.output
        assert "✓ Workflow completed" in cli_result.output
        assert "with 1 warnings" not in cli_result.output
        assert "⚠️ Warnings:" not in cli_result.output
        assert "Advisories:" in cli_result.output
        assert "ran with 0 items" in cli_result.output

    def test_real_warning_still_degrades_under_warnings(self) -> None:
        """Contrast: a WARNING keeps the degraded header and the Warnings section."""
        formatted = self._formatted()
        warning = Diagnostic(
            severity=Severity.WARNING,
            message="something genuinely off",
            node_id="n",
            source="runtime",
        )

        @click.command()
        def cmd() -> None:
            _display_execution_summary(formatted, verbose=False, warning_diagnostics=[warning])

        cli_result = click.testing.CliRunner().invoke(cmd)
        assert "Workflow completed with 1 warnings" in cli_result.output
        assert "⚠️ Warnings:" in cli_result.output
        assert "Advisories:" not in cli_result.output

    def test_legacy_warnings_dict_key_does_not_resurrect_old_count(self) -> None:
        """The completion-header count derives from the partitioned
        ``warning_diagnostics``, NOT the legacy ``formatted_result['warnings']``
        list. A stray INFO entry in that key must not re-trigger the pre-fix
        '⚠️ completed with N warnings' header — pins the regression against the
        old ``len(formatted_result.get('warnings', []))`` source.
        """
        formatted = self._formatted()
        advisory = Diagnostic(
            severity=Severity.INFO,
            message="Batch 'consume' ran with 0 items (input list was empty).",
            node_id="consume",
            source="runtime",
        )
        # Simulate the legacy data source still carrying the advisory: the
        # pre-fix code counted this list, so a regression to that source would
        # mis-render the header.
        formatted["warnings"] = [advisory.to_display_dict()]

        @click.command()
        def cmd() -> None:
            _display_execution_summary(formatted, verbose=False, warning_diagnostics=[advisory])

        cli_result = click.testing.CliRunner().invoke(cmd)
        assert "✓ Workflow completed" in cli_result.output
        assert "with 1 warnings" not in cli_result.output


class TestDisplayFailureDetailsAdvisories:
    def test_info_advisory_renders_under_advisories_not_warnings(self) -> None:
        error = Diagnostic(
            severity=Severity.ERROR,
            message="workflow failed",
            source="runtime",
        )
        advisory = Diagnostic(
            severity=Severity.INFO,
            message="Line 3: '## Input' looks like a typo for '## Inputs'.",
            source="parser",
        )

        @click.command()
        def cmd() -> None:
            _display_text_error_details(SimpleNamespace(errors=[error], diagnostics=[error, advisory]))

        cli_result = click.testing.CliRunner(mix_stderr=False).invoke(cmd)

        assert cli_result.exit_code == 0, cli_result.output
        assert "Advisories:" in cli_result.stderr
        assert "⚠️ Warnings:" not in cli_result.stderr
        assert "1 warning" not in cli_result.stderr
        assert "## Input" in cli_result.stderr
