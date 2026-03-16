# Task 92 Review: Remove Planning Module and Repair System

## Metadata
- Implementation Date: 2026-03-16
- Branch: `refactor/remove-planning-and-repair`
- Pre-task PR: #121 (`core/workflow/` extraction)

## Executive Summary

Removed the gated planning module (~7,300 production lines, ~23,000 test lines) and repair system (~1,050 production lines). Replaced PocketFlow-based discovery nodes with plain functions returning typed dataclasses. Dropped direct `anthropic` SDK dependency. Fixed two pre-existing runtime bugs in error reporting exposed during the refactor. Net reduction: ~40,000+ lines. Final state: 4,067 tests pass, 0 skipped from planning/repair.

## Implementation Overview

### What Was Built

The original Task 92 spec proposed replacing the planner with an agent + MCP tools (Option 1). We implemented **Option 2** (remove entirely) with an enhancement: discovery features preserved as plain functions.

**Deviations from original spec:**
- No agent replacement built — the planner was removed, not replaced
- Discovery preserved as standalone functions instead of being removed with the planner
- A pre-task (`core/workflow/` extraction) was added that wasn't in any spec — emerged from discussion about where to put workflow discovery
- Two pre-existing runtime bugs in `executor_service.py` were fixed (API warning surfacing, MCP null error handling)

### Implementation Approach

Three-phase approach, each independently testable:

1. **Pre-task**: Extract `core/workflow/` subdirectory (46 files, 53 patch strings — pure mechanical refactor)
2. **Phase 1**: Relocate active dependencies out of `planning/`, create replacement discovery functions
3. **Phase 2**: Delete `planning/`, repair, gated code paths, dead tests, stale docs

Each phase was planned in detail via scratchpad documents (`scratchpads/planning-removal/00-03`) with exact file paths, line numbers, blast radius analysis, and verification checklists. Subagents executed the pre-task and Phase 1 from these specs. Phase 2 was done in the main conversation with subagents for code cleanup and the main agent for documentation.

## Files Modified/Created

### New Modules

| File | Purpose |
|------|---------|
| `src/pflow/core/llm_utils.py` | `parse_structured_response()` — generic LLM JSON→Pydantic parser. Extracted from `planning/utils/llm_helpers.py`. |
| `src/pflow/core/prompt_utils.py` | `load_prompt()`, `format_prompt()` — prompt file loading with strict variable validation. Adapted from `planning/prompts/loader.py`. |
| `src/pflow/core/workflow/discovery.py` | `discover_workflow()` → `WorkflowMatch` dataclass. Replaces `WorkflowDiscoveryNode`. |
| `src/pflow/core/workflow/context.py` | `build_workflows_context()` — formats saved workflows for LLM consumption. Extracted from `planning/context_builder.py`. |
| `src/pflow/core/workflow/prompts/discovery.md` | Workflow discovery prompt template. Moved from `planning/prompts/`. |
| `src/pflow/registry/discovery.py` | `discover_components()` → `ComponentSelection` dataclass. Replaces `ComponentBrowsingNode`. |
| `src/pflow/registry/context_builder.py` | `build_component_context()`, `build_nodes_context()` — node specs for discovery. Extracted from `planning/context_builder.py`. ~900 lines, ~20 functions extracted, ~7 dead functions dropped. |
| `src/pflow/registry/prompts/component_browsing.md` | Component browsing prompt template. Moved from `planning/prompts/`. |

### Deleted (~40,000 lines)

| Path | What |
|------|------|
| `src/pflow/planning/` (32 files) | Entire planning module |
| `src/pflow/execution/repair_service.py` | LLM-powered repair |
| `src/pflow/execution/workflow_diff.py` | Repair diff tracking |
| `src/pflow/cli/repair_save_handlers.py` | Repair save strategies |
| `tests/test_planning/` (68 files) | All planning/repair tests |
| 8 additional test files | Repair, planner flags, gated tests |
| `examples/runtime_feedback_demo.py` | Orphaned planning demo |
| `scripts/tools/test_prompt_accuracy.py` | Orphaned prompt test script |

### Significantly Modified

