# Detailed Fix Plan: Restrict Planner Execution

## Goal

**Only execute planner when:**
```bash
pflow "natural language prompt"
```

**Show helpful errors for:**
```bash
pflow lets do this thing          # Error: Quote your prompt
pflow jkahsd "some prompt"        # Error: Quote your prompt or specify workflow
pflow random text                 # Error: Quote your prompt
```

## Solution Overview

Replace the "fallback to planner" approach with **explicit validation** that checks:
1. Input must be exactly 1 argument (`len(workflow) == 1`)
2. That argument must contain spaces (indicating it was quoted)
3. Or show a helpful error message

## Implementation Plan

### Step 1: Create Helper Function

Add new function before `workflow_command()`:

```python
def _is_valid_natural_language_input(workflow: tuple[str, ...]) -> bool:
    """Check if input is valid for natural language planning.

    Valid natural language input must be:
    - Exactly one argument (quoted string from shell)
    - Contains spaces (not a single word)
    - Not a file path or workflow name (already filtered upstream)

    Args:
        workflow: Tuple of command line arguments

    Returns:
        True if valid natural language input, False otherwise
    """
    # Must be exactly one argument
    if len(workflow) != 1:
        return False

    text = workflow[0]

    # Must contain spaces (quoted multi-word phrase)
    if " " not in text:
        return False

    # Must not look like a file path
    # (This is defensive - should already be filtered by _try_execute_named_workflow)
    if _is_path_like(text):
        return False

    return True
```

### Step 2: Create Error Handler Function

Add function to show helpful error:

```python
def _handle_invalid_planner_input(ctx: click.Context, workflow: tuple[str, ...]) -> None:
    """Show helpful error for invalid planner input.

    Args:
        ctx: Click context
        workflow: Invalid workflow tuple
    """
    if not workflow:
        # Should be caught earlier, but defensive
        click.echo("❌ No workflow specified.", err=True)
        click.echo("", err=True)
        click.echo("Usage:", err=True)
        click.echo('  pflow "natural language prompt"    # Use quotes for planning', err=True)
        click.echo('  pflow workflow.json                 # Run workflow from file', err=True)
        click.echo('  pflow my-workflow                   # Run saved workflow', err=True)
        click.echo('  pflow workflow list                 # List saved workflows', err=True)
        ctx.exit(1)

    if len(workflow) == 1:
        # Single word without spaces
        word = workflow[0]
        click.echo(f"❌ '{word}' is not a known workflow or command.", err=True)
        click.echo("", err=True)
        click.echo("Did you mean:", err=True)
        click.echo(f'  pflow "{word} <rest of prompt>"    # Use quotes for natural language', err=True)
        click.echo(f'  pflow workflow list                 # List saved workflows', err=True)
        ctx.exit(1)

    # Multiple unquoted arguments
    joined = " ".join(workflow)
    click.echo(f"❌ Invalid input: {workflow[0]} {workflow[1]} ...", err=True)
    click.echo("", err=True)
    click.echo("Natural language prompts must be quoted:", err=True)
    click.echo(f'  pflow "{joined}"', err=True)
    click.echo("", err=True)
    click.echo("Or use a workflow:", err=True)
    click.echo("  pflow workflow.json", err=True)
    click.echo("  pflow my-workflow param=value", err=True)
    ctx.exit(1)
```

### Step 3: Modify workflow_command() Flow

Replace lines 3394-3405 in `workflow_command()`:

**BEFORE:**
```python
    # Validate input for natural language processing
    raw_input = _validate_and_prepare_natural_language_input(workflow)

    # Handle single-token workflow with guardrails
    if _handle_single_token_workflow(ctx, workflow, stdin_data, output_key, output_format, verbose):
        return

    # Multi-word or parameterized input: planner by design
    cache_planner = ctx.obj.get("cache_planner", False)
    _execute_with_planner(
        ctx, raw_input, stdin_data, output_key, verbose, "args", trace, planner_timeout, cache_planner
    )
```

**AFTER:**
```python
    # Check if this is valid natural language input for planner
    if not _is_valid_natural_language_input(workflow):
        # Not valid for planner - show helpful error
        _handle_invalid_planner_input(ctx, workflow)
        return  # Never reached, but explicit

    # Valid natural language input - prepare and execute with planner
    raw_input = _validate_and_prepare_natural_language_input(workflow)
    cache_planner = ctx.obj.get("cache_planner", False)
    _execute_with_planner(
        ctx, raw_input, stdin_data, output_key, verbose, "args", trace, planner_timeout, cache_planner
    )
```

### Step 4: Remove/Simplify Single Token Handler

The `_handle_single_token_workflow()` function (lines 3187-3216) becomes unnecessary because:
- Single words without spaces: now caught by `_is_valid_natural_language_input()` → error
- Saved workflows: already handled by `_try_execute_named_workflow()`

We can delete this function entirely.

### Step 5: Simplify Validation Function

The `_validate_and_prepare_natural_language_input()` function can be simplified since we've already validated the structure:

**Current:**
```python
def _validate_and_prepare_natural_language_input(workflow: tuple[str, ...]) -> str:
    """Validate and prepare input for natural language processing."""
    raw_input = " ".join(workflow) if workflow else ""

    if not raw_input:
        raise click.ClickException("cli: No workflow provided. Use --help to see usage examples.")

    # Validate input length (100KB limit)
    if len(raw_input) > 100 * 1024:
        raise click.ClickException(
            "cli: Workflow input too large (max 100KB). Consider breaking it into smaller workflows."
        )

    return raw_input
```

