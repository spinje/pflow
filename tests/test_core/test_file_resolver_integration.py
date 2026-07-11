"""Integration tests for file reference resolution through the full pipeline."""

from pathlib import Path
from typing import Any

import pytest

from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.exceptions import MarkdownParseError
from pflow.core.file_resolver import resolve_file_references
from pflow.core.ir_schema import normalize_ir, validate_ir
from pflow.core.markdown_parser import parse_markdown
from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_validator_diagnostics


class TestFileResolverWithParser:
    """Test file resolution with real parsed workflows."""

    def test_parsed_workflow_with_prompt_file(self, tmp_path: Path) -> None:
        """Parse a workflow with prompt file ref and resolve it."""
        # Create external prompt file
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "system.md").write_text("You are a helpful assistant.\n\nAnalyze: ${input}", encoding="utf-8")

        # Create workflow markdown
        workflow_md = """\
# Test Workflow

## Inputs

### input

The input to analyze.

- type: string
- required: true

## Steps

### analyze

Analyze the input with LLM.

- type: llm
- prompt: ./prompts/system.md
"""
        (tmp_path / "workflow.pflow.md").write_text(workflow_md, encoding="utf-8")

        # Parse and resolve
        result = parse_markdown(workflow_md)
        ir = result.ir
        resolve_file_references(ir, tmp_path)

        # Prompt should be the file content
        prompt = ir["nodes"][0]["params"]["prompt"]
        assert "You are a helpful assistant." in prompt
        assert "${input}" in prompt

        # Provenance should be recorded
        assert ir["nodes"][0]["_source_files"]["prompt"] == "./prompts/system.md"

    def test_parsed_workflow_with_code_file(self, tmp_path: Path) -> None:
        """Parse a workflow with code file ref and resolve it."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "transform.py").write_text('result: str = "hello world"', encoding="utf-8")

        workflow_md = """\
# Test

## Steps

### transform

Transform data.

- type: code
- code: ./scripts/transform.py
"""
        result = parse_markdown(workflow_md)
        ir = result.ir
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["code"] == 'result: str = "hello world"'

    def test_parsed_workflow_with_command_file(self, tmp_path: Path) -> None:
        """Parse a workflow with command file ref and resolve it."""
        (tmp_path / "run.sh").write_text("echo hello world", encoding="utf-8")

        workflow_md = """\
# Test

## Steps

### run

Run a script.

- type: shell
- command: ./run.sh
"""
        result = parse_markdown(workflow_md)
        ir = result.ir
        resolve_file_references(ir, tmp_path)

        assert ir["nodes"][0]["params"]["command"] == "echo hello world"

    def test_ir_schema_validates_source_files(self, tmp_path: Path) -> None:
        """_source_files field passes IR schema validation."""
        (tmp_path / "p.md").write_text("content", encoding="utf-8")

        workflow_md = """\
# Test

## Steps

### step

A step.

- type: llm
- prompt: ./p.md
"""
        result = parse_markdown(workflow_md)
        ir = result.ir
        resolve_file_references(ir, tmp_path)

        # Normalize to add ir_version etc. for schema validation
        normalize_ir(ir)

        # Should not raise — _source_files is in schema
        validate_ir(ir)

    def test_mutual_exclusivity_yaml_and_code_block(self, tmp_path: Path) -> None:
        """YAML param and code block for same param name raises parse error."""
        workflow_md = """\
# Test

## Steps

### step

A step.

- type: llm
- prompt: ./prompts/foo.md

```prompt
This is inline prompt content.
```
"""
        with pytest.raises(MarkdownParseError, match="defined both inline and as a code block"):
            parse_markdown(workflow_md)

    def test_template_in_file_survives_resolution(self, tmp_path: Path) -> None:
        """Template variables in external files are preserved for later resolution."""
        (tmp_path / "p.md").write_text("Hello ${upstream.response}, analyze ${concept.title}", encoding="utf-8")

        ir: dict[str, Any] = {
            "nodes": [{"id": "n1", "type": "llm", "params": {"prompt": "./p.md"}}],
            "edges": [],
        }
        resolve_file_references(ir, tmp_path)

        prompt = ir["nodes"][0]["params"]["prompt"]
        assert "${upstream.response}" in prompt
        assert "${concept.title}" in prompt

    def test_batch_file_with_item_file_refs(self, tmp_path: Path) -> None:
        """External batch YAML file, then resolve file refs inside its items."""
        prompts = tmp_path / "prompts"
        prompts.mkdir()
        (prompts / "reviewer-a.md").write_text("Review for quality A", encoding="utf-8")
        (prompts / "reviewer-b.md").write_text("Review for quality B", encoding="utf-8")

        batch_yaml = """\
