# Task 21: Why Workflow Input/Output Declaration Matters

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

Users must open analyzer.json and hunt through all the template variables to figure out what parameters it needs. Even worse, there's no way to know what data the workflow will produce without reading through all the nodes.

### 2. The Validation Problem
Currently, if you forget to map a required parameter, you only find out at runtime when the template resolution fails deep inside the child workflow execution. Similarly, you can't validate if a workflow actually produces the outputs you're expecting to use.

### 3. The Planner Problem
The Task 17 planner needs to know workflow interfaces for composition. Currently it would have to:
- Parse the entire workflow to find all template variables
- Guess which ones are inputs vs internal variables
- Analyze all nodes to determine what outputs are produced
- Match outputs from one workflow to inputs of another blindly
- Hope it got it right

## What Input/Output Declaration Enables

### 1. Immediate Discovery
```json
// analyzer.json
{
  "ir_version": "0.1.0",
  "inputs": {
    "text": {"description": "Text to analyze", "required": true},
    "language": {"description": "Language code", "default": "en"}
  },
  "outputs": {
    "summary": {"description": "Generated summary", "type": "string"},
    "word_count": {"description": "Number of words", "type": "number"},
    "language_detected": {"description": "Detected language", "type": "string"}
  },
  // ... nodes and edges
}
```

Now it's immediately clear what the workflow needs AND what it produces.

### 2. Complete Validation
```
Error: Workflow 'analyzer.json' requires input 'text' but param_mapping does not provide it

Error: Workflow 'formatter.json' expects input 'summary' but 'analyzer.json' does not declare this output

Error: Template variable '$analyzer_result.summary' references undeclared output 'summary'
```

Fail fast with clear messages for both missing inputs AND invalid output references.

### 3. Planner Integration
The planner can read input/output declarations to:
- Know exactly what parameters to provide
- Understand what data workflows produce
- Automatically match compatible workflows (outputs → inputs)
- Generate valid template paths like `$analyzer_result.summary`
- Enable true workflow composition

### 4. Future Tooling
- IDE autocomplete for param_mapping and output references
- Workflow documentation generation showing complete interfaces
- API-like workflow contracts
- Workflow marketplace/sharing with searchable inputs/outputs
- Visual workflow composition based on compatible interfaces
- Automatic workflow chaining suggestions

## Design Philosophy

Keep it simple:
- Declarations go in the IR (the workflow contract), not metadata
- Basic types only (string, number, boolean, object, array)
- Focus on documentation and discovery
- Complete interfaces (both inputs AND outputs)
- Single source of truth for workflow contracts

This feature is about making workflows more approachable and easier to compose, not about adding complexity.

## Implementation Notes

Since this is MVP with no existing users:
- No migration needed for existing workflows
- Can make this required for all new workflows
- Metadata (name, description) remains separate from contract (IR with inputs/outputs)

## Complete Example: Workflow Composition

With input/output declarations, workflow composition becomes natural:

```json
// analyzer.json declares outputs
{
  "outputs": {
    "summary": {"type": "string"},
    "word_count": {"type": "number"}
  }
}

// formatter.json declares inputs
{
  "inputs": {
    "summary": {"type": "string", "required": true},
    "format": {"type": "string", "default": "markdown"}
  }
}

// Parent workflow can compose them confidently
{
  "nodes": [
    {
      "id": "analyze",
      "type": "workflow",
      "params": {
        "workflow_ref": "analyzer.json",
        "param_mapping": {"text": "$input_text"}
      }
    },
    {
      "id": "format",
      "type": "workflow",
      "params": {
        "workflow_ref": "formatter.json",
        "param_mapping": {
          "summary": "$analyze.summary"  // Validated at compile time!
        }
      }
    }
  ]
}
```

The system can validate this composition before execution, ensuring the data flow is correct.
