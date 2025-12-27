"""Validate that shipped example workflows conform to IR schema.

This test suite ensures:
1. Valid examples in examples/ pass IR schema validation
2. Invalid examples in examples/invalid/ correctly fail validation
3. Examples remain valid as the IR schema evolves

Speed optimized:
- Single directory scan (cached at class scope)
- Lightweight schema validation only (no compilation)
- Batch assertions with clear failure reporting
- All files validated in <100ms

Supported formats:
- Raw IR: {"ir_version": "...", "nodes": [...]}
- Wrapper format: {"name": "...", "ir": {"ir_version": "...", "nodes": [...]}}
"""

import json
from pathlib import Path

import pytest

from pflow.core import ValidationError, validate_ir

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def extract_ir(data: dict) -> dict | None:
    """Extract IR from either raw IR or wrapper format.

    Returns None if the data doesn't contain valid IR structure.
    """
    # Wrapper format: {"name": "...", "ir": {...}}
    if "ir" in data and isinstance(data["ir"], dict):
        ir = data["ir"]
        if "nodes" in ir:
            return ir

    # Raw IR format: {"ir_version": "...", "nodes": [...]}
    if "nodes" in data and "ir_version" in data:
        return data

    return None


class TestExampleValidation:
    """Validate shipped example workflows."""

    @pytest.fixture(scope="class")
    def valid_workflow_files(self) -> list[tuple[Path, dict]]:
        """Collect valid example files (outside examples/invalid/ and legacy/)."""
        if not EXAMPLES_DIR.exists():
            pytest.skip("Examples directory not found")

        files = []
        for json_file in EXAMPLES_DIR.rglob("*.json"):
            # Skip invalid examples, legacy examples, and config files
            if "invalid" in json_file.parts:
                continue
            if "legacy" in json_file.parts:
                continue
            if "config" in json_file.name.lower():
                continue

            try:
                with open(json_file) as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                continue  # Skip malformed JSON (separate concern)

            # Extract IR (handles both wrapper and raw formats)
            ir = extract_ir(data)
            if ir is not None:
                files.append((json_file, ir))

        return files

    @pytest.fixture(scope="class")
    def invalid_workflow_files(self) -> list[tuple[Path, dict]]:
        """Collect invalid example files (in examples/invalid/)."""
        invalid_dir = EXAMPLES_DIR / "invalid"
        if not invalid_dir.exists():
            return []

        files = []
        for json_file in invalid_dir.glob("*.json"):
            try:
                with open(json_file) as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                continue

            # For invalid examples, we validate the raw data
            # (they're intentionally malformed IR)
            if "nodes" in data:
                files.append((json_file, data))

        return files

    def test_valid_examples_pass_schema_validation(self, valid_workflow_files: list[tuple[Path, dict]]) -> None:
        """All valid example workflows should pass IR schema validation."""
        assert valid_workflow_files, "No valid example files found"

        failures = []
        for json_file, data in valid_workflow_files:
            try:
                validate_ir(data)
            except ValidationError as e:
                rel_path = json_file.relative_to(EXAMPLES_DIR)
                failures.append(f"  {rel_path}: {e}")

        if failures:
            pytest.fail(f"Schema validation failed for {len(failures)} file(s):\n" + "\n".join(failures))

    def test_invalid_examples_fail_schema_validation(self, invalid_workflow_files: list[tuple[Path, dict]]) -> None:
        """All invalid example workflows should fail IR schema validation."""
        if not invalid_workflow_files:
            pytest.skip("No invalid example files found")

        unexpected_passes = []
        for json_file, data in invalid_workflow_files:
            try:
                validate_ir(data)
                unexpected_passes.append(json_file.name)
            except ValidationError:
                pass  # Expected - invalid examples should fail

        if unexpected_passes:
            pytest.fail(f"These files should fail validation but passed: {unexpected_passes}")

    def test_example_coverage_is_meaningful(self, valid_workflow_files: list[tuple[Path, dict]]) -> None:
        """Ensure we're testing a meaningful number of examples."""
        # If this fails, example files may have been deleted or moved
        assert len(valid_workflow_files) >= 10, (
            f"Expected at least 10 valid example files, found {len(valid_workflow_files)}. "
            "Examples may have been deleted or the directory structure changed."
        )
