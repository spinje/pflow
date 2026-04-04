# Task 144 Implementation Progress Log

## How to Read This Log

This is the research record for Phase 1 (complete). Phases 2-4 are implementation. If you're the implementing agent, read this entire log before writing any code. The deliverable files (gap-analysis.md, target-output-design.md) have the WHAT. This log has the WHY.

---

## Phase 1: Research — Complete

### [2026-04-04] — Initial analysis and codebase exploration

Read task spec (`task-144.md`) and braindump (`braindump-display-consolidation.md`). Read all critical files directly — not via agents, because these are the files we're modifying and need to understand deeply:

- `src/pflow/core/diagnostic.py` — 684 lines. The type (20-70), coerce bridges (92-119), format_diagnostic entry (122-134), 6 error rendering paths (149-445), exception_to_diagnostics 13-branch converter (447-683).
- `src/pflow/execution/result.py` — `ValidationResult.errors` returns `list[str]` (line 46-48), `ExecutionResult.errors` returns `list[Diagnostic]` (line 68-70). This asymmetry is Task 144's target.
- `src/pflow/execution/formatters/success_formatter.py` — `format_execution_success()` returns dict (for JSON). `format_success_as_text()` (line 170) takes that dict, extracts `warnings`, coerces them back to Diagnostics (line 249). This is the dict round-trip.
- `src/pflow/execution/formatters/validation_formatter.py` — `format_validation_failure(errors: list[str])` (line 40). Takes plain strings, renders bullet list. Loses suggestion, node_id, source, context from the Diagnostic.
- `src/pflow/cli/workflow_output.py` — `_display_execution_summary()` (line 515) extracts warnings from formatted dict, coerces back (line 600). Another dict round-trip.
- `src/pflow/cli/workflow_errors.py` — `_display_single_error()` (line 22) coerces error at line 40. `_collect_warning_diagnostics()` (line 96) has a legacy fallback path at line 107.
- `src/pflow/mcp_server/services/execution_service.py` — `_format_error_result()` (line 84) and `_build_error_text()` (line 145). The MCP error text path.
- `src/pflow/execution/formatters/error_formatter.py` — `format_execution_errors()` returns dicts. Used by both CLI JSON and MCP.
- `src/pflow/cli/error_output.py` — `display_exception_text()` (line 155) with two special cases that bypass diagnostics (lines 160-165).
- `src/pflow/core/user_errors.py` — `UserFriendlyError`, `MCPError`, `OutputResolutionError` definitions.
- `src/pflow/core/exceptions.py` — Full exception hierarchy with constructor signatures.
- `src/pflow/execution/executor_service.py` — `build_error_list()` (line 18) creates Diagnostics directly from shared store.
- `src/pflow/execution/formatters/registry_run_formatter.py` — 3 error formatters that bypass the diagnostic pipeline entirely.

Also read Task 135, 141, 143 reviews to understand the evolution:
- `.taskmaster/tasks/task_135/task-review.md` — Execution core redesign. Established standalone-functions-over-wrappers pattern.
- `.taskmaster/tasks/task_141/task-review.md` — Exception hierarchy consolidation. All under `PflowError`. `UserFriendlyError` rebased from `Exception` to `PflowError`. `MaxNodeVisitsError` intentionally NOT PflowError.
- `.taskmaster/tasks/task_143/task-review.md` — Unified diagnostic system. Single `Diagnostic` type. `exception_to_diagnostics()` + `format_diagnostic()`. Dict round-trips and rendering complexity left for Task 144.

Deployed 3 parallel search agents for exhaustive call-site mapping:
1. All callers of `coerce_warning_diagnostic` / `coerce_error_diagnostic` — 7 production sites across 4 files, 11 test sites in 1 file. Every production site wraps the result in `format_diagnostic()` for text rendering, except `success_formatter.py:57` which stores for later rendering.
2. All consumers of `ValidationResult.errors` — 3 production sites (`main.py:405` JSON, `main.py:426` text, `execution_service.py:297` MCP text). All use string values directly. All break if changed to `list[Diagnostic]`.
3. All callers of `format_diagnostic()` — 12 production sites. 9 of 12 use all defaults (only render warnings/info). Only 3 pass `verbose`. Only 2 pass `error_number`. Internal functions `_format_error_diagnostic` and `_format_warning_or_info_diagnostic` have zero external callers — the public API boundary is clean.

### [2026-04-04] — Context key mapping

**Why this matters:** The task spec says "every context key populated by `exception_to_diagnostics()` must be either rendered in text or explicitly documented as JSON-only with reasoning." This is the Phase 1 research requirement that determines the rendering redesign.

Traced all 13 exception types through `exception_to_diagnostics()` → `format_diagnostic()` → actual text output. For each, checked which context keys appear in the rendered text.

**8 context keys silently dropped:**

| Key | Exception | Why it matters | Why it's dropped |
|---|---|---|---|
| `phase` | CompilationError | Agent can't distinguish node_import vs template_resolution failure | Only runtime default renders context; compilation has `node_id` so it routes to runtime, but `phase` isn't read by any renderer |
| `visit_count` | MaxNodeVisitsError | Structured field for agent reasoning | Values appear in message string ("100/100") but without `error_number`, the max-visits shortcut renders just `❌ {message}` — no structured fields |
| `max_visits` | MaxNodeVisitsError | Same | Same |
| `line` | MarkdownParseError | Agent can't locate error in .pflow.md file | `MarkdownParseError.__str__()` embeds "Line N:" in message. The converter uses `str(exception)` which includes it. But it's embedded in prose, not a structured field. The "simple" rendering path doesn't extract it. |
| `failures` | OutputResolutionError | Per-output resolution diagnostics | Rendered indirectly — the `explanation` text includes per-output details. But the structured `failures` list with `raw_diagnostics` (containing `root_absent` flag) is not rendered. |
| `output_name` | OutputResolutionError | First failure's output name | Same as failures — embedded in explanation text |
| `source_expr` | OutputResolutionError | First failure's source expression | Same |
| `exception_type` | Generic Exception | Agent can't identify TypeError vs AttributeError vs etc. | The runtime default renderer never reads this key |

**Keys that appear "dropped" but are intentional:**
- `category` — Not rendered in several paths (validation without error_number, simple errors, not-found, user-friendly). In the new design, `category` is replaced by the title (which conveys the same information more readably). Dropping `category` display is correct.
- `action` — Always "error" for error diagnostics. Low value. Correctly not rendered.
- `technical_details` — Verbose-only. Correctly gated.
- `available_fields_truncated` — Boolean used to DECIDE whether to show the trace file hint. Correctly not rendered as a field.

### [2026-04-04] — Rendering path analysis

