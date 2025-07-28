# Task 21: Why Workflow Input Declaration Matters

## The Bigger Picture

pflow is evolving from "workflows as scripts" to "workflows as reusable components". This transition requires workflows to be more like functions - with clear interfaces that declare what they expect and what they provide.

## Current Pain Points

### 1. The Discovery Problem
```json
// parent_workflow.json wants to use analyzer.json
{
  "id": "analyze_step",
  "type": "workflow",
  "params": {
    "workflow_ref": "analyzer.json",
    "param_mapping": {
      "???": "$my_text"  // What parameter name does analyzer expect?
    }
  }
}
```

Users must open analyzer.json and hunt through all the template variables to figure out what parameters it needs.

### 2. The Validation Problem
Currently, if you forget to map a required parameter, you only find out at runtime when the template resolution fails deep inside the child workflow execution.

### 3. The Planner Problem
The Task 17 planner needs to know what parameters workflows expect. Currently it would have to:
- Parse the entire workflow
- Find all template variables
- Guess which ones are inputs vs internal variables
- Hope it got it right

## What Input Declaration Enables

### 1. Immediate Discovery
```json
// analyzer.json
{
  "inputs": {
    "text": {"description": "Text to analyze", "required": true},
    "language": {"description": "Language code", "default": "en"}
  },
  // ... rest of workflow
}
```

Now it's immediately clear what the workflow needs.

### 2. Compile-Time Validation
```
Error: Workflow 'analyzer.json' requires input 'text' but param_mapping does not provide it
```

Fail fast with clear messages.

### 3. Planner Integration
The planner can read input declarations and know exactly what parameters to provide, including descriptions for context.

### 4. Future Tooling
- IDE autocomplete for param_mapping
- Workflow documentation generation
- API-like workflow interfaces
- Workflow marketplace/sharing

## Design Philosophy

Keep it simple:
- Optional feature (backward compatible)
- Basic types only (string, number, etc.)
- Focus on documentation and discovery
- Not about strict typing or complex validation

This feature is about making workflows more approachable and easier to compose, not about adding complexity.
