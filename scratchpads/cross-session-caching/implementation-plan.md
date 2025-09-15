# Implementation Plan: Cross-Session Caching Feature

**Date**: January 2025
**Purpose**: Step-by-step implementation plan to fix planner and add cross-session caching
**Priority**: URGENT - Planner is currently broken

## Phase 1: Immediate Fix (15 minutes)

### Goal: Make the planner work again

#### 1.1 Fix AnthropicLLMModel (`src/pflow/planning/utils/anthropic_llm_model.py`)

```python
def prompt(self, prompt, schema=None, temperature=0.0, cache_blocks=None, **kwargs):
    """Execute a prompt using the Anthropic SDK.

    Args:
        cache_blocks: Optional list of cache blocks for multi-block caching
    """
    # Handle both cached and non-cached paths
    if cache_blocks is not None:
        # Use provided cache blocks (current behavior for Planning/Generator nodes)
        return self._prompt_with_cache_blocks(
            prompt=prompt,
            schema=schema,
            temperature=temperature,
            cache_blocks=cache_blocks,
            **kwargs,
        )
    else:
        # No cache blocks - pass None to structured client (it handles it!)
        prompt_str = prompt if isinstance(prompt, str) else str(prompt)

        if schema:
            # Structured output without caching
            result, usage = self.client.generate_with_schema(
                prompt=prompt_str,
                response_model=schema,
                temperature=temperature,
                cache_blocks=None,  # Structured client handles None perfectly
            )
        else:
            # Text output without caching
            from pflow.planning.ir_models import FlowIR
            result, usage = self.client.generate_with_schema_text_mode(
                prompt=prompt_str,
                response_model=FlowIR,
                temperature=temperature,
                cache_blocks=None,
                force_text_output=True,
            )

        return AnthropicResponse(result, usage, is_structured=bool(schema))
```

**⚠️ IMPORTANT**: Do NOT modify AnthropicStructuredClient - it already handles cache_blocks=None perfectly!

**Test**: Run `uv run pflow "create a workflow"` - should work again!

## Phase 2: Add CLI Flag (30 minutes)

### Goal: Add --cache-planner flag and propagate through pipeline

#### 2.1 Update CLI (`src/pflow/cli/main.py`)

Add flag to run command (~line 760):
```python
@click.option(
    "--cache-planner",
    is_flag=True,
    help="Enable cross-session caching for planner LLM calls (reduces cost for repeated runs)",
)
def run(
    ctx,
    query,
    # ... other params ...
    cache_planner,  # Add parameter
):
```

#### 2.2 Propagate flag to shared store (~line 1663)

In `_setup_planner_execution()`:
```python
# Initialize shared state
shared = {
    "user_input": raw_input,
    "workflow_manager": WorkflowManager(),
    "stdin_data": stdin_data if stdin_data else None,
    "cache_planner": cache_planner,  # ADD THIS LINE
}
```

## Phase 3: Create Cache Infrastructure (45 minutes)

### Goal: Add helper utilities for building cache blocks

#### 3.1 Create cache utilities module (`src/pflow/planning/utils/cache_builder.py`)

```python
"""Cache block builder utilities for cross-session caching."""

from typing import Any, Optional


def build_discovery_cache_blocks(discovery_context: str) -> list[dict[str, Any]]:
    """Build cache blocks for WorkflowDiscoveryNode.

    Separates static workflow descriptions from dynamic user input.
    """
    blocks = []

    # Extract static content (everything except user request)
    # The discovery_context contains workflows overview which is static
    if discovery_context and len(discovery_context) > 100:
        blocks.append({
            "text": discovery_context,
            "cache_control": {"type": "ephemeral"}
        })

    return blocks


def build_component_cache_blocks(
    nodes_context: str,
    workflows_context: str,
    prompt_template: str
) -> list[dict[str, Any]]:
    """Build cache blocks for ComponentBrowsingNode.

    Combines all static documentation into cacheable blocks.
    """
    blocks = []

    # Block 1: Node documentation (static)
    if nodes_context:
        blocks.append({
            "text": f"## Available Nodes\n\n{nodes_context}",
            "cache_control": {"type": "ephemeral"}
        })

    # Block 2: Workflow documentation (static)
    if workflows_context:
        blocks.append({
            "text": f"## Available Workflows\n\n{workflows_context}",
            "cache_control": {"type": "ephemeral"}
        })

    # Block 3: Prompt template (static)
    if prompt_template and len(prompt_template) > 500:
        blocks.append({
            "text": prompt_template,
            "cache_control": {"type": "ephemeral"}
        })

    return blocks


def build_simple_cache_blocks(
    static_prompt: str,
    static_context: Optional[str] = None
) -> list[dict[str, Any]]:
    """Build cache blocks for simpler nodes.

    Used by RequirementsAnalysisNode, ParameterDiscoveryNode, etc.
    """
    blocks = []

    # Combine static content if both exist
    if static_context:
        combined = f"{static_context}\n\n{static_prompt}"
    else:
        combined = static_prompt

    # Only cache if substantial
    if combined and len(combined) > 500:
        blocks.append({
            "text": combined,
            "cache_control": {"type": "ephemeral"}
        })

    return blocks
```

