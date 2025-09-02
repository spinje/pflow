# Task 53 Review: Add Rerun Command Display

## Executive Summary
Implemented a feature to display executable `pflow` commands after workflow execution, enabling users to bypass the planner on subsequent runs. Added security masking for sensitive parameters and achieved 100% round-trip compatibility with the CLI's parameter parsing.

## Implementation Overview

### What Was Built
A rerun command display system that shows the exact command to re-execute workflows after they run. When workflows complete (whether reused or newly created), users see:
```
✨ Run again with:
  $ pflow workflow-name param=value

📖 Learn more:
  $ pflow workflow describe workflow-name
```

**Critical deviation from spec**: Original task showed `pflow run analyzer` format but actual CLI uses `pflow analyzer` (no "run" prefix for saved workflows). The `_preprocess_run_prefix()` function strips "run" transparently.

### Implementation Approach
- Created standalone `rerun_display.py` module to avoid circular imports
- Modified `_prompt_workflow_save()` to return save status (architectural change)
- Added display logic at two integration points in main.py
- Implemented universal shell escaping with `shlex.quote()`
- Added security layer for sensitive parameter masking

## Files Modified/Created

### Core Changes
- `src/pflow/cli/rerun_display.py` - New module with formatting utilities (created)
- `src/pflow/cli/main.py` - Modified at lines 486-546 (save function) and 1364-1383 (display points)

### Test Files
- `tests/test_cli/test_rerun_display.py` - 88 comprehensive tests including critical round-trip verification

## Integration Points & Dependencies

### Incoming Dependencies
None yet - this is a new leaf feature that other components don't depend on.

### Outgoing Dependencies
- `pflow.cli.main.infer_type()` - Must reverse its type conversion logic exactly
- `pflow.cli.main.parse_workflow_params()` - Commands must parse back identically
- `click.echo()` - For terminal output
- `shlex.quote()` - For shell escaping (critical for security)

### Shared Store Keys
None - this feature only displays commands, doesn't interact with shared store.

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Local imports over module-level imports**
   - Decision: Import `display_rerun_commands` locally in main.py
   - Reasoning: Prevents circular import issues
   - Alternative: Module-level import would require restructuring

2. **Modify _prompt_workflow_save() return type**
   - Decision: Change from `-> None` to `-> tuple[bool, str | None]`
   - Reasoning: Clean way to track save status without global state
   - Alternative: Global flag or separate tracking (messy)

3. **Universal shlex.quote() application**
   - Decision: Apply to ALL parameter values, even "simple" ones
   - Reasoning: Even simple values like `$HOME` can break commands
   - Alternative: Conditional escaping (security risk)

4. **Security-by-default with SENSITIVE_KEYS**
   - Decision: Mask common secret patterns as `<REDACTED>`
   - Reasoning: Prevent accidental secret exposure in terminal
   - Alternative: No masking (security risk)

### Technical Debt Incurred
- Hard-coded SENSITIVE_KEYS set should eventually move to configuration
- No way to override masking for debugging (might need `--show-secrets` flag)
- Display logic embedded in main.py could be abstracted to a display service

## Testing Implementation

### Test Strategy Applied
Focused on round-trip compatibility over coverage. Every displayed command MUST parse back to identical parameters. Used parametrized tests extensively for type conversions.

### Critical Test Cases
- `TestRoundTripCompatibility::test_round_trip` - THE most important test, verifies displayed commands work
- `TestSecurityAndStress::test_command_injection_attempts` - Ensures shell injection is impossible
- `TestFormatParamValue::test_type_conversions` - Validates exact reversal of infer_type()

## Unexpected Discoveries

### Gotchas Encountered

1. **The "run" prefix doesn't exist for saved workflows**
   - Spec showed `pflow run analyzer` but it's actually `pflow analyzer`
   - Wasted time until discovering `_preprocess_run_prefix()` strips it

2. **No is_saved flag exists**
   - Spec assumed this flag would be available
   - Had to modify _prompt_workflow_save() to return status

3. **Empty string round-trip works perfectly**
   - Code reviewer claimed it would fail
   - Testing proved: `empty=''` → `shlex.split()` → `empty=` → works fine

4. **Only ONE caller of _prompt_workflow_save()**
   - Made signature change safe
   - Located at line 1376 (was 1370 before changes)

### Edge Cases Found
- JSON with nested quotes needs `separators=(',', ':')` for compact format
- Very small floats use scientific notation (acceptable, parses correctly)
- Empty parameters dict must display just `pflow workflow-name` (no params)

## Patterns Established

### Reusable Patterns

1. **Type conversion reversal pattern**:
```python
def format_param_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()  # Must be lowercase for CLI
    elif isinstance(value, (list, dict)):
        return json.dumps(value, separators=(',', ':'))  # Compact JSON
    # ... handle other types
```

2. **Security masking pattern**:
```python
SENSITIVE_KEYS = {"password", "token", "api_key", ...}
if key.lower() in SENSITIVE_KEYS:
    param_str = f"{key}=<REDACTED>"
```

### Anti-Patterns to Avoid
- DON'T conditionally escape "complex" values - escape EVERYTHING with shlex.quote()
- DON'T display "run" prefix - it's optional and not canonical
- DON'T show commands for unsaved workflows - confusing for users

## Breaking Changes

### API/Interface Changes
- `_prompt_workflow_save()` now returns `tuple[bool, str | None]` instead of `None`
- Only one caller existed, so impact was minimal

### Behavioral Changes
None - purely additive feature, doesn't change existing behavior.

## Future Considerations

### Extension Points
- `SENSITIVE_KEYS` could be loaded from settings.json
- Display format could be customized (different emoji, colors)
- Could add `--copy-command` flag to copy to clipboard

### Scalability Concerns
- Very long parameter lists make commands hard to read (might need line wrapping)
- No pagination for many parameters (terminal scrolling only)

## AI Agent Guidance

### Quick Start for Related Tasks

**If modifying parameter display**, read these first:
1. `src/pflow/cli/main.py::infer_type()` - Understand forward conversion
2. `src/pflow/cli/rerun_display.py::format_param_value()` - See reversal logic
3. `tests/test_cli/test_rerun_display.py::TestRoundTripCompatibility` - Critical tests

**Key insight**: The round-trip MUST work: user input → Python types → CLI string → parse → same Python types

### Common Pitfalls

1. **Assuming shell handles quoting** - NO! Python sees args AFTER shell processing. Empty string becomes `param=` not `param=''`

2. **Testing with CliRunner only** - Also test with real `shlex.split()` to simulate shell behavior

3. **Forgetting None filtering** - Parameters with None values must be skipped entirely

4. **Using generic "key" for secrets** - Too many false positives, only mask specific patterns

### Test-First Recommendations

When modifying this feature, run these tests first:
```bash
# Most critical - ensures commands actually work
pytest tests/test_cli/test_rerun_display.py::TestRoundTripCompatibility -xvs

# Security - prevents secret leaks
pytest tests/test_cli/test_rerun_display.py::TestSecurityFeatures -xvs

# Then run all
pytest tests/test_cli/test_rerun_display.py -xvs
```

If these pass, you probably haven't broken anything critical.

---

## Implementation Metadata

- **Claude Session ID**: `6d8e578c-26cc-40d0-93b6-a4b2b42c1ecd`
- **Pull Request**: https://github.com/spinje/pflow/pull/13
- **Implementation Date**: 2025-09-02

---

*Generated from implementation context of Task 53*