# Fix: Wire WorkflowValidator into CLI Save Path (GH #236)

## Context

`pflow workflow save` only runs IR schema validation (`validate_ir()`), never the full 9-step `WorkflowValidator.validate()`. Broken workflows (unknown params, non-existent node refs, template errors) get silently accepted into `~/.pflow/workflows/` and only fail when the user tries to run them. The MCP save path correctly validates; the CLI save path doesn't. Root cause: `save_workflow_with_options` trusts callers to pre-validate — two callers (CLI, MCP) each implemented their own "prepare for save" logic, and the CLI one only did schema validation.

Applying the Task 144 pattern ("delete the bypass, bring behavior into the unified pipeline"): `save_workflow_with_options` should own parse + validate + save as one atomic operation. Callers can't skip validation because it's inside the save function. This deletes 2 CLI helper functions, simplifies the MCP save method, and eliminates the bug class (not just the bug instance).

## Files to Modify

| File | Change |
|------|--------|
| `src/pflow/core/workflow/save_service.py` | `save_workflow_with_options` gains parse + validate; return type adds validated IR |
| `src/pflow/cli/commands/workflow.py` | Delete `_load_and_parse_workflow`, delete `_save_with_overwrite_check`, rewrite `save_workflow` command |
| `src/pflow/mcp_server/services/execution_service.py` | Simplify `save_workflow` + `_save_and_format_result` |
| `tests/test_core/test_workflow_save_service.py` | Update for new return type + validation in save |
| `tests/test_cli/test_workflow_save_cli.py` | Update error message assertions for rich diagnostic display |
| `tests/test_mcp_server/test_workflow_save.py` | Update for simplified MCP save path |
| `tests/test_integration/test_workflow_bundling.py` | Update 4 unpack sites for new return type; fix 1 test assertion (error source changes) |
| `src/pflow/core/workflow/CLAUDE.md` | Update save_service documentation |
| `src/pflow/cli/commands/CLAUDE.md` | Update workflow save documentation |

## Implementation

### Phase 1: `save_workflow_with_options` owns validation

**File: `src/pflow/core/workflow/save_service.py`**

1. Change return type from `tuple[Path, list[str]]` to `tuple[Path, list[str], dict[str, Any]]` (third element: validated IR)

2. Add parse + validate at the top of `save_workflow_with_options`, before the existing existence check:

```python
def save_workflow_with_options(
    name: str,
    markdown_content: str,
    *,
    force: bool = False,
    metadata: Optional[dict[str, Any]] = None,
    source_path: Optional[Path] = None,
) -> tuple[Path, list[str], dict[str, Any]]:
    # --- NEW: parse + validate ---
    result = parse_markdown(markdown_content)
    validated_ir = _validate_and_normalize_ir(
        result.ir,
        auto_normalize=True,
        source_desc=f"Invalid workflow '{name}'",
        source_path=source_path,
    )
    # --- existing logic below (unchanged) ---
    manager = WorkflowManager()
    # ... existence check, deps, save ...
    return Path(saved_path), bundled_files, validated_ir
```

3. New exceptions that can propagate from this function:
   - `MarkdownParseError` — from `parse_markdown()` (new)
   - `WorkflowValidationError` with `validation_errors` populated — from `_validate_and_normalize_ir()` (new)
   - `FileExistsError`, `WorkflowValidationError` (summary-only) — from existing save mechanics (unchanged)

4. Update the docstring: remove "pre-validated by caller", document that validation is internal. Update the Raises section.

**`parse_markdown` is already imported** at the top of the file (line 15). `_validate_and_normalize_ir` is defined in the same file. No new imports needed.

### Phase 2: Simplify CLI save command

**File: `src/pflow/cli/commands/workflow.py`**

1. **Delete `_load_and_parse_workflow`** (lines 225-273) — this bypass caused #236

2. **Delete `_save_with_overwrite_check`** (lines 276-323) — thin wrapper with one caller, no abstraction value once `_load_and_parse_workflow` is gone

3. **Rewrite `save_workflow` click command** (lines 351-397) as a single coherent flow:

