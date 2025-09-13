# CRITICAL CONTEXT BRAINDUMP - Cross-Session Caching Implementation

**URGENT**: The planner is COMPLETELY BROKEN right now. This must be fixed FIRST before any other work.

## 🚨 CURRENT BROKEN STATE

### The Bug That Breaks Everything
- **File**: `src/pflow/planning/utils/anthropic_llm_model.py`
- **Lines**: 74-79
- **Problem**: The code REQUIRES `cache_blocks` parameter but 6 out of 8 planner nodes don't provide it
- **Impact**: ALL planner commands fail immediately with ValueError

```python
# CURRENT BROKEN CODE (lines 74-79)
if cache_blocks is None:
    raise ValueError(
        "cache_blocks parameter is required. "
        "Nodes must provide cache blocks from PlannerContextBuilder."
    )
```

### Why This Happened
We implemented multi-block caching for PlanningNode → WorkflowGeneratorNode (Task 52) and made cache_blocks required. But we forgot the other 6 nodes exist!

## 🔑 KEY INSIGHTS NOT IN OTHER DOCS

### 1. AnthropicStructuredClient ALREADY Handles None!
**CRITICAL**: Don't create new methods in AnthropicStructuredClient! Both `generate_with_schema` and `generate_with_schema_text_mode` already accept `cache_blocks=None` and handle it perfectly. When None, they just don't add system parameter.

### 2. The Tool-Choice Hack Must Be Preserved
For cache sharing between PlanningNode and WorkflowGeneratorNode to work:
- BOTH must import FlowIR 
- PlanningNode uses `force_text_output=True` (tool_choice='none')
- WorkflowGeneratorNode uses `force_text_output=False` (tool_choice='tool')
- This tricks Anthropic into sharing cache despite different output formats

### 3. Current Cache Block Implementation
**Already working in PlanningNode/WorkflowGeneratorNode**:
- PlanningNode creates blocks [A, B, C] where C is the plan
- WorkflowGeneratorNode reads [A, B, C] and adds [D, E] for retries
- Blocks stored in shared store as `planner_base_blocks`, `planner_extended_blocks`, `planner_accumulated_blocks`

### 4. Shared Store Propagation
- Created in `src/pflow/cli/main.py` at line ~1663 in `_setup_planner_execution()`
- Every node gets it through `prep(shared)` method
- Add `"cache_planner": cache_planner` here for flag propagation

### 5. Model Detection Logic
The monkey-patching in `install_anthropic_model()` (line 216-235 of anthropic_llm_model.py) detects Claude models by:
```python
is_planning_model = model_name and (
    "claude-sonnet-4" in model_name or 
    model_name == "anthropic/claude-sonnet-4-0"
)
```
This ONLY applies AnthropicLLMModel to Claude models. Other models use regular llm library.

## 📋 COMPLETE NODE LIST WITH LLM CALLS

All in `src/pflow/planning/nodes.py`:

1. **WorkflowDiscoveryNode** (line 155) - `model.prompt(prompt, schema=WorkflowDecision, temperature=...)`
2. **ComponentBrowsingNode** (line 354) - `model.prompt(prompt, schema=ComponentSelection, temperature=...)`  
3. **RequirementsAnalysisNode** (line 774) - `model.prompt(prompt, schema=RequirementsSchema, temperature=...)`
4. **ParameterDiscoveryNode** (line 593) - `model.prompt(prompt, schema=ParameterDiscovery, temperature=...)`
5. **PlanningNode** (line 974) - `model.prompt(instructions, cache_blocks=base_blocks, temperature=...)` ✅ WORKING
6. **WorkflowGeneratorNode** (line 1660) - `model.prompt(instructions, schema=FlowIR, cache_blocks=blocks, temperature=...)` ✅ WORKING
7. **ParameterMappingNode** (line 1293) - `model.prompt(prompt, schema=ParameterExtraction, temperature=...)`
8. **MetadataGenerationNode** (line 1951) - `model.prompt(prompt, schema=WorkflowMetadata, temperature=...)`

## ⚠️ IMPLEMENTATION GOTCHAS

### 1. Don't Break What's Working!
PlanningNode and WorkflowGeneratorNode ALREADY use cache blocks perfectly. Don't change their cache logic - just check for the flag.

### 2. The 1024 Token Minimum
Anthropic requires >1024 tokens for caching. If content is smaller, it just won't cache but WON'T ERROR. So don't worry about checking sizes.

### 3. Static vs Dynamic Content Separation
- **Static** (cacheable): Prompts, node docs, workflow descriptions, rules
- **Dynamic** (not cacheable): User input, selected components, generated content
- Put static in cache_blocks, dynamic in prompt parameter