| File | What Changed |
|------|-------------|
| `src/pflow/execution/workflow_execution.py` | 642 → 83 lines. Removed repair loop, checkpoint resume. Now: validate → execute → return. |
| `src/pflow/cli/main.py` | ~3,978 → ~3,300 lines. Removed 13 planner functions, 7 CLI flags, `auto_repair` parameter threading, planner dispatch. |
| `src/pflow/core/metrics.py` | Removed planner fields (`planner_start`, `planner_end`, `planner_nodes`), `is_planner` parameter. |
| `src/pflow/runtime/instrumented_wrapper.py` | Removed `__is_planner__`, `__non_repairable_error__`, `__modified_nodes__` handling, `is_planner` threading. |
| `src/pflow/execution/executor_service.py` | Removed `repaired_workflow_ir` field, `_is_fixable_error()`. Fixed API warning surfacing and MCP null error bugs. |

### Bug Fixes (pre-existing, fixed during refactor)

| File | Bug | Fix |
|------|-----|-----|
| `executor_service.py:_extract_error_info` | API warnings in `__warnings__` were never surfaced as error messages — user saw generic "Workflow failed with action: error" | Check `__warnings__` as highest-priority error source before falling back to node-level errors |
| `executor_service.py:_extract_node_level_error` | MCP responses with `"error": null` produced `str(None)` = `"None"` as error message | Use `.get("error")` to skip falsy values |
| `executor_service.py:_extract_error_from_mcp_result` | Nested MCP payloads like `{"error": null, "data": {"error": "channel_not_found"}}` never unwrapped `data.error` | Added `data.error` unwrapping after top-level check |

## Integration Points & Dependencies

### Incoming Dependencies (what uses our new code)

| Consumer | Uses | Interface |
|----------|------|-----------|
| `cli/commands/workflow.py` | `discover_workflow()` | `WorkflowMatch` dataclass |
| `cli/registry.py` | `discover_components()`, `build_component_context()` | `ComponentSelection` dataclass, markdown string |
| `mcp_server/services/discovery_service.py` | `discover_workflow()`, `discover_components()` | Same dataclasses |
| `mcp_server/services/registry_service.py` | `build_component_context()` | Markdown string or error dict |
| `registry/smart_filter.py` | `parse_structured_response()` | Dict from Pydantic validation |
| `execution/formatters/node_output_formatter.py` | `smart_filter_fields_cached()` | Tuple of field tuples |

### Outgoing Dependencies (what our new code uses)

| Module | Depends On | Via |
|--------|-----------|-----|
| `core/workflow/discovery.py` | `llm` library, `WorkflowManager`, `build_workflows_context`, `parse_structured_response`, `prompt_utils` | `llm.get_model()` + `schema=` |
| `registry/discovery.py` | `llm` library, `Registry`, `build_nodes_context`, `build_component_context`, `build_workflows_context`, `parse_structured_response`, `prompt_utils` | Same pattern |
| `registry/context_builder.py` | `WorkflowManager`, `Registry` (lazy) | Direct imports |

### Prompt Files

| Prompt | Location | Variables | Used By |
|--------|----------|-----------|---------|
| `discovery.md` | `core/workflow/prompts/` | `{{discovery_context}}`, `{{user_input}}` | `discover_workflow()` |
| `component_browsing.md` | `registry/prompts/` | `{{nodes_context}}`, `{{workflows_context}}`, `{{user_input}}`, `{{requirements}}` | `discover_components()` |

Loaded via `core/prompt_utils.py:load_prompt(Path)` — strips YAML frontmatter and H1 header. `format_prompt()` enforces strict bidirectional variable validation (all provided vars must exist in template AND vice versa).

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|----------|-----------|----------------------|
| Plain functions over PocketFlow nodes | Discovery nodes were never composed in flows. Shared store ceremony added no value. Functions have explicit typed contracts. | Keep as PocketFlow nodes in new `discovery/` module — rejected as unnecessary complexity. |
| `core/workflow/` + `registry/` split | Component discovery operates on Registry data, workflow discovery operates on WorkflowManager data. Each lives next to the data it queries. | Single `discovery/` module — rejected because `discover_workflow` doesn't touch Registry. |
| Drop direct `anthropic>=0.75` | Only used by planning's custom Anthropic SDK wrapper. `llm-anthropic` plugin natively supports `schema=` for structured output. | Keep for version pinning — unnecessary, transitive dep handles it. |
| `build_planning_context` → `build_component_context` rename | Function has nothing to do with planning anymore. Name should reflect actual purpose. | Keep old name for backward compat — no external consumers, no BC needed. |
| Fix pre-existing API warning bugs | We removed the (dead) code that would have surfaced them. We own the execution path now. | Defer to follow-up — rejected by user ("why not fix now?"). |

