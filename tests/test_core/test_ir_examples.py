"""Tests for JSON IR examples to ensure they remain valid.

This test module validates all examples in the examples/ directory:
- Ensures valid examples pass validation
- Ensures invalid examples produce expected errors
- Verifies example documentation exists
- Tests that examples demonstrate intended features

For more information about the examples, see examples/README.md
"""

import json
from pathlib import Path

import pytest

from pflow.core import ValidationError, validate_ir


class TestValidExamples:
    """Test that all valid examples pass validation."""

    @pytest.fixture
    def examples_dir(self):
        """Get the examples directory path.

        The examples/ directory contains:
        - core/: Essential examples showing fundamental patterns
        - advanced/: Complex real-world examples
        - invalid/: Examples of common mistakes with expected errors

        See examples/README.md for detailed documentation.
        """
        return Path("examples")

    def test_core_examples_exist(self, examples_dir):
        """Verify core examples are present."""
        core_dir = examples_dir / "core"
        expected = [
            "minimal.json",
            "simple-pipeline.json",
            "template-variables.json",
            "error-handling.json",
            "proxy-mappings.json",
        ]
        for example in expected:
            assert (core_dir / example).exists(), f"Missing core example: {example}"

    def test_advanced_examples_exist(self, examples_dir):
        """Verify advanced examples are present."""
        advanced_dir = examples_dir / "advanced"
        expected = ["github-workflow.json", "content-pipeline.json"]
        for example in expected:
            assert (advanced_dir / example).exists(), f"Missing advanced example: {example}"

    def test_invalid_examples_exist(self, examples_dir):
        """Verify invalid examples are present."""
        invalid_dir = examples_dir / "invalid"
        expected = [
            "missing-version.json",
            "duplicate-ids.json",
            "bad-edge-ref.json",
            "wrong-types.json",
        ]
        for example in expected:
            assert (invalid_dir / example).exists(), f"Missing invalid example: {example}"

    @pytest.mark.parametrize(
        "example_file",
        [
            "core/minimal.json",
            "core/simple-pipeline.json",
            "core/template-variables.json",
            "core/error-handling.json",
            "core/proxy-mappings.json",
            "advanced/github-workflow.json",
            "advanced/content-pipeline.json",
        ],
    )
    def test_valid_examples_pass_validation(self, examples_dir, example_file):
        """Test that valid examples pass validation."""
        file_path = examples_dir / example_file
        with open(file_path) as f:
            ir_data = json.load(f)

        # Should not raise any exception
        validate_ir(ir_data)

    def test_documentation_exists_for_examples(self, examples_dir):
        """Verify each example has corresponding documentation."""
        for subdir in ["core", "advanced", "invalid"]:
            json_files = (examples_dir / subdir).glob("*.json")
            for json_file in json_files:
                md_file = json_file.with_suffix(".md")
                assert md_file.exists(), f"Missing documentation for {json_file}"


class TestInvalidExamples:
    """Test that invalid examples produce expected errors."""

    @pytest.fixture
    def examples_dir(self):
        """Get the examples directory path."""
        return Path("examples")

    def test_missing_version_error(self, examples_dir):
        """Test missing ir_version produces correct error."""
        with open(examples_dir / "invalid/missing-version.json") as f:
            ir_data = json.load(f)

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir_data)

        error = exc_info.value
        assert error.path == "root"
        assert "'ir_version' is a required property" in error.message
        assert "Add the required field 'ir_version'" in error.suggestion

    def test_duplicate_ids_error(self, examples_dir):
        """Test duplicate node IDs produce correct error."""
        with open(examples_dir / "invalid/duplicate-ids.json") as f:
            ir_data = json.load(f)

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir_data)

        error = exc_info.value
        assert "nodes[1].id" in error.path
        assert "Duplicate node ID 'processor'" in str(error)
        assert "Use unique IDs for each node" in error.suggestion

    def test_bad_edge_ref_error(self, examples_dir):
        """Test edge referencing non-existent node produces correct error."""
        with open(examples_dir / "invalid/bad-edge-ref.json") as f:
            ir_data = json.load(f)

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir_data)

        error = exc_info.value
        assert "edges[0].to" in error.path
        assert "non-existent node 'middle'" in str(error)
        assert "['end', 'start']" in error.suggestion or "['start', 'end']" in error.suggestion

    def test_wrong_types_error(self, examples_dir):
        """Test wrong field types produce correct error."""
        with open(examples_dir / "invalid/wrong-types.json") as f:
            ir_data = json.load(f)

        with pytest.raises(ValidationError) as exc_info:
            validate_ir(ir_data)

        # The first error will be about ir_version format
        error = exc_info.value
        assert "ir_version" in error.path
        # Either pattern matching error or type error
        assert "does not match" in str(error) or "not of type 'string'" in str(error)


class TestExampleContent:
    """Test specific content patterns in examples."""

    @pytest.fixture
    def examples_dir(self):
        """Get the examples directory path."""
        return Path("examples")

    def test_template_variables_contains_dollar_syntax(self, examples_dir):
        """Verify template variables example actually uses $variable syntax."""
        with open(examples_dir / "core/template-variables.json") as f:
            content = f.read()

        # Check for multiple template variables
        assert "$api_endpoint" in content
        assert "$api_token" in content
        assert "$recipient_email" in content

    def test_error_handling_has_action_edges(self, examples_dir):
        """Verify error handling example uses action-based routing."""
        with open(examples_dir / "core/error-handling.json") as f:
            ir_data = json.load(f)

        # Find edges with "error" action
        error_edges = [edge for edge in ir_data.get("edges", []) if edge.get("action") == "error"]
        assert len(error_edges) > 0, "No error action edges found"

        # Should have retry action too
        retry_edges = [edge for edge in ir_data.get("edges", []) if edge.get("action") == "retry"]
        assert len(retry_edges) > 0, "No retry action edges found"

    def test_proxy_mappings_has_mappings(self, examples_dir):
        """Verify proxy mappings example includes actual mappings."""
        with open(examples_dir / "core/proxy-mappings.json") as f:
            ir_data = json.load(f)

        assert "mappings" in ir_data
        assert len(ir_data["mappings"]) > 0

        # Check for input/output mappings
        for _node_id, mapping in ir_data["mappings"].items():
            assert "input_mappings" in mapping or "output_mappings" in mapping

    def test_all_json_files_are_valid_json(self, examples_dir):
        """Ensure all JSON files can be parsed."""
        for json_file in examples_dir.rglob("*.json"):
            with open(json_file) as f:
                try:
                    json.load(f)
                except json.JSONDecodeError as e:
                    pytest.fail(f"Invalid JSON in {json_file}: {e}")