## Phase 4: Update All LLM Nodes (2 hours)

### Goal: Add caching support to all 8 LLM-calling nodes

#### 4.1 Pattern for updating each node

Each node needs this pattern in its `exec()` method:

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    # Check if caching is enabled
    cache_planner = prep_res.get("cache_planner", False)

    # Special nodes ALWAYS cache (for intra-session benefit)
    force_cache = self.name in ["planning", "workflow-generator"]

    model = llm.get_model(prep_res["model_name"])

    if cache_planner or force_cache:
        # Build cache blocks for static content
        cache_blocks = self._build_cache_blocks(prep_res)

        # Dynamic content only (user-specific)
        dynamic_prompt = self._build_dynamic_prompt(prep_res)

        response = model.prompt(
            dynamic_prompt,
            schema=self.schema_class if hasattr(self, 'schema_class') else None,
            cache_blocks=cache_blocks,
            temperature=prep_res["temperature"]
        )
    else:
        # Traditional approach - no caching
        full_prompt = self._build_full_prompt(prep_res)

        response = model.prompt(
            full_prompt,
            schema=self.schema_class if hasattr(self, 'schema_class') else None,
            temperature=prep_res["temperature"]
        )

    return self._parse_response(response)
```

#### 4.2 Node-specific implementations

**WorkflowDiscoveryNode** (~line 150):
```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks with static workflow descriptions."""
    from pflow.planning.utils.cache_builder import build_discovery_cache_blocks
    return build_discovery_cache_blocks(prep_res["discovery_context"])

def _build_dynamic_prompt(self, prep_res: dict) -> str:
    """Extract dynamic user-specific content."""
    return f"User Request: {prep_res['user_input']}"

def _build_full_prompt(self, prep_res: dict) -> str:
    """Traditional full prompt for non-cached mode."""
    from pflow.planning.prompts.loader import load_prompt
    discovery_prompt = load_prompt("discovery")
    return f"{prep_res['discovery_context']}\n\n{discovery_prompt.format(user_input=prep_res['user_input'])}"
```

**ComponentBrowsingNode** (~line 340):
```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks with static node/workflow documentation."""
    from pflow.planning.utils.cache_builder import build_component_cache_blocks
    from pflow.planning.prompts.loader import load_prompt

    prompt_template = load_prompt("component_browsing")
    return build_component_cache_blocks(
        nodes_context=prep_res.get("nodes_context", ""),
        workflows_context=prep_res.get("workflows_context", ""),
        prompt_template=prompt_template
    )

def _build_dynamic_prompt(self, prep_res: dict) -> str:
    """Extract dynamic user-specific content."""
    parts = [
        f"User Request: {prep_res['user_input']}",
        f"Requirements: {prep_res.get('requirements_text', '')}",
    ]
    return "\n\n".join(parts)
```

**RequirementsAnalysisNode** (~line 770):
```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks with static analysis rules."""
    from pflow.planning.utils.cache_builder import build_simple_cache_blocks
    from pflow.planning.prompts.loader import load_prompt

    static_prompt = load_prompt("requirements_analysis")
    return build_simple_cache_blocks(static_prompt)

def _build_dynamic_prompt(self, prep_res: dict) -> str:
    """Extract dynamic user input."""
    return f"Analyze this request: {prep_res['templatized_input']}"
```

**ParameterDiscoveryNode** (~line 590):
```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks with static extraction rules."""
    from pflow.planning.utils.cache_builder import build_simple_cache_blocks
    from pflow.planning.prompts.loader import load_prompt

    static_prompt = load_prompt("parameter_discovery")
    return build_simple_cache_blocks(static_prompt)

def _build_dynamic_prompt(self, prep_res: dict) -> str:
    """Extract dynamic user input and components."""
    return f"User Input: {prep_res['user_input']}\n\nSelected Components: {prep_res.get('browsed_components', {})}"