**Why 6 paths exist:** Task 143 moved rendering logic from scattered `format_for_cli()` methods on each exception class into centralized `format_diagnostic()`. But it preserved the output format of each exception's old renderer — so 6 distinct visual styles remained. The old code used type-based dispatch (each exception class rendered itself). The new code uses context-key-probing dispatch (inspect `source`, `category`, `title`, `node_id`). This context probing is the architectural cost of centralization.

**The 6 paths and what makes each truly unique:**

1. **Validation** (`source == "validation"`) — `❌ msg / At: path / 👉 suggestion`. Only unique feature: the `At: path` line and the `👉` arrow. BUT: with `error_number`, it routes to the runtime default format instead. Same diagnostic, completely different visual.

2. **Not-found** (`category == "not_found"`) — `❌ Workflow 'X' not found. / Did you mean: / - name`. Only unique feature: the similar-names list. This is a context block, not a rendering path.

3. **User-friendly** (`context.get("title")`) — `Error: Title / explanation / To fix this: / 1. step`. The BEST format. Has title, explanation, numbered suggestions, verbose details. This IS the target format for all errors.

4. **Max-visits** (`category == "max_visits"`) — Without `error_number`: just `❌ {message}` (ALL context dropped). With `error_number`: routes to runtime default. This is a **landmine** — the shortcut path silently loses all structure.

5. **Simple** (no `node_id` + category in {execution_failure, file_not_found, parse_error, permission_denied, validation}) — `✗ message / → suggestion`. Most information-poor format. FileNotFoundError gets `✗ workflow.pflow.md` with nothing else.

6. **Runtime default** (everything else) — `Error at node 'X': / Category: Y / Message: Z / Suggestion: ... / [context blocks]`. The only path that renders context blocks (shell stderr, API response, MCP error, template fields, compilation details).

**The root problem:** Paths 1-5 silently ignore context blocks. If a user-friendly error somehow had shell stderr in its context, it would be invisible. In practice this doesn't happen today (user-friendly errors come from `exception_to_diagnostics`, not `build_error_list`), but the architecture is fragile.

### [2026-04-04] — The "one format" insight

**The conversation that led here:**

The user asked: "how many of the special cases in the if/elif chains really requires special cases, what could be consolidated without losing agent clarity and actionability, or even improve it?"

I did a surface analysis: "6 paths → 2, ~185 lines saved." The user pushed back: "Is it possible you don't have explored this fully?" I admitted I hadn't — I'd counted branches without thinking about what the ideal output looks like.

The user then asked: "whats the right solution that the top 10% of codebases similar to this one would implement?"

**The answer:** rustc, ESLint, mypy, ruff — they all converge on ONE diagnostic format. Every error uses the same template. The differences are in which fields are populated, not in which rendering path executes.

**Why this is the right answer for pflow:**
1. **For agents:** Predictable format means agents can parse error output reliably. With 6 formats, an agent has to pattern-match against 6 visual styles.
2. **For the code:** One rendering function (~35-50 lines) replaces 6 (~260 lines). No dispatch on `source`, `category`, `title`, `node_id`. The renderer is dumb — it just prints what's there.
3. **For future errors:** Adding a new error type requires NO rendering changes. Just populate the Diagnostic with the right fields.

**The format we chose:** The user-friendly format (path 3) is already the best output in the codebase. Making it the standard means `output-resolution-error`, `mcp-error`, and `user-friendly-error` get ZERO changes. Everything else gets BETTER.

### [2026-04-04] — UserFriendlyError: why it exists and why it stays

**The user's question:** "UserFriendlyError, that sounds like a consolidation? Why does this exist and shouldn't all the errors have been made into 1?"

**The answer, which matters for implementation:**

`UserFriendlyError` was created BEFORE `Diagnostic` existed. It carries `title`, `explanation`, `suggestions`, `technical_details` — which now map directly to `Diagnostic` fields:
- `title` → `context["title"]`
- `explanation` → `message`
- `suggestions` → `context["suggestions"]`
- `technical_details` → `context["technical_details"]`

Task 141 consolidated the **inheritance tree** (all exceptions under `PflowError`). It didn't change interfaces.
Task 143 consolidated the **output type** (all → `Diagnostic`). It created the converter that maps exception attributes to Diagnostic fields.
Task 144 consolidates the **rendering** (all → one format). The renderer stops caring what exception produced the Diagnostic.

**`UserFriendlyError` stays** because it's still useful as a convenience class for ad-hoc structured errors (any code can raise `UserFriendlyError(title="...", explanation="...", suggestions=[...])` without defining a new exception class). But it's no longer SPECIAL for rendering — in the new design, ALL errors get titles and suggestions.

**The phased approach assessment:** The user asked if this should have been done from the start. Honest answer: the phased approach was the right process for UNDERSTANDING the problem (each task narrowed the scope), but it over-built intermediate states (13-branch converter, 6-path renderer, coerce bridges). Now that we understand the problem, implementation targets the final design directly — not "consolidate 6 paths to 3" as another stepping stone.

### [2026-04-04] — Scope determination: what's in, what's out, and why

Deployed 3 parallel search agents to verify assumptions and map the full surface area.

