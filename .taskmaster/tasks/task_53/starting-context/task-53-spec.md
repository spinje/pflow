# Feature: rerun_command_display

## Objective

Display executable rerun commands after workflow execution.

## Requirements

- Must extract workflow name from planner output
- Must extract execution parameters from planner output
- Must format parameters with shell-safe escaping
- Must display both run and describe commands
- Must handle both reused and newly-saved workflows
- Must modify `_prompt_workflow_save()` to return save status

## Scope

- Does not display for unsaved workflows
- Does not modify workflow execution behavior
- Does not change parameter parsing logic
- Does not create new CLI commands

## Inputs

- `planner_output`: dict[str, Any] - Complete planner output containing:
  - `workflow_ir`: dict - The workflow IR (if successful)
  - `execution_params`: dict[str, Any] | None - Parameters used in execution
  - `workflow_metadata`: dict | None - Metadata including suggested_name
  - `workflow_source`: dict | None - Source information with structure:
    ```python
    {
        "found": bool,              # True if existing workflow reused
        "workflow_name": str|None,  # Name if found, None if generated
        "confidence": float,        # 0.0-1.0 match confidence
        "reasoning": str            # LLM reasoning
    }
    ```
  - `success`: bool - Whether planning succeeded

## Outputs

Side effects: Prints formatted rerun commands to stdout with:
- Run command with escaped parameters (without "run" prefix)
- Describe command for workflow exploration

## Structured Formats

```json
{
  "display_format": {
    "rerun_command": "pflow {name} {params}",
    "describe_command": "pflow workflow describe {name}",
    "param_format": "{key}={escaped_value}"
  },
  "escaping": {
    "method": "shlex.quote",
    "triggers": ["spaces", "quotes", "special_chars", "newlines", "shell_metacharacters"]
  }
}
```

## State/Flow Changes

- Modify `_prompt_workflow_save()` to return `tuple[bool, str | None]` indicating (was_saved, workflow_name)
- Add display logic in `_execute_successful_workflow()` after execution
- Add display logic in `_prompt_workflow_save()` after successful save

## Constraints

- Parameter names must be valid Python identifiers
- Workflow name must exist for display
- Shell escaping must preserve parameter parseability

## Rules

1. Display rerun command only when workflow name is known (reused or saved)
2. For reused workflows: Display immediately after successful execution
3. For new workflows: Display only after user saves with chosen name
4. Use shlex.quote() for ALL parameter values to ensure shell safety
5. Convert boolean True to string "true" (lowercase)
6. Convert boolean False to string "false" (lowercase)
7. Convert lists to JSON string using json.dumps() with no spaces
8. Convert dicts to JSON string using json.dumps() with no spaces
9. Convert numbers directly to string representation
10. Display parameters in key=value format (no -- prefix)
11. Display workflow name without "run" prefix (e.g., `pflow analyzer` not `pflow run analyzer`)
12. Include only non-None execution_params in rerun command
13. Display describe command after rerun command
14. Use emoji prefixes for visual distinction (✨ for run, 📖 for describe)
15. Skip display entirely if workflow_source is None or execution_params is None

## Edge Cases

- No parameters → display command without parameters
- Empty string parameter → display as key=""
- Parameter with quotes → escape with shlex.quote()
- Parameter with spaces → escape with shlex.quote()
- Parameter with newlines → escape with shlex.quote()
- JSON object parameter → convert to JSON string then escape
- Workflow not saved (new workflow, user declines) → skip display entirely
- Missing workflow name → skip display entirely
- execution_params is None (planning failure) → skip display entirely
- workflow_source is None → skip display entirely

## Error Handling

- Invalid parameter name → log warning and skip that parameter
- Shell escaping failure → fall back to repr() with quotes
- JSON serialization failure → use repr() as fallback
- Missing workflow_metadata → proceed without suggested_name
- _prompt_workflow_save returns error → log and continue without display

## Non-Functional Criteria

- Display latency < 10ms
- Shell command must be copy-pasteable
- Output must be parseable by existing CLI

## Examples

### Reused workflow with simple parameters
```
Input:
  workflow_source: {"found": true, "workflow_name": "analyzer"}
  execution_params: {"count": 5}
Output:
✨ Run again with:
  $ pflow analyzer count=5

📖 Learn more:
  $ pflow workflow describe analyzer
```

### Newly saved workflow with complex parameters
```
Input:
  workflow_source: {"found": false, "workflow_name": null}
  execution_params: {"message": "hello world", "config": {"key": "value"}}
  After save: workflow_name="processor"
Output:
✨ Run again with:
  $ pflow processor message='hello world' config='{"key":"value"}'

📖 Learn more:
  $ pflow workflow describe processor
```

