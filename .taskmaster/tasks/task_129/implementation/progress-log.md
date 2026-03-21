# Task 129: External File References — Implementation Progress Log

## Implementation Steps

1. ✅ Create `src/pflow/core/file_resolver.py`
2. ✅ Update IR schema for `_source_files`
3. ✅ Write unit tests
4. ✅ Insert into `compile_ir_to_flow()` + fix `workflow_executor.py`
5. ✅ Insert into validate-only paths
6. ✅ Fix MCP server `_pflow_workflow_file`
7. ✅ Write integration tests
8. ✅ Update CLAUDE.md documentation
9. ✅ Run `make test` and `make check`
10. ✅ Create manual testing plan and test workflows
11. ✅ Fix bugs found during testing
12. ✅ Add high-value tests for silent failure modes

---

## Design Phase — Analyzing the Problem

### Reading the Feature Request

Started by reading `scratchpads/prompt-file-references/README.md` — a feature request from an AI agent that had been building a real music-generation pipeline with pflow. The agent proposed `prompt_file:` for external prompts and `{{include}}` for shared prompt fragments.

### Reading the Real Workflows

Read all 4 workflow files from `~/projects/music-generation/workflows/` one at a time:

**`song-creator.pflow.md` (913 lines)** — the monster. 682 lines are prompt content across 8 LLM nodes. The specialist-reviews batch block (lines 383-605) has 5 specialist prompts (~213 lines total) inside YAML multi-line strings inside a markdown code fence. This is the worst editing experience in the project — maintaining YAML indentation for 220 lines of prompt content.

**`fetch-source.pflow.md` (140 lines)** — pure plumbing. Zero LLM nodes. Conditional branching, shell commands, MCP fallback. This workflow BENEFITS from the single-file property. Important counterexample: `prompt_file:` must be additive, never making workflows like this feel like they're missing something.

**`analyze-source.pflow.md` (166 lines)** — 5 analysis specialists in a YAML batch, same pattern as song-creator's review step. Bug found: first 4 specialists say "You are one of **four** specialists" but the musicality specialist says "five." There are 5 specialists.

**`lyrics-generator.pflow.md` (526 lines)** — the orchestrator. References 3 sub-workflows by relative path. The full pipeline does ~58 LLM calls per run. Has `build-file-list` — a **105-line Python code node** embedded in the workflow. This revealed that the problem isn't prompt-specific — code blocks have the same editing problem.

### Debunking the Agent's Claims

The agent's feature request overstated the DRY problem:

- **"The creative brief appears in 3 different prompts"** — Actually appears in 5, but as `${creative_brief}` template references. This IS the solution, not the problem. The template system already handles shared content.
- **"Shared PROMPT INSTRUCTIONS are copy-pasted across prompts"** — Overstated. The "Hard Rules" in write-lyrics and the specialist reviewer criteria overlap *conceptually* but are appropriately different content for different contexts. The actual literal copy-paste is the Core Concept block (3 lines × 5 occurrences) — too trivial to justify a feature.
- **"Each 40-60 lines"** for specialist prompts — Range is actually 31-61 lines.

**What's actually wrong**: File size (913 lines), navigation, editing ergonomics (YAML-indented prompts in batch blocks), and diff noise. NOT duplication.

### The YAML Batch Block — The Real Pain Point

The agent never specifically called out that the specialist prompts are multi-line YAML strings inside a `yaml batch` code block inside markdown. Editing these means maintaining YAML indentation for 220 lines. With `prompt_file:` in batch items, this:

```yaml
items:
  - focus: ai-tells
    prompt: |
      You are a specialist reviewer...
      [31 lines of YAML-indented prompt]
```

Becomes:

```yaml
items:
  - focus: ai-tells
    prompt: ./prompts/reviews/ai-tells.prompt.md
```

### Code Blocks Have the Same Problem

`build-file-list` in lyrics-generator is 105 lines of Python with no syntax highlighting, no linting, no test isolation. The feature was generalized from "prompt files" to "any code block parameter can reference a file."

### Cross-Workflow Patterns Discovered

- The **format code node** is duplicated across workflows (analyze-source:format, song-creator:format-reviews, lyrics-generator:prepare-evaluation) — same logic, different labels. Actual code duplication, but across workflow files not within one.
- The **specialist batch pattern** (N parallel LLM prompts → format node) appears in both analyze-source and song-creator. A higher-level pattern worth noting for future "workflow templates" thinking.