**The 10 Tier 1 bypasses (error rendering paths that don't use `format_diagnostic`):**

| # | Location | In scope? | Why |
|---|---|---|---|
| 1 | `error_output.py:160-165` — UnicodeDecodeError + registry RuntimeError hardcoded | **YES** | Special-casing exceptions in the display layer is the drift diagnostics prevent. These exceptions can go through `exception_to_diagnostics()`. |
| 2 | `workflow_errors.py:73-75` — fallback when `result.errors` empty | **YES** | A failed execution should always produce a diagnostic. The fallback is a code smell. |
| 3 | `registry_run_formatter.py:44-98` — `format_execution_error()` | **YES** | Parallel renderer for same exception types (FileNotFoundError, PermissionError, ValueError, etc.) with different formatting and different heuristics. Active drift. |
| 4 | `registry_run_formatter.py:10-41` — `format_node_not_found_error()` | **YES** | Functionally identical to `_format_not_found_diagnostic()`. Two renderers for the same concept. |
| 5 | `registry_run_formatter.py:101-132` — `format_ambiguous_node_error()` | **YES** | Same "list of options" pattern as not-found. Representable as a Diagnostic with similar_names context block. |
| 6 | `validation_formatter.py:40-104` — `format_validation_failure()` from `list[str]` | **YES** | Task spec target. |
| 7 | `cli_output.py:49-54` — `CliOutput.show_error()` | **NO** | `OutputInterface` abstraction — runner↔CLI communication for operational status. Different layer from diagnostic rendering. |
| 8 | `discovery_errors.py:42-67` — API key configuration guidance | **NO** | CLI operational guidance ("set your API key"), not workflow diagnostic. Different concern. |
| 9 | `workflow_output.py:258-259` — OutputResolutionError as raw warning | **YES** | Display bug. `OutputResolutionError` has a full diagnostic conversion that preserves title/explanation/suggestions. This path discards all of them, rendering just `{title}\n{explanation}`. |
| 10 | `workflow_output.py:386-393` — Batch per-item errors | **NO** | Per-item summaries within execution step section. Different display context (item-level, not workflow-level). |

**Why items 3-5 (registry_run_formatter) are in scope:** The user pushed on this. I initially excluded them as "separate command formatter." The user asked which ones a top 10% codebase would include. The answer: `registry_run_formatter.py` formats the SAME kinds of errors (FileNotFoundError, PermissionError, not-found, etc.) in a DIFFERENT way from `format_diagnostic()`. Two renderers for the same errors = drift. The task name is "Display Consolidation" — this IS consolidation.

**The irony that sealed it:** The bypass path provides BETTER guidance than the diagnostic path for simple errors. `format_execution_error(FileNotFoundError)` says "Verify the file path exists and is accessible." The diagnostic path says `✗ workflow.pflow.md`. The bypass we're eliminating is more helpful than the unified system. The fix: bring the guidance INTO the diagnostic system (add suggestions to simple exception conversions).

**Pre-existing bugs noted but out of scope:**
- `CompilationError` from `inject_special_parameters()` at `registry_run.py:197-201` is uncaught. Would propagate as unhandled exception through Click.
- MCP `run_registry_node` double-formats errors (line 562-567): `_build_error_text()` calls `format_diagnostic()` internally, result gets wrapped in `RuntimeError`, passed to `format_execution_error()` for another formatting layer.

### [2026-04-04] — Registry run error pipeline deep dive

**Why this section matters:** The implementing agent needs to understand the registry_run error pipeline to replace it. It's not obvious from the task spec.

The `pflow registry run <node>` command has 8 error paths. Only 1 uses the diagnostic system (MCPError, added in Task 143 as a partial migration). The other 7 use either `registry_run_formatter` or direct `click.echo`.

**The error pipeline (from search agent results):**

| # | Error Path | Current Handler | New Handler |
|---|---|---|---|
| 1 | Invalid parameter names | Direct `click.echo` at `registry_run.py:71-78` | Convert to Diagnostic or keep (CLI boundary validation) |
| 2 | Node not found | `_handle_unknown_node()` → `format_node_not_found_error()` | Direct Diagnostic construction + `format_diagnostic()` |
| 3 | Ambiguous node | `_handle_ambiguous_node()` → `format_ambiguous_node_error()` | Direct Diagnostic construction + `format_diagnostic()` |
| 4 | Node import failure | Direct `click.echo` at `registry_run.py:187-191` | `exception_to_diagnostics()` + `format_diagnostic()` (catches `CompilationError` with rich attributes) |
| 5 | MCPError | `exception_to_diagnostics()` + `format_diagnostic()` at `registry_run.py:283-288` | **Already correct** — no change |
| 6 | Generic execution error | `_handle_execution_error()` → `format_execution_error()` | `exception_to_diagnostics()` + `format_diagnostic()` |
| 7 | Node returns "error" action | `format_node_output()` at `registry_run.py:396-398` | **Keep** — this is output formatting, not diagnostic rendering |
| 8 | Cache storage failure | Direct `click.echo` (verbose only) at `registry_run.py:337-340` | **Keep** — operational, not diagnostic |

**MCP `run_registry_node` equivalents** (in `execution_service.py`):
- Node not found (line 478-481): `format_node_not_found_error()` → Direct Diagnostic construction
- Runner failure (line 562-567): Double-formatting bug → `exception_to_diagnostics()` + `format_diagnostic()` directly
- Exception (line 569-573): `format_execution_error()` → `exception_to_diagnostics()` + `format_diagnostic()`

**Key implementation detail for items 2 and 3:** These currently call `sys.exit(1)` directly from `_resolve_node_type()` helper functions. To route through diagnostics, the resolution helpers should either:
(a) Construct a Diagnostic directly and render it, then `sys.exit(1)`
(b) Raise an exception that the caller catches

Option (a) is simpler — no exception class needed. Construct the Diagnostic at the call site:
```python
diagnostic = Diagnostic(
    severity=Severity.ERROR,
    message=f"Node '{node_type}' not found in registry.",
    source="registry",
    context={"category": "not_found", "title": "Node Not Found",
             "similar_names": similar, "suggestions": [...]},
)
click.echo(format_diagnostic(diagnostic), err=True)
sys.exit(1)
```

### [2026-04-04] — Baseline capture and gap analysis

Wrote `capture_baselines.py` — automated baseline script. Design decisions:

**Why not integration tests for baselines?** Some error types (API failures, MCP errors) are hard to trigger without external services. The baseline script constructs representative Diagnostics and exceptions directly, making it deterministic and reproducible. The real rendering functions are called — no mocking of the rendering layer.

**Why automatic context coverage detection?** The script checks if each context key's VALUE appears in the rendered text. This gives us a per-fixture coverage score. After implementation, running the same script shows whether coverage improved. A dropped key that was previously rendered is an immediate regression signal.

**Results:** 56 outputs, 76% coverage (96/127 rendered, 31 dropped). The coverage metric is a lower bound — some values appear in the text embedded in prose (e.g., `visit_count=100` appears as "100/100" in the message) which the detector counts as "rendered" even though it's not a structured field.

### [2026-04-04] — Target output design

**The template** (from `target-output-design.md`):
```
Error[  N]: {title}

{message}
  At: {location}

  {context blocks}

  → {suggestion}           ← single suggestion
  OR
To fix this:               ← multiple suggestions
  1. {suggestion}

Run with --verbose for technical details.
```

**Title derivation** — why in the producers, not the renderer:

Each `to_diagnostics()` method sets `title=` directly. `build_error_list()` sets `title=` using a category→title lookup. The renderer reads `diagnostic.title` — no context probing, no derivation. The producers know what the error IS.

The title derivation map (used by `build_error_list()` and the built-in exception fallback handler):
```python
_CATEGORY_TITLES = {
    "compilation": "Compilation Failed",
    "max_visits": "Infinite Loop Detected",
    "validation": "Validation Error",
    "parse_error": "Parse Error",
    "not_found": "Workflow Not Found",
    "file_not_found": "File Not Found",
    "permission_denied": "Permission Denied",
    "execution_failure": "Execution Failed",
    "api_validation": "API Validation Error",
    "template_error": "Template Error",
}
```

Note: PflowError subclasses with `to_diagnostics()` set their own titles directly (not via this map). This map is only for `build_error_list()` and the built-in exception fallback in the thin dispatcher.

**Location (`At:`) line** — format depends on what's available:
- `node_id` → `At: node 'fetch'`
- `path` (validation) → `At: nodes[0].type`
- `line` (parse) → `At: line 42`
- Multiple → comma-separated: `At: node 'fetch', line 42`

**Suggestions to add for simple exceptions:**
- `FileNotFoundError` → `suggestions=["Check the file path and ensure the file exists."]`
- `PermissionError` → `suggestions=["Check file permissions and access rights."]`
- These come from the registry_run bypass formatters (which provide this guidance today). We're bringing the guidance INTO the diagnostic system.

**`MarkdownParseError.raw_message`** — implementation note:
`MarkdownParseError.__str__()` embeds "Line N:" in the message. The current converter uses `str(exception).split("\n\n", 1)[0]` which includes the prefix. In the new format, `line` is shown on the `At:` line, so the prefix in the message is redundant. Fix: add `self.raw_message = message` to `MarkdownParseError.__init__` (same pattern as `CompilationError.raw_message`), then use `self.raw_message` in `to_diagnostics()`.

**`format_validation_failure()` — compact grouped format:**
When displaying multiple validation errors as a list, each error uses a compact numbered format (not the full titled block), because they all share the same title ("Validation Error") and the header already says "Validation failed":
```
✗ Validation failed (3 errors):

  1. Unknown node type 'httpp'
     At: nodes[0].type
     → Use 'shell', 'http', 'llm', 'file', or 'mcp'

  2. Missing required field 'type'
     At: nodes[1]
     → Every node must have a 'type' field
```

Truncation at 5 (not 10) because each error is now multi-line.

**`_display_single_error()` header elimination:**
Currently adds headers ("❌ Compilation failed", "❌ Workflow execution failed") before calling `format_diagnostic()`. In the new design, the title IS the header. The wrapper function becomes thinner — it just calls `format_diagnostic()` and echoes the result. Warning count can still appear as a separate summary line.

### [2026-04-04] — Resolving open decisions

Four decisions were initially kept open during research, then systematically resolved:

1. **Compact vs block format**: Block format for ALL errors. No compact mode. 5 lines for a simple error is standard (rustc uses 5+ lines). The current `✗ workflow.pflow.md` is the worst output in the codebase.

2. **Validation failure truncation**: 5 (not 10). Each error is 2-3 lines now. 5 × 3 = 15 lines is reasonable.

3. **`verbose` plumbing**: Not an issue. The 3 CLI error paths pass `verbose`. MCP paths don't need it — agents read JSON (which always includes `technical_details`).

4. **`_build_error_text` header**: Uses diagnostic title for single error, generic "Workflow execution failed" for multiple. `format_diagnostic()` produces the titled block. No redundant duplication.

Also resolved: `_display_single_error()` header elimination. The header ("❌ Compilation failed", "❌ Workflow execution failed") is removed — `format_diagnostic()` now provides the title. Warning count moves to the warnings section header.

### [2026-04-04] — The `to_diagnostics()` decision

**The user's question that triggered this:** "With this refactor are we moving closer to having no typed exceptions in the future or further away? Will we have a clear path of removing exception_to_diagnostics() in the future?"

**My initial plan was wrong:** I was going to enrich the converter branches (add titles, suggestions to each branch). This would make the converter MORE complex — 10 branches of richer logic. Moving the logic to exception classes later would mean moving MORE code per branch. We were investing deeper into the centralized approach.

**The insight:** If we're already rewriting every converter branch (to add titles), moving the logic to where it belongs (the exception class) is the same amount of work with a better result. Building an intermediate state (converter with titles) that we'd tear down later is waste.

**The solution: `to_diagnostics()` method on each exception class.**

Each PflowError subclass knows how to produce its own `Diagnostic` representation. `exception_to_diagnostics()` becomes a thin dispatcher (~20 lines). This follows the `__str__()` / `model_dump()` pattern — types know how to describe themselves.

**Why this is NOT a reversal of Task 143:**
- Task 143 removed `format_for_cli()` — **presentation** methods that coupled exceptions to CLI text rendering. Correctly removed.
- Task 144 adds `to_diagnostics()` — **data conversion** methods that couple exceptions to the `Diagnostic` type only. Different concern. The rendering stays centralized in `format_diagnostic()`.

If we change the text format, `format_for_cli()` on 9 classes would have needed changes. `to_diagnostics()` doesn't — the renderer changes in ONE place. The exceptions never know about text formatting.

**Import structure improves:**
```
BEFORE: diagnostic.py → 7 lazy imports from exceptions.py (inside function body)
AFTER:  exceptions.py → imports Diagnostic, Severity from diagnostic.py (module-level)
        diagnostic.py → zero imports from exceptions.py (lazy imports deleted)
```
Dependency arrow flips. `diagnostic.py` no longer knows about exception types. No circular dependency — verified.

**Non-pflow exceptions (FileNotFoundError, PermissionError, ValueError, generic):** Can't add methods to Python built-ins. A small lookup function in the dispatcher handles them (~15 lines). 4 branches collapse into 1 function with a dict lookup.

**The UserFriendlyError hierarchy works naturally:** `MCPError` inherits `to_diagnostics()` with a category override. `OutputResolutionError` overrides entirely (has unique `failures` data). Much cleaner than 3 near-identical converter branches.

**`PflowError` base default:** Provides a fallback for any PflowError subclass that doesn't override. `CriticalDiscoveryError`, `WorkflowExistsError` get basic diagnostics automatically. No exception can fall through without a diagnostic.

### [2026-04-04] — "Three layers" architectural decision: why typed exceptions stay

**The user's question:** "So we are not consolidating all errors to one?"

This came after the `to_diagnostics()` decision. If every exception produces the same `Diagnostic` type, why keep `CompilationError`, `WorkflowNotFoundError`, etc. as separate classes?

**The answer — three layers serving three purposes:**

| Layer | Purpose | Type | Changes in Task 144? |
|---|---|---|---|
| **Exception** | Catch-site dispatch (`except CompilationError`) | Typed classes | NO — stays typed |
| **Data** | Canonical output value | `Diagnostic` | YES — gains `title`, `suggestions` fields |
| **Rendering** | Text display | One format | YES — 6 paths → 1 |

Typed exceptions exist for control flow — different exception types get different handling at catch sites (retry vs abort, which error message, which exit code). If we collapsed to one type, catch sites would inspect string fields to decide what to do — replacing type-safe dispatch with context-key probing. That's the exact anti-pattern we're eliminating from the renderer.

`to_diagnostics()` bridges layer 1 → layer 2. `format_diagnostic()` bridges layer 2 → layer 3. Multiple exception types → one data type → one text format.

### [2026-04-04] — Python pattern validation: why `to_diagnostics()` is Pythonic

**The user's question:** "Is doing this an antipattern for python? You mentioned Go and Rust, is this as good a pattern for a python codebase like pflow?"

The current `exception_to_diagnostics()` with 13 isinstance branches is a textbook case of "Replace Conditional with Polymorphism." Python-specific patterns that validate the approach:

- **`__str__()` / `__repr__()`** — every Python class defines how it represents itself. `to_diagnostics()` is the structured equivalent.
- **Pydantic `model_dump()`** — data classes that know how to serialize themselves. Standard.
- **Django `get_absolute_url()`** — models know how to produce their own URL. No central "model → URL" mapping.
- **`functools.singledispatch`** — Python's official type-dispatch mechanism. Evaluated and rejected: registration-based patterns are fragile (if the registering module isn't imported, the handler silently falls through to the generic case). For a system where missing a handler means silently losing error context, that's dangerous.