```python
def save_workflow(file_path: str, name: str, delete_draft: bool, force: bool) -> None:
    from pathlib import Path as PathLib
    from pflow.core.workflow.save_service import save_workflow_with_options, validate_workflow_name

    # Validate name
    is_valid, error = validate_workflow_name(name)
    if not is_valid:
        click.echo(f"Error: {error}", err=True)
        sys.exit(1)

    # Reject JSON files (CLI-specific migration message)
    path = PathLib(file_path)
    if path.suffix == ".json":
        click.echo(
            "Error: JSON workflow format is no longer supported. "
            "Use .pflow.md format instead.",
            err=True,
        )
        sys.exit(1)

    # Save (parse + validate + persist — all inside save_workflow_with_options)
    try:
        content = path.read_text(encoding="utf-8")
        saved_path, bundled_files, workflow_ir = save_workflow_with_options(
            name=name,
            markdown_content=content,
            force=force,
            source_path=path,
        )
    except FileExistsError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("  Use --force to overwrite.", err=True)
        sys.exit(1)
    except WorkflowValidationError as e:
        # Rich diagnostic display — same format as --validate-only
        if e.validation_errors:
            from pflow.execution.formatters.validation_formatter import (
                format_validation_failure,
            )
            click.echo(format_validation_failure(e.validation_errors), err=True)
        else:
            click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except MarkdownParseError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError:
        click.echo(f"Error: File not found: {file_path}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error saving workflow: {e}", err=True)
        sys.exit(1)

    if force:
        click.echo(f"✓ Overwritten existing workflow '{name}'")

    _delete_draft_if_requested(file_path, delete_draft)

    from pflow.execution.formatters.workflow_save_formatter import format_save_success
    success_message = format_save_success(
        name=name,
        saved_path=str(saved_path),
        workflow_ir=workflow_ir,
        metadata=None,
        bundled_files=bundled_files,
    )
    click.echo(success_message)
```

**Key display decision**: `WorkflowValidationError` with `validation_errors` uses `format_validation_failure()` — the same renderer as `--validate-only`. This gives the rich numbered format with suggestions, matching the acceptance criteria. `WorkflowValidationError` without `validation_errors` (I/O errors from save mechanics) falls back to the string message.

**Edge case — JSON rejection**: Stays in the CLI command (not in `save_workflow_with_options`) because it's a CLI-specific migration message, not a validation concern.

### Phase 3: Simplify MCP save

**File: `src/pflow/mcp_server/services/execution_service.py`**

1. **Simplify `save_workflow`** (lines 304-378): Delete the manual `parse_markdown` + `load_and_validate_workflow` block (lines 349-368). The validation now happens inside `save_workflow_with_options`.

New flow:
```python
@classmethod
@ensure_stateless
def save_workflow(cls, workflow: str, name: str, force: bool = False) -> str:
    from pflow.core.workflow.save_service import save_workflow_with_options, validate_workflow_name

    # Validate name (unchanged)
    is_valid, error = validate_workflow_name(name)
    if not is_valid:
        raise ValueError(f"Invalid workflow name: {error}")

    # Determine content and source_path (unchanged logic, simplified)
    if "\n" in workflow:
        markdown_content = workflow
        source_path = None
    elif workflow.lower().endswith(".pflow.md") or Path(workflow).expanduser().exists():
        file_path = Path(workflow).expanduser()
        if not file_path.exists():
            raise ValueError(f"Workflow file not found: {workflow}")
        markdown_content = file_path.read_text(encoding="utf-8")
        source_path = file_path
    else:
        raise ValueError(
            f"Cannot save '{workflow}'. Pass raw .pflow.md content or a file path."
        )

    # Save (validation is internal) + format result
    try:
        return cls._save_and_format_result(name, markdown_content, force, source_path)
    except WorkflowValidationError as e:
        from pflow.execution.formatters.validation_formatter import format_validation_failure
        rendered = (
            format_validation_failure(e.validation_errors)
            if e.validation_errors
            else f"Invalid workflow: {e}"
        )
        raise ValueError(rendered) from e
    except MarkdownParseError as e:
        raise ValueError(f"Invalid workflow: {e}") from e
```

