"""Tests for workflow interface description formatter.

Ensures consistent output formatting between CLI and MCP server.
"""

from pflow.execution.formatters.workflow_describe_formatter import (
    _format_example_usage_section,
    _format_inputs_section,
    _format_outputs_section,
    format_workflow_interface,
)


class TestFormatWorkflowInterface:
    """Test complete workflow interface formatting."""

    def test_formats_complete_workflow(self):
        """FORMAT: Complete workflow with inputs, outputs, and description."""
        metadata = {
            "description": "Analyzes GitHub pull requests",
            "ir": {
                "inputs": {
                    "repo": {
                        "required": True,
                        "description": "Repository name (org/repo format)",
                    },
                    "pr_number": {"required": True, "description": "Pull request number"},
                    "verbose": {
                        "required": False,
                        "description": "Enable verbose output",
                        "default": False,
                    },
                },
                "outputs": {
                    "analysis": {"description": "Detailed PR analysis"},
                    "summary": {"description": "Executive summary"},
                },
            },
        }

        result = format_workflow_interface("pr-analyzer", metadata)

        # Verify all sections present
        assert "Workflow: pr-analyzer" in result
        assert "Description: Analyzes GitHub pull requests" in result
        assert "\nInputs:" in result
        assert "  - repo (required): Repository name (org/repo format)" in result
        assert "  - pr_number (required): Pull request number" in result
        assert "  - verbose (optional): Enable verbose output" in result
        assert "    Default: False" in result
        assert "\nOutputs:" in result
        assert "  - analysis: Detailed PR analysis" in result
        assert "  - summary: Executive summary" in result
        assert "\nExample Usage:" in result
        assert "  pflow pr-analyzer repo=<value> pr_number=<value>" in result

    def test_formats_workflow_with_no_description(self):
        """FORMAT: Workflow with missing description shows default."""
        metadata = {
            "ir": {
                "inputs": {"name": {"required": True, "description": "User name"}},
                "outputs": {"greeting": {"description": "Greeting message"}},
            }
        }

        result = format_workflow_interface("greeter", metadata)

        assert "Workflow: greeter" in result
        assert "Description: No description" in result

    def test_formats_workflow_with_empty_description(self):
        """FORMAT: Workflow with empty description shows empty value."""
        metadata = {
            "description": "",
            "ir": {
                "inputs": {"name": {"required": True, "description": "Name"}},
            },
        }

        result = format_workflow_interface("test", metadata)

        assert "Description: " in result
        # Empty description should be preserved, not replaced with "No description"

    def test_formats_workflow_with_special_characters_in_descriptions(self):
        """FORMAT: Descriptions with special characters are preserved."""
        metadata = {
            "description": "Uses $variable and ${template} syntax",
            "ir": {
                "inputs": {
                    "pattern": {
                        "required": True,
                        "description": "Regex pattern with special chars: ^[a-z]+$",
                    }
                },
                "outputs": {"result": {"description": 'Output with quotes: "quoted" value'}},
            },
        }

        result = format_workflow_interface("special", metadata)

        assert "Uses $variable and ${template} syntax" in result
        assert "^[a-z]+$" in result
        assert '"quoted"' in result