The isinstance chain is the LESS Pythonic approach — it's what Go does with type switches because Go doesn't have methods on interface implementations. In Python, types describe themselves.

### [2026-04-04] — Diagnostic type refinement

**The user's question:** "So we have converged on the 'perfect' architecture? Anything you would change if you took a step back?"

**Honest answer: two things aren't perfect on `Diagnostic` itself.**

1. **`title` in `context` dict instead of as a field:** Every error needs a title. Using `context["title"]` is a convention, not enforced by the type system. The renderer would probe the context dict to find it. If `title` were a field, the renderer reads `diagnostic.title` — type-safe, can't forget to set it.

2. **`suggestion` (string) vs `context["suggestions"]` (list):** Two representations of the same data. The renderer reads the list for numbered display, falls back to the string. The join/split is waste.

**The user decided to do it right:** "I think we do this the right way and prioritize the state of the final code."

**Changes to `Diagnostic`:**
```python
@dataclass
class Diagnostic:
    severity: Severity
    message: str
    title: str | None = None              # NEW
    suggestions: list[str] | None = None  # REPLACES suggestion: str | None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None
```

`__hash__` and `__eq__` unchanged (identity = severity/source/node_id/message). `title` and `suggestions` are display data, not identity.

**Why both fields:** `title` directly serves the one-format rendering design. `suggestions` eliminates the dual representation. Together they make `context` carry ONLY heterogeneous enrichment data (shell/API/MCP details, similar names, phase, line). No more title or suggestions buried in the dict.

