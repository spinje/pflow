# Task 28: Prompt Improvement Handoff - The Real Story

## 🎯 Current State & What We Actually Achieved

**Where we are now:**
- `metadata_generation`: 90% accuracy (was 16.7%)
- `component_browsing`: 91.7% accuracy (was 16.7%)
- `discovery`: 100% accuracy (was 52.6%)
- `workflow_generator`: Updated to generate purpose fields
- `parameter_discovery` & `parameter_mapping`: Still at 0% (untouched)

**The real achievement**: We didn't just improve accuracy - we fundamentally transformed how pflow understands workflows through semantic purpose fields and rich context provision.

## 🧠 The Meta-Breakthrough That Changes Everything

### Context Provision >>> Prompt Wording

This is THE insight. We spent minimal time rewording prompts and maximum time enriching context. Here's what actually moved the needle:

**For metadata_generation:**
```xml
<!-- BEFORE: Just a list -->
<nodes>github-list-issues, llm, write-file</nodes>

<!-- AFTER: Four layers of understanding -->
<flow>github-list-issues → llm → write-file</flow>
<stages>
1. github-list-issues: Fetch closed issues for changelog generation
2. llm: Analyze and format as structured changelog
3. write-file: Save formatted changelog to file
</stages>
<inputs>
• repo_owner [string, required]
  The GitHub repository owner
• issue_count [integer, optional, default=20]
  Number of issues to fetch
</inputs>
<parameter_bindings>
• repo_owner → github-list-issues
• issue_count → github-list-issues
</parameter_bindings>
```

The arrows in the flow are NOT decorative - they show causality and data flow. The LLM can now SEE what the workflow does, not just what nodes it has.

## ⚠️ The Purpose Field Crisis & Recovery

### What Happened
1. Added purpose as required field with min=10, max=200 chars
2. **88 test failures** - entire test suite exploded
3. User made the pragmatic call: "do you think this was the right call?"
4. Pivoted to optional in schema, required in generation

### The Pattern That Saved Us
```python
# In IR schema - optional
"purpose": {"type": "string", "description": "..."}  # NO required

# In Pydantic model - validates when present
purpose: str = Field(..., min_length=10, max_length=200)

# In generator prompt - ENFORCED
"9. EVERY node MUST have a clear purpose field"

# In consumers - graceful fallback
purpose = node.get("purpose", "No purpose specified")
```

This is THE pattern for MVP development: **Gradual Enhancement**. New code gets the feature, old code doesn't break.

## 🔧 Critical Technical Implementations

### 1. Recursive Parameter Extraction (`nodes.py:1509-1536`)
```python
def _extract_templates_from_params(self, params: dict[str, Any]) -> set[str]:
    """This handles ANY nesting level - dicts in lists in dicts"""
    templates = set()

    def _scan_value(value: Any) -> None:
        if isinstance(value, str):
            templates.update(TemplateResolver.extract_variables(value))
        elif isinstance(value, dict):
            for v in value.values():
                _scan_value(v)  # Recursive!
        elif isinstance(value, list):
            for item in value:
                _scan_value(item)  # Recursive!

    _scan_value(params)
    return templates
```

**Critical detail**: Must distinguish `${input_param}` from `${node_id.output}` - see lines 1558-1563 for the check.

### 2. Flow Visualization Reuse (`context_builder.py:571-608`)
We reused `_build_node_flow()` everywhere. BUT there's a gotcha - some tests create nodes without IDs. I had to add graceful handling (lines 580-583).

### 3. Rich Input Formatting (`nodes.py:1572-1599`)
Shows type, required/optional, default, AND description. This transformed metadata quality.

## 🧪 The Test Philosophy Revolution

### What We Learned About Test Quality

**STOP testing exact keywords**. The test expected "priority" but the LLM wrote "Prioritizes issues by severity" - that's SUCCESS, not failure.

**Semantic equivalence patterns we fixed:**
- "priority" → accepts "prioritize", "prioritizes", "prioritization"
- "archive" → accepts "archival", "archiving", "archived"
- "log" → accepts "logs", "logging"

See `tests/test_planning/llm/prompts/test_metadata_generation_prompt.py:297-323` for implementation.

**Forbidden values trap**: Test forbade "config" but LLM wrote "configuration backup" - that's generic, not specific! Only forbid truly problematic values like numbers, specific names, paths.

## 📊 Model Performance Variance

**This matters more than you think:**
- `gpt-5-nano`: 50-60% accuracy, $0.007 per test run, fast
- `claude-sonnet-4-0`: 90% accuracy, $0.09 per test run, slow

**Strategy that worked**: Iterate with gpt-5-nano until ~60%, then validate with Claude. Don't chase 90% with the cheap model - timeouts ≠ logic failures.