2. **Simplify `_save_and_format_result`** (lines 380-429): Remove the `workflow_ir` parameter — it comes from the save result now.

```python
@classmethod
def _save_and_format_result(
    cls,
    name: str,
    markdown_content: str,
    force: bool,
    source_path: Optional[Path] = None,
) -> str:
    from pflow.core.workflow.save_service import save_workflow_with_options
    from pflow.execution.formatters.workflow_save_formatter import format_save_success

    saved_path, bundled_files, workflow_ir = save_workflow_with_options(
        name=name,
        markdown_content=markdown_content,
        force=force,
        source_path=source_path,
    )
    return format_save_success(
        name=name,
        saved_path=str(saved_path),
        workflow_ir=workflow_ir,
        metadata=None,
        bundled_files=bundled_files,
    )
```

3. **Remove stale imports**: `parse_markdown` and `load_and_validate_workflow` are no longer needed in this file's save path. Check if they're used elsewhere in the file before removing.

### Phase 4: Update tests

**4a. `tests/test_core/test_workflow_save_service.py` — `TestSaveWorkflowWithOptions`**

These 7 tests mock `WorkflowManager` and test save mechanics (force, overwrite, re-enrich). Since `save_workflow_with_options` now parses and validates internally:

- Update all `path, bundled = save_workflow_with_options(...)` to `path, bundled, ir = ...`
- Use `ir_to_markdown()` from `tests/shared/markdown_utils.py` to create valid workflow content that passes full validation (replace any minimal/invalid test fixtures)
- For tests that specifically test save mechanics (force, delete, re-enrich), use a simple valid workflow: single shell node with `command` param
- Verify existing assertions still hold after fixture updates

**4b. `tests/test_cli/test_workflow_save_cli.py`**

- `test_workflow_save_rejects_invalid_workflow` — This test likely passes an invalid workflow and checks for rejection. After the change, the error message may be richer (diagnostic format instead of plain schema error). Update assertion to match the new format.
- Other tests that create valid workflows should continue passing (they already create workflows that pass schema validation; most should also pass full validation).

**4c. `tests/test_mcp_server/test_workflow_save.py`**

- Update any tests that check return type or call signature of `_save_and_format_result` (if directly tested)
- Tests that go through `ExecutionService.save_workflow` should largely pass since the behavior is the same — just the internal flow changed

**4d. `tests/test_integration/test_workflow_bundling.py`** (found by code review — missed in initial plan)

This file calls `save_workflow_with_options` directly in 6 places across 3 test classes.

- **Return type fix (4 sites)**: Update lines 347, 382, 562, 644 from `path, bundled = save_workflow_with_options(...)` to `path, bundled, ir = ...`
- **Error source change (1 test)**: `test_raw_content_with_sub_workflow_ref_rejected` expects `WorkflowValidationError` matching `"file references"`. After the change, validation runs FIRST — the sub-workflow validator (step 8) will fail with `"Cannot resolve relative sub-workflow"` before `_reject_unbundleable_file_refs` runs. Update the assertion to match the new error. The behavior is actually better (more specific error, caught earlier).
- **Verify prompt-ref test**: `test_raw_content_with_prompt_file_ref_rejected` should be unaffected (prompt path is a string param, not a sub-workflow reference), but verify during implementation.

**Run bundling tests immediately after Phase 1** to catch any ordering interactions between the new validation and the existing file-ref guards.

