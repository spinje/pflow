# Task 22 Review: Named Workflow Execution (Unified Resolution, Run Prefix, Single-Token Guardrails)

## Executive Summary
We delivered a unified, intuitive CLI experience for executing workflows by name or file path, removed the `--file` flag, added workflow discovery commands, and hardened error UX. We also implemented run-prefix handling and single-token guardrails to prevent accidental planner invocations. The result is simpler code, predictable behavior, and faster feedback for users.

## Implementation Overview

### What Was Built
- Unified workflow resolution (`resolve_workflow`) for saved names and file paths (including `~`, absolute/relative, and case-insensitive `.json`).
- `pflow workflow` command group with `list` and `describe` for discovery.
- Removal of the `--file` flag; direct file paths now “just work”.
- Improved error UX: clear JSON syntax errors, permission/encoding messages, and helpful “did you mean?” suggestions.
- Run prefix handling: `pflow run …` is transparently normalized.
- Single-token guardrails: prevent accidental planner calls for ambiguous one-word inputs; provide targeted hints.
- Cross-platform path heuristics and parameter key validation.

### Implementation Approach
- Deleted ~200 lines of complex routing and replaced with a small set of helpers and a single resolution path.
- Followed “clear heuristics first, planner last” to avoid incidental AI usage.
- Extracted helpers in `main.py` to keep complexity under ruff’s threshold and improve readability.

## Files Modified/Created

### Core Changes
- `src/pflow/cli/main.py` - Unified resolution, run-prefix preprocessing, single-token hints/guardrails, error UX, parameter key validation; refactors for complexity.
- `src/pflow/cli/main_wrapper.py` - Subcommand routing (ensures `workflow` group is recognized before catch-all).
- `src/pflow/cli/commands/workflow.py` - New discovery commands (`workflow list`, `workflow describe`) with JSON/human output.

### Test Files
- `tests/test_cli/test_workflow_resolution.py` - New coverage for resolution, run-prefix, parameter typing, and UX assertions.
- `tests/test_cli/test_main.py` - Updated expectations for removed `--file`, new error messages, and single-token behavior.
- Multiple CLI/integration tests updated to use file paths directly and reflect improved messages (metrics, e2e, outputs, save).

## Integration Points & Dependencies

### Incoming Dependencies
- CLI entry (`workflow_command`) is the user’s primary interface; `main_wrapper` routes subcommands.

### Outgoing Dependencies
- `pflow.core.workflow_manager.WorkflowManager` - `exists`, `load_ir`, `list_all` for saved workflow resolution.
- `pflow.runtime.compile_ir_to_flow` and validators - unchanged contracts used by `execute_json_workflow`.
- `pflow.registry.Registry` - IR validation and execution require registry to be present.

### Shared Store Keys
- No new shared store keys introduced. Existing keys used by runtime/output handling remain unchanged.

## Architectural Decisions & Tradeoffs

### Key Decisions
- Unified resolution over multiple code paths → reduces bugs and maintenance.
- Remove `--file` flag → users specify paths or names directly (MVP simplification).
- Single-token guardrails → conserve planner calls; ensure intentional AI usage.
- Run-prefix normalization → frictionless UX for users used to `run` commands.
- Case-insensitive `.json` and `os.sep`/`os.altsep` → robust cross-platform behavior.

### Technical Debt Incurred
- None significant; extracted helpers keep complexity within limits. Planner heuristics remain minimal by design (intended for MVP).

## Testing Implementation

### Test Strategy Applied
- Behavior-first CLI tests with `CliRunner` to assert user-visible output and exit codes.
- Unit-style tests for resolution function; integration-style tests for discovery and execution flows.
- Hardened tests for error messages and parameter typing; reduced brittle exception-based assertions.

### Critical Test Cases
- Saved-name vs. file-path vs. not-found resolution.
- JSON syntax error with line/column pointer.
- Permission/encoding errors for files.
- Parameter inference (bool/int/float/list/dict/string) and invalid key validation.
- Single-token guardrails and run-prefix handling.

## Unexpected Discoveries