---

## Design Phase — Feature Decisions

### Killing `{{include}}`

The user asked: *"but isn't this solved by the template system?"* — and they were right. `${var}` with input defaults or a code node that reads files already handles shared content across prompts. `{{include}}` would be compile-time sugar for something the runtime already supports, solving a problem that barely exists in this project. **Killed.**

### The `prompt_file:` → Auto-Detection Progression

Three iterations, each driven by the user questioning assumptions:

1. **`prompt_file:` suffix** — 8 new param names, verbose. User: *"why do we want to use `_file`? and not just the original name like 'prompt' and write a file path instead?"*
2. **`file:` prefix** — `- prompt: file:./path`. Explicit but new syntax.
3. **Auto-detection** — same param name, detect by pattern + existence check. User: *"im leaning towards automatic, whats really the command where writing only a filepath would make sense?"*

For `command`, a bare file path as the entire YAML param value is not a real-world pattern. Users either use code blocks for inline commands or write `bash ./script.sh` (with args). **Auto-detection chosen.**

### Evaluating Additional Agent Feedback

Four more items from the agent were evaluated:

1. **"No prompt composition"** — Debunked. `${creative_brief}` IS composition.
2. **"No conditional logic in prompts"** — Dismissed. The actual prompt says *"If this is a 'wild_card' narrator, lean into..."* — the LLM handles conditionals in natural language just fine.
3. **"Can't vary node params per batch item"** — **Real limitation.** Different `reasoning_effort` or `model` per batch item isn't possible. Worth tracking as a separate feature.
4. **"YAML indentation anxiety"** — Already on our list, solved by this feature.

### The "Same Problem as Sub-Workflows" Insight

User spotted immediately: *"how are we currently handling saved workflows that use subworkflows? wouldn't that be the same problem?"* — and they were right. `pflow workflow save` copies a single file. Sub-workflow references (`- workflow: ./sub.pflow.md`) already break when saved. Adding prompt files doesn't create a new portability problem — it inherits an existing one. This reframed the discussion from "how to handle prompt file portability" to "solve the general workflow dependency problem once."

### Two-Task Split

- **Task 129** (this task): External file references — the editing ergonomics feature
- **Task 130**: Workflow bundling on save — fixes existing sub-workflow save bug AND supports new file references

### Save Model Decisions (for Task 130)

- **Always a folder** (`~/.pflow/workflows/{name}/`) — even for single-file workflows. Avoids two code paths, no migration from file to folder later.
- **`{name}.pflow.md` entry point**, not `WORKFLOW.pflow.md` — user pushed back on "tooling simplicity" argument, found it was negligible (one string concatenation vs one constant). Filename carries meaning in logs and error messages.
- **Preserve relative structure** on save — don't reorganize, don't enforce layout. What works locally works when saved.
- **Sub-workflows by name are NOT bundled** — shared dependencies referenced by name live in their own saved folders. Only file-path references are bundled.

### Identifying the Actual Problems

After all analysis, the distilled problem statement:

1. **Editing prompts/code inside a 913-line file is painful** — navigation, YAML indentation, diff noise
2. **Large code blocks have the same problem** — not just prompts
3. **Diffs can't isolate what changed** — prompt tweak buried in workflow file diff
4. **Saved workflows break with file dependencies** — existing bug with sub-workflows

Two features solve all four: external file references (this task) + workflow bundling (Task 130).

---

## Design Phase — Architecture Decisions

### Compile-Time vs Runtime Resolution

Initial instinct was runtime resolution because the batch wrapper processes items at runtime and the compiler doesn't parse batch YAML. User pushed back: *"we need to make sure we can validate everything as early as possible."*

Subagent research revealed the critical ordering: validation runs BEFORE node creation in the compiler. If file references resolved at runtime, template variables inside external files wouldn't be validated. In a 58-LLM-call pipeline, discovering a missing file mid-execution wastes time and money.

**Chosen: Compile-time resolution via IR transformation.**

### Where to Insert: Parser vs Compiler vs Separate Step