### Technical Debt Incurred

- `generate_workflow_metadata()` in `save_service.py` is a stub returning `None`. If metadata generation is wanted later, it needs reimplementation without the planning module.
- `_auto_save_workflow()` and `_prompt_workflow_save()` dead code in `cli/main.py` survived initial Phase 2 pass — caught and deleted by code review. Lesson: "GATED" comments can cause agents to preserve dead code.
- `CriticalDiscoveryError` (renamed from `CriticalPlanningError`) is only used by `cli/discovery_errors.py`. Could be simplified to a plain exception, but the structured error fields (reason, original_error) are still useful.

## Testing Implementation

### Critical Test Cases

| Test | What It Validates |
|------|-------------------|
| `test_core/test_workflow_discovery.py::test_returns_not_found_when_no_workflows_exist` | Early return without LLM call when library is empty |
| `test_core/test_workflow_discovery.py::test_returns_not_found_when_workflow_missing_on_disk` | LLM says "found" but file doesn't exist → graceful degradation |
| `test_registry/test_component_discovery.py::test_workflow_names_from_llm_are_cleared` | LLM returns workflow_names but they're dropped (deliberate decision) |
| `test_cli/test_discovery_commands.py` (9 tests) | CLI integration — mocks at function level, verifies error handling and argument passing |
| `test_execution/test_api_warning_system.py::test_slack_mcp_channel_not_found` | End-to-end API warning detection for exact Slack MCP payload shape |

### Tests That Would Have Caught Bugs

The formatter data shape mismatch (Phase 1 C1 bug) was caught by manual testing, not unit tests. The test fixtures matched the formatter's expectations instead of production data. An integration test exercising `discover_workflow()` → `format_discovery_result()` with real `WorkflowManager.load()` data would have caught it immediately.

## Unexpected Discoveries

### Gotchas Encountered

1. **`patch()` strings are the silent killer.** After the `core/workflow/` extraction (46 files moved), 53 `monkeypatch.setattr("pflow.core.workflow_manager.X")` strings needed updating. These don't cause ImportError — they silently mock nothing. Always grep for string-based paths after module moves.

2. **`install_anthropic_model()` was already dead code.** The function `_install_anthropic_model_if_needed()` in `cli/main.py` was defined but never called — orphaned when the planner was gated. We assumed it was actively needed by the MCP server.

3. **All 3 context builder functions were needed, not just `build_planning_context`.** Initial analysis said only `build_planning_context()` was used by active code. Verification revealed the new discovery functions also need `build_nodes_context()` and `build_workflows_context()`.

4. **`__warnings__` surfacing was already broken.** The repair system's `_handle_non_repairable_error()` was the only code that surfaced API warnings as user-visible errors. Since `enable_repair=False` was always set, API warnings were lost in production even before our refactor.

5. **MCP responses with `"error": null` produce `"None"` strings.** `str(None)` in Python. APIs frequently include `"error": null` to indicate no error. Always use `.get("error")` for truthiness, not `"error" in dict`.

### Edge Cases Found

- Nested MCP payloads: `{"successful": true, "error": null, "data": {"ok": false, "error": "channel_not_found"}}` — the error is two levels deep. `_extract_error_from_mcp_result` now unwraps `data.error`.
- `build_component_context()` returns `str | dict` — returns error dict on failure (missing nodes). Callers must check `isinstance(result, dict)`.

## Patterns Established

### Reusable Patterns

**LLM-powered feature pattern** (use for any new LLM feature):
```python
from pflow.core.llm_utils import parse_structured_response
from pflow.core.prompt_utils import format_prompt, load_prompt

class MyResult(BaseModel):  # Pydantic schema for LLM output
    field: str

@dataclass(frozen=True)
class MyOutput:  # Typed return value
    field: str

def my_llm_feature(query: str, model_name: str | None = None) -> MyOutput:
    from pflow.core.llm_config import get_model_for_feature
    model_name = model_name or get_model_for_feature("discovery")
    prompt_path = Path(__file__).parent / "prompts" / "my_prompt.md"
    template = load_prompt(prompt_path)
    prompt = format_prompt(template, variables={"query": query})
    model = llm.get_model(model_name)
    response = model.prompt(prompt, schema=MyResult)
    result = parse_structured_response(response, MyResult)
    return MyOutput(field=result["field"])
```

