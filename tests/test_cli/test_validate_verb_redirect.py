"""Tests for the validation-verb redirect.

pflow has no `validate`/`check` subcommand by design — validation is the
`--validate-only` flag on the run path. Agents/humans pattern-match the verb from
other CLIs (`terraform validate`, `cargo check`), so typing `pflow validate <wf>`
must redirect to `pflow <wf> --validate-only` instead of hitting the generic
"invalid input" / "workflow not found" dead-end.

Implementation: src/pflow/cli/commands/run.py::_redirect_validation_verb, called
once from the run handler before workflow resolution so both the no-params and
with-params forms hit the same redirect.
"""

from click.testing import CliRunner

from pflow.cli.main import main


class TestValidationVerbRedirect:
    """`pflow <verb> ...` redirects to the --validate-only flag."""

    def test_validate_name_redirects_to_flag(self):
        """`pflow validate my-workflow` (no params) → --validate-only suggestion."""
        result = CliRunner().invoke(main, ["validate", "my-workflow"])

        assert result.exit_code != 0
        # Names the real incantation and reconstructs the intended target.
        assert "--validate-only" in result.output
        assert "pflow my-workflow --validate-only" in result.output
        # Does not pretend `validate` is a runnable workflow.
        assert "not found" not in result.output.lower()

    def test_validate_with_params_redirects_with_full_target(self):
        """`pflow validate wf.pflow.md repo=x` → params preserved in the suggestion.

        The guard fires before any workflow resolution, so the trailing `repo=x`
        (which would otherwise make the verb look like a named workflow) doesn't
        change the outcome — no bogus "workflow 'validate' not found".
        """
        result = CliRunner().invoke(main, ["validate", "wf.pflow.md", "repo=x"])

        assert result.exit_code != 0
        assert "pflow wf.pflow.md repo=x --validate-only" in result.output
        assert "'validate' not found" not in result.output

    def test_check_synonym_redirects(self):
        """`check` is a close synonym agents reach for (e.g. `cargo check`)."""
        result = CliRunner().invoke(main, ["check", "my-workflow"])

        assert result.exit_code != 0
        assert "pflow has no 'check' command" in result.output
        assert "pflow my-workflow --validate-only" in result.output

    def test_lint_is_not_a_validation_verb(self):
        """`lint` is deliberately NOT redirected — it's reserved for the planned
        linting feature (Task 118). Redirecting it to --validate-only would bake
        in a misleading collision. Pins the exclusion so it isn't re-added."""
        result = CliRunner().invoke(main, ["lint", "my-workflow"])

        assert result.exit_code != 0
        assert "--validate-only" not in result.output

    def test_bare_verb_uses_placeholder_target(self):
        """`pflow validate` with no target → <workflow> placeholder in suggestion."""
        result = CliRunner().invoke(main, ["validate"])

        assert result.exit_code != 0
        assert "pflow <workflow> --validate-only" in result.output

    def test_non_verb_invalid_input_not_hijacked(self):
        """A genuine unknown first token keeps the generic error (no redirect).

        Guards against the redirect over-firing — only validation verbs should
        be rewritten; everything else gets the normal invalid-input guidance.
        """
        result = CliRunner().invoke(main, ["frobnicate", "something"])

        assert result.exit_code != 0
        assert "--validate-only" not in result.output
        assert "not recognized as a valid workflow invocation" in result.output