- **Parser**: Can't — `parse_markdown()` takes only `content: str`, no file path parameter. `MarkdownParseResult` has no source path field. Parser is deliberately path-unaware.
- **Compiler**: The compiler has `initial_params["_pflow_workflow_file"]` for the base path. Insert inside `compile_ir_to_flow()` between `_parse_ir_input()` and `_validate_workflow()`.
- **IR transformation step**: A pure function `resolve_file_references(ir_dict, base_dir)` that modifies the IR in place. Independently testable, compiler stays clean.

**Chosen: Pure IR transformation function, called inside `compile_ir_to_flow()` and in validate-only paths.**

### Research Findings That Changed the Architecture

Eight subagent runs verified critical assumptions:

1. **All compilation paths funnel through `compile_ir_to_flow()`** — CLI, MCP, nested workflows. Single insertion point covers all three.
2. **Validate-only paths DON'T call `compile_ir_to_flow()`** — need separate insertion in CLI `_handle_validate_only_mode()` and MCP `validate_workflow()`.
3. **IR mutations are fully visible to validation** — zero deep copies anywhere in the pipeline. Modifying the IR dict before `_validate_workflow()` means validation sees the file content. Confirmed.
4. **Batch config is a parsed Python dict in the IR** — not a raw YAML string. The parser already `yaml.safe_load()`s it. Inline batch items are inspectable at compile time.
5. **`_pflow_workflow_file` is NOT in `child_params`** — it's set in `child_storage` (line 340), not in the `child_params` passed to `compile_ir_to_flow()`. Need explicit injection.
6. **MCP server never sets `_pflow_workflow_file`** — relative paths in MCP-executed workflows fall back to CWD. Need to fix for saved and file workflows.
7. **Source line tracking barely exists** — `_source_lines` maps param→line number. Only `PythonCodeNode` reads it. Validation errors have zero source location. Added `_source_files` for provenance.
8. **Mutual exclusivity already handled** — existing `_check_param_code_block_conflicts()` catches same-name conflicts. Since we use the same param name (`prompt`, not `prompt_file`), no new check needed.
9. **Save paths should NOT resolve files** — they preserve original source for bundling (Task 130).

---

## Implementation Phase 1 — Core Module and Unit Tests

Created `src/pflow/core/file_resolver.py` with three functions:

- `is_file_reference(value)` — detection heuristic
- `resolve_file_references(ir_dict, base_dir)` — IR transformation
- `get_base_dir(initial_params)` — utility for base dir derivation

**Detection heuristic rules**: string, no `${`, no newlines, no spaces, no `://`, and either starts with `./`/`../` or contains `/` with recognized extension (.md, .txt, .py, .sh, .yaml, .yml, .json).

**YAML-aware substitution**: batch, output_schema, headers get `yaml.safe_load()`. Everything else gets raw text content. Matches the `is_yaml_config` distinction in `markdown_parser.py`.

**Batch handling**: `node["batch"]` is at the node top level (NOT in `node["params"]`). Parser routes it there at `markdown_parser.py:1008-1010`. If batch is a string file reference, reads and YAML-parses. If it's a dict with inline items, walks items.

44 unit tests written and passing on first attempt (except one URL edge case — added `://` exclusion).

## Implementation Phase 2 — Pipeline Integration

### Compiler insertion

Inserted `resolve_file_references()` in `compile_ir_to_flow()` between `_parse_ir_input()` and `_validate_workflow()`. Lazy import inside function body, matching existing compiler patterns. Wrapped `FileNotFoundError` in `CompilationError` for proper error handling.

### Workflow executor fix

Added `_pflow_workflow_file` injection into `child_params` in `WorkflowExecutor.exec()`. Guard: `if workflow_path and workflow_path != "<inline>"`. This ensures nested workflows resolve file references relative to their own location.

### Validate-only paths

Added file resolution in `_handle_validate_only_mode()` (CLI) and `validate_workflow()` (MCP server). Created `_resolve_file_refs_or_exit()` helper for reuse between validate-only and execution paths.

### MCP server fix

Set `_pflow_workflow_file` in `execute_workflow()` for "file" and "library" sources. Extracted into `_inject_workflow_file_path()` helper to avoid complexity warning.

## Implementation Phase 3 — Test Failures and Bug Discovery

First full test run: **39 failures** out of 4146. All caused by the file resolver incorrectly resolving params that contain file path VALUES.

### Bug 1: Non-dict nodes in IR (39→20 failures after combined fix)

`resolve_file_references()` called `.get()` on nodes that were strings (bad IR test cases). Fix: `if not isinstance(node, dict): continue`.

