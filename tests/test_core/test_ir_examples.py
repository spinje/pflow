"""Tests for .pflow.md examples to ensure they remain valid.

This test module validates all examples in the examples/ directory:
- Ensures valid examples parse and pass validation
- Ensures invalid examples produce expected parse errors
- Tests that examples demonstrate intended features

For more information about the examples, see examples/README.md
"""

from pathlib import Path

import pytest

from pflow.core import ValidationError, validate_ir
from pflow.core.ir_schema import normalize_ir
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown


class TestValidExamples:
    """Test that all valid examples parse and pass validation."""

    @pytest.fixture
    def examples_dir(self):
        """Get the examples directory path."""
        return Path("examples")

    def test_core_examples_exist(self, examples_dir):
        """Verify core examples are present."""
        core_dir = examples_dir / "core"
        expected = [
            "minimal.pflow.md",
            "simple-pipeline.pflow.md",
            "template-variables.pflow.md",
            "error-handling.pflow.md",
            "proxy-mappings.pflow.md",
        ]
        for example in expected:
            assert (core_dir / example).exists(), f"Missing core example: {example}"

    def test_advanced_examples_exist(self, examples_dir):
        """Verify advanced examples are present."""
        advanced_dir = examples_dir / "advanced"
        expected = [
            "github-workflow.pflow.md",
            "content-pipeline.pflow.md",
        ]
        for example in expected:
            assert (advanced_dir / example).exists(), f"Missing advanced example: {example}"

    def test_invalid_examples_exist(self, examples_dir):
        """Verify invalid examples are present."""
        invalid_dir = examples_dir / "invalid"
        expected = [
            "missing-steps.pflow.md",
            "missing-type.pflow.md",
            "missing-description.pflow.md",
            "unclosed-fence.pflow.md",
            "bare-code-block.pflow.md",
            "duplicate-param.pflow.md",
            "duplicate-ids.pflow.md",
            "yaml-syntax-error.pflow.md",
        ]
        for example in expected:
            assert (invalid_dir / example).exists(), f"Missing invalid example: {example}"

    @pytest.mark.parametrize(
        "example_file",
        [
            "core/minimal.pflow.md",
            "core/simple-pipeline.pflow.md",
            "core/template-variables.pflow.md",
            "core/error-handling.pflow.md",
            "core/proxy-mappings.pflow.md",
            "advanced/github-workflow.pflow.md",
            "advanced/content-pipeline.pflow.md",
        ],
    )
    def test_valid_examples_pass_validation(self, examples_dir, example_file):
        """Test that valid examples parse and pass validation."""
        file_path = examples_dir / example_file
        content = file_path.read_text()
        result = parse_markdown(content)
        ir_data = result.ir
        normalize_ir(ir_data)

        # Should not raise any exception
        validate_ir(ir_data)

    def test_pflow_md_files_are_self_documenting(self, examples_dir):
        """Verify .pflow.md files ARE the documentation (no separate .md companion needed)."""
        for subdir in ["core", "advanced"]:
            dir_path = examples_dir / subdir
            if not dir_path.exists():
                continue
            for pflow_file in dir_path.glob("*.pflow.md"):
                content = pflow_file.read_text()
                result = parse_markdown(content)
                # Every valid workflow should have a title
                assert result.title is not None, f"Missing title in {pflow_file}"


class TestInvalidExamples:
    """Test that invalid examples produce expected parse errors."""

    @pytest.fixture
    def examples_dir(self):
        """Get the examples directory path."""
        return Path("examples")

    def test_missing_steps_error(self, examples_dir):
        """Test missing Steps section produces correct error."""
        content = (examples_dir / "invalid/missing-steps.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="Missing.*Steps.*section"):
            parse_markdown(content)

    def test_missing_type_error(self, examples_dir):
        """Test missing node type produces correct error."""
        content = (examples_dir / "invalid/missing-type.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="missing.*type.*parameter"):
            parse_markdown(content)

    def test_missing_description_error(self, examples_dir):
        """Test missing description produces correct error."""
        content = (examples_dir / "invalid/missing-description.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="missing a description"):
            parse_markdown(content)

    def test_unclosed_fence_error(self, examples_dir):
        """Test unclosed code fence produces correct error."""
        content = (examples_dir / "invalid/unclosed-fence.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="Unclosed code block"):
            parse_markdown(content)

    def test_bare_code_block_error(self, examples_dir):
        """Test code block without tag produces correct error."""
        content = (examples_dir / "invalid/bare-code-block.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="no tag"):
            parse_markdown(content)

    def test_duplicate_param_error(self, examples_dir):
        """Test duplicate param (inline + code block) produces correct error."""
        content = (examples_dir / "invalid/duplicate-param.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="defined both inline and as a code block"):
            parse_markdown(content)

    def test_duplicate_ids_error(self, examples_dir):
        """Test duplicate node IDs produce correct error."""
        content = (examples_dir / "invalid/duplicate-ids.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="Duplicate entity ID"):
            parse_markdown(content)

    def test_yaml_syntax_error(self, examples_dir):
        """Test YAML syntax error produces correct error."""
        content = (examples_dir / "invalid/yaml-syntax-error.pflow.md").read_text()

        with pytest.raises(MarkdownParseError, match="YAML syntax error"):
            parse_markdown(content)


class TestExampleContent:
    """Test specific content patterns in examples."""

    @pytest.fixture
    def examples_dir(self):
        """Get the examples directory path."""
        return Path("examples")

    def test_template_variables_contains_dollar_syntax(self, examples_dir):
        """Verify template variables example actually uses ${variable} syntax."""
        content = (examples_dir / "core/template-variables.pflow.md").read_text()

        # Check for multiple template variables
        assert "${api_endpoint}" in content
        assert "${api_token}" in content
        assert "${recipient_email}" in content

    def test_error_handling_has_multiple_nodes(self, examples_dir):
        """Verify error handling example has nodes for error/fallback/retry pattern."""
        content = (examples_dir / "core/error-handling.pflow.md").read_text()
        result = parse_markdown(content)
        ir_data = result.ir

        node_ids = [n["id"] for n in ir_data["nodes"]]
        assert "log_error" in node_ids
        assert "create_fallback" in node_ids
        assert "retry_processor" in node_ids

    def test_proxy_mappings_example_parses(self, examples_dir):
        """Verify proxy mappings example parses successfully.

        Note: mappings are an IR-level feature not represented in markdown
        syntax. The example tests that the basic workflow structure parses.
        """
        content = (examples_dir / "core/proxy-mappings.pflow.md").read_text()
        result = parse_markdown(content)
        ir_data = result.ir
        normalize_ir(ir_data)

        validate_ir(ir_data)
        node_ids = [n["id"] for n in ir_data["nodes"]]
        assert "reader" in node_ids
        assert "test_processor" in node_ids
        assert "writer" in node_ids

    def test_all_pflow_md_files_parse(self, examples_dir):
        """Ensure all .pflow.md files in non-invalid dirs can be parsed."""
        for pflow_file in examples_dir.rglob("*.pflow.md"):
            # Skip invalid examples — they are expected to fail
            if "invalid" in pflow_file.parts:
                continue
            content = pflow_file.read_text()
            try:
                result = parse_markdown(content)
                ir_data = result.ir
                normalize_ir(ir_data)
                validate_ir(ir_data)
            except (MarkdownParseError, ValidationError) as exc:
                pytest.fail(f"Failed to parse/validate {pflow_file}: {exc}")
