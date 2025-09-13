# Immediate Fix & Groundwork Implementation

## Current Breaking Issue

**Problem**: `cache_blocks` is REQUIRED in AnthropicLLMModel.prompt()
```python
# Current broken code
if cache_blocks is None:
    raise ValueError("cache_blocks parameter is required.")
```

**Impact**: ALL planner nodes except PlanningNode/WorkflowGeneratorNode are broken

## Phase 1: Immediate Fix (Make Planner Work Again)

### 1. Update AnthropicLLMModel

```python
# src/pflow/planning/utils/anthropic_llm_model.py

def prompt(self, prompt, schema=None, temperature=0.0, cache_blocks=None, **kwargs):
    """Execute a prompt using the Anthropic SDK.
    
    Args:
        cache_blocks: Optional list of cache blocks. If None, no caching is applied.
    """
    if cache_blocks is not None:
        # Optimized path with caching
        return self._prompt_with_cache_blocks(
            prompt=prompt,
            schema=schema,
            temperature=temperature,
            cache_blocks=cache_blocks,
            **kwargs
        )
    else:
        # Fallback path without caching
        return self._prompt_without_cache(
            prompt=prompt,
            schema=schema, 
            temperature=temperature,
            **kwargs
        )

def _prompt_without_cache(self, prompt, schema, temperature, **kwargs):
    """Execute prompt without cache blocks (fallback path)."""
    prompt_str = prompt if isinstance(prompt, str) else str(prompt)
    
    if schema:
        # Structured output without caching
        result, usage = self.client.generate_with_schema(
            prompt=prompt_str,
            response_model=schema,
            temperature=temperature,
            max_tokens=8192
        )
    else:
        # Text output without caching
        # Still use FlowIR tool for consistency but no cache blocks
        from pflow.planning.ir_models import FlowIR
        result, usage = self.client.generate_with_schema_text_mode(
            prompt=prompt_str,
            response_model=FlowIR,
            temperature=temperature,
            force_text_output=True
        )
    
    return AnthropicResponse(result, usage, is_structured=bool(schema))
```

### 2. Update AnthropicStructuredClient

```python
# src/pflow/planning/utils/anthropic_structured_client.py

def generate_with_schema(self, prompt, response_model, temperature=0.0, max_tokens=8192):
    """Generate structured output WITHOUT cache blocks.
    
    This is the fallback method when caching is not needed.
    """
    # Set up tool
    tool_name = "respond"
    tool = {
        "name": tool_name,
        "description": f"Generate a {response_model.__name__}",
        "input_schema": response_model.model_json_schema()
    }
    
    # Create messages without system parameter
    messages = [{"role": "user", "content": prompt}]
    
    # Call Anthropic
    response = self.client.messages.create(
        model=self.model,
        messages=messages,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool_name},
        temperature=temperature,
        max_tokens=max_tokens
    )
    
    # Extract result
    # ... (same extraction logic)
    
    return result, usage
```

## Phase 2: Add --cache-planner Flag Groundwork

### 1. Update CLI to Accept Flag

```python
# src/pflow/cli/main.py

@click.option(
    "--cache-planner",
    is_flag=True,
    help="Enable cross-session caching for planner LLM calls (reduces cost for repeated runs)",
)
def run(ctx, query, ..., cache_planner):
    """Run a workflow from natural language or workflow name."""
    
    # Store in context for propagation
    ctx.obj["cache_planner"] = cache_planner
    
    # ... existing code ...
    
    # When creating shared store for planner
    shared = {
        "user_input": query,
        "cache_planner": cache_planner,  # Propagate flag
        # ... other fields
    }
```

### 2. Update Nodes to Check Flag

Example for WorkflowDiscoveryNode:

```python
def exec(self, prep_res):
    # Check if caching should be enabled
    cache_planner = prep_res.get("cache_planner", False)
    
    # Get model
    model = llm.get_model(prep_res["model_name"])
    
    if cache_planner:
        # Build cache blocks for static content
        blocks = self._build_cache_blocks(prep_res)
        
        # Dynamic content only
        dynamic_prompt = f"User Request: {prep_res['user_input']}"
        
        response = model.prompt(
            dynamic_prompt,
            cache_blocks=blocks,
            schema=WorkflowDecision,
            temperature=prep_res["temperature"]
        )
    else:
        # Traditional approach - no caching
        full_prompt = prep_res["discovery_context"]
        response = model.prompt(
            full_prompt,
            schema=WorkflowDecision,
            temperature=prep_res["temperature"]
        )
    
    return self._parse_response(response)

def _build_cache_blocks(self, prep_res):
    """Build cache blocks for cross-session caching."""
    blocks = []
    
    # Add static workflow descriptions (this doesn't change between queries)
    static_context = prep_res.get("discovery_context", "")
    # Remove dynamic parts (user query)
    static_parts = self._extract_static_content(static_context)
    
    if static_parts and len(static_parts) > 1024:  # Min for caching
        blocks.append({
            "text": static_parts,
            "cache_control": {"type": "ephemeral"}
        })
    
    return blocks
```

## Testing the Fix

### 1. Test Immediate Fix
```bash
# This should work again (was broken)
uv run pflow "create a workflow to analyze GitHub issues"
```

### 2. Test Cache Flag (Phase 2)
```bash
# First run - creates cache
uv run pflow --cache-planner "create a workflow"

# Second run - uses cache (should be much faster/cheaper)
uv run pflow --cache-planner "different workflow"
```

### 3. Verify Cache Metrics
```python
# Add logging to see cache working
logger.info(f"Cache metrics: created={cache_creation}, read={cache_read}")
```

## Priority Order

1. **URGENT**: Fix AnthropicLLMModel to make cache_blocks optional (unblock planner)
2. **Important**: Add --cache-planner flag to CLI
3. **Nice to have**: Update each node to support caching
4. **Future**: Add cache metrics display

## Files to Modify

### Phase 1 (Immediate Fix)
- `src/pflow/planning/utils/anthropic_llm_model.py` - Make cache_blocks optional
- `src/pflow/planning/utils/anthropic_structured_client.py` - Add non-cache method

### Phase 2 (Flag Support)  
- `src/pflow/cli/main.py` - Add --cache-planner flag
- `src/pflow/planning/nodes.py` - Update nodes to check flag

### Phase 3 (Full Implementation)
- Each planner node to add _build_cache_blocks() method
- Update prompts to separate static from dynamic content