## 🏗️ Architectural Decisions & Their Ripple Effects

### 1. Removed `discovered_params` from metadata prompt
- They're intermediate hints from parameter discovery
- Workflow inputs are the canonical source
- Having both creates confusion about what's "real"

### 2. Deleted `nodes_summary`
- The flow contains all nodes already
- Single source of truth principle
- If it exists in two places, it WILL diverge

### 3. Made purpose optional in schema
- 88 test failures → 14 test failures
- Backward compatibility preserved
- New workflows get semantic understanding
- Old workflows still work

## 📁 Key Files You Need to Know

**Modified for purpose field:**
- `/src/pflow/core/ir_schema.py` - Schema definition (lines 135-140)
- `/src/pflow/planning/ir_models.py` - Pydantic model (lines 13-18)
- `/src/pflow/planning/prompts/workflow_generator.md` - Generation enforcement (lines 43-50)

**Enhanced for rich context:**
- `/src/pflow/planning/nodes.py` - All the new methods (lines 1509-1639)
- `/src/pflow/planning/prompts/metadata_generation.md` - New template structure
- `/src/pflow/planning/context_builder.py` - Flow visualization (lines 571-608)

**Test files showing patterns:**
- `/tests/test_planning/llm/prompts/test_metadata_generation_prompt.py` - Semantic keyword matching
- `/tests/test_core/test_ir_schema.py` - How we added purpose to 29 test nodes
- `/tests/test_planning/test_ir_models.py` - Pydantic model tests with purpose

## ⚠️ Warnings & Gotchas

### 1. The Purpose Strictness Trap
DON'T make purpose required in schema. We tried. 88 test failures. The gradual enhancement approach works.

### 2. Node Output vs Input Parameter Confusion
When extracting templates, `${node_id.output}` is NOT an input parameter. Check if the base variable before the dot matches a node ID (see `nodes.py:1558-1563`).

### 3. Test Quality Traps
- Don't test exact keywords - test semantic meaning
- Don't forbid generic terms like "config" or "data"
- Don't test confidence scores - test decisions
- 10 good tests > 50 mediocre ones

### 4. Context Builder Graceful Degradation
Some tests create nodes without IDs. The `_build_node_flow` function now handles both formats (see `context_builder.py:580-583`).

## 🚀 Applying These Patterns to Remaining Prompts

### For `parameter_discovery` & `parameter_mapping` (0% accuracy)
These need the most work. They would benefit from:
- Seeing workflow purposes to understand intent
- Rich input specifications to know what's configurable
- Parameter bindings to understand data flow

### For `workflow_generator`
Already updated with purpose generation. Could benefit from:
- Examples of good vs bad purposes
- Pattern library of successful workflows

### For other prompts
The pattern is clear:
1. Enhance context FIRST (what data is missing?)
2. Show flow, not lists
3. Include purposes when available
4. Rich specifications > simple lists
5. Test semantic correctness, not exact matches

## 💎 The Deepest Insights

1. **Purpose transforms intent**: Forcing nodes to explain their purpose prevents over-engineering and ensures each step has a reason to exist.

2. **Arrows reveal understanding**: `A → B → C` shows causality. `A, B, C` shows existence. The arrow IS the understanding.

3. **Gradual enhancement is THE pattern**: Optional in schema, required in new code, graceful fallbacks. Progress without breakage.

4. **Context provision is 80% of the solution**: Better data beats better instructions every time.

5. **Single source of truth**: If information exists in two places, it will diverge. Pick one, delete the other.

## 🔗 Links to Critical Documentation

- **Progress log with all insights**: `.taskmaster/tasks/task_28/implementation/progress-log.md`
- **Discovery handoff**: `.taskmaster/tasks/task_28/starting-context/handover-from-discovery-node-agent.md`
- **Component browsing handoff**: `.taskmaster/tasks/task_28/starting-context/handover-from-component-browsing-agent.md`
- **Implementation steps**: `.taskmaster/tasks/task_28/starting-context/implementation-steps.md`

## 🎬 Final Words

The purpose field implementation is more than a feature - it's a philosophical shift. We're no longer connecting nodes; we're composing intentions. The metadata improvements aren't just about accuracy; they're about genuine semantic understanding.

The test philosophy changes aren't just about making tests pass; they're about testing what actually matters to users.

The gradual enhancement pattern isn't just about backward compatibility; it's about shipping working code while improving systematically.

---

**To the next agent**: Don't just implement - understand WHY these patterns work. The context provision breakthrough applies everywhere. The purpose field transforms everything it touches. And remember: when you hit 88 test failures, sometimes the answer is to make the field optional.

**IMPORTANT**: Do not begin implementing immediately. Read this entire handoff, review the progress log, understand the patterns, and then explicitly state "I'm ready to begin" before starting any work.