### Bug 2: `workflow` param resolved as file reference (the critical discovery)

The `workflow` param on nested workflow nodes (e.g., `- workflow: /tmp/child.pflow.md`) matched `is_file_reference()` because absolute paths contain `/` and end with `.md`. **The file resolver was reading the child workflow markdown and replacing the `workflow` param value with the full markdown content.** This silently broke nested workflow execution.

**Root cause**: The detection heuristic was applied to ALL params. But many params contain file-path VALUES (destination paths, references) that should NOT be inlined.

**First fix attempted**: Blocklist with `EXCLUDED_PARAMS = {"workflow"}`. This fixed nested workflows but `file_path` on write-file nodes, `url` on HTTP nodes, etc. also matched.

**Final fix**: Allowlist approach — `FILE_RESOLVABLE_PARAMS` containing only the 8 code-block-mapped params (prompt, code, command, source, batch, stdin, headers, output_schema). Only these params can be resolved as file references.

💡 **Key insight**: An allowlist is fundamentally safer than a blocklist. New node types with path-valued params won't accidentally be resolved. The allowlist matches exactly `_CODE_BLOCK_TAG_TO_PARAM` from the markdown parser.

⚠️ **Plan deviation**: The implementation plan specified `EXCLUDED_PARAMS = {"workflow"}` (blocklist). The real-world test suite revealed this was insufficient. The allowlist approach was not in the original plan.

### Bug 3: Shell command with path (20→1 failure)

`- command: touch /tmp/xxx/validate_only_proof.txt` matched because it contains `/` and ends with `.txt`. Fix: added `" " in value` check — strings with spaces are commands or prose, not file paths.

⚠️ **Plan deviation**: The space exclusion was not in the original detection heuristic design.

### Bug 4: `ctx` not in scope in `_perform_validation()`

The validate-only insertion initially referenced `ctx` in `_perform_validation()` which doesn't take `ctx`. The plan specified inserting in `_perform_validation()`. Moved to `_handle_validate_only_mode()` where `ctx` is available.

### Bug 5: Complexity warning in MCP execution_service

Adding `_pflow_workflow_file` injection pushed `execute_workflow()` past complexity limit (11 > 10). Extracted `_inject_workflow_file_path()` helper function.

### Bug 6: `CompilationError` constructor signature

Missing `message` positional argument and wrong type for `details` (str instead of dict). The plan didn't specify the exact constructor call.

### Bug 7: Example file broke existing test

`examples/file-references/batch-file-ref.pflow.md` with `- batch: ./config/reviewers.yaml` failed `test_all_pflow_md_files_parse` because the IR schema expects batch to be an object after parsing, but file resolution happens after parsing. Changed example to use inline YAML batch.

💡 **Insight**: There's a chicken-and-egg issue with batch file references and schema validation. The IR schema validates batch as an object, but a batch file reference is a string at parse time. Resolution converts it to an object, but only at compile time. This means `- batch: ./reviews.yaml` as a YAML param won't pass standalone IR validation (without compilation). This is acceptable — schema validation is a subset of compilation validation.

## Implementation Phase 4 — Manual Testing

Created `examples/file-references/TESTING.md` with 9 manual test scenarios. A `code-implementer` subagent executed all tests.

### Bug 8: Execution path didn't resolve files before pre-execution validation

The most important bug found by manual testing. `execute_json_workflow()` called `_validate_before_execution()` on the raw IR before `compile_ir_to_flow()` ran. File resolution only happened inside `compile_ir_to_flow()`. So pre-execution validation saw `- prompt: ./prompts/analyze.prompt.md` as a literal string and reported "input never used" because `${input}` was inside the unresolved file.

The `--validate-only` path worked because we added file resolution there. The execution path was missing it.

**Fix**: Added `_resolve_file_refs_or_exit()` call before `_validate_before_execution()` in `execute_json_workflow()`.

⚠️ **Plan deviation**: The plan explicitly said `_validate_before_execution()` did NOT need insertion because it's "followed by `compile_ir_to_flow()` which handles it." This was wrong — pre-execution validation runs BEFORE compilation and fails on unresolved file references. The plan's reasoning was flawed: idempotency means the second resolution is harmless, but the FIRST resolution (before validation) is essential.