### Workflow with no parameters
```
Input:
  workflow_source: {"found": true, "workflow_name": "simple-task"}
  execution_params: {}
Output:
✨ Run again with:
  $ pflow simple-task

📖 Learn more:
  $ pflow workflow describe simple-task
```

## Test Criteria

1. Reused workflow with no parameters → displays `pflow workflow-name`
2. Reused workflow with string parameter → displays with shlex.quote() escaping
3. Reused workflow with spaces in parameter → displays with proper escaping
4. Reused workflow with quotes in parameter → displays with proper escaping
5. New workflow saved with boolean True → displays as `param=true`
6. New workflow saved with boolean False → displays as `param=false`
7. New workflow saved with number → displays as `param=42`
8. New workflow saved with list → displays as `param='[1,2,3]'`
9. New workflow saved with dict → displays as `param='{"key":"value"}'`
10. New workflow not saved (user declines) → no display output
11. Missing workflow_source → no display output
12. execution_params is None → no display output
13. Empty string parameter → displays as `key=''`
14. Newline in parameter → displays with shlex escaping
15. Shell metacharacters ($, &, ;, |) → displays with shlex escaping
16. Round-trip test: displayed command executes identically
17. _prompt_workflow_save returns (True, name) → displays with that name
18. _prompt_workflow_save returns (False, None) → no display

## Notes (Why)

- Shell escaping prevents command injection and ensures parseability
- Displaying actual values accelerates user learning curve
- Saved-only display prevents confusion with unsaved workflows
- Emoji prefixes improve visual scanning in terminal output

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 10, 11, 12                 |
| 2      | 1, 2, 3, 4                 |
| 3      | 17, 18                     |
| 4      | 2, 3, 4, 13, 14, 15        |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 8                          |
| 8      | 9                          |
| 9      | 7                          |
| 10     | 1-9                        |
| 11     | 1, 16                      |
| 12     | 12                         |
| 13     | 1-9                        |
| 14     | 1-9                        |
| 15     | 11, 12                     |

## Versioning & Evolution

- v1.0.0 — Initial specification for rerun command display

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes shlex.quote() available in Python standard library (verified: YES, part of stdlib)
- Assumes execution_params contains actual user values (verified: YES, direct from planner)
- Assumes workflow_source structure is stable (verified: YES, Pydantic schema enforced)
- Unknown: whether users want parameters sorted alphabetically (decision: preserve order from execution_params)

### Conflicts & Resolutions

- Task doc showed `pflow run analyzer` format, actual CLI uses `pflow analyzer`. Resolution: Use actual implementation (no "run" prefix for saved workflows)
- Spec assumed `is_saved` flag exists, it doesn't. Resolution: Use `workflow_source["found"]` and track save status from _prompt_workflow_save return value
- Confusion about when to display. Resolution: Reused workflows display immediately, new workflows only after save

### Decision Log / Tradeoffs

- Display only for known workflow names (reused or saved) over showing natural language for unsaved (prevents confusion)
- Use shlex.quote() for ALL values over conditional escaping (safety over optimization)
- Show all execution_params over only explicit params (reproducibility over brevity)
- Modify _prompt_workflow_save to return status over tracking state globally (cleaner architecture)
- Display actual parameter values over placeholders (user learning over documentation)

### Ripple Effects / Impact Map

- `_prompt_workflow_save()` signature change affects all callers (only one location)
- New display functions in CLI main.py (additive, no breaking changes)
- No impact on parameter parsing logic
- No impact on workflow execution
- No impact on planner behavior

### Residual Risks & Confidence

- Risk: Complex nested JSON might exceed terminal width. Mitigation: Users can scroll, most terminals wrap
- Risk: shlex.quote() might produce non-intuitive output for some edge cases. Mitigation: Well-tested stdlib function
- Risk: Users might expect "run" prefix. Mitigation: CLI already accepts both formats transparently
- Confidence: High (95%) - Based on thorough codebase analysis

### Epistemic Audit (Checklist Answers)

1. Verified assumptions through parallel codebase searches with actual file evidence
2. Wrong assumption about "run" prefix would have caused confusion; corrected based on implementation
3. Prioritized safety (always escape) over elegance (conditional escaping) for robustness
4. All 15 rules mapped to 18 test criteria with full coverage
5. Changes isolated to display layer with one function signature modification
6. Parameter sorting preference remains unknown but defaulting to preserving order is safest; Overall confidence: High