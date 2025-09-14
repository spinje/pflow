# Planning Infrastructure Guide

## Overview

The Natural Language Planner transforms user requests into executable PocketFlow workflows through a multi-stage pipeline. It uses LLMs to understand intent, discover components, and generate workflow IR.

**Core Flow**: User Input → Requirements → Discovery → Planning → Generation → Validation

## Core Architecture

### Planning Pipeline

```
1. Requirements Analysis → Extract operational requirements
2. Parameter Discovery → Find parameters in user input  
3. Component Browsing → Select nodes/workflows to use
4. Planning → Create execution plan
5. Workflow Generation → Generate workflow IR
6. Parameter Mapping → Map discovered params to workflow inputs
7. Metadata Generation → Create searchable metadata
```

### Node Types

All nodes inherit from `pflow.core.node.Node` and implement `prep()`, `exec()`, `post()` lifecycle.

**Discovery Nodes** (Path A/B routing):
- `WorkflowDiscoveryNode` - Finds existing workflows
- `ComponentBrowsingNode` - Selects available nodes

**Analysis Nodes**:
- `RequirementsAnalysisNode` - Extracts requirements (NEW)
- `ParameterDiscoveryNode` - Finds parameters
- `ParameterMappingNode` - Maps params to inputs

**Generation Nodes**:
- `PlanningNode` - Creates execution plan (NEW)
- `WorkflowGeneratorNode` - Generates workflow IR
- `MetadataGenerationNode` - Creates metadata

## Caching System

Three distinct patterns based on node requirements:

### 1. Standard Nodes (Simple Instruction Caching)
Uses `build_cached_prompt()` from `prompt_cache_helper.py`:
- RequirementsAnalysisNode
- ParameterDiscoveryNode  
- ParameterMappingNode
- MetadataGenerationNode

### 2. Special Context Nodes (Custom Caching)
Implement own `_build_cache_blocks()` methods:
- `WorkflowDiscoveryNode` - Caches workflow documentation
- `ComponentBrowsingNode` - Caches node/workflow docs

### 3. Planning Nodes (Multi-Stage Accumulation)
Use `PlannerContextBuilder` for context accumulation:
- `PlanningNode` - Creates and extends blocks
- `WorkflowGeneratorNode` - Accumulates through retries

**Key Pattern**: Single execution path with conditional cache_blocks:
```python
cache_blocks, prompt = build_cached_prompt(...)
response = model.prompt(
    prompt,
    cache_blocks=cache_blocks if cache_planner else None
)
```

## Key Concepts

### Anthropic Model Integration
- **Monkey-patching**: `install_anthropic_model()` replaces `llm.get_model` for planning models
- **When**: Automatically for models containing "claude-sonnet-4"
- **Why**: Enables prompt caching and better structured output
- **Location**: `utils/anthropic_llm_model.py`

### Debug Infrastructure
- **DebugWrapper**: Wraps nodes to capture execution data
- **TraceCollector**: Records all LLM calls and node executions
- **PlannerProgress**: Shows real-time progress to user
- **Location**: `debug.py`

### Prompt Templates
- All prompts stored as `.md` files in `prompts/`
- Loaded via `prompts/loader.py`
- Variables replaced with `${variable}` syntax
- Split at `## Context` for cache optimization

### Error Handling
- `PlannerError` hierarchy for user-friendly messages
- Automatic retry on transient failures
- Fallback responses for critical nodes
- Location: `error_handler.py`

## File Reference

```
planning/
├── __init__.py                    # Package exports
├── flow.py                        # Main planner flow orchestration
├── nodes.py                       # All planning node implementations
├── ir_models.py                   # Pydantic models for workflow IR
├── context_blocks.py              # PlannerContextBuilder for caching
├── context_builder.py             # Legacy context building (mostly unused)
├── debug.py                       # Debug wrapper and tracing
├── error_handler.py               # Error classification and handling
│
├── prompts/                       # Prompt templates (markdown)
│   ├── loader.py                  # Template loading and formatting
│   ├── discovery.md               # Workflow discovery prompt
│   ├── requirements_analysis.md  # Requirements extraction prompt
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
    ├── anthropic_llm_model.py    # Anthropic SDK wrapper + monkey-patch
    ├── anthropic_structured_client.py  # Low-level Anthropic client
    ├── prompt_cache_helper.py     # Simple prompt caching helper
    ├── llm_helpers.py             # LLM response parsing utilities
    ├── registry_helper.py         # Node registry access
    └── workflow_loader.py         # Workflow loading utilities
```

## Implementation Notes

### Critical Patterns

1. **Single Code Path**: No `if cache_planner:` branches in exec methods
2. **Node-Owned Caching**: Each node knows what content is cacheable
3. **Lazy Imports**: Import at point of use for rarely-executed paths
4. **Immutable Blocks**: Cache blocks are never modified, only replaced

### Adding New Nodes

1. Decide which caching pattern fits:
   - Simple prompts → Standard pattern
   - Special context → Custom `_build_cache_blocks()`
   - Multi-stage → Use `PlannerContextBuilder`

2. Follow existing node structure:
   ```python
   class MyNode(Node):
       name = "my-node"
       def prep(self, shared): ...
       def exec(self, prep_res): ...
       def post(self, shared, prep_res, exec_res): ...
   ```

3. Create prompt template in `prompts/my_node.md`

### Performance Considerations

- **Cache Creation Cost**: 25% MORE than regular tokens
- **Cache Read Savings**: ~90% cost reduction
- **Minimum Cache Size**: 1000 characters (~250 tokens)
- **Max Cache Blocks**: 4 per request (Anthropic limit)

### Common Pitfalls

1. **Don't modify cache blocks** - always create new lists
2. **Don't cache dynamic content** - only static instructions/docs
3. **Don't skip prep()** - it's required by PocketFlow
4. **Don't import at module level** - use lazy imports for optional deps

### Testing

- Mock at the LLM level, not the node level
- Test single execution path (cache_blocks=None when disabled)
- Verify prompt templates exist and load correctly
- Check that nodes handle missing/invalid responses

## Quick Reference

**Enable Caching**: `--cache-planner` CLI flag
**Debug Mode**: `--debug` flag creates trace files
**Trace Location**: `.pflow/debug/planner_trace_*.json`
**Default Model**: `anthropic/claude-sonnet-4-0`
**Retry Limit**: 2 attempts for transient failures