**4e. New regression test** (acceptance criteria from #236)

Add to `tests/test_cli/test_workflow_save_cli.py`:

```python
def test_workflow_save_rejects_unknown_parameter_with_rich_diagnostic(self, ...):
    """Regression test for GH #236: save must reject broken workflows
    with the same rich diagnostic format as --validate-only."""
    # Create workflow with unknown parameter (typo: file_pat instead of file_path)
    broken_md = textwrap.dedent("""\
        # Broken Workflow

        ## Steps

        ### writer
        Writes content.

        - type: write-file
        - file_pat: output.txt
        - content: hello
    """)
    draft = tmp_path / "broken.pflow.md"
    draft.write_text(broken_md)

    result = runner.invoke(workflow_cmd, ["save", str(draft), "--name", "test-broken"])
    assert result.exit_code != 0
    # Rich diagnostic format — same as --validate-only
    # CliRunner mixes stderr into result.output by default
    assert "Unknown parameter" in result.output
    assert "file_pat" in result.output
```

Also add a positive test confirming valid workflows still save successfully (if not already covered).

### Phase 5: Update documentation

- `src/pflow/core/workflow/CLAUDE.md` — Update `save_service.py` section: document that `save_workflow_with_options` now owns parse + validate. Remove "pre-validated by caller" language. Note the return type change.
- `src/pflow/cli/commands/CLAUDE.md` — Update workflow save section: remove mentions of `_load_and_parse_workflow` and `_save_with_overwrite_check`. Document the simplified flow.

## Edge Cases Addressed

| Edge case | How it's handled |
|-----------|-----------------|
| Unknown params (the #236 repro) | Full 9-step validation catches it, `WorkflowValidationError` with rich diagnostics |
| `MarkdownParseError` from malformed content | Propagates from `save_workflow_with_options`; CLI catches and displays, MCP wraps as ValueError |
| `WorkflowValidationError` from validation vs from I/O | CLI checks `e.validation_errors`: populated → rich display, empty → string message |
| JSON file rejection | Stays in CLI command (before `save_workflow_with_options` call) — CLI-specific migration message |
| `FileExistsError` without `--force` | Unchanged — still raised by save mechanics inside `save_workflow_with_options` |
| Dependency bundling (sub-workflows, file refs) | Unchanged — runs after validation inside `save_workflow_with_options` |
| File refs without source_path (MCP raw content) | `_reject_unbundleable_file_refs` still runs inside `save_workflow_with_options` |
| #247 false positive (`${input.field}` in outputs) | Pre-existing — already affects MCP save and `--validate-only`. CLI save now gains the same exposure (previously skipped the validator entirely). This is correct: the validator is applied consistently. #247 should be fixed separately. Note in PR. |
| Tests passing minimal fixtures | Update to use `ir_to_markdown()` with valid workflow content |

## What's NOT Changing

- `WorkflowValidator.validate()` — the underlying 9-step validator, untouched
- `_validate_and_normalize_ir()` — the shared validation core, untouched (now called from one more place)
- `load_and_validate_workflow()` — public API for load+validate, untouched. Note: loses its last production caller (MCP save) after this change; remains useful as public API and is exercised by tests
- `WorkflowRunner._validate()` / `.validate()` — execution and validate-only paths, separate and correct
- `_delete_draft_if_requested()` — post-save action, stays as-is
- `_discover_and_bundle_deps()` / `_reject_unbundleable_file_refs()` — dependency handling, untouched

## Verification

1. **Reproduce the bug, confirm the fix:**
   ```bash
   # Create broken workflow (unknown param)
   cat > /tmp/broken.pflow.md <<'PFLOW'
   # Broken Workflow

   ## Steps

   ### writer
   Writes content using a typoed parameter.

   - type: write-file
   - file_pat: output.txt
   - content: hello
   PFLOW

   # Should now FAIL with rich diagnostic (was: silent success)
   uv run pflow workflow save /tmp/broken.pflow.md --name test-broken

   # Compare with --validate-only (should show same diagnostic format)
   uv run pflow /tmp/broken.pflow.md --validate-only

   # Valid workflow should still save
   cat > /tmp/valid.pflow.md <<'PFLOW'
   # Valid Workflow

   ## Steps

   ### echo
   Echoes hello.

   - type: shell
   - command: echo hello
   PFLOW

   uv run pflow workflow save /tmp/valid.pflow.md --name test-valid --force
   ```

2. **Run tests:**
   ```bash
   # Targeted tests first (includes bundling tests — run early to catch ordering interactions)
   pytest tests/test_core/test_workflow_save_service.py tests/test_cli/test_workflow_save_cli.py tests/test_mcp_server/test_workflow_save.py tests/test_integration/test_workflow_bundling.py tests/test_cli/test_validate_only.py -v

   # Full suite
   make test

   # Quality checks
   make check
   ```

3. **Verify CLI/MCP parity**: Both paths reject the same broken workflow with structured diagnostics.