Note: File resolution now runs twice for the execution path (pre-validation + compilation). The function is idempotent so this is correct but slightly wasteful. Acceptable tradeoff.

## Implementation Phase 5 — Loose Ends and High-Value Tests

### Batch items didn't check `FILE_RESOLVABLE_PARAMS`

The node-level param resolution correctly filtered by allowlist, but inside batch items, ALL keys were checked. A batch item with `{"file_path": "./data.md", "prompt": "inline"}` would incorrectly resolve `file_path`. Fixed by adding the same `FILE_RESOLVABLE_PARAMS` check in `_resolve_batch_file_references()`.

### Two high-value tests for silent failure modes

After implementation was "complete," we stepped back and asked: what could actually break in production that isn't covered? Two scenarios:

1. **Template variables in external files invisible to template wrapping** — If file resolution runs but template detection doesn't see the resolved content, `${var}` in external files becomes literal text at runtime. A silent bug with no error message. **Test**: `test_compile_ir_detects_templates_in_file_content` — compiles a workflow through `compile_ir_to_flow()` where `${fetch.stdout}` is inside an external file. If file resolution fails silently, template validation reports the error.

2. **Nested workflow file references resolve from wrong directory** — If the `_pflow_workflow_file` injection breaks, a child workflow's `./prompts/foo.md` resolves from the parent's directory or CWD. **Test**: `test_nested_workflow_file_refs_resolve_from_child_dir` — verifies correct resolution AND verifies failure from wrong directory.

Both use shell nodes to avoid LLM API key dependency while testing the same compilation code path.

---

## Final State

- **4151 tests pass** (57 new: 46 unit + 11 integration)
- **All checks pass** (ruff, ruff-format, mypy, deptry)
- **9/9 manual tests pass** (after Bug 8 fix)

### Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `src/pflow/core/file_resolver.py` | ~210 | Core module |
| `tests/test_core/test_file_resolver.py` | ~380 | Unit tests |
| `tests/test_core/test_file_resolver_integration.py` | ~370 | Integration tests |
| `examples/file-references/TESTING.md` | ~130 | Manual test plan |
| `examples/file-references/*.pflow.md` | ~80 | Test workflows |
| `examples/file-references/prompts/*` | ~10 | Test prompt files |
| `examples/file-references/scripts/*` | ~5 | Test script files |
| `examples/file-references/config/*` | ~5 | Test config files |

### Files Modified

| File | Change |
|------|--------|
| `src/pflow/runtime/compilation/compiler.py` | Insert `resolve_file_references()` + `CompilationError` wrapping |
| `src/pflow/runtime/workflow_executor.py` | Inject `_pflow_workflow_file` into child params |
| `src/pflow/cli/main.py` | `_resolve_file_refs_or_exit()` in validate-only + execution paths |
| `src/pflow/mcp_server/services/execution_service.py` | File resolution in validate + `_inject_workflow_file_path()` in execute |
| `src/pflow/core/ir_schema.py` | Added `_source_files` field to node schema |
| `src/pflow/core/CLAUDE.md` | Documented new module |

---

## Key Decisions (Full List)

### Design Phase

1. **No `{{include}}`** — template system already handles reuse via `${var}`
2. **Auto-detection over `_file` suffix** — simpler, zero new concepts. User drove this simplification.
3. **Compile-time resolution, not runtime** — catch errors before execution starts
4. **IR transformation function, not parser change** — parser stays path-unaware
5. **Two-task split** — file references (129) + bundling (130). Independent value delivery.
6. **Always-folder for saved workflows** (Task 130 decision) — avoids two-class system
7. **`{name}.pflow.md` over `WORKFLOW.pflow.md`** — "tooling simplicity" was overstated

### Implementation Phase

8. **Allowlist over blocklist** for resolvable params — the plan's blocklist was insufficient. Allowlist (`FILE_RESOLVABLE_PARAMS`) is safer against new node types with path-valued params.
9. **Space exclusion** in detection heuristic — distinguishes file paths from shell commands. Not in original plan.
10. **URL exclusion** (`://`) — prevents `https://example.com/path.md` matching. Not in original plan.
11. **`_resolve_file_refs_or_exit()` helper** — reused between validate-only and execution paths. Reduces complexity.
12. **`resolve_file_references` runs twice** in execution path — idempotent, tradeoff for clean code separation
13. **Shell nodes in compilation tests** — avoids LLM API key dependency while testing the same code path

