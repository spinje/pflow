# Conceptual Model: Nodes vs Workflows vs Runtime Components

## The Clear Distinctions

### 1. Nodes (Building Blocks)
- **What they are**: Atomic units of computation
- **Where they live**: `src/pflow/nodes/`
- **Examples**: read-file, write-file, copy-file
- **User sees**: Listed in planner as available building blocks
- **User thinks**: "I'll use the read-file node to load my data"

### 2. Workflows (Compositions)
- **What they are**: Saved combinations of nodes
- **Where they live**: `~/.pflow/workflows/` (as JSON files)
- **Examples**: sentiment-analyzer.json, data-processor.json
- **User sees**: Listed in planner as available workflows
- **User thinks**: "I'll use my sentiment analyzer workflow"

### 3. Runtime Components (Infrastructure)
- **What they are**: Internal machinery that makes things work
- **Where they live**: `src/pflow/runtime/`
- **Examples**: TemplateAwareNodeWrapper, WorkflowExecutor
- **User sees**: Nothing - these are invisible
- **User thinks**: Nothing - they don't know these exist

## Why WorkflowExecutor is a Runtime Component

WorkflowExecutor executes workflows. It's not a building block users combine - it's the machinery that makes workflow composition possible.

### Analogy
Think of it like a kitchen:
- **Nodes** = Ingredients (flour, eggs, sugar)
- **Workflows** = Recipes (chocolate cake, apple pie)
- **WorkflowExecutor** = The oven that bakes the recipes

You don't list "oven" as an ingredient. It's infrastructure that makes recipes possible.

## The User's Mental Model

```
When I'm building a workflow:
1. I choose from nodes (building blocks)
2. I can reference saved workflows
3. I don't think about HOW workflows execute

When I write IR:
- "type": "read-file" → Use the read-file node
- "type": "workflow" → Use a workflow (which one is in params)
```

## The Implementation Model

```
When the system sees "type": "workflow":
1. Compiler recognizes this special type
2. Uses WorkflowExecutor (runtime component)
3. WorkflowExecutor loads and runs the specified workflow
4. User never knows WorkflowExecutor exists
```

## Why This Matters

If WorkflowNode appeared in the planner:
- Users would see "workflow" as a node type
- Conceptual confusion: "Is workflow a building block?"
- Recursive confusion: "Can I put a workflow node in my workflow?"
- Mental model breaks down

With WorkflowExecutor as runtime component:
- Planner stays clean - only shows actual building blocks
- Mental model stays clear - workflows are compositions
- Implementation stays flexible - we can change how workflows execute

## The Principle

**User-facing components go in nodes/**
**Infrastructure goes in runtime/**

WorkflowExecutor is infrastructure, not a user-facing component.
