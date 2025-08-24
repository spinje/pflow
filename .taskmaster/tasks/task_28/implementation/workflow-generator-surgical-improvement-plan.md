# Workflow Generator Surgical Improvement Plan

## Core Behaviors We're Testing For

### 1. **Template Variable Semantics** (MOST CRITICAL)
The LLM must understand the fundamental distinction:
- User provides: repo_name, file_path, limit → goes in "inputs"
- Nodes generate: issues, response, data → referenced as ${node.output}, NOT in inputs

This is THE hardest concept. Most failures stem from this confusion.

### 2. **Input-to-Usage Coupling**
Every input declared must be used. Every template variable used must be declared (unless it's a node output).
This is a bidirectional constraint that ensures workflow validity.

### 3. **Complex Workflow Decomposition**
An 8-step request needs 8+ nodes, not 4. Each distinct operation needs its own node.
The LLM tends to compress steps, missing intermediate transformations.

### 4. **Validation Error Recovery**
When given specific errors, the LLM must parse and fix them surgically, not regenerate from scratch.

## Root Cause Analysis of Current Prompt

### What's Working Well
- Purpose field requirement is clear
- Linear workflow constraint is understood
- Basic template variable syntax is followed

### What's Failing

1. **Information Overload**: Too many warnings and rules dilute the critical message
2. **Lack of Concrete Examples**: The example shows a 2-node toy workflow, not the 6-10 node reality
3. **Validation Recovery Too Generic**: "Fix the errors" vs specific patterns for each error type
4. **Missing Mental Model**: The prompt doesn't build intuition for WHY these rules exist

## Surgical Improvement Strategy

### Strategy 1: Build the Right Mental Model FIRST
Instead of rules, explain the SYSTEM:
- Workflows are data pipelines
- Users provide starting parameters
- Each node transforms data and passes it forward
- The "inputs" section is the workflow's API

### Strategy 2: Show, Don't Tell
Replace the toy example with a REAL 6-node changelog workflow that demonstrates:
- Multiple node outputs feeding forward
- Clear distinction between inputs and generated data
- Realistic complexity

### Strategy 3: Validation Recovery Patterns
Instead of generic "fix errors", provide specific patterns:
- "Template variable ${X} not defined" → Add X to inputs
- "Input Y never used" → Remove Y from inputs
- "Node type 'Z' not found" → Check available nodes for correct name

### Strategy 4: Simplify Critical Rules
Reduce cognitive load by consolidating rules:
- ONE rule about inputs
- ONE rule about node outputs
- ONE rule about complexity
- ONE rule about validation

### Strategy 5: Visual Structure
Use formatting to create visual hierarchy:
- 🔴 for critical NEVER do this
- ✅ for ALWAYS do this
- Clear sections with purpose

## Specific Surgical Changes

### Change 1: Add System Mental Model (NEW)
```
## Understanding the System:
Workflows are DATA PIPELINES where:
1. Users provide STARTING PARAMETERS (inputs)
2. Each node TRANSFORMS data and outputs results
3. Later nodes CONSUME outputs from earlier nodes
4. The "inputs" section defines the workflow's API - what users can configure
```

### Change 2: Replace Toy Example with Real One
Current: 2-node joke generator
New: 6-node changelog generator showing:
- GitHub data → LLM analysis → file writing → git operations
- Clear ${fetch_issues.issues} → ${analyze.response} flow
- Realistic input parameters

### Change 3: Consolidate Rules into Clear Patterns
Instead of numbered lists, use pattern matching:
```
## Core Patterns:

**If user provides it** → Goes in "inputs" section
**If a node generates it** → Reference as ${node_id.output}
**If you declare an input** → You MUST use it
**If you use ${variable}** → It MUST be declared OR be a node output
```

### Change 4: Specific Validation Fix Patterns
```
## Fixing Validation Errors:

Error: "Template variable ${repo} not defined"
→ Fix: Add "repo" to inputs section

Error: "Input 'output_file' never used"
→ Fix: Remove "output_file" from inputs (it's probably node-generated)

Error: "Node type 'github_commits' not found"
→ Fix: Use 'github-list-commits' (check available nodes)
```

### Change 5: Complexity Guidance
```
## Workflow Complexity Guide:

Simple request (1-2 operations) → 2-3 nodes
Medium request (3-4 operations) → 4-6 nodes
Complex request (5+ operations) → 6-10+ nodes

Each distinct step needs its own node:
- Fetching data → 1 node
- Each analysis → 1 node
- Each output file → 1 node
```

## Expected Impact

1. **Template Variable Confusion**: Mental model + real example should reduce from 40% error to <10%
2. **Unused Inputs**: Clear coupling rule should eliminate these
3. **Complexity**: Guide should ensure proper decomposition
4. **Validation Recovery**: Specific patterns should improve from 0% to 80%+

## Implementation Priority

1. **FIRST**: Add mental model section (builds intuition)
2. **SECOND**: Replace example with realistic 6-node workflow
3. **THIRD**: Add validation fix patterns
4. **FOURTH**: Simplify and consolidate rules
5. **FIFTH**: Add complexity guide

This approach doesn't overfit to tests but addresses the fundamental conceptual gaps that cause failures.