```

**ParameterMappingNode** (~line 1290):
```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks with static mapping rules."""
    from pflow.planning.utils.cache_builder import build_simple_cache_blocks
    from pflow.planning.prompts.loader import load_prompt

    static_prompt = load_prompt("parameter_mapping")
    return build_simple_cache_blocks(static_prompt)

def _build_dynamic_prompt(self, prep_res: dict) -> str:
    """Extract dynamic workflow and params."""
    import json
    return f"Workflow: {json.dumps(prep_res['workflow'], indent=2)}\n\nParameters: {prep_res.get('extracted_params', {})}"
```

**MetadataGenerationNode** (~line 1950):
```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks with static metadata rules."""
    from pflow.planning.utils.cache_builder import build_simple_cache_blocks
    from pflow.planning.prompts.loader import load_prompt

    static_prompt = load_prompt("metadata_generation")
    return build_simple_cache_blocks(static_prompt)

def _build_dynamic_prompt(self, prep_res: dict) -> str:
    """Extract dynamic workflow for metadata generation."""
    import json
    return f"Generate metadata for: {json.dumps(prep_res['workflow'], indent=2)}"
```

**⚠️ CRITICAL**: PlanningNode and WorkflowGeneratorNode already use cache blocks but currently ALWAYS use them. They should ALWAYS continue using cache blocks (for intra-session benefit between each other) regardless of the flag. The flag only affects whether OTHER nodes use caching.

```python
# PlanningNode and WorkflowGeneratorNode - NO CHANGES NEEDED
# They already use cache blocks and should continue to do so
# The intra-session caching between these two nodes is always beneficial
# Do NOT make them conditional on the cache_planner flag
```

## Phase 5: Testing (30 minutes)

### 5.1 Test without flag (default behavior)
```bash
# Should work normally, no caching for discovery/browsing/etc
uv run pflow "create a workflow to analyze GitHub issues"
```

### 5.2 Test with flag (caching enabled)
```bash
# First run - creates cache
uv run pflow --cache-planner "create a workflow to analyze GitHub issues"
# Note the execution time and cost

# Second run - different query, should use cache
uv run pflow --cache-planner "fetch slack messages and summarize"
# Should be noticeably faster/cheaper

# Third run - another query
uv run pflow --cache-planner "deploy to kubernetes"
# Still benefiting from cache
```

### 5.3 Verify cache metrics
Add temporary logging to see cache working:
```python
# In AnthropicLLMModel._prompt_with_cache_blocks()
if usage:
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_creation > 0 or cache_read > 0:
        logger.info(
            f"Cache metrics: created={cache_creation} tokens, "
            f"read={cache_read} tokens, blocks={len(cache_blocks)}"
        )
```

## Implementation Order

1. **URGENT - Phase 1**: Fix AnthropicLLMModel (15 min)
   - Makes planner work again

2. **Phase 2**: Add CLI flag (30 min)
   - Sets up infrastructure

3. **Phase 3**: Create cache utilities (45 min)
   - Reusable helpers

4. **Phase 4**: Update nodes incrementally (2 hours)
   - Start with WorkflowDiscoveryNode
   - Then ComponentBrowsingNode
   - Then simpler nodes

5. **Phase 5**: Test thoroughly (30 min)
   - Verify both modes work

## Success Criteria

- [ ] Planner works without --cache-planner flag
- [ ] Planner works with --cache-planner flag
- [ ] Second run with flag shows cache_read > 0 in metrics
- [ ] All 8 LLM nodes support caching when flag is set
- [ ] No regression in functionality

## Files to Modify

### Phase 1 (Immediate)
- `src/pflow/planning/utils/anthropic_llm_model.py`

### Phase 2 (CLI)
- `src/pflow/cli/main.py`

### Phase 3 (Infrastructure)
- `src/pflow/planning/utils/cache_builder.py` (new file)

### Phase 4 (Nodes)
- `src/pflow/planning/nodes.py` (6 nodes to update)

### Phase 5 (Testing)
- No file changes, just testing

## Risk Mitigation

1. **Test after each phase** - Ensure no regression
2. **Keep PlanningNode/WorkflowGeneratorNode unchanged** - They already work
3. **Make caching optional** - Flag controls behavior
4. **Log cache metrics** - Verify it's working
5. **Small batches** - Update nodes one at a time
6. **DO NOT break the tool-choice hack** - Both PlanningNode and WorkflowGeneratorNode use FlowIR tool definition to share cache namespace
7. **DO NOT modify AnthropicStructuredClient** - It already handles None perfectly

This plan fixes the immediate issue first, then progressively adds the cross-session caching feature in manageable chunks.