### Gotchas Encountered
- Many tests depended on `--file`; removing it required broad updates and new expectations.
- Single-word inputs were unintentionally routed to the planner; this was a UX footgun and required a new guardrail policy.

### Edge Cases Found
- `.JSON` vs `.json` and Windows-style paths; both now work.
- Keys with invalid Python identifiers; now validated early with actionable errors.

## Patterns Established

### Reusable Patterns
- Heuristic-first resolution with early normalization (strip `run`, identify paths/extensions) before falling through to planner.
- Friendly CLI error pattern with targeted hints and suggestions.

### Anti-Patterns to Avoid
- Parallel routing paths to the same execution function; centralize through a single resolution function instead.

## Breaking Changes

### API/Interface Changes
- `--file` flag removed.
- Stdin JSON workflows are not accepted as workflow IR.

### Behavioral Changes
- Single-token generic inputs no longer trigger planner; they produce fast not-found/hints.
- Improved and standardized error outputs for JSON/permission/encoding issues.

## Future Considerations

### Extension Points
- Optional “quoted single word forces planner” mode if desired (e.g., `pflow "analyze"`).
- Workflow aliases and versioning could plug into the same resolution hook.
- URL-based workflows (http/https) detection as an additional resolution branch.

### Scalability Concerns
- None immediate; CLI flow is synchronous and intentionally simple for MVP. Planner latency remains the dominant factor and is only used when needed.

## AI Agent Guidance

### Quick Start for Related Tasks
- Read `src/pflow/cli/main.py` (helpers near resolution block), then `src/pflow/cli/commands/workflow.py` for discovery behavior.
- Keep planner usage intentional: multi-word or explicit parameters suggest NL planner; single tokens should be explicit names or show hints.
- When adding new inputs, enforce validation where close to user input is best (before compilation).

### Common Pitfalls
- Re-introducing multiple routing paths. Always route through the unified resolver.
- Breaking cross-platform path/extension detection; rely on `os.sep`/`os.altsep` and `.lower().endswith(".json")`.
- Making tests depend on internal exceptions. Prefer exit codes and output assertions.

### Test-First Recommendations
- Add CLI tests for any new user-visible behavior first (error messages, flags, discovery outputs).
- For planner-related features, decouple tests from external services by mocking planner entry.

## User Interaction Guide (What Users Do Now)

### Run Saved Workflows
```bash
pflow my-workflow                  # Executes saved workflow by name
pflow my-workflow.json             # .json extension is stripped automatically
```

### Run from File Path (No --file Needed)
```bash
pflow ./workflow.json              # Relative path
pflow /tmp/workflow.json           # Absolute path
pflow ~/workflows/analysis.json    # Home path
pflow my-workflow.JSON             # Case-insensitive extension
```

### Pass Parameters to Workflows
```bash
pflow process-data input=data.csv format=parquet
# Types are inferred: true/false, numbers, JSON lists/objects
```

### Discover Saved Workflows
```bash
pflow workflow list                # Human-readable list
pflow workflow list --json         # JSON output for tooling
pflow workflow describe my-flow    # Inputs/outputs/example usage
```

### Natural Language (Planner)
```bash
pflow "summarize the file report.txt"  # Multi-word → planner
pflow analyze input=data.csv            # Has params → planner
```

### Run Prefix Convenience
```bash
pflow run my-workflow              # Same as: pflow my-workflow
pflow run ./workflow.json          # Same as: pflow ./workflow.json
pflow run "generate a changelog"   # Multi-word → planner
pflow run                          # Error: need to specify what to run
```

### Single-Token Guardrails (Fast Feedback, No Planner)
```bash
pflow workflows   # → “Did you mean: pflow workflow list”
pflow list        # → “Did you mean: pflow workflow list”
pflow help        # → “For help: pflow --help”
pflow abcdeasd    # → “Workflow 'abcdeasd' not found”
```

### Error UX Improvements
- Invalid JSON files show line/column and a caret pointing to the error.
- Unreadable files show a clear permission error.
- Non-UTF8 files show a decoding error with guidance.

---

*Generated from implementation context of Task 22*