class TestFormatInputsSection:
    """Test input section formatting."""

    def test_formats_required_and_optional_inputs(self):
        """INPUTS: Shows required/optional status correctly."""
        ir = {
            "inputs": {
                "required_param": {"required": True, "description": "Required parameter"},
                "optional_param": {
                    "required": False,
                    "description": "Optional parameter",
                },
            }
        }

        result = _format_inputs_section(ir)

        assert "required_param (required):" in result
        assert "optional_param (optional):" in result

    def test_formats_inputs_with_defaults(self):
        """INPUTS: Shows default values indented."""
        ir = {
            "inputs": {
                "count": {
                    "required": False,
                    "description": "Number of items",
                    "default": 10,
                },
                "enabled": {
                    "required": False,
                    "description": "Enable feature",
                    "default": True,
                },
                "message": {
                    "required": False,
                    "description": "Message text",
                    "default": "Hello",
                },
            }
        }

        result = _format_inputs_section(ir)

        # Verify defaults are shown with proper indentation
        assert "    Default: 10" in result
        assert "    Default: True" in result
        assert "    Default: Hello" in result

    def test_formats_input_defaults_with_none_value(self):
        """INPUTS: None default value is NOT shown (matches CLI behavior)."""
        ir = {
            "inputs": {
                "value": {
                    "required": False,
                    "description": "Optional value",
                    "default": None,
                },
            }
        }

        result = _format_inputs_section(ir)

        # None is treated same as missing default - not displayed
        assert "Default:" not in result
        assert "value (optional): Optional value" in result

    def test_formats_input_defaults_with_zero(self):
        """INPUTS: Zero default value is shown (not hidden as falsy)."""
        ir = {
            "inputs": {
                "offset": {
                    "required": False,
                    "description": "Starting offset",
                    "default": 0,
                },
            }
        }

        result = _format_inputs_section(ir)

        assert "    Default: 0" in result

    def test_formats_no_inputs(self):
        """INPUTS: Empty inputs dict shows 'None'."""
        ir = {"inputs": {}}

        result = _format_inputs_section(ir)

        assert result == "\nInputs: None"

    def test_formats_missing_inputs_key(self):
        """INPUTS: Missing inputs key shows 'None'."""
        ir = {}

        result = _format_inputs_section(ir)

        assert result == "\nInputs: None"

    def test_formats_inputs_without_descriptions(self):
        """INPUTS: Missing descriptions show as empty string."""
        ir = {
            "inputs": {
                "param1": {"required": True},
                "param2": {"required": False, "default": "test"},
            }
        }

        result = _format_inputs_section(ir)

        # Should not crash, should show empty description
        assert "param1 (required):" in result
        assert "param2 (optional):" in result

    def test_formats_inputs_defaults_to_required_true(self):
        """INPUTS: Missing 'required' key defaults to True."""
        ir = {
            "inputs": {
                "implicit_required": {"description": "No required key specified"},
            }
        }

        result = _format_inputs_section(ir)

        assert "implicit_required (required):" in result


class TestFormatOutputsSection:
    """Test output section formatting."""

    def test_formats_multiple_outputs(self):
        """OUTPUTS: Multiple outputs listed correctly."""
        ir = {
            "outputs": {
                "result": {"description": "Main result"},
                "metadata": {"description": "Result metadata"},
                "logs": {"description": "Execution logs"},
            }
        }

        result = _format_outputs_section(ir)

        assert "  - result: Main result" in result
        assert "  - metadata: Result metadata" in result
        assert "  - logs: Execution logs" in result

    def test_formats_outputs_without_descriptions(self):
        """OUTPUTS: Missing descriptions show as empty string."""
        ir = {
            "outputs": {
                "output1": {},
                "output2": {"description": ""},
            }
        }

        result = _format_outputs_section(ir)

        assert "  - output1:" in result
        assert "  - output2:" in result

    def test_formats_no_outputs(self):
        """OUTPUTS: Empty outputs dict shows 'None'."""
        ir = {"outputs": {}}

        result = _format_outputs_section(ir)

        assert result == "\nOutputs: None"

    def test_formats_missing_outputs_key(self):
        """OUTPUTS: Missing outputs key shows 'None'."""
        ir = {}

        result = _format_outputs_section(ir)

        assert result == "\nOutputs: None"


