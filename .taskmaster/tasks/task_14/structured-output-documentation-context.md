# Structured Output Documentation: Context and Rationale

## The Core Problem

The pflow planner needs to generate workflows that connect nodes together, often requiring data transformation between incompatible interfaces. When nodes output complex JSON structures, the planner must generate proxy mappings with paths like `"author": "issue_data.user.login"` to extract nested values.

Currently, node metadata only declares outputs as simple key names:
```python
"""
Outputs: issue_data
"""
```

This creates a fundamental information gap: the planner cannot see that `issue_data` contains `user.login`, so it cannot generate valid paths except by:
- Guessing based on LLM training data (works for GitHub API, fails for custom APIs)
- Trial and error through validation failures
- Luck

## Why This Matters for pflow

### 1. Path-Based Proxy Mappings Are Central to pflow's Value

The proxy mapping system (documented in `architecture/core-concepts/shared-store.md`) allows workflows to:
- Extract nested data without intermediate nodes
- Connect incompatible node interfaces elegantly
- Keep workflows simple and maintainable

Without knowing data structures, this powerful feature is severely limited.

### 2. The Planner Cannot Generate What It Cannot See

When creating a workflow for "analyze github issue", the planner needs to:
1. Use github-get-issue node (outputs `issue_data`)
2. Extract the author's name for the analyzer
3. Generate mapping: `{"author": "issue_data.user.login"}`

Without structure documentation, step 3 is impossible to do reliably.

### 3. Validation Cannot Fix Generation Problems

The three-tier validation pipeline (Section 9 of task-17-planner-ambiguities.md) can detect invalid paths, but:
- By then, the wrong workflow is already generated
- The planner must regenerate blindly
- This creates a poor user experience with multiple retries

## How This Integrates with Existing Systems

### Context Builder (Task 16)
- Already extracts metadata from docstrings
- Presents node information to the planner
- Needs enhancement to parse and present structures

### Metadata Extractor
- Currently parses simple lists from docstrings
- Located in `src/pflow/registry/metadata_extractor.py`
- Has the infrastructure to be extended

### Planner (Task 17)
- Receives context from context builder
- Uses it to generate workflows
- Would immediately benefit from seeing available paths

### Node Docstring Format
- Already established pattern for documentation
- Uses structured format with sections
- Natural place to add output structures

## What Success Looks Like

When this task is complete:
1. Nodes can document their output structures in docstrings
2. The context builder includes these structures when presenting to the planner
3. The planner can generate valid nested paths on the first attempt
4. Custom and internal APIs work as well as well-known ones

## Critical Nodes Needing Documentation

Based on the existing codebase and common workflow patterns:

1. **github-get-issue** - Complex nested API response
2. **llm** - May output structured data depending on prompt
3. **claude-code** - Outputs code_report with potential structure
4. **read-file** - Simple output but sets the pattern
5. **write-file** - Even simpler, but consistency matters

## Backward Compatibility Consideration

Many existing nodes use simple output declarations:
```python
"""
Outputs: content, error
"""
```

The new system must:
- Continue to support this format
- Not break existing metadata extraction
- Allow gradual migration to structured format

## Relationship to JSON IR and Workflow Execution

This documentation is purely for the planner's benefit during workflow generation. It does not affect:
- How nodes execute at runtime
- The JSON IR structure
- The actual proxy mapping implementation

It only affects whether the planner can generate correct paths in the first place.

## Integration Points

### Where Structure Information Flows:
1. **Node Docstring** → defines structure
2. **Metadata Extractor** → parses structure from docstring
3. **Registry** → stores structure with other metadata
4. **Context Builder** → includes structure in planning context
5. **Planner** → uses structure to generate valid paths
6. **Validation** → can verify paths against structure

### What Doesn't Change:
- Node execution logic
- Shared store implementation
- Proxy mapping runtime behavior
- JSON IR schema

## Why This Cannot Be Deferred

Without structured documentation:
1. Path-based mappings only work for APIs the LLM knows
2. Users get confusing errors when paths don't exist
3. The planner's sophistication is wasted on guesswork
4. Custom/internal APIs effectively cannot use proxy mappings

This is foundational infrastructure that enables the planner to work as designed.

## The Minimal Viable Approach

This doesn't require:
- Full JSON Schema validation
- Type checking at runtime
- Complex parsing logic
- Changes to node execution

It only requires:
- A way to document structure in docstrings
- Parsing that structure into metadata
- Presenting it to the planner

The implementation can be minimal while still solving the core problem: giving the planner visibility into data structures.

## Connection to User Value

From the user's perspective:
- Workflows "just work" instead of failing with path errors
- Natural language requests successfully generate complex data flows
- Internal APIs are as easy to use as public ones
- Fewer retries and failed generation attempts

This is invisible infrastructure that dramatically improves the user experience.

## What NOT to Do - Out of Scope

### Do NOT Implement:

1. **Runtime Type Checking**
   - This is only for planner visibility, not runtime validation
   - Nodes should not validate their outputs against documented structures
   - No runtime overhead should be added

2. **Complex Type Systems**
   - No need for full JSON Schema
   - No need for Pydantic models for output structures
   - Keep it simple - just enough for the planner to see paths

3. **Automatic Structure Inference**
   - Don't try to infer structures from node code
   - Don't analyze actual API responses
   - Structure must be explicitly documented

4. **Changes to Node Execution**
   - No modifications to how nodes run
   - No changes to the shared store
   - No alterations to proxy mapping runtime

5. **Validation Beyond Path Existence**
   - Don't validate data types at planning time
   - Don't check value constraints
   - Only care about path availability

6. **Structure Enforcement**
   - Nodes can output different structures than documented
   - Documentation is a hint, not a contract
   - Flexibility is more important than strict adherence

7. **Complex Parsing Logic**
   - Avoid over-engineering the docstring parser
   - Simple JSON-like notation is sufficient
   - Don't support every edge case

8. **Integration with External Systems**
   - No OpenAPI/Swagger imports
   - No automatic API discovery
   - Manual documentation only

### Keep Focus On:
- Giving the planner visibility into structures
- Enabling correct path generation
- Maintaining backward compatibility
- Keeping implementation minimal

The goal is simply to let the planner see what paths are available, nothing more.

## Summary

Structured output documentation is not a nice-to-have validation feature. It's a fundamental requirement for the planner to generate correct workflows. Without it, the sophisticated path-based proxy mapping system is limited to well-known APIs that exist in the LLM's training data. With it, any API with documented structure can be used effectively in pflow workflows.
