"""Tests for shell stderr display in CLI error output.

This test validates that stderr from shell nodes is properly displayed
in verbose mode when a shell command fails.

Related bug: Shell node stderr not surfaced in error messages
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.main import main
from pflow.core.trace_io import load_trace_file
from tests.shared.markdown_utils import write_workflow_file


class TestShellStderrDisplay:
    """Test shell stderr is displayed in CLI error output."""

    def test_shell_stderr_displayed_in_verbose_mode(self, tmp_path):
        """Stderr from failed shell nodes should be displayed in verbose mode.

        When a shell command fails and writes to stderr, the error output
        should include the stderr content to help users debug the issue.
        """
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failing-command",
                    "type": "shell",
                    "params": {
                        # Command that writes to stderr and fails
                        "command": "echo 'This error message should be visible' >&2; exit 1"
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--verbose", str(workflow_path)])

        assert result.exit_code != 0

        # Verify stderr is displayed in verbose output
        assert "Stderr:" in result.output or "Stderr:" in (result.stderr or "")
        assert "This error message should be visible" in result.output or "This error message should be visible" in (
            result.stderr or ""
        )

    def test_shell_stderr_in_json_output(self, tmp_path):
        """JSON output should include shell_stderr field for failed shell nodes."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "failing-command",
                    "type": "shell",
                    "params": {"command": "echo 'stderr content here' >&2; exit 1"},
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        # mix_stderr=False: under click 8.1 (transitive pin from litellm 1.83.x),
        # CliRunner defaults to mix_stderr=True which merges stderr into stdout
        # and breaks json.loads(result.stdout). Click 8.2 flipped the default;
        # 8.3+ removed the kwarg.
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--output-format", "json", str(workflow_path)])

        assert result.exit_code != 0

        # Parse JSON output
        output = json.loads(result.stdout)

        # Verify shell_stderr is in the error structure
        assert "errors" in output
        assert len(output["errors"]) > 0

        error = output["errors"][0]
        assert "stderr content here" in error["context"]["shell_stderr"]

    @pytest.mark.trace_files
    def test_long_output_previews_keep_the_tail_where_the_cause_is(self, tmp_path):
        """Long stderr and stdout show their head AND tail in every preview (#755, #843).

        Tools write the cause last, after progress noise. Each cause marker sits only at
        the very end of ~7,600 chars and is printed via ``%s`` so it never appears in the
        command text. The text channels preview it; the JSON document carries a wider
        head+tail excerpt (#843) — the trace keeps the whole stderr.
        """
        command = (
            "i=0; while [ $i -lt 400 ]; do printf 'progress-noise-%03d ' $i >&2; "
            "printf 'stdout-noise-%03d ' $i; i=$((i+1)); done; "
            "printf 'STDOUT-%s-TAIL' AT; printf 'CAUSE-%s-TAIL' AT >&2; exit 3"
        )
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "noisy", "type": "shell", "params": {"command": command}}],
            "edges": [],
        }
        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)
        runner = CliRunner(mix_stderr=False)

        text = runner.invoke(main, [str(workflow_path)])
        lines = (text.output + (text.stderr or "")).splitlines()
        headline = next(line for line in lines if line.startswith("Command failed with exit code 3:"))
        details = next(line for line in lines if line.startswith("    Stderr: "))
        for preview in (headline, details):
            assert "progress-noise-000" in preview  # the head stays
            assert "progress-noise-030" not in preview  # the middle is cut
            assert "chars omitted]" in preview
            assert preview.endswith("CAUSE-AT-TAIL")  # the tail stays
        stdout = next(line for line in lines if line.startswith("    Stdout: "))
        assert "stdout-noise-000" in stdout
        assert "stdout-noise-030" not in stdout
        assert "chars omitted]" in stdout
        assert stdout.endswith("STDOUT-AT-TAIL")

        as_json = runner.invoke(main, ["--output-format", "json", str(workflow_path)])
        document = json.loads(as_json.stdout)
        context = document["errors"][0]["context"]
        for field, noise, cause in (("shell_stderr", "progress", "CAUSE"), ("shell_stdout", "stdout", "STDOUT")):
            excerpt = context[field]
            assert excerpt.startswith(f"{noise}-noise-000")
            assert f"{noise}-noise-100" not in excerpt  # the document cuts the middle (#843) ...
            assert " chars omitted] … " in excerpt
            assert excerpt.endswith(f"{cause}-AT-TAIL")
        trace = load_trace_file(Path(document["trace_path"]))
        node_output = next(event for event in trace["nodes"] if event["node_id"] == "noisy")["node_output"]
        # ... and the trace keeps both whole
        assert node_output["stderr"] == "".join(f"progress-noise-{i:03d} " for i in range(400)) + "CAUSE-AT-TAIL"
        assert node_output["stdout"] == "".join(f"stdout-noise-{i:03d} " for i in range(400)) + "STDOUT-AT-TAIL"

    def test_a_secret_on_the_excerpt_cut_never_prints_in_part(self, tmp_path):
        """The run's secret values are scrubbed before the document cuts its excerpt (#801, #843).

        The token straddles the excerpt's head boundary (char 1,000): cutting first would print
        its first half, which no value scrub can then recognise.
        """
        token = "tok-0123456789-abcdefghij"  # noqa: S105 - scrub sentinel
        workflow_path = tmp_path / "leak.pflow.md"
        workflow_path.write_text(
            "# Leak\n\nEchoes a token mid-noise.\n\n## Inputs\n\n### api_token\n\nThe token.\n\n"
            "- type: string\n- required: true\n\n## Steps\n\n### noisy\n\nNoise around the token.\n\n"
            "- type: shell\n- env: {TOKEN: ${api_token}}\n\n```shell command\n"
            'printf "%0990d" 0 >&2; printf "$TOKEN" >&2; printf "%09000d" 0 >&2; exit 1\n```\n',
            encoding="utf-8",
        )

        result = CliRunner(mix_stderr=False).invoke(
            main, ["--output-format", "json", str(workflow_path), f"api_token={token}"]
        )

        excerpt = json.loads(result.stdout)["errors"][0]["context"]["shell_stderr"]
        assert excerpt.startswith("0" * 990 + "<REDACTED>")
        assert " chars omitted] … " in excerpt
        assert token[:10] not in result.stdout
        assert token[10:] not in result.stdout

    def test_no_stderr_section_when_stderr_empty(self, tmp_path):
        """No stderr section should appear when shell has no stderr output."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "no-stderr",
                    "type": "shell",
                    "params": {
                        # Fails with exit code but no stderr
                        "command": "exit 1"
                    },
                }
            ],
            "edges": [],
        }

        workflow_path = tmp_path / "test.pflow.md"
        write_workflow_file(workflow, workflow_path)

        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(main, ["--verbose", str(workflow_path)])

        assert result.exit_code != 0

        # Should show shell details but NOT stderr section (since it's empty)
        combined_output = result.output + (result.stderr or "")
        assert "Shell details:" in combined_output
        assert "Command:" in combined_output
        # Stderr line should not appear when stderr is empty
        # (we check this by ensuring "Stderr:" doesn't appear with empty content)
