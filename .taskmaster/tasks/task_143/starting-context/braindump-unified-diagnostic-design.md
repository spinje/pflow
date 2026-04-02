# Braindump: Task 143 — Unified Diagnostic System

## Where I Am

Design phase complete. Task spec and research document written. No implementation started. The user explicitly said "Done!" after #212 was fixed in PR #217, and we shifted to creating the task spec for #143. This is a handoff for implementation.

## User's Mental Model

This user thinks in terms of **top 10% codebases** — they repeatedly asked "what would the top 10% of codebases similar to this one implement?" They don't want incremental patches. They want the structurally correct solution even if it's more work.

Key phrases they used:
- "we should prioritize simplicity of the final code, not how easy it is to get there"
- "errors, warnings, all outputs should be tailored for AI agents and actionable"
- "the hard part is verifying and testing not the actual implementation"
- "the implementer will have to create a vast array of baseline outputs to compare against"

Their unstated priority: **agent actionability**. Every diagnostic output should tell an AI agent what's wrong and what to do about it. This isn't just a refactor — it's a UX redesign for AI consumers. The `suggestion` field on every Diagnostic is the manifestation of this.

They think about this as a **compiler diagnostic system** (rustc, eslint, mypy). One type, one severity field, one render function. They explicitly rejected incremental approaches twice — first when we proposed doing warnings first then errors (they said "I think B is the right call"), then when we proposed phasing the implementation (they agreed to do it all at once).

## Key Insights

### The conversation evolved through 4 distinct phases

1. **Started at issue #204** — "lets discuss gh issue 204" — which was already fixed. This was about understanding the problem space.
2. **Expanded to related issues** — #209 (warnings lost), #212 (duplicate sections). We mapped the full problem surface.
3. **Pivoted to architecture** — The user pushed past "fix the warning pipeline" to "what's the right diagnostic system?" This is where the unified Diagnostic type emerged.
4. **Scoped as one task** — User decided errors AND warnings in one pass, because baseline capture is the real cost.

### Why Option 3 won over Option 1