**Prompt co-location**: Prompt `.md` files live in a `prompts/` subdirectory next to the module that uses them. Loaded via `Path(__file__).parent / "prompts" / "name.md"`.

### Anti-Patterns to Avoid

- **PocketFlow nodes for non-flow features.** Discovery nodes were PocketFlow nodes that were never composed in flows. The shared store ceremony, prep/exec/post lifecycle, and exec_fallback added complexity with zero benefit.
- **Delegating context-heavy docs to subagents.** CLAUDE.md updates require understanding WHY things changed. Implementer agents have no context and produce stale or incorrect documentation.
- **Test fixtures that match implementation instead of production data.** Fixtures should use the exact data shapes that production code produces, not the shapes the code under test expects.

## Breaking Changes

### Removed CLI Flags
`--trace-planner`, `--planner-timeout`, `--planner-model`, `--save/--no-save`, `--cache-planner`, `--auto-repair`, `--no-update`, `--generate-metadata`

### Removed Parameters
- `execute_workflow()`: `enable_repair`, `repair_model`, `resume_state`, `original_request`
- `record_node_execution()`: `is_planner`
- `_capture_llm_usage()`: `is_planner`
- `_handle_api_warning()`: `is_planner`

### Renamed
- `CriticalPlanningError` → `CriticalDiscoveryError`
- `build_planning_context` → `build_component_context`
- `ComponentSelection.planning_context` → `ComponentSelection.component_context`

### Removed from Shared Store
`__is_planner__`, `__non_repairable_error__`, `__modified_nodes__`

### Behavioral Change
- Natural language CLI input (e.g., `pflow "analyze my data"`) now shows "not a known workflow or command" instead of "temporarily unavailable"
- API warning messages (GraphQL errors, Slack failures) now appear in error output instead of being silently lost

## AI Agent Guidance

### Quick Start for Related Tasks

If you're adding a new LLM-powered feature:
1. Read `core/llm_utils.py` and `core/prompt_utils.py` — your building blocks
2. Read `registry/discovery.py` — the pattern to follow (plain function + dataclass)
3. Put your prompt in a `prompts/` subdirectory next to your module
4. Use `llm.get_model()` + `schema=PydanticModel` — the llm library handles provider differences

If you're modifying discovery:
1. Read `core/workflow/discovery.py` and `registry/discovery.py` — the two discovery functions
2. Read `registry/context_builder.py` — the node spec builder (900 lines, ~20 functions)
3. The prompts are in `core/workflow/prompts/discovery.md` and `registry/prompts/component_browsing.md`

If you're modifying error handling:
1. Read `execution/executor_service.py:_extract_error_info` — the error source priority chain
2. `__warnings__` (from `InstrumentedNodeWrapper`) is checked FIRST, then root-level error, then node-level error
3. MCP nested payloads unwrap `data.error` — see `_extract_error_from_mcp_result`

### Common Pitfalls

1. **Don't use `"error" in dict`** for API response parsing — use `dict.get("error")` to skip `null`/falsy values
2. **Don't assume `build_component_context` returns a string** — it returns `str | dict` (error dict on missing nodes)
3. **Don't forget `format_prompt` is strict** — all template variables must be provided, and all provided variables must exist in the template. Missing or extra variables raise errors.
4. **`ComponentSelection.component_context` can be empty string** on error — handle gracefully

### Test-First Recommendations

When modifying discovery: run `tests/test_core/test_workflow_discovery.py` and `tests/test_registry/test_component_discovery.py` first.

When modifying error formatting: run `tests/test_execution/test_api_warning_system.py` — this tests the exact Slack/GraphQL payloads that exposed bugs.

When modifying context builders: run `tests/test_integration/test_metadata_flow.py` and `tests/test_integration/test_settings_filtering.py` — these test the registry describe pipeline end-to-end.

---

*Generated from implementation context of Task 92*