## Plan Deviations

| Plan said | Reality | Why |
|-----------|---------|-----|
| `EXCLUDED_PARAMS = {"workflow"}` blocklist | `FILE_RESOLVABLE_PARAMS` allowlist | Blocklist insufficient — `file_path`, `url`, and many other params also contain path values |
| Detection: `./` or `/` + extension | Added: no spaces, no `://` | Shell commands and URLs matched the original heuristic |
| Insert in `_perform_validation()` | Insert in `_handle_validate_only_mode()` | `_perform_validation()` doesn't have `ctx` in scope |
| `_validate_before_execution()` doesn't need insertion | It does — Bug 8 | Pre-execution validation runs before compilation, sees raw file paths |
| No `_resolve_file_refs_or_exit()` helper | Needed for complexity limits | Both CLI paths need the same logic, extracted to avoid duplication and C901 |

## Patterns Worth Reusing

- **Allowlist for parameter handling**: When a feature only applies to specific param types, use an allowlist not a blocklist. Safer against future additions.
- **IR transformation as a pure function**: `resolve_file_references(ir, base_dir) → ir` is independently testable, composable, and doesn't require changes to the parser or compiler internals.
- **Idempotent transformations**: Making the resolver idempotent (resolved content doesn't re-match the heuristic) means it can safely run multiple times in different code paths.
- **Test with wrong inputs, not just right ones**: The nested workflow test verifies both correct resolution AND failure from wrong directory. The failure case catches the actual regression.

## Known Limitations

- **Batch file reference as YAML param** (`- batch: ./reviews.yaml`): Passes compilation but fails standalone IR schema validation (schema expects batch to be an object, not a string). Only an issue if someone runs `validate_ir()` without `compile_ir_to_flow()`.
- **File resolution runs twice** in execution path: once before pre-execution validation, once inside `compile_ir_to_flow()`. Correct but slightly wasteful.

---

## Phase 6 — Code Review and Follow-up

Two code reviews were conducted (saved in `scratchpads/task-129-code-review.md` and `scratchpads/task-129-staged-review-2026-03-21.md`). 9 findings total, 5 confirmed, 2 disputed, 2 deferred-then-upgraded.

### Review Fixes (completed in main session)

**Fix 1 — Batch early return bug (Critical):** Both reviews found that `_resolve_batch_file_references()` returned early after B1 (string→YAML), never running B2 (walk items). This meant batch files like `./reviews.yaml` with `prompt: ./prompts/reviewer-a.md` inside items would never resolve the item-level file refs in a single pass. The integration test masked this by calling the resolver twice. Fix: removed `return`, changed to `batch = node["batch"]` fall-through. Updated test to single call.

**Fix 2 — Path traversal vulnerability (Critical):** `_read_file` resolved `../../../etc/passwd` without containment check. Added `is_relative_to(base_dir.resolve())` guard. Two new tests: `test_path_traversal_blocked` and `test_path_traversal_dot_dot_in_middle`.

**Fix 3 — `batch` dead code in `FILE_RESOLVABLE_PARAMS` (Warning):** Removed `"batch"` from the set since the parser routes batch to `node["batch"]` (top-level), not `node["params"]`. Added comment explaining batch is handled separately.

**Fix 4 — Tests (Suggestion):** Improved `test_idempotent` to verify `_source_files` stability. Integration test now calls resolver once (matching production).

### Disputed Findings

- **Lazy imports in hot path**: Reviewer suggested moving `file_resolver` imports to top-level. Disputed — the compiler package uses lazy imports as a consistent pattern (documented in `compilation/CLAUDE.md`). Matching existing patterns > marginal perf.
- **batch-file-ref.pflow.md example**: Reviewer said it should demonstrate the feature. Disputed — the example lives in `examples/` which is parsed by `test_all_pflow_md_files_parse` (schema validation without compilation). A `- batch: ./reviews.yaml` string would fail schema validation since batch must be an object at parse time.

### Review Follow-up Items (being implemented by code-implementer agent)

Two items from the review were initially deferred but upgraded after discussion about pflow's agent-first error UX:

**Item 5 — `_source_files` provenance in template error messages:**

The `_source_files` dict was being written to nodes but never read. Template validation errors say "in node 'X', param 'prompt'" but don't mention the source file. For an agent, knowing WHICH FILE to edit is critical.

Research findings:
- Template extraction (`_extract_all_templates`) produces a flat `set[str]` — loses the template→node association
- Error formatting functions in `path_validation.py` receive `workflow_ir` (full node dicts with `_source_files`)
- The dispatcher `create_template_error()` at `path_validation.py:318` is the single point all errors flow through
- Solution: add `_find_template_source_file(template, workflow_ir)` helper that scans nodes for the template string, checks `_source_files` for the containing param. Append `"Loaded from file: ./prompts/foo.md"` to error messages via `_append_source_file_hint()` wrapper in `create_template_error()`.

**Item 6 — MCP inline workflow clear error:**

When an agent sends inline markdown with file references to MCP, there's no file path to resolve from. Currently falls back to CWD (server's working directory) — either reads wrong files silently or gives a confusing "file not found" error referencing the wrong directory.

