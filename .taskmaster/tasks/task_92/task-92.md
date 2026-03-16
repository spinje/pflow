# Task 92: Remove Planning Module and Repair System

## Status
completed

## Description

Removed the gated planning module (~7,300 production lines, ~23,000 test lines) and repair system (~1,050 production lines) from the codebase. Replaced PocketFlow-based discovery nodes with plain functions. Dropped the direct `anthropic` SDK dependency.

This was originally scoped as "Replace Planner with Agent + MCP Tools" with three options. We implemented **Option 2** (remove CLI natural language entirely) with an enhancement: discovery features (`workflow discover`, `registry discover`) were preserved as plain functions instead of being removed.

## What Was Done

### Pre-task: Extract `core/workflow/` subdirectory (PR #121)
Moved 6 workflow files from `core/` to `core/workflow/` to create a natural home for workflow discovery. ~46 files updated, 53 `patch()` strings in tests.

### Phase 1: Relocate active dependencies
- `parse_structured_response` → `core/llm_utils.py`
- `smart_filter.py` → `registry/smart_filter.py`
- `build_planning_context` + `build_nodes_context` → `registry/context_builder.py`
- `build_workflows_context` → `core/workflow/context.py`
- Prompt loader → `core/prompt_utils.py`
- `WorkflowDiscoveryNode` → `core/workflow/discovery.py:discover_workflow()` (plain function + `WorkflowMatch` dataclass)
- `ComponentBrowsingNode` → `registry/discovery.py:discover_components()` (plain function + `ComponentSelection` dataclass)
- Removed `install_anthropic_model` monkey-patch from CLI and MCP server
- Dropped `anthropic>=0.75` direct dependency

### Phase 2: Delete planning, repair, and gated code
- Deleted `src/pflow/planning/` (entire directory)
- Deleted `execution/repair_service.py`, `execution/workflow_diff.py`, `cli/repair_save_handlers.py`
- Cleaned gated code paths in `cli/main.py` (~654 lines removed), `execution/workflow_execution.py` (642→83 lines)
- Removed `PlannerError`, `update_ir()`, `generate_workflow_metadata` planning import, `_is_fixable_error()`, `repaired_workflow_ir` field
- Removed planner metrics fields and `is_planner` parameter threading
- Cleaned 7 hidden CLI flags, planner dispatch, repair loop
- Deleted all planning/repair test files (~23,000 lines)
- Updated all CLAUDE.md files, agent definitions, shared test docs

## Impact
- **Net deletion**: ~40,000+ lines
- **Tests**: 4,072 pass, 0 planner/repair skips remaining (post-review: dead code cleanup removed 2 tests, added 1)
- **Dependencies**: `anthropic>=0.75` removed (remains as transitive via `llm-anthropic`)
- **Discovery preserved**: `pflow workflow discover` and `pflow registry discover` work via plain functions

## Key Decisions

1. **Plain functions over PocketFlow nodes** — Discovery nodes were never composed in flows outside the planner. Shared store ceremony added no value. Plain functions with typed dataclass returns are simpler, more testable, and have explicit contracts.

2. **Drop Anthropic SDK** — Only used by planning's custom SDK wrapper for prompt caching and thinking tokens. The `llm-anthropic` plugin supports `schema=` for structured output natively, which is all discovery needs.

3. **Separate pre-task for `core/workflow/`** — The ~46-file extraction was purely mechanical and shouldn't be mixed with the planning removal. Isolating it reduced risk.

4. **Keep discovery, remove planner** — Discovery is useful for MCP agents. The planner's multi-phase LLM orchestration was fragile and unmaintained. Clean removal beats maintaining dormant code.

## Dependencies
- Task 72: MCP Server (completed — discovery tools still work)
- Task 107: Markdown Format (completed — was the original gating reason)

## Tasks Made Obsolete
- Task 60: Support Gemini Models for Planner (deprecated)
- Task 61: Implement Fast Mode for Planner (deprecated)
- Task 69: Refactor Repair to Use PocketFlow (deprecated)
- Task 73: Checkpoint Persistence for Repair (deprecated)