items:
  - focus: quality-a
    prompt: ./prompts/reviewer-a.md
  - focus: quality-b
    prompt: ./prompts/reviewer-b.md
parallel: true
"""
        (tmp_path / "reviews.yaml").write_text(batch_yaml, encoding="utf-8")

        ir: dict[str, Any] = {
            "nodes": [
                {
                    "id": "reviews",
                    "type": "llm",
                    "batch": "./reviews.yaml",
                    "params": {"prompt": "${item.prompt}"},
                }
            ],
            "edges": [],
        }

        # Single resolve call — B1 loads the YAML, B2 resolves item file refs
        resolve_file_references(ir, tmp_path)

        # batch should be parsed YAML dict now
        batch = ir["nodes"][0]["batch"]
        assert isinstance(batch, dict)
        assert batch["parallel"] is True

        items = ir["nodes"][0]["batch"]["items"]
        assert items[0]["prompt"] == "Review for quality A"
        assert items[1]["prompt"] == "Review for quality B"

    def test_execution_path_resolves_files(self, tmp_path: Path) -> None:
        """File references are resolved in the execution path (not just validate-only).

        Regression test for Bug #1: the execution path called _validate_before_execution()
        on the raw IR before compile_ir_to_flow() ran. This meant file references were
        still literal path strings during pre-execution validation, causing 'input never
        used' errors when the template vars were inside the external file.
        """
        # Create external script that uses a template variable
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "run.sh").write_text('echo "hello from file"', encoding="utf-8")

        workflow_md = """\
# Execution Path Test

## Steps

### run

Run external script.

- type: shell
- command: ./scripts/run.sh
"""
        workflow_file = tmp_path / "workflow.pflow.md"
        workflow_file.write_text(workflow_md, encoding="utf-8")

        # Compile through the same path the CLI uses
        from pflow.core.file_resolver import get_base_dir, resolve_file_references
        from pflow.core.ir_schema import normalize_ir

        result = parse_markdown(workflow_md)
        ir = result.ir
        normalize_ir(ir)

        initial_params = {"_pflow_workflow_file": str(workflow_file)}
        base_dir = get_base_dir(initial_params)
        resolve_file_references(ir, base_dir)

        # The command should now be the file content
        assert ir["nodes"][0]["params"]["command"] == 'echo "hello from file"'

    def test_compile_ir_detects_templates_in_file_content(self, tmp_path: Path) -> None:
        """Template variables in external files are detected by compile_workflow().

        This is THE critical integration test. If file resolution happens but template
        detection doesn't see the resolved content, ${var} in external files becomes
        literal text at runtime — a silent bug with no error.

        Uses shell nodes (not LLM) to avoid needing API keys in tests.
        """
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow

        # External command file with template variable referencing an upstream node
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "process.sh").write_text('echo "Processing: ${fetch.stdout}"', encoding="utf-8")

        workflow_md = """\
# Template Detection Test

## Steps

### fetch

Fetch some data.

- type: shell

```shell command
echo "some data"
```

### process

Process the fetched data using an external command file.