**After:**
```python
def _validate_and_prepare_natural_language_input(workflow: tuple[str, ...]) -> str:
    """Prepare validated natural language input for planning.

    Args:
        workflow: Already validated workflow tuple (single quoted string)

    Returns:
        The natural language prompt string

    Raises:
        ClickException: If input is too large
    """
    # At this point we know workflow is a single element with spaces
    raw_input = workflow[0]

    # Validate input length (100KB limit)
    if len(raw_input) > 100 * 1024:
        raise click.ClickException(
            "cli: Workflow input too large (max 100KB). Consider breaking it into smaller workflows."
        )

    return raw_input
```

## Expected Behavior After Fix

### Valid Cases (unchanged)

```bash
# ✅ Quoted prompt → planner
pflow "do something"

# ✅ File path → direct execution
pflow workflow.json
pflow ./my-workflow.json
pflow ~/workflows/test.json

# ✅ Saved workflow → direct execution
pflow my-workflow
pflow my-workflow input=file.txt

# ✅ Subcommands → route to command groups
pflow registry list
pflow workflow describe my-workflow
pflow mcp list
```

### Invalid Cases (now show errors)

```bash
# ❌ Multiple unquoted words → ERROR
$ pflow lets do this thing
❌ Invalid input: lets do ...

Natural language prompts must be quoted:
  pflow "lets do this thing"

Or use a workflow:
  pflow workflow.json
  pflow my-workflow param=value

# ❌ Mixed quoted/unquoted → ERROR
$ pflow jkahsd "do something"
❌ Invalid input: jkahsd do something ...

Natural language prompts must be quoted:
  pflow "jkahsd do something"

Or use a workflow:
  pflow workflow.json
  pflow my-workflow param=value

# ❌ Single unquoted word → ERROR (not a workflow)
$ pflow random
❌ 'random' is not a known workflow or command.

Did you mean:
  pflow "random <rest of prompt>"    # Use quotes for natural language
  pflow workflow list                 # List saved workflows
```

## Testing Strategy

### Unit Tests

Add to `tests/test_cli/test_main.py`:

```python
def test_is_valid_natural_language_input():
    """Test natural language input validation."""
    # Valid: single quoted argument with spaces
    assert _is_valid_natural_language_input(("do something",)) is True
    assert _is_valid_natural_language_input(("analyze this file and summarize it",)) is True

    # Invalid: multiple unquoted arguments
    assert _is_valid_natural_language_input(("lets", "do", "this")) is False
    assert _is_valid_natural_language_input(("jkahsd", "do something")) is False

    # Invalid: single word (no spaces)
    assert _is_valid_natural_language_input(("random",)) is False
    assert _is_valid_natural_language_input(("workflow",)) is False

    # Invalid: empty
    assert _is_valid_natural_language_input(()) is False

    # Invalid: file paths (defensive check)
    assert _is_valid_natural_language_input(("workflow.json",)) is False
    assert _is_valid_natural_language_input(("./path/to/file.json",)) is False
```

### Integration Tests

Add to `tests/test_cli/test_main_integration.py`:

```python
def test_unquoted_multi_word_shows_error(runner):
    """Multiple unquoted words should show helpful error."""
    result = runner.invoke(workflow_command, ["lets", "do", "this"])
    assert result.exit_code == 1
    assert "Invalid input" in result.output or "must be quoted" in result.output


def test_mixed_quoted_unquoted_shows_error(runner):
    """Mixed quoted/unquoted should show helpful error."""
    result = runner.invoke(workflow_command, ["jkahsd", "do something"])
    assert result.exit_code == 1
    assert "Invalid input" in result.output or "must be quoted" in result.output


def test_single_unquoted_word_not_workflow_shows_error(runner):
    """Single unquoted word that's not a workflow should error."""
    result = runner.invoke(workflow_command, ["randomnonexistent"])
    assert result.exit_code == 1
    assert "not a known workflow" in result.output


def test_quoted_prompt_goes_to_planner(runner, mock_planner):
    """Quoted multi-word prompt should trigger planner."""
    result = runner.invoke(workflow_command, ["do something cool"])
    # Should attempt to use planner (or show planner error if not configured)
    assert result.exit_code in (0, 1)  # Depends on planner availability
```

## Edge Cases to Consider

1. **Empty input:** Already handled by validate function
2. **Very long quoted strings:** Already handled by 100KB limit check
3. **Stdin input:** Not affected by this change (workflow tuple would be empty)
4. **Flags in wrong order:** Already handled by _validate_workflow_flags
5. **Workflow with spaces in filename:** Would be quoted by shell, but has .json extension or / → caught by _try_execute_named_workflow

## Rollout Plan

1. Implement helper functions
2. Update workflow_command() flow
3. Add unit tests
4. Add integration tests
5. Run full test suite
6. Manual testing of edge cases
7. Update CLI help text if needed

## Files to Modify

- `src/pflow/cli/main.py` - Main changes
- `tests/test_cli/test_main.py` - Unit tests
- `tests/test_cli/test_main_integration.py` - Integration tests (if exists, or create)

## Backward Compatibility

This is a **breaking change** but justified:
- Current behavior allows invalid input that wastes API calls
- Users trying `pflow lets do this` likely expect it to work or get clear error
- Error messages guide users to correct syntax
- MVP with no production users → safe to fix

## Success Criteria

✅ `pflow "quoted prompt"` works
✅ `pflow workflow.json` works
✅ `pflow my-workflow` works
✅ `pflow registry list` works
❌ `pflow lets do this` shows clear error
❌ `pflow random` shows clear error
❌ `pflow word "prompt"` shows clear error

