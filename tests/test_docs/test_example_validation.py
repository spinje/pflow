"""Validate that shipped example workflows conform to the full validator contract.

This test suite ensures:
1. Valid .pflow.md examples in examples/ pass the 10-step WorkflowValidator pipeline
   (not just IR schema). This catches stale examples that reference undeclared inputs,
   non-existent node outputs, removed params, etc. — rot that accumulated when the
   suite only ran validate_ir().
2. Invalid .pflow.md examples in examples/invalid/ correctly fail parsing or validation.
3. Examples remain valid as the validator and IR schema evolve.

Skip contract: workflows whose ONLY unregistered node types are `mcp-*` (MCP tools
supplied by user-configured servers) are skipped with a recorded reason. Workflows
with any non-MCP unregistered type (typos, removed node types) still fail — that's
the rot we want to catch.

Latent gap: the skip predicate pre-scans only top-level `node.type` strings. If a
parent workflow references a sub-workflow file whose own nodes include unregistered
MCP types, the validator will recurse and fail; the pre-scan won't know to skip.
No shipped example currently has that shape.
"""

import copy
from pathlib import Path

import pytest
import yaml

from pflow.core.diagnostic import Severity
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
from pflow.core.file_resolver import get_base_dir, resolve_file_references
from pflow.core.ir_schema import normalize_ir, validate_ir
from pflow.core.markdown_parser import parse_markdown
from pflow.core.validation_utils import generate_dummy_parameters
from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def _collect_used_node_types(ir_data: dict) -> set[str]:
    """Return the set of node type strings referenced directly by this workflow."""
    return {node.get("type") for node in ir_data.get("nodes", []) if node.get("type")}


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

    def test_valid_examples_pass_full_validation(self, valid_workflow_files: list[tuple[Path, dict]]) -> None:
        """All valid examples must pass the full 10-step WorkflowValidator pipeline.

        Schema-only validation (validate_ir) missed real user-facing rot:
        undeclared inputs, ${input.x} syntax, stale node-output references, removed
        params. This test runs the same validation the CLI runs.

        Files whose ONLY unregistered types are `mcp-*` are skipped (they depend on
        user-configured external servers). Any non-MCP unregistered type still fails
        so typos and removed node types surface as errors.
        """
        assert valid_workflow_files, "No valid example files found"

        registry = Registry()
        registered_types = set(registry.load().keys())

        skipped: list[tuple[Path, set[str]]] = []
        failures: list[tuple[Path, str]] = []

        for pflow_file, ir_data in valid_workflow_files:
            used_types = _collect_used_node_types(ir_data)
            missing_types = used_types - registered_types
            if missing_types and all(t.startswith("mcp-") for t in missing_types):
                skipped.append((pflow_file, missing_types))
                continue

            # Deep-copy before mutation: the class-scoped fixture shares IR dicts
            # across tests, and resolve_file_references writes in place. Copying
            # isolates each test's view.
            ir_local = copy.deepcopy(ir_data)
            rel_path = pflow_file.relative_to(EXAMPLES_DIR)

            # Fill declared required inputs with dummy values — mirrors CLI
            # `--validate-only`, which runs structural validation with placeholders
            # rather than real user input.
            dummy_params = generate_dummy_parameters(ir_local.get("inputs", {}))
            dummy_params["_pflow_workflow_file"] = str(pflow_file)

            # Resolve external file refs (e.g., `- prompt: ./prompts/x.md`) in place
            # so template validation sees the real content, matching CLI behavior.
            # A broken file ref in one example would otherwise crash the whole
            # test run and mask regressions in every other example.
            try:
                resolve_file_references(ir_local, get_base_dir(dummy_params))
            except (FileNotFoundError, OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                failures.append((rel_path, f"file resolution failed: {exc}"))
                continue

            diagnostics = WorkflowValidator.validate(
                ir_local,
                extracted_params=dummy_params,
                registry=registry,
                workflow_file=pflow_file,
            )
            errors = [d for d in diagnostics if d.severity == Severity.ERROR]
            for err in errors:
                failures.append((rel_path, err.message))

        if failures:
            unique_files = {path for path, _ in failures}
            rendered = "\n".join(f"  {path}: {msg}" for path, msg in failures)
            pytest.fail(
                f"Full validation failed for {len(failures)} diagnostic(s) across "
                f"{len(unique_files)} file(s):\n{rendered}"
            )

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
            except (MarkdownParseError, SchemaValidationError, ValueError):
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