Research findings:
- `_resolve_and_validate_workflow()` discards `source` as `_source` (line 46) — need to surface it
- `execute_workflow()` calls `resolve_workflow()` twice (lines 46 and 256) — redundant, can be eliminated
- `validate_workflow()` also discards source
- Solution: add `has_file_references(ir_dict)` scanner to `file_resolver.py` (reuses `is_file_reference` without file I/O), surface `source` from `_resolve_and_validate_workflow()` as 4th return element, check for file refs in inline/direct sources before resolution

Implementation plan at `/Users/andfal/.claude/plans/sequential-wishing-manatee.md`.

## Phase 7 — Review Follow-up Implementation

Both review follow-up items implemented and verified.

### Part A: File Provenance in Template Validation Errors

**`src/pflow/runtime/template_validation/path_validation.py`:**

Added three functions in a new "Source file provenance helpers" section:
- `_find_template_source_file(template, workflow_ir)` — scans nodes to find which external file a template variable came from via `_source_files` provenance
- `_search_params_for_source()` and `_search_batch_items_for_source()` — extracted from `_find_template_source_file` to satisfy C901 complexity limits
- `_append_source_file_hint(error, template, workflow_ir)` — appends `"\n  Loaded from file: ./path"` to error messages when applicable

Modified `create_template_error()` — all three return paths (node reference, path template, simple template) now pass through `_append_source_file_hint()`.

**Result**: Template errors for content loaded from external files now include the source file path:
```
✗ Static validation failed:
  • Template variable ${nonexistent_node.output} has no valid source - ...
  Loaded from file: ./prompts/bad-prompt.md
```

### Part B: MCP Inline Workflow File Reference Error

**`src/pflow/core/file_resolver.py`:**

Added `has_file_references(ir_dict)` — scans IR for file references without resolving them. Returns list of detected reference strings. Helper functions `_collect_param_file_refs()` and `_collect_batch_file_refs()` extracted for complexity.

**`src/pflow/mcp_server/services/execution_service.py`:**

Three changes:
1. `_resolve_and_validate_workflow()` return type changed from 3-tuple to 4-tuple — surfaces `source` (was discarded as `_source`)
2. Removed redundant second `resolve_workflow(workflow)` call in `execute_workflow()` (line 256 in original)
3. Added `_check_inline_file_references()` module-level helper — called in both `execute_workflow()` and `validate_workflow()` for `source in ("content", "direct")`

**Result**: Inline workflows with file references get a clear, actionable error:
```
Workflow contains file references (./prompts/system.md) but was provided as inline content.
File references require a workflow file path to resolve relative paths from.
Save the workflow to a file and reference it by path or saved name.
```

### Tests Added

| File | Tests | What they verify |
|------|-------|-----------------|
| `tests/test_core/test_file_resolver.py` | `TestHasFileReferences` (7 tests) | `has_file_references()` scan: detects prompt/batch/batch-item refs, ignores non-resolvable params, handles empty IR |
| `tests/test_core/test_file_resolver_integration.py` | `TestTemplateErrorSourceFileProvenance` (2 tests) | Error from external file includes `"Loaded from file: ./prompts/bad.md"`; inline error does NOT include hint |

### Manual Verification

7 manual tests run, all passing:

