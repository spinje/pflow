# Implementation Spec: `pflow workflow history` Command

## Problem

When an agent invokes a pflow skill, it often needs to suggest sensible input values based on past usage. For example, a Slack channel ID (`C09ABC123`) is frequently reused but hard to remember. Currently:

1. `last_execution_params` is stored in workflow frontmatter after each run
2. But there's no agent-friendly way to retrieve it
3. `pflow workflow describe` shows execution history but repeats workflow content
4. Skills philosophy: agents shouldn't read files directly — they use commands

## Solution

Add `pflow workflow history <name>` command that returns focused execution history including last used inputs.

## Output Format

```
Execution History: release-announcements

Runs: 5
Last run: 2026-02-05 02:22:06
Status: Success

Last used inputs:
  slack_channel: C09ABC123
  version: 1.2.0
  discord_channel_id: 123456789
```

If no execution history:
```
No execution history for 'release-announcements'.
```

## Design Decisions

### 1. "Inputs" not "Parameters"

**Decision**: Use "inputs" in user-facing output.

**Reasoning**:
- Workflows have `## Inputs` section
- CLI uses `pflow workflow input=value`
- IR schema uses `"inputs": {}`
- "Parameters" is internal terminology (node params)

**Implementation**: Keep `last_execution_params` in storage (no migration), display as "inputs".

### 2. Focused output, not full describe

**Decision**: Only show execution-related data — no workflow description, inputs spec, outputs spec.

**Reasoning**:
- Agent already has workflow content from SKILL.md
- `describe` would be redundant
- Fewer tokens = faster agent responses
- Clear single purpose

### 3. Add hint to `## Usage` section

**Decision**: Include the history command in skill's Usage section.

**Reasoning**:
- Agent sees it when reading the skill
- Teaches agent the command exists
- Contextual — appears next to execution command

**Template addition**:
```bash
# View execution history and last used inputs:
pflow workflow history {workflow_name}
```

### 4. Sanitization already handled

**Verified**: `last_execution_params` is sanitized at storage time in `executor_service.py:518`:
- Sensitive keys (api_key, token, password, etc.) → `<REDACTED>`
- Environment-sourced params → `<REDACTED>`
- Long strings → truncated

No additional sanitization needed at display time.

### 5. Extensible structure

**Decision**: Name it `history` not `last-inputs`.

**Reasoning**:
- Room to add more data later (durations, error history, multiple runs)
- `history` is intuitive
- Matches common CLI patterns (`git log`, `docker history`)

## Files to Modify

### 1. `src/pflow/cli/commands/workflow.py`

Add new subcommand:

```python
@workflow.command(name="history")
@click.argument("workflow_name")
def workflow_history(workflow_name: str) -> None:
    """Show execution history and last used inputs.

    Useful for finding previously used input values like channel IDs,
    API endpoints, or other parameters that are often reused.

    Example:
        pflow workflow history release-announcements
    """
```

### 2. `src/pflow/execution/formatters/history_formatter.py`

Add new function or extend existing:

```python
def format_workflow_history(metadata: dict[str, Any]) -> str:
    """Format complete execution history for workflow history command."""
```

Or reuse `format_execution_history` with a new mode.

### 3. `src/pflow/core/skill_service.py`

Update `generate_usage_section()` template to include:

```bash
# View execution history and last used inputs:
pflow workflow history {workflow_name}
```

## Implementation Plan

### Phase 1: Add formatter function

Location: `src/pflow/execution/formatters/history_formatter.py`

Add `format_workflow_history(metadata)` that outputs:
- Workflow name header
- Run count
- Last run timestamp
- Status (success/failed)
- Last used inputs (if any)

### Phase 2: Add CLI command

Location: `src/pflow/cli/commands/workflow.py`

1. Add `@workflow.command(name="history")`
2. Load workflow via `WorkflowManager`
3. Call formatter
4. Output result

### Phase 3: Update Usage section template

Location: `src/pflow/core/skill_service.py`

Add history command hint to `generate_usage_section()`.

### Phase 4: Tests

1. `tests/test_execution/formatters/test_history_formatter.py` — formatter tests
2. `tests/test_cli/test_workflow_commands.py` — CLI integration tests
3. Update existing skill service tests if Usage section assertions exist

## Edge Cases

1. **Workflow not found** → Clear error with suggestion
2. **No execution history** → "No execution history for 'name'."
3. **No last_execution_params** → Show runs/timestamp but skip inputs section
4. **Params all redacted** → Show them (agent sees `<REDACTED>` which is correct)

## Verification

```bash
# Test with workflow that has history
pflow workflow history directory-file-lister

# Test with workflow that has no history (newly saved)
pflow workflow save examples/core/minimal.pflow.md --name test-minimal --force
pflow workflow history test-minimal

# Test non-existent workflow
pflow workflow history nonexistent

# Verify skill Usage section includes hint
pflow skill save directory-file-lister
cat ~/.pflow/workflows/directory-file-lister.pflow.md | grep "history"
```

## Future Extensions

Once the foundation exists, we could add:
- `--json` flag for structured output
- Multiple execution history (store list, not just last)
- Duration stats
- Error history with failure reasons
- Parameter frequency analysis
