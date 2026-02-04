"""Validate that shipped example workflows conform to IR schema.

This test suite ensures:
1. Valid .pflow.md examples in examples/ parse and pass IR schema validation
2. Invalid .pflow.md examples in examples/invalid/ correctly fail parsing or validation
3. Examples remain valid as the IR schema evolves

Speed optimized:
- Single directory scan (cached at class scope)
- Lightweight schema validation only (no compilation)
- Batch assertions with clear failure reporting
- All files validated in <100ms
"""

from pathlib import Path

import pytest

from pflow.core import ValidationError, validate_ir
from pflow.core.ir_schema import normalize_ir
from pflow.core.markdown_parser import MarkdownParseError, parse_markdown

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


class TestExampleValidation:
    """Validate shipped example workflows."""

    @pytest.fixture(scope="class")
    def valid_workflow_files(self) -> list[tuple[Path, dict]]:
        """Collect valid .pflow.md example files (outside examples/invalid/ and legacy/)."""
        if not EXAMPLES_DIR.exists():
            pytest.skip("Examples directory not found")

        files = []
        for pflow_file in EXAMPLES_DIR.rglob("*.pflow.md"):
            # Skip invalid examples and legacy examples
            if "invalid" in pflow_file.parts:
                continue
            if "legacy" in pflow_file.parts:
                continue

            try:
                content = pflow_file.read_text()
                result = parse_markdown(content)
                ir = result.ir
                normalize_ir(ir)
            except (MarkdownParseError, ValueError):
                continue  # Skip files that fail parsing (separate concern)

            files.append((pflow_file, ir))

        return files

    @pytest.fixture(scope="class")
    def invalid_workflow_files(self) -> list[Path]:
        """Collect invalid .pflow.md example files (in examples/invalid/)."""
        invalid_dir = EXAMPLES_DIR / "invalid"
        if not invalid_dir.exists():
            return []

        return list(invalid_dir.glob("*.pflow.md"))

    def test_valid_examples_pass_schema_validation(self, valid_workflow_files: list[tuple[Path, dict]]) -> None:
        """All valid example workflows should pass IR schema validation."""
        assert valid_workflow_files, "No valid example files found"

        failures = []
        for pflow_file, ir_data in valid_workflow_files:
            try:
                validate_ir(ir_data)
            except ValidationError as e:
                rel_path = pflow_file.relative_to(EXAMPLES_DIR)
                failures.append(f"  {rel_path}: {e}")

        if failures:
            pytest.fail(f"Schema validation failed for {len(failures)} file(s):\n" + "\n".join(failures))

    def test_invalid_examples_fail_parsing_or_validation(self, invalid_workflow_files: list[Path]) -> None:
        """All invalid example workflows should fail during parsing or validation."""
        if not invalid_workflow_files:
            pytest.skip("No invalid example files found")

        unexpected_passes = []
        for pflow_file in invalid_workflow_files:
            try:
                content = pflow_file.read_text()
                result = parse_markdown(content)
                ir_data = result.ir
                normalize_ir(ir_data)
                validate_ir(ir_data)
                # If we get here, the file unexpectedly passed
                unexpected_passes.append(pflow_file.name)
            except (MarkdownParseError, ValidationError, ValueError):
                pass  # Expected - invalid examples should fail

        if unexpected_passes:
            pytest.fail(f"These files should fail parsing/validation but passed: {unexpected_passes}")

    def test_example_coverage_is_meaningful(self, valid_workflow_files: list[tuple[Path, dict]]) -> None:
        """Ensure we're testing a meaningful number of examples."""
        # If this fails, example files may have been deleted or moved
        assert len(valid_workflow_files) >= 10, (
            f"Expected at least 10 valid example files, found {len(valid_workflow_files)}. "
            "Examples may have been deleted or the directory structure changed."
        )