| # | Test | Result |
|---|------|--------|
| 1 | Template error from external file shows `Loaded from file: ./prompts/bad-prompt.md` | Pass |
| 2 | Inline template error does NOT show file hint | Pass |
| 3 | Simple (non-dotted) template from external file shows hint | Pass |
| 4 | MCP `validate_workflow` with inline content + file refs → clear error | Pass |
| 5 | MCP `execute_workflow` with inline content + file refs → ValueError | Pass |
| 6 | MCP inline workflow without file refs validates normally | Pass |
| 7 | Existing file-reference example workflows still validate | Pass |

### Final State

- **4161 tests pass** (9 new: 7 unit + 2 integration), 1 pre-existing failure (unrelated `test_shell_smart_handling`)
- **All checks pass** (ruff, ruff-format, mypy, deptry)
- **7/7 manual tests pass**

### Files Modified

| File | Change |
|------|--------|
| `src/pflow/runtime/template_validation/path_validation.py` | `_find_template_source_file()`, `_append_source_file_hint()`, modified `create_template_error()` |
| `src/pflow/core/file_resolver.py` | `has_file_references()`, `_collect_param_file_refs()`, `_collect_batch_file_refs()` |
| `src/pflow/mcp_server/services/execution_service.py` | 4-tuple return, removed redundant resolve call, `_check_inline_file_references()` |
| `tests/test_core/test_file_resolver.py` | `TestHasFileReferences` class (7 tests) |
| `tests/test_core/test_file_resolver_integration.py` | `TestTemplateErrorSourceFileProvenance` class (2 tests) |

### Test Value Assessment

After implementation, we evaluated whether any high-value tests were missing — specifically tests that could catch real bugs, not coverage optimization. Conclusion: the changes are narrow and well-covered. The riskiest change (4-tuple return from `_resolve_and_validate_workflow`) is covered by 350 existing MCP/validation tests. The provenance lookup (`_find_template_source_file`) has a graceful degradation mode — worst case is a missing hint, not wrong behavior. No additional tests warranted.

## Phase 8 — PR Review Fixes

PR #134 received automated code review from Claude. 8 findings evaluated:

- **2 disputed**: `ctx.exit(1)` not stopping execution (wrong — Click's `ctx.exit()` raises `SystemExit`), `get_path()` returning None (wrong — always returns `str`).
- **3 confirmed**: `yaml.YAMLError` not caught in CLI/compiler/MCP error handlers. Fixed by adding `yaml.YAMLError` to except clauses alongside `FileNotFoundError` in `_resolve_file_refs_or_exit`, `compile_ir_to_flow`, and MCP `validate_workflow`.
- **2 confirmed (minor)**: `./` prefix always-match behavior documented in `is_file_reference` docstring. Redundant `normalize_ir` import removed from integration test.
- **1 positive**: Test and documentation quality praised.

GitHub issue created: #133. PR: #134. Manual test plan executed by subagent: 11/11 pass.

## Phase 9 — Documentation Updates

Minimal docs updates for user-facing documentation and agent instructions:

- **`docs/reference/nodes/llm.mdx`** — Updated `prompt` param description to mention file paths. Added "External prompt file" example.
- **`docs/reference/nodes/shell.mdx`** — Updated `command` param description. Added "External script file" example.
- **`docs/reference/nodes/code.mdx`** — Updated `code` param description. Added "External code file" example.
- **`src/pflow/cli/resources/cli-agent-instructions.md`** — Added one line to syntax reference: agents now know `- prompt: ./path` works as an alternative to code blocks.

## Phase 10 — Final PR Review Fixes

Third review (`scratchpads/task-129-pr-review-2026-03-21.md`) found 3 issues, 2 confirmed, 1 disputed:

**Fix: Removed path containment check.** The `is_relative_to()` check in `_read_file()` rejected `../` paths, contradicting both `is_file_reference()` (which accepts `../`) and existing workflow ref behavior (no containment). Blocked legitimate layouts like `workflows/main.pflow.md` referencing `../prompts/shared.md`. Removed — pflow is a local CLI tool, users have full file system access. Tests rewritten from "traversal blocked" to "parent directory reference works."

**Fix: Guard non-dict params.** Malformed IR with `"params": "oops"` crashed with `AttributeError` before schema validation. Added `isinstance(params, dict)` guards in `resolve_file_references()` and `_collect_param_file_refs()`.

**Disputed: Spaces in file paths.** Reviewer noted `./my prompt.md` is silently ignored. Accepted limitation — the space check prevents shell commands matching (20 test failures without it). Paths with spaces in developer projects are rare. Documented in docstring.