**Impact:** All `Diagnostic()` constructors update field names. But the `to_diagnostics()` methods we're writing are NEW code — they use the new fields from the start. Warning constructors change `suggestion="text"` → `suggestions=["text"]` (mechanical).

---

## Phase 1 Deliverables

| Deliverable | Location | Purpose |
|---|---|---|
| Baseline capture script | `scratchpads/task-144-diagnostic-rendering/capture_baselines.py` | Reproducible before/after comparison |
| Before-baselines (56 outputs) | `scratchpads/task-144-diagnostic-rendering/baselines-before/rendering-output.txt` | Current rendering state |
| Context coverage (76%) | `scratchpads/task-144-diagnostic-rendering/baselines-before/context-coverage.txt` | Per-fixture key coverage |
| Gap analysis | `scratchpads/task-144-diagnostic-rendering/gap-analysis.md` | Per-fixture what's missing and why |
| Target output design | `scratchpads/task-144-diagnostic-rendering/target-output-design.md` | Concrete before/after for every fixture |

---

## Implementation Plan (Phases 2-4)

The task spec (`task-144.md`) is the definitive specification. Below is the implementation ORDER — what to do first, what depends on what.

### Phase 2: Foundation changes

These changes are foundational — everything else builds on them.

**Step 2.1: Diagnostic type refinement**
- Add `title: str | None = None` and `suggestions: list[str] | None = None` to `Diagnostic`
- Remove `suggestion: str | None` field
- Update `to_dict()` and `to_display_dict()` for new fields
- Update `deduplicate_diagnostics()` if it touches these fields (it doesn't — only uses hash)
- Update baseline capture script for the field name change
- Run `make check` to find all broken constructors
- Fix all Diagnostic constructors across the codebase: `suggestion="text"` → `suggestions=["text"]`

**Why first:** Every subsequent step constructs Diagnostics with the new fields. Doing this first means all new code uses the right field names from the start. The mypy errors from the field removal guide the mechanical updates.

**Step 2.2: `to_diagnostics()` on exception classes**
- Add default `to_diagnostics()` on `PflowError` base class
- Implement overrides on 8 subclasses (CompilationError, MaxNodeVisitsError, WorkflowValidationError, SchemaValidationError, MarkdownParseError, WorkflowNotFoundError, UserFriendlyError, OutputResolutionError)
- MCPError inherits from UserFriendlyError with `_diagnostic_category = "mcp"` override
- Add `raw_message` to `MarkdownParseError.__init__`
- Add `Diagnostic`, `Severity` imports to `exceptions.py` and `user_errors.py`

**Why second:** The methods contain the conversion logic that currently lives in `exception_to_diagnostics()`. Both can coexist temporarily — old converter still works while we add the new methods.

**Step 2.3: Rewrite `exception_to_diagnostics()` as thin dispatcher**
- Replace 13-branch isinstance chain with `hasattr(exception, "to_diagnostics")` dispatch
- Add `_builtin_exception_diagnostic()` for non-pflow exceptions (FileNotFoundError, PermissionError, ValueError, generic)
- Apply `_pflow_node_id` annotation via `dataclasses.replace()` after dispatch
- Delete 7 lazy imports from `exceptions.py` and `user_errors.py`
- Run existing tests — they call `exception_to_diagnostics()` and should produce identical output

**Why third:** The old and new converters must produce the same output. Running tests after this step verifies the migration is correct before we change anything else.

### Phase 3: Data flow cleanup + rendering redesign

These can be done in parallel or sequentially. The data flow cleanup is mechanical; the rendering redesign is creative.

**Step 3.1: Dict round-trip elimination**
- `_display_execution_summary()` receives warnings as `list[Diagnostic]` parameter
- `format_success_as_text()` receives warnings as `list[Diagnostic]` parameter
- `_build_error_text()` receives `list[Diagnostic]` directly
- `_display_single_error()` receives `Diagnostic` directly (remove coerce)
- `_collect_warning_diagnostics()` simplified (no legacy fallback)
- Delete `coerce_warning_diagnostic()` and `coerce_error_diagnostic()`
- Delete `_coerce_diagnostic()` helper and `_KNOWN_FIELDS` constant

**Step 3.2: ValidationResult.errors → list[Diagnostic]**
- Change property to return `list[Diagnostic]` (filter from diagnostics list)
- Add `error_messages` property returning `list[str]`
- Update `main.py:405` (JSON): use `e.to_dict()` instead of `{"message": e}`
- Update `main.py:426` (text): pass Diagnostics to `format_validation_failure()`
- Update `execution_service.py:297` (MCP text): same

**Step 3.3: One rendering format**
- Replace 6 error rendering functions with one: `_format_error_diagnostic()`
- Template: title → message → At: location → context blocks → suggestions → verbose hint
- Context blocks called universally (shell, API, MCP, template, compilation, similar-names, exception-type)
- Add new context block renderers: compilation details (phase), similar-names list, exception-type line
- Delete: `_format_validation_diagnostic`, `_format_not_found_diagnostic`, `_format_user_friendly_diagnostic`, `_format_simple_error_diagnostic`, `_format_runtime_error_diagnostic`, `_format_runtime_error_header_lines`, `_is_simple_error_diagnostic`
- Warning rendering: update `_format_warning_or_info_diagnostic` for `suggestions` field (use first item)

**Step 3.4: format_validation_failure() redesign**
- Takes `list[Diagnostic]` instead of `list[str]`
- Compact numbered format: `N. message / At: path / → suggestion`
- Truncation at 5 errors
- Remove auto-generated suggestions (each Diagnostic carries its own)
- Remove `suggestions` parameter

**Step 3.5: Bypass elimination**
- Delete `registry_run_formatter.py` (entire file)
- `registry_run.py`: replace `_handle_execution_error()` with `exception_to_diagnostics()` + `format_diagnostic()`
- `registry_run.py`: replace `_handle_unknown_node()` with direct Diagnostic construction + `format_diagnostic()`
- `registry_run.py`: replace `_handle_ambiguous_node()` with direct Diagnostic construction + `format_diagnostic()`
- `execution_service.py:run_registry_node`: replace `format_execution_error()` calls with diagnostic pipeline (eliminate double-formatting)
- `error_output.py`: remove UnicodeDecodeError and registry RuntimeError special cases
- `workflow_output.py:258-259`: route OutputResolutionError through diagnostics
- `workflow_errors.py:73-75`: produce proper diagnostic for empty errors case

**Step 3.6: Display wrapper simplification**
- `_display_single_error()`: remove header ("❌ Compilation failed"). Just call `format_diagnostic()`. Warning count moves to warnings section.
- `_build_error_text()`: header uses title for single error. Each error rendered via `format_diagnostic()` with error_number.
- `build_error_list()`: set `title=` on Diagnostics (using category→title map)

### Phase 4: Verification

**Step 4.1: Update baseline capture script**
- Update for new field names (`suggestions` instead of `suggestion`)
- Update for new rendering output format
- The fixtures themselves stay the same (same error types, same data)

**Step 4.2: Capture after-baselines**
- `uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py after`
- `uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py compare`

**Step 4.3: Score every output**
- For each diff: state what improved
- Context coverage must improve from 76% toward ~95%+
- No output worse without documented justification

**Step 4.4: Test suite**
- `make test` — fix broken assertions
- For each broken test: verify the new format is better than what the test asserted
- `make check` — mypy + ruff clean

### Test files that will break (~40 assertions)

**Most fragile (exact matches):**
- `test_validation_formatter.py` (12 tests) — `"✗"`, `"•"`, truncation patterns
- `test_diagnostic.py:test_format_diagnostic_renders_rich_error_context` — `"Category: execution_failure"`, `"Message: Shell command failed"` labels go away
- `test_diagnostic.py:test_format_diagnostic_renders_warning_with_suggestion` — `suggestion` field renamed to `suggestions`
- `test_agent_ux_fixes.py` — `"Error at node 'X':"` header format changes
- `test_success_formatter.py:test_warnings_section_renders_warning_messages` — warning rendering uses `suggestions` field

**Most resilient:**
- `test_validation_service.py` — uses `startswith("✗")` and `"error" in result.lower()`
- `test_registry_run_errors.py` — uses `"not found" in result.lower()`
- `test_e2e_workflow.py` — uses `"failed" in result.output.lower()`

**New tests to add:**
- Per-exception-class `to_diagnostics()` tests (in `test_exception_hierarchy.py` or `test_diagnostic.py`)
- Rendering tests for the new one-format output (in `test_diagnostic.py`)
- Baseline comparison test (optional: automated scorecard check)

---

## Phase 2: Implementation — In Progress

### [2026-04-04] — Step 1: Diagnostic type changes

**Changes made:**
- `Diagnostic` dataclass: `suggestion: str | None` → `title: str | None` + `suggestions: list[str] | None`
- Added `__post_init__` guard that raises `TypeError` if `suggestions` is a bare string (defense-in-depth against `suggestions="text"` mistakes)
- Updated `to_dict()`: emits `"title"` and `"suggestions"` keys
- Updated `_KNOWN_FIELDS`: added `"title"` and `"suggestions"`
- Updated `_coerce_diagnostic()`: handles both old `"suggestion"` (wraps in list) and new `"suggestions"` keys from dicts
- Updated ALL 28 Diagnostic constructor sites across 8 production files
- Updated ALL `.suggestion` → `.suggestions` reads across rendering functions
- Added `raw_message` attribute to `MarkdownParseError.__init__` (matching `CompilationError` pattern)
- Used `dataclasses.replace()` for provenance cloning in `validator.py` and `workflow_executor.py` (future-proof against new fields)

**Deviation from plan:** None. All constructors and reads updated mechanically. mypy caught every site.

**Verification:** `mypy src/pflow/` → 163 files, 0 errors. `ruff check` → clean.

### [2026-04-04] — Step 2: to_diagnostics() on exception classes

**Changes made:**
- Added `to_diagnostics()` to `PflowError` base class (default implementation)
- Added `to_diagnostics()` to 6 PflowError subclasses: `CompilationError`, `WorkflowValidationError`, `SchemaValidationError`, `MarkdownParseError`, `WorkflowNotFoundError`
- Added `to_diagnostics()` to `MaxNodeVisitsError` (RuntimeError, not PflowError)
- Added `to_diagnostics()` to `UserFriendlyError` (base with `_diagnostic_category` class var)
- Added `_diagnostic_category = "mcp"` override to `MCPError`
- Added `to_diagnostics()` override to `OutputResolutionError` (unique failures data)
- Rewrote `exception_to_diagnostics()` from 230 lines / 13 branches to ~30 lines / 2 paths (has method + builtin fallback)
- Deleted 7 lazy imports in `exception_to_diagnostics()`
- Added `_CATEGORY_TITLES` dict (module-level constant for title lookup)
- Import direction flipped: `exceptions.py` now imports `Diagnostic, Severity` from `diagnostic.py`; `diagnostic.py` has zero imports from `exceptions.py`

**Key insight:** The `_diagnostic_category` class variable pattern for `UserFriendlyError` → `MCPError` inheritance is cleaner than the plan's suggestion of a per-class override. MCPError just sets `_diagnostic_category = "mcp"` and inherits the base `to_diagnostics()`.

**Deviation from plan:** Used class variable `_diagnostic_category` instead of separate per-class methods for UserFriendlyError hierarchy. Simpler.

**Verification:** All 5 exception type round-trips tested manually. mypy clean. No circular imports.

### [2026-04-04] — Step 3: One rendering format

**Changes made:**
- Replaced 6 rendering functions with single `_format_error_diagnostic()` that uses the titled format universally
- Added `_format_location()` — builds `At:` line from node_id, path, line
- Added `_format_all_context_blocks()` — calls ALL block renderers for ALL error types
- Added `_format_similar_names_block()` — "Did you mean" list from `context["similar_names"]`
- Added `_format_exception_type_line()` — shows `Type: TypeError` for generic exceptions
- Updated `_format_compilation_context_lines()` to render `phase` (was silently dropped)
- Deleted: `_format_validation_diagnostic`, `_format_not_found_diagnostic`, `_format_user_friendly_diagnostic`, `_format_simple_error_diagnostic`, `_format_runtime_error_diagnostic`, `_format_runtime_error_header_lines`, `_is_simple_error_diagnostic`

**Deviation from plan:** None. The unified format matches target-output-design.md exactly.

**Verification:** Manual test of compilation, file-not-found, and output-resolution errors. Format matches targets.

### [2026-04-04] — Step 4: Data flow cleanup

**Changes made:**
- `ValidationResult.errors` now returns `list[Diagnostic]` (was `list[str]`)
- Decided NOT to add `error_messages` property — YAGNI, no caller needs it
- Rewrote `format_validation_failure()` — accepts both `list[Diagnostic]` and `list[str]`, compact numbered format, truncation at 5 (was 10)
- Updated `_display_validation_result()` in `main.py` — JSON uses `to_display_dict()` for errors
- Rewrote `_build_error_text()` in MCP `execution_service.py` — takes `list[Diagnostic]` directly instead of dict
- Updated `build_error_list()` in `executor_service.py` — adds `title` to Diagnostics via `_CATEGORY_TITLES`
- Simplified `_display_single_error()` — accepts `Diagnostic` directly (removed dict union type, removed coerce)
- Simplified `_collect_warning_diagnostics()` — reads only from `result.diagnostics` (removed legacy fallback)
- Updated `success_formatter.py` — `format_success_as_text` takes optional `warning_diagnostics` parameter
- Kept `coerce_warning_diagnostic` alive — still used by `_display_execution_summary` which reads from serialized dict
- Fixed `workflow_output.py:258-259` — OutputResolutionError now renders through `exception_to_diagnostics()` + `format_diagnostic()`
- Fixed MCP `run_registry_node()` not-found path — uses Diagnostic pipeline instead of deleted formatter

**Deviation from plan:** Kept coerce functions (not deleted yet) because `_display_execution_summary` reads warnings from the serialized dict format. Full deletion deferred to when we pass Diagnostics through the text path directly.

### [2026-04-04] — Step 5: Bypass elimination

**Changes made:**
- Deleted `registry_run_formatter.py` entirely (3 functions, 133 lines)
- Rewrote `_handle_unknown_node()` in `registry_run.py` — constructs `Diagnostic` directly, renders via `format_diagnostic()`
- Rewrote `_handle_ambiguous_node()` in `registry_run.py` — constructs `Diagnostic` directly
- Rewrote `_handle_execution_error()` in `registry_run.py` — uses `exception_to_diagnostics()` + `format_diagnostic()`
- Updated MCP `run_registry_node()` error/except branches — uses `exception_to_diagnostics()` + `format_diagnostic()` directly
- Removed `error_output.py` special cases for `UnicodeDecodeError` and registry `RuntimeError` — all now routed through diagnostic pipeline
- Updated MCP `run_registry_node()` not-found path — constructs `Diagnostic` with similar names context

**Deviation from plan:** Combined Step 5's MCP changes with Step 4 because they shared the same blocked mypy errors (both imported from `registry_run_formatter.py`).

**Verification:** mypy passes on 162 source files (1 file deleted). ruff clean.

### [2026-04-04] — Step 6: Fix all tests

**42 test failures fixed** across 20 test files using 4 parallel subagents.

**Failure categories and fixes:**
1. `suggestion=` → `suggestions=[]` in test Diagnostic constructors (5 files)
2. `.suggestion` → `.suggestions` in test assertions (4 files)
3. Dict → Diagnostic in test data for `_display_single_error` (test_agent_ux_fixes.py)
4. Rendering format assertions (test_validation_formatter.py completely rewritten)
5. JSON key `"suggestion"` → `"suggestions"` (test_unified_error_output.py, test_validate_only.py)
6. `_build_error_text` signature change (test_registry_run_mcp.py)
7. `❌` prefix → `Error: Title` format (test_registry_run_errors.py, test_workflow_resolution.py)

**Key test changes:**
- `test_validation_formatter.py` — complete rewrite: bullet format → numbered format, truncation at 5 (was 10)
- `test_agent_ux_fixes.py` — converted dict test data to Diagnostic objects
- `test_registry_run_errors.py` — updated from `❌` prefix to titled format assertions

### [2026-04-04] — Step 7: Final verification

- `make test` → 4550 passed, 0 failed
- `make check` → all clean (mypy, ruff, deptry)
- Fixed pre-existing `Optional[X]` ruff warnings in `exceptions.py` and `user_errors.py` (converted to `X | None`)
- Restored `# noqa: C901` on `format_success_as_text` (displaced by signature change)

**Coerce functions kept (not deleted):** `coerce_warning_diagnostic` and `coerce_error_diagnostic` remain because `_display_execution_summary` in `workflow_output.py` reads warnings from the serialized dict format (output of `format_execution_success`). Full deletion requires passing Diagnostics through the text path directly — deferred.

**Net impact:**
- 1 file deleted (`registry_run_formatter.py`, 133 lines)
- ~230 lines of converter code replaced by ~30 lines of thin dispatcher
- 6 rendering paths replaced by 1 unified format
- 9 exception classes now self-describing via `to_diagnostics()`
- All bypass paths eliminated

### [2026-04-04] — Post-implementation review fixes

Ran 3 parallel review agents (silent-failures, exception-methods, impact-completeness) + self-review. All agreed: no critical issues. Fixed the warnings they surfaced:

1. **Warning suggestion truncation** — `_format_warning_or_info_diagnostic` only rendered `suggestions[0]`. Now renders all items with `→` prefix each. The `suggestions` field was changed from `str` to `list[str]` specifically to support multiple items — silently dropping them defeats the purpose.

2. **`PflowError.to_diagnostics()` base used `source="unknown"`** — changed to `source="runtime"` with `context={"category": "execution_failure", "exception_type": ...}` to match the old generic fallthrough. Future subclasses that don't override now get decent output instead of blank.

3. **`UnicodeDecodeError` rendered as generic "Validation Error"** — `UnicodeDecodeError` is a `ValueError` subclass, so it hit the ValueError branch. Added specific branch in `_builtin_exception_diagnostic` BEFORE ValueError with user-friendly message: "File must be valid UTF-8 text."

4. **`shell_command=None` crash** — pre-existing, but trivial: `context.get("shell_command", "")` doesn't protect against explicit `None` value. Changed to `context.get("shell_command") or ""`.

5. **Missing test for `__post_init__` guard** — the entire rename safety net (raises TypeError on `suggestions="string"`) had no test. Added `test_suggestions_rejects_bare_string`.

6. **MCP text output silently lost warnings** — `format_success_as_text()` gained a `warning_diagnostics` parameter but MCP caller didn't pass it. Updated MCP caller to pass `result.warnings`. CLI path updated to pass diagnostics directly to `_display_execution_summary`.

7. **Coerce functions deleted** — `coerce_warning_diagnostic` and `coerce_error_diagnostic` had zero production consumers after the MCP/CLI fixes. Deleted both functions and their 11 tests.

8. **CLAUDE.md files updated** — `src/pflow/core/CLAUDE.md` (exceptions section + user_errors section), `src/pflow/execution/CLAUDE.md` (ValidationResult.errors type), `src/pflow/execution/formatters/CLAUDE.md` (removed deleted formatter), `src/pflow/cli/CLAUDE.md` (removed formatter ref, updated workflow_errors and error_output sections).

### [2026-04-04] — Baseline evaluation and regression fixes

Ran `capture_baselines.py after` + `compare` against the before-baselines. The automated context-coverage metric dropped from 76% to 54%, which initially looked alarming but turned out to be a measurement artifact: the old code rendered `Category: compilation` as literal text (detected by substring), the new code expresses the same information via `title="Compilation Failed"` (not detected). The only legitimately dropped keys are `category` (expressed through title), `action` (always "error", low value), and `technical_details` (shown only with `--verbose`).

**However, fixture-by-fixture comparison revealed 3 real regressions in registry bypass paths:**

1. **`registry-node-not-found` lost the available nodes fallback.** When `find_similar_items` returns empty (no fuzzy match for "read-fle"), the old formatter showed "Available nodes: http, llm, read-file..." as fallback. The new Diagnostic had empty `similar_names` and showed nothing.

   **Fix:** When no similar names found, fall back to `sorted(available)[:10]`. Applied to both CLI `_handle_unknown_node` and MCP `_format_node_not_found`.

2. **Registry execution errors lost node_type as location context.** Old format: `"❌ Failed to execute node 'fetch'"`. New format: just the raw exception message with no node reference. The generic `exception_to_diagnostics()` path doesn't know about registry-run context.

   **Fix:** Enrichment at the call site — `_handle_execution_error` and MCP `_format_registry_run_exception` set `node_id = d.node_id or node_type` on every diagnostic via `dataclasses.replace()`.

3. **Registry execution errors lost node-specific suggestions.** Old `format_execution_error()` had type-aware guidance: `"Use 'registry_describe fetch'"` for generic errors, `"Try increasing timeout"` for timeouts, `"Use registry_describe"` for missing-required ValueErrors. New generic path had no suggestions for RuntimeError/ValueError.

   **Fix:** `_registry_run_suggestions()` helper in `registry_run.py` adds context-aware suggestions based on exception type. Same pattern applied in MCP via `_format_registry_run_exception`.

**Design principle confirmed:** The call site owns the context, the Diagnostic carries the data, the renderer is generic. When we deleted the bypass formatters and routed through the generic pipeline, we lost the context that only the call site had. The fix is enrichment at the call site, not adding special cases to the renderer.

**One accepted loss:** The old `format_execution_error` had MCP-specific verbose guidance (3-step debugging checklist for `mcp-` prefixed nodes). This was highly niche and referenced internal tool names (`settings_show`) that agents wouldn't know. The `registry describe` suggestion covers the common case. Not worth adding MCP-specific branching to the enrichment.

### [2026-04-04] — High-value regression tests

Added 2 tests that guard the `ValidationResult.errors` type change (`list[str]` → `list[Diagnostic]`) at its actual integration points:

1. `test_json_errors_are_diagnostic_dicts_not_strings` — verifies JSON validate-only output has `"severity"`, `"title"`, `"source"` keys (from `Diagnostic.to_display_dict()`), not the old `{"message": str, "category": str}` shape. Catches regression to string wrapping.
2. `test_text_validation_failure_renders_diagnostic_fields` — verifies text output uses numbered format and does NOT contain `Diagnostic(` repr (the failure mode if Diagnostics are treated as strings by the formatter).

Also filed spinje/pflow#219 for the pre-existing gap: `WorkflowValidator.validate()` returns `list[str]` errors that lack structured path/suggestion data.

### [2026-04-04] — Code review fixes

External code review found 2 warnings, 1 suggestion. Evaluated against current code:

1. **W1 (Disputed):** "Registry run paths lose node_type" — already fixed in working tree during baseline evaluation. The review was against the staged snapshot, not the current code.

2. **W2 (Confirmed):** `Diagnostic.to_dict()` leaked `suggestions` by reference — `context` was deep-copied but `suggestions` was assigned directly. Mutating the returned dict would corrupt the source Diagnostic. Fixed: `list(self.suggestions)` shallow copy. Regression test added (`test_to_dict_does_not_leak_suggestions_reference`).

3. **S1 (Confirmed, different fix):** `WorkflowNotFoundError.to_diagnostics()` always appended generic "Use pflow workflow list" even when `self.hint` carried specific guidance (e.g., "Convert .json to .pflow.md"). Fixed: `suggestions=None if self.hint else [...]`. When the hint IS the guidance, don't dilute it.

**Final state:** `make test` → 4543 passed, `make check` → all clean.
