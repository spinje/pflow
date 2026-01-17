# Task 110: PIPESTATUS-Based Pipeline Failure Detection

## Description

Use bash's PIPESTATUS to accurately detect which command in a pipeline failed, enabling precise "no results" vs "real error" detection. This is the root-cause solution for silent pipeline failures in shell nodes.

## Status
not started

## Priority

low

## Problem

Current smart error handling can't distinguish between:
1. `grep notfound | cat` → grep returns 1 (no matches) - legitimate
2. `grep hello | sed 's/bad//'` → sed returns 1 (error) - should fail

Both cases show exit code 1 for the pipeline. The simpler stderr check (Task 109) covers ~95% of cases, but edge cases like `grep | false` (silent failure, no stderr) still incorrectly succeed.

Bash provides `${PIPESTATUS[@]}` which gives the exit code of EVERY command in a pipeline, not just the last one. This would let us know exactly which command failed.

## Solution

1. Execute shell commands with `executable='/bin/bash'` instead of default `/bin/sh`
2. Wrap commands to capture PIPESTATUS after execution
3. Parse the pipeline to identify which stage contains grep/rg/etc.
4. Only treat exit 1 as "no match" if the failing command IS grep/rg

## Design Decisions

- **Bash requirement**: PIPESTATUS is bash-specific. We accept this dependency since bash is available on virtually all systems where pflow runs.
- **Deferred after stderr check**: The simpler stderr check (Task 109) handles 95%+ of cases. PIPESTATUS is the "complete" solution if edge cases become a problem in practice.
- **Parse pipeline stages**: Need to split command by `|` and map positions to PIPESTATUS indices. Must handle quoted strings containing `|`.

## Dependencies

- Task 109: Stderr-Based Smart Error Handling — Should be implemented first as the simpler solution

## Implementation Notes

### PIPESTATUS Capture (Verified Working)

```python
wrapper = f'''
set -o pipefail
{command}
__PSTAT=("${{PIPESTATUS[@]}}")
echo ""
echo "__PIPESTATUS__:${{__PSTAT[*]}}"
'''

result = subprocess.run(
    wrapper,
    shell=True,
    executable='/bin/bash',
    capture_output=True,
    text=True
)
```

### Pipeline Analysis (Verified Working)

```python
def analyze_failure(command, pipestatus):
    parts = [p.strip() for p in command.split('|')]

    for i, code in enumerate(pipestatus):
        if code != 0:
            cmd_name = parts[i].split()[0]
            is_grep = cmd_name in ('grep', 'rg', 'ag')

            if is_grep and code == 1:
                continue  # grep exit 1 = no match, OK
            else:
                return "error"  # Real failure

    return "no_match"  # Only grep-like commands returned 1
```

### Test Results (From Investigation)

| Scenario | PIPESTATUS | Result |
|----------|------------|--------|
| `grep notfound \| cat` | [0, 1, 0] | no_match ✓ |
| `grep hello \| sed fails` | [0, 0, 1] | error ✓ |
| `grep notfound` | [0, 1] | no_match ✓ |
| `grep \| grep \| cat` | [0, 0, 1, 0] | no_match ✓ |

### Edge Cases to Handle

1. **Quoted pipes**: `echo "a|b" | grep a` - simple split breaks
2. **Subshells**: `(cmd1 | cmd2) | cmd3` - nested pipes
3. **Command substitution**: `echo $(cmd | cmd)` - embedded pipes

### Files to Modify

- `src/pflow/nodes/shell/shell.py`:
  - Add `_wrap_command_for_pipestatus()`
  - Add `_parse_pipestatus()` to extract from stdout
  - Add `_parse_pipeline()` to split command into stages
  - Add `_analyze_pipeline_failure()`
  - Modify `exec()` to use bash and wrapper
  - Modify `post()` to use PIPESTATUS analysis

## Verification

1. All existing shell node tests pass
2. New tests for PIPESTATUS scenarios:
   - `grep notfound | cat` → success (no match)
   - `grep hello | sed 's/bad//'` → failure (sed error)
   - `grep | false` → failure (this is the edge case stderr check misses)
3. Test script from bug report passes: `scratchpads/test-grep-stdin-bug.sh`
4. Performance: measure overhead of PIPESTATUS capture

## Related Files

- Bug report: `scratchpads/shell-grep-stdin-exit-code-bug.md`
- Test script: `scratchpads/test-grep-stdin-bug.sh`
- Shell node: `src/pflow/nodes/shell/shell.py`
- Investigation notes: This task was created after extensive investigation in conversation
