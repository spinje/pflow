# Workflow Generator Prompt - Real-World Optimization Plan

## Current State Analysis

### What We Added for Tests (That Hurts Real Usage)
1. **Overly strict sequential enforcement** - Fighting LLM's correct instincts for efficiency
2. **Long 6-node example** - 175 lines of JSON for one example (huge token cost!)
3. **Repetitive warnings** - Same concepts explained 3-4 times
4. **Validation error patterns** - LLMs regenerate anyway, don't do surgical fixes

### What Actually Matters for Real Usage
1. **Core distinction**: User inputs vs node outputs
2. **Purpose fields**: Make workflows self-documenting
3. **Valid structure**: Must compile and execute
4. **Practical workflows**: Get the job done efficiently

## Token & Performance Analysis

Current prompt: ~650 lines including example
- Mental model: 7 lines ✅ (valuable)
- Sequential warning: 22 lines ⚠️ (fights good instincts)
- Complexity guide: 11 lines ✅ (helpful)
- Purpose requirements: 6 lines ✅ (essential)
- 6-node example: 175 lines ❌ (excessive!)
- Structure requirements: 8 lines ✅ (needed)
- Common mistakes: 10 lines 🔄 (redundant)
- Validation errors: 24 lines ❌ (rarely helps)
- Discovered params: 8 lines ✅ (useful)

**Total waste: ~200+ lines that don't help real usage**

## Optimization Strategy

### 1. Replace Long Example with Compact Patterns
Instead of 175-line JSON example, show patterns:
```
Simple (2-3 nodes): fetch → process → save
Medium (4-6 nodes): fetch → filter → analyze → generate → save → notify
Complex (7+ nodes): multiple sources → multiple analyses → multiple outputs
```

### 2. Merge Redundant Sections
Combine:
- Core Pattern Rules + Common Mistakes → Single "Key Rules" section
- Workflow Structure + Output Requirements → Single "Requirements" section
- Sequential warning + Complexity guide → Single "Execution Model" section

### 3. Trust the LLM More
Remove:
- Detailed validation error patterns (LLMs regenerate anyway)
- Repetitive warnings about same concepts
- Over-explanation of obvious things

### 4. Acknowledge Reality
Instead of fighting parallel instincts:
```
Note: Parallel execution would be optimal but system currently executes sequentially.
Design the most logical workflow - we'll handle execution order.
```

### 5. Focus on Patterns, Not Rules
LLMs learn better from patterns than prescriptive rules:
- Show input→output pattern once clearly
- Trust it to apply the pattern
- Don't repeat the same warning 5 times

## Proposed Optimized Structure

```markdown
# Workflow Generator

Generate workflow for: {{user_input}}

## Core Concept
Workflows are data pipelines: Users provide inputs → Nodes transform data → Results flow forward

## Key Rules
- User provides → Goes in "inputs" as ${param}
- Node generates → Reference as ${node.output}, never in inputs
- Every input declared must be used
- Every node needs a purpose (10-200 chars, specific to this workflow)

## Workflow Patterns
Simple: read → process → save
Complex: fetch_multiple → analyze → generate_multiple → save_multiple

## Example (Compact)
```json
{
  "nodes": [
    {"id": "fetch", "type": "github-list-issues", "purpose": "Get issues for changelog",
     "params": {"repo": "${repo}", "limit": "${limit}"}},
    {"id": "generate", "type": "llm", "purpose": "Format as changelog",
     "params": {"prompt": "Create changelog: ${fetch.issues}"}},
    {"id": "save", "type": "write-file", "purpose": "Save changelog file",
     "params": {"path": "${output_path}", "content": "${generate.response}"}}
  ],
  "edges": [{"from": "fetch", "to": "generate"}, {"from": "generate", "to": "save"}],
  "inputs": {
    "repo": {"type": "string", "required": true},
    "limit": {"type": "integer", "default": 20},
    "output_path": {"type": "string", "default": "CHANGELOG.md"}
  },
  "outputs": {
    "file": {"description": "Saved file", "source": "${save.path}"}
  }
}
```

## Technical Requirements
- Include "ir_version": "0.1.0"
- Sequential execution only (one outgoing edge per node)
- Outputs need "source" field for namespacing

<available_nodes>
{{planning_context}}
</available_nodes>

{{#if validation_errors}}
Fix these errors: {{validation_errors}}
{{/if}}
```

**Reduction: From 650 lines to ~100 lines (85% reduction!)**

## Expected Improvements

### For Real Usage
1. **Better workflows** - Not fighting parallel instincts
2. **Faster generation** - 85% fewer tokens to process
3. **More flexible** - Trusts LLM judgment more
4. **Clearer intent** - Focus on what matters

### Performance Gains
- Input tokens: -85% (faster, cheaper)
- Output quality: Better (not over-constrained)
- Generation time: Much faster
- Maintenance: Easier (less to update)

## Critical Tradeoffs

### What We Lose
1. Explicit validation error patterns (but LLMs don't use them well anyway)
2. Detailed sequential enforcement (but this fights good instincts)
3. Long example (but patterns are clearer)

### What We Gain
1. Clarity and conciseness
2. Trust in LLM capabilities
3. Better real-world workflows
4. Massive token savings

## Implementation Priority

1. **MUST KEEP**: Template variable distinction, purpose requirement
2. **SHOULD SIMPLIFY**: Example to show pattern only
3. **SHOULD REMOVE**: Validation patterns, redundant warnings
4. **SHOULD ACKNOWLEDGE**: Sequential is limitation, not ideal