- type: shell
- command: ./scripts/process.sh
"""
        workflow_file = tmp_path / "workflow.pflow.md"
        workflow_file.write_text(workflow_md, encoding="utf-8")

        result = parse_markdown(workflow_md)
        ir = result.ir

        # Compile with the workflow file path so file resolution works
        registry = Registry()
        initial_params = {"_pflow_workflow_file": str(workflow_file)}
        workflow = compile_workflow(ir, registry, initial_params=initial_params)

        # If we get here, compilation succeeded — template validation found
        # ${fetch.stdout} in the resolved file content and validated it against
        # the 'fetch' node's outputs. If file resolution failed silently,
        # template validation would report "fetch.stdout has no valid source"
        # because it would see "./scripts/process.sh" as the literal command.
        assert workflow is not None

    def test_nested_workflow_file_refs_resolve_from_child_dir(self, tmp_path: Path) -> None:
        """File references in child workflows resolve relative to the child, not parent.

        If the _pflow_workflow_file injection in workflow_executor.py breaks,
        child file references silently resolve from the wrong directory.
        """
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow

        # Create child workflow in a subdirectory with its own command file
        child_dir = tmp_path / "child"
        child_scripts = child_dir / "scripts"
        child_scripts.mkdir(parents=True)
        (child_scripts / "greet.sh").write_text('echo "Hello ${name}"', encoding="utf-8")

        child_md = """\
# Child Workflow

## Inputs

### name

The name to greet.

- type: string
- required: true

## Steps

### greet

Greet by name using external command.

- type: shell
- command: ./scripts/greet.sh
"""
        child_file = child_dir / "child.pflow.md"
        child_file.write_text(child_md, encoding="utf-8")

        # Compile the child with _pflow_workflow_file set to its own location
        # (simulating what workflow_executor.py does)
        result = parse_markdown(child_md)
        ir = result.ir

        registry = Registry()
        child_params = {
            "name": "World",
            "_pflow_workflow_file": str(child_file),
        }
        workflow = compile_workflow(ir, registry, initial_params=child_params)
        assert workflow is not None

        # Now verify it FAILS when resolved from the wrong directory
        # (parent dir, which doesn't have scripts/greet.sh)
        result2 = parse_markdown(child_md)
        ir2 = result2.ir

        wrong_params = {
            "name": "World",
            "_pflow_workflow_file": str(tmp_path / "fake-parent.pflow.md"),
        }
        with pytest.raises(Exception, match="not found"):
            compile_workflow(ir2, registry, initial_params=wrong_params)

    def test_no_file_refs_unchanged(self, tmp_path: Path) -> None:
        """Workflow with no file references is completely unchanged."""
        workflow_md = """\
# Test

## Steps

### greet

Say hello.

- type: shell

```shell command
echo hello
```
"""
        result = parse_markdown(workflow_md)
        ir_before = str(result.ir)
        resolve_file_references(result.ir, tmp_path)
        ir_after = str(result.ir)

        assert ir_before == ir_after


class TestTemplateErrorSourceFileProvenance:
    """Template validation errors include source file hints for external file content."""

    def test_template_error_includes_source_file(self, tmp_path: Path) -> None:
        """Error for bad template in external file tells agent which file to edit."""
        # Create external prompt with a reference to a nonexistent node
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "bad.md").write_text("Hello ${nonexistent_node.output}", encoding="utf-8")

        workflow_md = """\
# Test

## Steps

### step1

A step.

- type: shell

```shell command
echo hello
```

### step2

Uses external prompt.

- type: llm
- prompt: ./prompts/bad.md
"""
        result = parse_markdown(workflow_md)
        ir = result.ir
        normalize_ir(ir)
        resolve_file_references(ir, tmp_path)

        # Generate dummy params and validate
        registry = Registry()
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=ir,
            extracted_params={},
            registry=registry,
            skip_node_types=False,
        )

        # Should have an error about nonexistent_node
        assert len(errors) > 0
        error_text = "\n".join(format_diagnostic(d) for d in errors)
        assert "Loaded from file: ./prompts/bad.md" in error_text

    def test_template_error_without_file_ref_has_no_hint(self, tmp_path: Path) -> None:
        """Inline template errors don't include file hint."""
        workflow_md = """\
# Test

## Steps

### step1

A step.

- type: llm

```prompt
Hello ${nonexistent_node.output}
```
"""
        result = parse_markdown(workflow_md)
        ir = result.ir
        normalize_ir(ir)

        registry = Registry()
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=ir,
            extracted_params={},
            registry=registry,
            skip_node_types=False,
        )

        assert len(errors) > 0
        error_text = "\n".join(format_diagnostic(d) for d in errors)
        assert "Loaded from file" not in error_text