### 4. Test the Fix Immediately
After fixing AnthropicLLMModel.prompt(), test with:
```bash
uv run pflow "create a workflow to analyze GitHub issues"
```
This should work again (currently broken).

## 🛠️ IMPLEMENTATION ORDER (CRITICAL)

### Phase 1: EMERGENCY FIX (5 minutes)
Fix `src/pflow/planning/utils/anthropic_llm_model.py` prompt method:
1. Remove the ValueError for cache_blocks=None
2. Add else branch that passes None to structured client
3. Test immediately - planner should work again

### Phase 2: CLI Flag (30 minutes)
Use code-implementer agent for this - it's mechanical work:
1. Add `--cache-planner` flag to run command
2. Add to shared store in `_setup_planner_execution()`
3. The flag will be available to all nodes via `prep_res.get("cache_planner", False)`

### Phase 3: Cache Utilities (30 minutes)
Create `src/pflow/planning/utils/cache_builder.py` with helpers to build cache blocks.
See implementation-plan.md for exact code.

### Phase 4: Update Each Node (2 hours)
For each of the 6 nodes without cache support:
1. Check if `cache_planner` flag is set
2. If yes, build cache blocks and pass dynamic content only
3. If no, use current behavior (full prompt, no cache blocks)

## 📝 CODE PATTERNS TO FOLLOW

### Node Update Pattern
```python
def exec(self, prep_res):
    cache_planner = prep_res.get("cache_planner", False)
    model = llm.get_model(prep_res["model_name"])
    
    if cache_planner:
        # Static content in blocks
        cache_blocks = self._build_cache_blocks(prep_res)
        # Dynamic content only
        dynamic_prompt = f"User request: {prep_res['user_input']}"
        response = model.prompt(
            dynamic_prompt,
            schema=MySchema,  # if structured
            cache_blocks=cache_blocks,
            temperature=prep_res["temperature"]
        )
    else:
        # Current behavior - everything in prompt
        full_prompt = prep_res["full_context"]
        response = model.prompt(
            full_prompt,
            schema=MySchema,
            temperature=prep_res["temperature"]
        )
```

## 🧪 TESTING STRATEGY

### Test 1: Basic Functionality (after Phase 1)
```bash
# This is currently BROKEN - should work after fix
uv run pflow "create a workflow"
```

### Test 2: Cache Flag (after Phase 2)
```bash
# First run - creates cache
uv run pflow --cache-planner "create workflow" 

# Second run - should use cache (check logs for cache_read > 0)
uv run pflow --cache-planner "different workflow"
```

### Test 3: Verify Cache Metrics
Add logging in AnthropicLLMModel to see cache working:
```python
if usage:
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_read > 0:
        logger.info(f"CACHE HIT! Read {cache_read} tokens from cache")
```

## 🔍 WHERE TO FIND THINGS

- **Broken code**: `src/pflow/planning/utils/anthropic_llm_model.py` lines 74-79
- **CLI entry**: `src/pflow/cli/main.py` line ~760 (run command)
- **Shared store creation**: `src/pflow/cli/main.py` line ~1663
- **All planner nodes**: `src/pflow/planning/nodes.py`
- **Context building**: `src/pflow/planning/context_blocks.py`
- **Prompts**: `src/pflow/planning/prompts/*.md`

## ⚡ QUICK WIN PATH

1. **Fix the ValueError** - Makes planner work again (5 min)
2. **Add CLI flag** - Use code-implementer (30 min)
3. **Update WorkflowDiscoveryNode first** - It's simple and high-impact
4. **Update ComponentBrowsingNode next** - Biggest static content (~10k tokens)
5. **Update remaining nodes** - Incremental value

## 🎯 SUCCESS CRITERIA

1. **Immediate**: Planner works without --cache-planner flag
2. **With flag**: Second run shows cache_read > 0 in logs
3. **Cost**: 90%+ reduction on subsequent runs with flag
4. **No regression**: All existing functionality preserved

## ⚠️ FINAL WARNINGS

1. **DON'T** modify AnthropicStructuredClient - it's perfect as-is
2. **DON'T** change PlanningNode/WorkflowGeneratorNode cache logic - just add flag check
3. **DON'T** worry about content <1024 tokens - Anthropic handles gracefully
4. **DO** test after EVERY change - the planner is critical infrastructure
5. **DO** preserve the tool-choice hack - it's what enables cache sharing

The immediate priority is fixing the ValueError. Everything else builds on that foundation.