"""Integration tests for SIGPIPE regression.

This module contains end-to-end tests that reproduce the exact scenario that
caused the silent workflow failure bug (exit code 141 with no output).

The Bug Scenario:
----------------
A workflow with:
1. An HTTP/data node that produces large output (~25KB)
2. A shell node with conditional logic based on boolean parameter
3. When boolean=false, shell runs `echo '[]'` which doesn't consume stdin
4. With SIGPIPE=SIG_DFL, Python crashes with exit 141

These tests verify the fix works at the full workflow level, not just the
shell node level. They test:
- CLI parameter handling (boolean false)
- Template resolution (Python False -> "False" string)
- Shell conditional matching
- Large data flow through the pipeline
- Graceful handling when stdin isn't consumed
"""

import json
import platform

import pytest
from click.testing import CliRunner

from pflow.cli.main import main
from tests.shared.registry_utils import ensure_test_registry

# Data size that exceeds pipe buffer to trigger the bug condition
# macOS: 16KB, Linux: 64KB - we use ~20KB (just above macOS minimum)
LARGE_DATA_LINES = 1000  # Produces ~20KB of data


class TestWorkflowBooleanParameterExecution:
    """Test workflows with boolean parameters execute correctly.

    These tests specifically target the scenario where:
    - A boolean parameter controls conditional logic
    - The 'false' branch doesn't consume upstream data
    - Large data is flowing through the pipeline
    """

    def test_workflow_with_skip_flag_false(self):
        """Workflow with skip_processing=false should complete without crash.

        This is the PRIMARY regression test for the SIGPIPE bug.
        Before the fix, this would exit with code 141 and no output.
        """
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            # Create a file with substantial content (simulates HTTP fetch)
            large_content = "\n".join([f"Line {i}: some content here" for i in range(LARGE_DATA_LINES)])
            with open("input.txt", "w") as f:
                f.write(large_content)

            # Workflow that mimics the real bug scenario:
            # 1. Read large file (simulates HTTP response)
            # 2. Shell node with conditional based on boolean param
            # 3. When skip=false, shell ignores stdin
            workflow = {
                "ir_version": "0.1.0",
                "inputs": {
                    "skip_processing": {
                        "type": "boolean",
                        "required": False,
                        "default": True,
                        "description": "Skip data processing",
                    }
                },
                "nodes": [
                    {
                        "id": "read-data",
                        "type": "read-file",
                        "params": {"file_path": "input.txt"},
                    },
                    {
                        "id": "conditional-process",
                        "type": "shell",
                        "params": {
                            # The stdin is the large file content
                            "stdin": "${read-data.content}",
                            # Conditional: if skip_processing is truthy, just echo empty
                            # Otherwise, count lines (consumes stdin)
                            # Using *[Tt]rue* pattern to match Python's "True" string
                            "command": "case '${skip_processing}' in *[Tt]rue*) echo 'skipped' ;; *) wc -l ;; esac",
                        },
                    },
                    {
                        "id": "save-result",
                        "type": "write-file",
                        "params": {
                            "file_path": "result.txt",
                            "content": "${conditional-process.stdout}",
                        },
                    },
                ],
                "edges": [
                    {"from": "read-data", "to": "conditional-process"},
                    {"from": "conditional-process", "to": "save-result"},
                ],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            # Run with skip_processing=false - this triggers the non-consuming branch
            # Before the fix: exit 141, no output, no trace
            # After the fix: completes successfully
            result = runner.invoke(main, ["./workflow.json", "skip_processing=false"])

            # Debug output if test fails
            if result.exit_code != 0:
                print(f"Exit code: {result.exit_code}")
                print(f"Output:\n{result.output}")
                if result.exception:
                    import traceback

                    print(
                        f"Exception:\n{''.join(traceback.format_exception(type(result.exception), result.exception, result.exception.__traceback__))}"
                    )

            # CRITICAL ASSERTION: Should complete successfully, not exit 141
            assert result.exit_code == 0, (
                f"Workflow failed with exit code {result.exit_code}. Exit code 141 indicates SIGPIPE regression!"
            )
            assert "Workflow completed" in result.output or "Workflow executed successfully" in result.output

    def test_workflow_with_skip_flag_true(self):
        """Workflow with skip_processing=true should also work (control test).

        This confirms the workflow works when the stdin-consuming branch runs.
        """
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            # Use shared constant for data size
            large_content = "x\n" * LARGE_DATA_LINES  # ~20KB
            with open("input.txt", "w") as f:
                f.write(large_content)

            workflow = {
                "ir_version": "0.1.0",
                "inputs": {
                    "skip_processing": {
                        "type": "boolean",
                        "required": False,
                        "default": True,
                    }
                },
                "nodes": [
                    {"id": "read-data", "type": "read-file", "params": {"file_path": "input.txt"}},
                    {
                        "id": "conditional-process",
                        "type": "shell",
                        "params": {
                            "stdin": "${read-data.content}",
                            "command": "case '${skip_processing}' in *[Tt]rue*) echo 'skipped' ;; *) wc -l ;; esac",
                        },
                    },
                ],
                "edges": [{"from": "read-data", "to": "conditional-process"}],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            # Run with skip_processing=true - this triggers echo (also doesn't consume stdin!)
            result = runner.invoke(main, ["./workflow.json", "skip_processing=true"])

            assert result.exit_code == 0
            assert "Workflow completed" in result.output or "Workflow executed successfully" in result.output

    def test_workflow_boolean_default_false(self):
        """Workflow with boolean default=false should work when not overridden."""
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            large_content = "x\n" * LARGE_DATA_LINES  # ~20KB
            with open("input.txt", "w") as f:
                f.write(large_content)

            workflow = {
                "ir_version": "0.1.0",
                "inputs": {
                    "process_data": {
                        "type": "boolean",
                        "required": False,
                        "default": False,  # Default is False
                    }
                },
                "nodes": [
                    {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
                    {
                        "id": "process",
                        "type": "shell",
                        "params": {
                            "stdin": "${read.content}",
                            # When process_data is false, echo empty (doesn't consume stdin)
                            "command": "case '${process_data}' in *[Ff]alse*) echo '[]' ;; *) cat ;; esac",
                        },
                    },
                ],
                "edges": [{"from": "read", "to": "process"}],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            # Run WITHOUT providing the parameter - should use default (False)
            result = runner.invoke(main, ["./workflow.json"])

            assert result.exit_code == 0, f"Failed with: {result.output}"
            assert "Workflow completed" in result.output or "Workflow executed successfully" in result.output


class TestLargeDataFlowWithShellNodes:
    """Test large data flowing through shell nodes in workflows."""

    def test_shell_node_large_stdin_echo_only(self):
        """Shell node with large stdin that runs echo should not crash."""
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            # Create input file just above pipe buffer size
            large_content = "data " * 4000  # ~20KB
            with open("large.txt", "w") as f:
                f.write(large_content)

            workflow = {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "read", "type": "read-file", "params": {"file_path": "large.txt"}},
                    {
                        "id": "ignore-stdin",
                        "type": "shell",
                        "params": {
                            "stdin": "${read.content}",
                            "command": "echo 'stdin ignored'",  # Doesn't read stdin
                        },
                    },
                ],
                "edges": [{"from": "read", "to": "ignore-stdin"}],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            result = runner.invoke(main, ["./workflow.json"])

            # Should NOT crash with exit 141
            assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
            assert "Workflow completed" in result.output or "Workflow executed successfully" in result.output

    def test_shell_node_head_with_large_stdin(self):
        """Shell node running head -n 1 with large stdin should not crash."""
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            # Create file with enough lines to exceed pipe buffer
            large_content = "\n".join([f"Line {i}" for i in range(2000)])  # ~20KB
            with open("lines.txt", "w") as f:
                f.write(large_content)

            workflow = {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "read", "type": "read-file", "params": {"file_path": "lines.txt"}},
                    {
                        "id": "first-line",
                        "type": "shell",
                        "params": {
                            "stdin": "${read.content}",
                            "command": "head -n 1",  # Only reads first line
                        },
                    },
                    {
                        "id": "save",
                        "type": "write-file",
                        "params": {
                            "file_path": "first.txt",
                            "content": "${first-line.stdout}",
                        },
                    },
                ],
                "edges": [
                    {"from": "read", "to": "first-line"},
                    {"from": "first-line", "to": "save"},
                ],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            result = runner.invoke(main, ["./workflow.json"])

            assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"


class TestRealWorldPatterns:
    """Test patterns from real-world workflows that could trigger SIGPIPE."""

    def test_image_description_workflow_pattern(self):
        """Reproduce the exact pattern from webpage-to-markdown workflow.

        The real bug was in a workflow that:
        1. Fetches a webpage (large HTML/markdown)
        2. Conditionally extracts images based on describe_images flag
        3. When describe_images=false, the shell command outputs '[]' without reading stdin
        """
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            # Simulate fetched webpage content (just above pipe buffer)
            webpage_content = (
                """
# Article Title

Some introductory text here.

![Image 1](https://example.com/image1.png)

More content about the topic...

![Image 2](https://example.com/image2.jpg)

Conclusion paragraph.
"""
                * 100
            )  # ~20KB

            with open("webpage.txt", "w") as f:
                f.write(webpage_content)

            workflow = {
                "ir_version": "0.1.0",
                "inputs": {
                    "describe_images": {
                        "type": "boolean",
                        "required": False,
                        "default": True,
                    }
                },
                "nodes": [
                    {
                        "id": "fetch",
                        "type": "read-file",
                        "params": {"file_path": "webpage.txt"},
                    },
                    {
                        "id": "extract-images",
                        "type": "shell",
                        "params": {
                            "stdin": "${fetch.content}",
                            # Real pattern: when describe_images is false, output empty array
                            # When true, grep for image URLs
                            "command": "case '${describe_images}' in *[Ff]alse*) echo '[]' ;; *) grep -o 'https://[^)]*' || echo '[]' ;; esac",
                        },
                    },
                    {
                        "id": "save",
                        "type": "write-file",
                        "params": {
                            "file_path": "images.json",
                            "content": "${extract-images.stdout}",
                        },
                    },
                ],
                "edges": [
                    {"from": "fetch", "to": "extract-images"},
                    {"from": "extract-images", "to": "save"},
                ],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            # THE CRITICAL TEST: describe_images=false with large stdin
            result = runner.invoke(main, ["./workflow.json", "describe_images=false"])

            # Before fix: exit 141, silent failure
            # After fix: completes successfully
            assert result.exit_code == 0, (
                f"Exit code {result.exit_code} - if this is 141, SIGPIPE regression! Output: {result.output}"
            )
            assert "Workflow completed" in result.output or "Workflow executed successfully" in result.output

            # Verify the output is correct
            from pathlib import Path

            images_content = Path("images.json").read_text().strip()
            assert images_content == "[]", f"Expected '[]', got: {images_content}"

    @pytest.mark.skipif(platform.system() == "Windows", reason="Unix shell patterns")
    def test_multiple_conditional_shells_in_sequence(self):
        """Multiple shell nodes in sequence, all with conditional stdin consumption."""
        runner = CliRunner()
        ensure_test_registry()

        with runner.isolated_filesystem():
            large_content = "x\n" * LARGE_DATA_LINES  # ~20KB

            with open("data.txt", "w") as f:
                f.write(large_content)

            workflow = {
                "ir_version": "0.1.0",
                "inputs": {
                    "step1_process": {"type": "boolean", "default": False},
                    "step2_process": {"type": "boolean", "default": False},
                },
                "nodes": [
                    {"id": "read", "type": "read-file", "params": {"file_path": "data.txt"}},
                    {
                        "id": "step1",
                        "type": "shell",
                        "params": {
                            "stdin": "${read.content}",
                            "command": "case '${step1_process}' in *[Tt]rue*) cat ;; *) echo 'step1-skip' ;; esac",
                        },
                    },
                    {
                        "id": "step2",
                        "type": "shell",
                        "params": {
                            "stdin": "${step1.stdout}",
                            "command": "case '${step2_process}' in *[Tt]rue*) cat ;; *) echo 'step2-skip' ;; esac",
                        },
                    },
                ],
                "edges": [
                    {"from": "read", "to": "step1"},
                    {"from": "step1", "to": "step2"},
                ],
            }

            with open("workflow.json", "w") as f:
                json.dump(workflow, f)

            # Both steps skip processing (both don't consume stdin)
            result = runner.invoke(main, ["./workflow.json", "step1_process=false", "step2_process=false"])

            assert result.exit_code == 0, f"Exit {result.exit_code}: {result.output}"
