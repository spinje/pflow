# Planning Infrastructure - Minimal Guide

> **GATED (Task 107)**: The planner system is gated pending markdown format migration. Planner prompts assume JSON workflow format. All code is preserved but entry points are guarded — CLI shows a "temporarily unavailable" message when natural language input is detected. Re-enable after prompt rewrite.

## Overview

Natural Language Planner transforms requests into executable PocketFlow workflows via multi-stage LLM pipeline.

**Core Dependency**: Built on PocketFlow framework (`src/pflow/pocketflow/__init__.py`)
- All nodes inherit from `pocketflow.Node` with `prep()`, `exec()`, `post()` lifecycle
- Nodes communicate via shared store dictionary
- Flow orchestrates node execution based on action strings

**Two Execution Paths**:
- **Path A (Reuse)**: Discovery finds workflow → Parameter Mapping → Result (fast ~7-15 seconds)
- **Path B (Generate)**: Discovery → Requirements → Browsing → Planning → Generation → Validation → Mapping (full pipeline ~50-80 seconds)

## Node Execution Order

**Common Start (Both Paths)**:
1. **WorkflowDiscoveryNode** → Returns "found_existing" (Path A) or "not_found" (Path B)
2. **ParameterDiscoveryNode** → Extract parameters → Returns empty string ""

**Path A - Reuse Existing** (skips to):
7. **ParameterMappingNode** → Map to existing workflow → Returns "params_complete"

**Path B - Generate New** (continues with):
3. **RequirementsAnalysisNode** → Analyze complexity → Returns "" or "clarification_needed"
4. **ComponentBrowsingNode** → Select nodes → Returns "generate"
5. **PlanningNode** → Create execution plan → Returns "" or "impossible_requirements"
6. **WorkflowGeneratorNode** → Generate IR → Returns "success" or "error"
7. **ParameterMappingNode** → Map to generated workflow → Returns "params_complete_validate"
8. **ValidatorNode** → Validate generated workflow → Returns "success" or "retry" (up to 3x)
9. **MetadataGenerationNode** → Create searchable metadata → Returns ""

**Final Nodes (Both Paths)**:
- **ParameterPreparationNode** → Prepare parameters for execution → Returns ""
- **ResultPreparationNode** → Package final result → Returns None (terminates flow)

## Three Caching Patterns (DO NOT UNIFY)

1. **Standard** → `build_cached_prompt()` (Requirements, Parameter, Mapping, Metadata nodes)
2. **Special Context** → Custom `_build_cache_blocks()` (Discovery, Browsing nodes)
3. **Planning** → `PlannerContextBuilder` (Planning, Generator nodes)

**Single Path Pattern**:
```python
cache_blocks, prompt = build_cached_prompt(...)
model.prompt(prompt, cache_blocks=cache_blocks if cache_planner else None)
```

## Critical Components

- **Monkey-patch**: `install_anthropic_model()` in `utils/anthropic_llm_model.py`
- **Debug**: `DebugWrapper` + `TraceCollector` in `debug.py`
- **Prompts**: `.md` files in `prompts/`, loaded by `loader.py`
- **Thinking Tokens**: Allocated by RequirementsAnalysisNode (0/4096/16384/32768)
- **Cost Tracking**: `llm_pricing.py` calculates at record time

## Complete File Structure

```
planning/
├── flow.py                        # Main planner flow orchestration
├── nodes.py                       # All 11 planning nodes (lines 866-1309 for new ones)
├── ir_models.py                   # Pydantic models for workflow IR
├── context_blocks.py              # PlannerContextBuilder for cache accumulation
├── context_builder.py             # Legacy context building (mostly unused)
├── debug.py                       # Debug wrapper, tracing, cost calculation
├── error_handler.py               # Error classification and handling
├── CLAUDE.md                      # This file
│
├── prompts/                       # Prompt templates (DO NOT edit frontmatter)
│   ├── loader.py                  # Template loading and formatting
│   ├── CLAUDE.md                  # Prompt directory guide
│   ├── README.md                  # Detailed prompt documentation
│   ├── discovery.md               # Workflow discovery prompt
│   ├── requirements_analysis.md  # Requirements + complexity scoring
│   ├── component_browsing.md     # Component selection prompt
│   ├── parameter_discovery.md    # Parameter finding prompt
│   ├── parameter_mapping.md      # Parameter mapping prompt
│   ├── planning_instructions.md  # Execution planning prompt
│   ├── metadata_generation.md    # Metadata generation prompt
│   ├── workflow_generator_instructions.md  # Generation prompt
│   ├── workflow_generator_retry.md        # Retry-specific prompt
│   └── workflow_system_overview.md        # System docs for context
│
└── utils/                         # Utility modules
    ├── anthropic_llm_model.py    # Monkey-patch (line 272) + thinking
    ├── anthropic_structured_client.py  # Structured output + thinking
    ├── prompt_cache_helper.py     # Simple prompt caching (~50 lines)
    ├── llm_helpers.py             # LLM response parsing utilities
    ├── registry_helper.py         # Node registry access
    └── workflow_loader.py         # Workflow loading utilities
```

## Key Shared Store Variables

- `shared["requirements_result"]` - Requirements analysis output with complexity_score and thinking_budget
- `shared["planning_context"]` - Context from ComponentBrowsingNode (ACTIVE, not dead code)
- `shared["planning_result"]` - Execution plan from PlanningNode
- `shared["planner_extended_blocks"]` - Cache blocks for WorkflowGeneratorNode
- `shared["planner_accumulated_blocks"]` - Grows with retries for learning

## PocketFlow Integration Points

- **Node Lifecycle**: Every node MUST implement `prep()`, `exec()`, `post()`
- **Shared Store**: All inter-node communication via `shared` dictionary
- **Action Strings**: `post()` returns action to control flow (e.g., "success", "error", "retry")
- **Flow Construction**: `create_planner_flow()` chains nodes with `>>` operator
- **No Direct Calls**: Never call node methods directly, Flow handles execution

## Critical Rules

1. **NO `if cache_planner:` branches** - Single path only
2. **Immutable blocks** - `blocks = blocks + [new]`, never `blocks.append()`
3. **Don't unify caching patterns** - They're separate for good reasons
4. **Don't edit prompt frontmatter** - Automated by test tool
5. **Check `PYTEST_CURRENT_TEST`** before monkey-patching
6. **All nodes need prep/exec/post** - PocketFlow requirement
7. **Cache minimum ~1024 tokens** - Smaller won't cache
8. **Use shared store for data** - Never pass data between nodes directly

## Quick Reference

- **Enable Cache**: `--cache-planner`
- **Trace**: `--trace-planner` → `.pflow/debug/planner_trace_*.json`
- **Model**: `anthropic/claude-sonnet-4-0`
- **Cache Cost**: 2x creation, 0.1x reads
- **Thinking Allocation**: Based on complexity score from RequirementsAnalysisNode