There was an agent (in another branch, the cache control PR #216) that recommended Option 1 (just delete the early display, keep two warning fields). The user brought that analysis to me. I agreed Option 1 was valid incrementally but Option 3 (unified field) was the right end state. The user's response was the pivotal moment: "so you will be doing option 3 along with the other work here in this session?" — they wanted the full solution, not the incremental fix. PR #216 ended up doing Option 1 (deleted early display) plus the ValidationWarning slim-down, which sets up Option 3 for this task.

### The error unification was NOT originally planned

The original scope was warnings only. The user asked "Should errors and warnings be consolidated at some point?" and I explained the rustc/eslint pattern. They then decided to include errors: "I think we should do warnings AND errors." Their reasoning: "we would need extensive baseline comparisons for 2 times either way." This doubled the scope but the user is comfortable with it.

### The `context: dict` decision

I initially proposed a typed `context` field. The user asked "what is the correct way here?" for top 10% codebases. I researched: rustc/eslint/mypy don't use grab-bags. But pflow's enrichment data (HTTP status, shell stderr, MCP errors) is genuinely heterogeneous. The Sentry pattern (clean message + optional context bag) was the best fit. The user accepted this without pushback.

## Assumptions & Uncertainties

ASSUMPTION: `format_for_cli()` methods can be fully replaced by Diagnostic rendering. I said "the conversion must produce Diagnostics whose rendering via `format_diagnostic()` is equivalent." But `UserFriendlyError.format_for_cli(verbose)` has a `verbose` parameter that gates technical details. The implementing agent needs to figure out how verbosity flows through the Diagnostic system. Possibly via context, possibly via a display parameter.

ASSUMPTION: The trace collector's `set_warnings()` interface can be updated to accept Diagnostics. I noted this in the research doc but didn't verify what the trace collector does with warnings — it might serialize them to JSON for the trace file. The Diagnostic type needs to be JSON-serializable.

ASSUMPTION: `generate_validation_suggestions()` output maps cleanly to `Diagnostic(severity=INFO)`. These suggestions are currently derived from error messages (pattern matching on error strings). They might need the original error Diagnostics as input instead of raw strings.

UNCLEAR: The exact JSON output shape for the `diagnostics` array. We said "backwards-incompatible change is acceptable" but didn't design the exact shape. The implementing agent needs to decide: flat `{"severity": "error", "message": "...", "suggestion": "...", "node_id": "...", "source": "...", "context": {...}}` or something else?

UNCLEAR: How `format_diagnostic()` handles errors with rich context vs. simple warnings. A warning is one line. An error with shell details, API response, and available fields is 15+ lines. One function handles both? Or `format_diagnostic()` for the header and separate helpers for context rendering (keeping the existing `_display_api_error_response` etc.)?

NEEDS VERIFICATION: The `_exception_to_errors()` helper functions in `error_output.py` (lines 190-270) — I noted they exist but the research agents didn't read the full implementations. The implementing agent should read `_workflow_validation_to_errors`, `_output_resolution_to_errors`, `_mcp_error_to_errors`, `_user_friendly_to_errors`, `_markdown_parse_to_errors`, `_schema_validation_to_errors`, and `_workflow_not_found_to_errors` before writing `exception_to_diagnostics()`.

NEEDS VERIFICATION: Whether `ValidationResult.suggestions` is actually useful as `Diagnostic(severity=INFO)` or if it's display noise. The suggestions are things like "Check template syntax: ${node.output}" — they might be more confusing than helpful for agents.

## Unexplored Territory

UNEXPLORED: **Diagnostic serialization for trace files.** The trace collector (`WorkflowTraceCollector`) receives warnings and writes them to JSON trace files (`~/.pflow/debug/workflow-trace-*.json`). If it currently expects dicts, it needs to handle Diagnostic objects. The trace file format might need updating.

UNEXPLORED: **How `format_execution_errors()` changes.** This function deep-copies error dicts, sanitizes them, and adds execution state. With Diagnostics, it needs to: (1) serialize Diagnostics to dicts, (2) sanitize context fields, (3) still add checkpoint/execution/metrics. The research doc says "it stays but changes input type" but the exact interface wasn't designed.

CONSIDER: **The `determine_error_category()` function** in `executor_service.py`. It pattern-matches on error message strings to determine category. With Diagnostic, category comes from the conversion, not from message parsing. But `build_error_list()` still needs it for runtime errors where the category isn't known from the exception type. Read this function before implementing.

CONSIDER: **Error count in JSON output.** Currently `_format_from_result()` derives a summary: `"Workflow execution failed (N errors)"`. With Diagnostics, the count is `len([d for d in diagnostics if d.severity == ERROR])`. But the `"error"` key in JSON is a summary string, not a Diagnostic. How does this work?

MIGHT MATTER: **The `__execution__` internal key** in shared store. `_extract_error_info()` reads from `shared_store.get("__execution__", {})` to get `failed_node` and `error_message`. This is the runtime error path for node failures. The implementing agent should read `_extract_error_info()` in `executor_service.py`.

MIGHT MATTER: **The `generate_validation_suggestions()` function** in `core/validation_utils.py`. It currently takes `errors: list[str]` and produces suggestion strings by pattern matching. With Diagnostics, it might take `list[Diagnostic]` instead. But suggestions are supposed to become INFO-level Diagnostics themselves. Circular dependency? The suggestions need to be generated from error Diagnostics, then added to the diagnostics list.

MIGHT MATTER: **Performance of convenience properties.** `result.errors` as `[d for d in self.diagnostics if d.severity == ERROR]` creates a new list on every access. If any hot path calls `result.errors` multiple times, this could be a concern. Probably fine for pflow's scale but worth noting.

UNEXPLORED: **The `--report` flag.** `generate_report()` in `core/trace_report.py` produces markdown reports from execution results. If it reads `result.errors` or `result.warnings`, it needs updating. We didn't check this.

UNEXPLORED: **The execution cache.** `core/execution_cache.py` stores execution results. If it serializes `ExecutionResult` including errors/warnings, the serialization format changes. The cache might need clearing/migration — though with no users, this is low risk.

## What I'd Tell Myself

1. **Start with baseline capture.** The user emphasized this repeatedly. Before touching any code, capture output from every path. This is the verification foundation. Without it, you can't prove the refactor didn't regress.

2. **The research document has the exact code.** Don't re-research. Read `.taskmaster/tasks/task_143/research/implementation-reference.md` — it has every change site with line numbers and current code. The task spec has the requirements and design decisions.

3. **The hardest part is `exception_to_diagnostics()`.** 13 exception types, each with different fields, two current conversion sites (`_exception_to_result` in runner, `_exception_to_errors` in error_output) that produce slightly different dict shapes. Unifying these into one function that handles all types correctly is the critical path.

4. **The display layer is the most test-sensitive.** ~130+ tests assert on exact text format. Even changing `"• node_id (warning):"` to `"• [node_id] warning:"` would break tests. The format should stay close to current for warnings. For errors, the enrichment display (shell details, API response, MCP errors) must be pixel-perfect.

5. **Don't try to refactor the display code AND unify the data type in the same pass.** Unify the data type first, keep display functions accepting Diagnostic, keep the output looking the same. THEN simplify display code in a follow-up if desired. The user said "Display consolidation is a follow-up."

6. **The user never commits/pushes without being explicitly asked.** They have a strong preference for reviewing changes locally first. Don't commit anything.

## Open Threads

- The user mentioned display consolidation (success/failure paths sharing display code) as a future follow-up. Not in this task's scope.
- We discussed the `⚠ Workflow completed with N warnings` status indicator. The implementation needs to count warnings in the diagnostics list and adjust the status line. The current `_display_workflow_completion_status()` has a `has_stderr_warnings` parameter — the new code adds a `has_diagnostics_warnings` check.
- `ValidationResult.suggestions` becoming `Diagnostic(severity=INFO)` was a late addition. The `generate_validation_suggestions()` function needs to be studied — it might need to take Diagnostics as input instead of error strings, or a wrapper converts the output.

## Relevant Files & References

**Task documents (READ FIRST):**
- `.taskmaster/tasks/task_143/task-143.md` — full spec with all requirements and design decisions
- `.taskmaster/tasks/task_143/research/implementation-reference.md` — exact current code at every change site

**Key source files (in order of importance for implementation):**
- `src/pflow/execution/result.py` — ExecutionResult, ValidationResult (change field types)
- `src/pflow/execution/runner.py` — the biggest change file (exception conversion, warning extraction, result construction)
- `src/pflow/cli/error_output.py` — second conversion boundary (pre-runner exceptions)
- `src/pflow/execution/executor_service.py` — runtime error extraction + enrichment
- `src/pflow/cli/workflow_errors.py` — error text display (reads from context instead of top-level dict)
- `src/pflow/cli/main.py` — merge site deletion, validation result display
- `src/pflow/cli/workflow_output.py` — warning display, status line
- `src/pflow/mcp_server/services/execution_service.py` — MCP merge site, warning formatting, error text
- `src/pflow/execution/formatters/success_formatter.py` — warning display in MCP text path
- `src/pflow/execution/formatters/error_formatter.py` — sanitization, execution state
- `src/pflow/runtime/template_validation/utils.py` — ValidationWarning (to be replaced)
- `src/pflow/core/markdown_parser.py` — parser warning sites
- `src/pflow/core/exceptions.py` — PflowError hierarchy
- `src/pflow/core/user_errors.py` — UserFriendlyError hierarchy

**Issues:**
- #209 (parser warnings lost) — fixed by this task
- #204, #212 — already fixed, provided context for this task

**PRs:**
- PR #216 — established current state (ValidationWarning slim, cache opt-out)
- PR #217 — duplicate section detection

## For the Next Agent

**Start by** reading the task spec (`task-143.md`) and research document (`research/implementation-reference.md`) completely. They contain everything: requirements, design decisions, exact code at every change site, import analysis, test impact.

**Don't bother** re-researching the codebase — the research agents already did thorough searches across 5 parallel sessions. The research doc has the results.

**The user cares most about**: (1) agent-actionable output — every Diagnostic must have a suggestion, (2) no display regressions — baseline capture before implementation, (3) simplicity of the final code — one type, one list, one render function.

**Implementation order suggestion**: Define `Diagnostic` type → update `ExecutionResult`/`ValidationResult` → convert warning producers → convert error producers (runner + executor_service) → create shared `exception_to_diagnostics()` → update display code (CLI + MCP) → thread parser warnings → update tests. Run `make test` at each boundary.

**The user's style**: They want to review and discuss before you implement. They'll likely want to see the plan and approve it. They never want you to commit without being told. They value honest assessment over optimistic promises. If something is harder than expected, say so.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
