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

### Basic execution with all inputs:
```bash
pflow run examples/interfaces/text_analyzer.json \
  --param text="Hello world, this is a test" \
  --param language="en" \
  --param max_length=50
```

### Using default values (omit optional params):
```bash
pflow run examples/interfaces/text_analyzer.json \
  --param text="Hello world, this is a test"
```

### Missing required input (will show helpful error):
```bash
pflow run examples/interfaces/text_analyzer.json
# Error: Workflow requires input 'text' (Text to analyze)
```

### Workflow composition:
```bash
pflow run examples/interfaces/workflow_composition.json \
  --param file_path="input.txt"
```

## Benefits

1. **Self-documenting**: Workflows clearly declare what they need and produce
2. **Early validation**: Catch missing inputs at compile time, not runtime
3. **Better errors**: Error messages include input descriptions
4. **Composition ready**: Parent workflows can validate child interfaces
5. **IDE friendly**: Future tooling can provide autocomplete and validation
