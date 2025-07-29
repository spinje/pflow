# Workflow Interface Examples

This directory contains examples demonstrating the new workflow input/output declaration feature in pflow.

## Features Demonstrated

1. **Input Declarations**: Define expected parameters with descriptions, types, and defaults
2. **Output Declarations**: Specify what data the workflow produces
3. **Compile-time Validation**: Missing required inputs are caught before execution
4. **Default Values**: Optional inputs use defaults when not provided
5. **Workflow Composition**: Parent workflows can validate child workflow interfaces

## Examples

### 1. text_analyzer.json

A simple workflow that demonstrates:
- Required input: `text` (string) - The text to analyze
- Optional inputs with defaults:
  - `language` (string, default: "en") - Language code
  - `max_length` (number, default: 100) - Maximum summary length
- Declared outputs:
  - `summary` (string) - Generated text summary
  - `word_count` (number) - Total word count
  - `language_detected` (string) - Detected language

### 2. workflow_composition.json

Shows how workflows can compose other workflows:
- Uses the text_analyzer workflow as a node
- Maps outputs from child workflow to parent's shared store
- Demonstrates param_mapping validation against child's inputs
- Shows output_mapping validation against child's outputs

## Running the Examples

While the pflow CLI doesn't support direct parameter passing yet, you can run these examples using wrapper workflows that provide the required parameters:

### Running the Text Analyzer Example:

```bash
# Run using the wrapper workflow
uv run pflow --file examples/interfaces/run_text_analyzer.json

# See validation error for missing required input
uv run pflow --file examples/interfaces/run_missing_input.json
```

This wrapper workflow:
1. Uses the WorkflowExecutor to call `text_analyzer.json`
2. Provides the required parameters via `param_mapping`
3. Demonstrates how input validation and defaults work

The missing input example shows the helpful error message:
```
Workflow requires input 'text' (Text to analyze)
```

### Running the Workflow Composition Example:

```bash
# Run the composition example
uv run pflow --file examples/interfaces/run_workflow_composition.json
```

This wrapper:
1. Creates a test file
2. Runs the workflow composition that reads and analyzes it
3. Shows how workflows can be chained with validated interfaces

### How It Works:

The wrapper workflows use the `workflow` node type (WorkflowExecutor) to:
- Load the target workflow
- Map parameters from parent to child
- Validate inputs against declarations
- Apply default values for optional inputs

### What the Examples Demonstrate:

1. **Input Validation** - Missing required inputs cause compile-time errors
2. **Default Values** - Optional parameters use defaults when not provided
3. **Type Documentation** - Interfaces show expected types
4. **Workflow Composition** - Parent workflows can validate child interfaces

## How to Run These Examples NOW

Since the CLI doesn't support direct parameter passing yet, you need to use wrapper workflows:

### Method 1: Static Parameters (Wrapper Workflow)

```bash
# Run with hardcoded parameters
uv run pflow --file examples/interfaces/run_text_analyzer.json
```

This wrapper workflow provides the required parameters via `param_mapping`.

### Method 2: Using Stdin Data

```bash
# Pipe text data to the analyzer
echo "This is some text to analyze" | uv run pflow --file examples/interfaces/run_text_analyzer_stdin.json
```

This wrapper maps stdin data to the text parameter.

### Method 3: Create Your Own Wrapper

Create a wrapper workflow that provides the parameters you want:

```json
{
  "ir_version": "0.1.0",
  "nodes": [{
    "id": "run_analyzer",
    "type": "workflow",
    "params": {
      "workflow_ref": "examples/interfaces/text_analyzer.json",
      "param_mapping": {
        "text": "Your text here",
        "language": "es",
        "max_length": 200
      }
    }
  }]
}
```

### Note About test-node

The example workflows use `test-node` which simply passes through data. In a real workflow, you'd use actual processing nodes like `llm`, `text-processor`, etc.

## Benefits

1. **Self-documenting**: Workflows clearly declare what they need and produce
2. **Early validation**: Catch missing inputs at compile time, not runtime
3. **Better errors**: Error messages include input descriptions
4. **Composition ready**: Parent workflows can validate child interfaces
5. **IDE friendly**: Future tooling can provide autocomplete and validation
