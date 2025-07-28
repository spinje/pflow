# Architectural Decision: WorkflowExecutor as Runtime Component

## Decision

**Move WorkflowNode to the runtime layer as WorkflowExecutor**, not as a discoverable node in the nodes/ directory.

## Why This Decision

### The Problem
If WorkflowNode lived in `nodes/` as originally planned:
1. It would appear in the planner's node list
2. Users would see "workflow" as a node type they can select
3. This breaks the mental model where workflows are compositions, not components

### The Solution
By moving to `runtime/` with special compiler handling:
1. It doesn't appear in the planner
2. Users just reference workflows naturally in their IR
3. The conceptual model remains clean

## What This Means

### For Implementation
1. WorkflowNode becomes WorkflowExecutor
2. Lives in `src/pflow/runtime/workflow_executor.py`
3. Compiler handles `type: "workflow"` specially
4. Everything else remains the same

### For Users
1. They write IR exactly as planned: `"type": "workflow"`
2. They never see "workflow" in the node list
3. The mental model stays clean: nodes are building blocks, workflows are compositions

### For the Architecture
1. Establishes pattern: runtime components in `runtime/`
2. Keeps nodes/ for user-facing components only
3. Minimal special casing (just one line in compiler)

## The Key Insight

WorkflowExecutor isn't really a "node" in the user-facing sense - it's runtime machinery. Just like TemplateAwareNodeWrapper lives in runtime/, so should WorkflowExecutor. Both are runtime components that enhance execution, not building blocks users compose with.

## Implementation Priority

This decision should be implemented BEFORE writing any code for Task 20. It affects:
- Where files are created
- How tests are organized
- What documentation is written

Start with the architectural change, then implement the functionality in the correct location.