class TestFormatExampleUsageSection:
    """Test example usage section formatting."""

    def test_formats_example_with_required_parameters(self):
        """EXAMPLE: Shows only required parameters as placeholders."""
        ir = {
            "inputs": {
                "required1": {"required": True, "description": "First required"},
                "optional1": {"required": False, "description": "Optional param"},
                "required2": {"required": True, "description": "Second required"},
            }
        }

        result = _format_example_usage_section("my-workflow", ir)

        assert "  pflow my-workflow required1=<value> required2=<value>" in result
        # Optional param should not appear
        assert "optional1" not in result

    def test_formats_example_with_no_required_parameters(self):
        """EXAMPLE: Workflow with no required params shows just command."""
        ir = {
            "inputs": {
                "optional1": {"required": False, "description": "Optional"},
                "optional2": {"required": False, "description": "Also optional"},
            }
        }

        result = _format_example_usage_section("simple-workflow", ir)

        assert "  pflow simple-workflow" in result
        # No parameters shown
        assert "=" not in result

    def test_formats_example_with_no_inputs(self):
        """EXAMPLE: Workflow with no inputs shows just command."""
        ir = {}

        result = _format_example_usage_section("no-input-workflow", ir)

        assert "  pflow no-input-workflow" in result
        assert "=" not in result

    def test_formats_example_implicit_required_true(self):
        """EXAMPLE: Missing 'required' key defaults to True, param included."""
        ir = {
            "inputs": {
                "implicit": {"description": "Implicitly required"},
                "explicit": {"required": True, "description": "Explicitly required"},
            }
        }

        result = _format_example_usage_section("test-workflow", ir)

        # Both should appear since both are required
        assert "implicit=<value>" in result
        assert "explicit=<value>" in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_empty_metadata(self):
        """EDGE: Empty metadata dict doesn't crash."""
        metadata = {}

        result = format_workflow_interface("empty", metadata)

        assert "Workflow: empty" in result
        assert "Description: No description" in result
        assert "Inputs: None" in result
        assert "Outputs: None" in result
        assert "pflow empty" in result

    def test_handles_metadata_with_empty_ir(self):
        """EDGE: Metadata with empty IR dict."""
        metadata = {"description": "Test", "ir": {}}

        result = format_workflow_interface("test", metadata)

        assert "Workflow: test" in result
        assert "Inputs: None" in result
        assert "Outputs: None" in result

    def test_preserves_parameter_order_in_example(self):
        """EDGE: Parameter order in example matches IR iteration order."""
        ir = {
            "inputs": {
                "zebra": {"required": True, "description": "Z param"},
                "alpha": {"required": True, "description": "A param"},
                "beta": {"required": True, "description": "B param"},
            }
        }

        result = _format_example_usage_section("test", ir)

        # Parameters should appear in IR dict order (Python 3.7+ preserves insertion order)
        param_section = result.split("pflow test ")[1]
        params = [p.split("=")[0] for p in param_section.split()]

        # Verify they appear in same order as dict
        assert params == ["zebra", "alpha", "beta"]

    def test_handles_complex_default_values(self):
        """EDGE: Complex default values (lists, dicts) formatted correctly."""
        ir = {
            "inputs": {
                "tags": {
                    "required": False,
                    "description": "Tags",
                    "default": ["tag1", "tag2"],
                },
                "config": {
                    "required": False,
                    "description": "Configuration",
                    "default": {"key": "value", "count": 5},
                },
            }
        }

        result = _format_inputs_section(ir)

        # Should show string representation of complex types
        assert "['tag1', 'tag2']" in result
        assert "{'key': 'value', 'count': 5}" in result


class TestCLIParity:
    """Tests ensuring MCP output matches CLI output exactly."""

    def test_section_spacing_matches_cli(self):
        """PARITY: Sections have blank lines matching CLI format."""
        metadata = {
            "description": "Test workflow",
            "ir": {
                "inputs": {"x": {"required": True, "description": "Input"}},
                "outputs": {"y": {"description": "Output"}},
            },
        }

        result = format_workflow_interface("test", metadata)

        lines = result.split("\n")

        # Find section headers
        inputs_idx = lines.index("Inputs:")
        outputs_idx = lines.index("Outputs:")
        example_idx = lines.index("Example Usage:")

        # Verify blank lines before sections
        assert lines[inputs_idx - 1] == ""  # Blank before Inputs
        assert lines[outputs_idx - 1] == ""  # Blank before Outputs
        assert lines[example_idx - 1] == ""  # Blank before Example

    def test_indentation_matches_cli(self):
        """PARITY: Indentation levels match CLI (2 spaces for items, 4 for defaults)."""
        metadata = {
            "description": "Test",
            "ir": {
                "inputs": {
                    "param": {
                        "required": False,
                        "description": "Test param",
                        "default": "value",
                    }
                },
            },
        }

        result = format_workflow_interface("test", metadata)

        # Verify exact indentation
        assert "  - param (optional):" in result  # 2 spaces
        assert "    Default: value" in result  # 4 spaces
