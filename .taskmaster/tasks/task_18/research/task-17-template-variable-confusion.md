# Task 17: Template Variable System Confusion

## Executive Summary

The task-17-context-and-implementation-details.md document extensively describes two JSON fields - `template_inputs` and `variable_flow` - that don't exist in the actual IR schema. This document analyzes the confusion, explains why it arose, and proposes a simpler solution that aligns with the actual implementation.

## The Problem

### What the Document Describes

The document presents an elaborate template variable system with two core components:

1. **`template_inputs`** - Supposedly stores template strings for node inputs:
```json
{
  "template_inputs": {
    "claude-code": {
      "prompt": "Fix this issue:\n$issue\n\nGuidelines:\n$coding_standards",
      "dependencies": ["issue", "coding_standards"]
    },
    "llm": {
      "prompt": "Write commit message for: $code_report"
    }
  }
}
```

2. **`variable_flow`** - Supposedly maps template variables to their sources:
```json
{
  "variable_flow": {
    "issue": "github-get-issue.outputs.issue_data",
    "issue_title": "github-get-issue.outputs.title",
    "code_report": "claude-code.outputs.code_report",
    "coding_standards": "read-file.outputs.content"
  }
}
```

### What Actually Exists

The real IR schema (`src/pflow/core/ir_schema.py`) only supports:
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "n1", "type": "github-get-issue", "params": {"issue": "$issue_number"}}
  ],
  "edges": [...],
  "start_node": "...",
  "mappings": {
    "node_id": {
      "input_mappings": {"key": "value"},
      "output_mappings": {"key": "value"}
    }
  }
}
```

Note: NO `template_inputs` or `variable_flow` fields exist!

## Why This Confusion Arose

### The Template Variable Challenge

Template variables serve two distinct purposes:

1. **Initial Parameters from User Input**
   - User says: "fix github issue 1234"
   - Planner extracts: `{"issue_number": "1234"}`
   - Workflow uses: `$issue_number`
   - Challenge: Where does "1234" come from at runtime?

2. **Inter-Node Data Flow**
   - Node A writes: `shared["issue_data"]`
   - Node B needs: `"Fix this issue: $issue_data"`
   - Challenge: How does the template get resolved?

### The Document's Overengineered Solution

The document tried to solve both challenges with explicit mappings:
- `template_inputs` to define where templates are used
- `variable_flow` to map every variable to its source

This creates several problems:
1. **Not in schema** - These fields don't exist
2. **Redundant** - Simple name matching would work
3. **Complex** - Requires LLM to generate complete mappings
4. **Inflexible** - Hardcodes data flow paths

## How Template Variables Actually Work

### Current Reality

Template variables CAN exist in node params:
```json
{
  "nodes": [
    {"id": "get-issue", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
    {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze: $issue_data"}}
  ]
}
```

But there's no mechanism in the IR to:
- Define where `$issue_number` gets its value
- Specify that `$issue_data` comes from `get-issue`

### The Real Challenge: Prompts as Shared Store Inputs

PocketFlow nodes have:
- **Static params** (set via `set_params()`) - configuration
- **Dynamic shared** (accessed in `exec()`) - runtime data

But prompts often need to be dynamic! An LLM node might need:
```
"Fix this issue: [CONTENT FROM SHARED STORE]
Following guidelines: [MORE CONTENT FROM SHARED STORE]"
```

This is why the document invented `template_inputs` - to define dynamic inputs separate from static params.

## The Simpler Solution

### 1. Template Variables in Params (Already Supported)

Keep template variables in params as the schema already allows:
```json
{
  "nodes": [
    {"id": "n1", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
    {"id": "n2", "type": "llm", "params": {"prompt": "Fix issue: $issue_data\nStandards: $coding_standards"}}
  ]
}
```

### 2. Two-Phase Substitution at Runtime

**Phase 1: Initial Parameter Substitution (from user input)**
```python
# Planner returns:
{
  "workflow_ir": {...},
  "parameter_values": {"issue_number": "1234"}  # Extracted from "fix issue 1234"
}

# CLI/Runtime substitutes in params:
params["issue"] = "$issue_number" → "1234"
```

**Phase 2: Shared Store Substitution (during execution)**
```python
# Before executing node n2:
# - shared["issue_data"] exists (written by n1)
# - shared["coding_standards"] exists (written by earlier node)

# Runtime resolves template in params:
params["prompt"] = "Fix issue: $issue_data\nStandards: $coding_standards"
                 → "Fix issue: {actual issue data}\nStandards: {actual standards}"
```

### 3. Simple Name Matching Rules

- `$foo` → `shared["foo"]`
- `$foo_bar` → `shared["foo_bar"]`
- No complex paths needed for MVP
- No explicit mappings required

### 4. Parameter Values from Planner

The planner only needs to return:
```json
{
  "workflow_ir": {
    "ir_version": "0.1.0",
    "nodes": [...],  // Contains $variables in params
    "edges": [...]
  },
  "parameter_values": {
    "issue_number": "1234",  // Extracted from natural language
    "date": "2024-01-15"     // Interpreted from "yesterday"
  }
}
```

## Implementation Details

### For Nodes with Dynamic Prompts

Nodes that need dynamic prompts use template strings in params:
```python
# In IR:
{"type": "llm", "params": {"prompt": "Summarize: $content", "temperature": 0.7}}

# At runtime, before node execution:
# 1. Runtime checks params for $ variables
# 2. Substitutes from shared store
# 3. Node receives resolved prompt
```

### For Initial Parameters

CLI receives parameter_values from planner and:
1. Validates all `$variables` in workflow have values
2. Substitutes during workflow compilation
3. Executes with resolved values

### Error Handling

- Missing initial parameter: "Parameter '$issue_number' not provided"
- Missing shared store key: "Template variable '$issue_data' not found in shared store"
- Clear, actionable errors

## Why This is Better

1. **Simpler** - No complex mapping structures
2. **Aligned with Schema** - Uses existing IR structure
3. **Flexible** - Nodes can use templates anywhere in params
4. **Natural** - `$foo` naturally maps to `shared["foo"]`
5. **Maintainable** - Less for LLM to generate correctly

## Migration Path

### Update Documentation

1. Remove all references to `template_inputs` and `variable_flow`
2. Clarify that template variables live in params
3. Explain two-phase substitution
4. Update examples to use actual schema

### Update Prompt Templates

Remove instructions about generating `template_inputs` and `variable_flow`. Instead:
```
Generate workflows where:
- Use $variables in params for dynamic values
- Initial parameters (from user input) use names like $issue_number
- Shared store references use names matching what nodes output
```

### Update Anti-Patterns

Add:
- Don't generate template_inputs (doesn't exist)
- Don't generate variable_flow (doesn't exist)
- Don't create complex mapping structures

## Validation Considerations

The planner should validate:
1. All `$variables` in params are either:
   - In parameter_values (initial parameters)
   - Will be written by earlier nodes (shared store)
2. No circular dependencies
3. Resolution order is possible

But this is much simpler than tracking explicit mappings.

## Example: Complete Flow

**User Input**: "fix github issue 1234"

**Planner Returns**:
```json
{
  "workflow_ir": {
    "ir_version": "0.1.0",
    "nodes": [
      {"id": "get", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
      {"id": "fix", "type": "claude-code", "params": {"prompt": "Fix this issue: $issue_data"}},
      {"id": "commit", "type": "git-commit", "params": {"message": "$commit_message"}}
    ],
    "edges": [
      {"from": "get", "to": "fix"},
      {"from": "fix", "to": "commit"}
    ]
  },
  "parameter_values": {
    "issue_number": "1234"
  }
}
```

**Runtime Execution**:
1. Substitute `$issue_number` → "1234" in get node
2. Execute get node → writes `shared["issue_data"]`
3. Substitute `$issue_data` → actual issue content in fix node
4. Execute fix node → writes `shared["commit_message"]`
5. Substitute `$commit_message` → actual message in commit node
6. Execute commit node

Simple, clean, and aligned with actual implementation.

## Summary

The document's `template_inputs` and `variable_flow` are overengineered solutions to a simple problem. Template variables in params + two-phase substitution (initial parameters and shared store) provides everything needed for the "Plan Once, Run Forever" philosophy without adding complexity that doesn't exist in the actual system.

The key insight: **Keep it simple**. Template variables are just strings that get substituted. The runtime can handle this without elaborate mapping structures.
