# Task 100: Implement Reduce/Fold Mode for Batch Processing

## Description
Add a `mode: "reduce"` option to batch processing that enables sequential chained operations where each iteration's output becomes the next iteration's input. This enables fold/accumulate patterns that are currently impossible in pflow without temp file workarounds.

## Status
not started

## Dependencies
- Task 96: Support Batch Processing in Workflows - The reduce mode builds on top of the existing batch infrastructure, extending it with a new execution mode

## Priority
medium

## Details
Currently, pflow's batch processing operates in **map** mode - each iteration receives the same input and produces independent outputs that are collected into a results array. This works well for parallel transformations but fails for use cases requiring sequential accumulation.

### The Problem

When building the `webpage-to-markdown-with-images` workflow, we needed to:
1. Take a markdown document
2. Apply N replacements sequentially (one per image)
3. Each replacement modifies the result of the previous one

This is impossible with current batch because:
- Templates like `${markdown.stdout}` are resolved **once** at batch start
- Each iteration sees the original value, not the modified value from previous iterations
- We had to use temp files as a workaround (write to file, each iteration reads/modifies file)

### Proposed Solution

Add a `mode` option to batch configuration:

```json
{
  "id": "apply-replacements",
  "type": "shell",
  "batch": {
    "items": "${replacements.stdout}",
    "mode": "reduce",
    "initial": "${markdown.stdout}"
  },
  "params": {
    "stdin": "${accumulator}",
    "command": "sed 's|${item.find}|${item.replace}|g'"
  }
}
```

### Behavior

**Map mode** (current default):
```
items: [a, b, c]
input: X (resolved once)

Iteration 1: X + a → result_1
Iteration 2: X + b → result_2
Iteration 3: X + c → result_3

Output: ${node.results} = [result_1, result_2, result_3]
```

**Reduce mode** (new):
```
items: [a, b, c]
initial: X

Iteration 1: X + a → acc_1
Iteration 2: acc_1 + b → acc_2
Iteration 3: acc_2 + c → acc_3

Output: ${node.result} = acc_3 (single value, not array)
```

### Key Design Decisions

1. **New template variable**: `${accumulator}` available in reduce mode, holds output from previous iteration (or `initial` for first iteration)
2. **Forces sequential**: Reduce mode automatically sets `parallel: false` (parallelism doesn't make sense for chained operations)
3. **Single output**: `${node.result}` returns final accumulated value, not an array
4. **Backwards compatible**: Default mode remains "map", existing workflows unchanged

### Implementation Considerations

- Modify `BatchNode` in `src/pflow/runtime/batch_node.py` to support the new mode
- Add `initial` parameter resolution
- Track accumulator state between iterations
- Update template resolver to recognize `${accumulator}`
- Ensure proper error handling - if any iteration fails, the reduce stops

## Test Strategy
Testing should verify both the new reduce mode and ensure existing map mode is unaffected:

### Unit Tests
- Test reduce mode with simple numeric accumulation
- Test reduce mode with string concatenation/modification
- Test that `${accumulator}` resolves correctly per iteration
- Test `initial` value is used for first iteration
- Test error handling when an iteration fails mid-reduce
- Test that `parallel: true` is ignored/overridden in reduce mode

### Integration Tests
- Test reduce mode in a full workflow (the image replacement use case)
- Test reduce mode with different node types (shell, llm)
- Verify existing map-mode batch workflows still work unchanged

### Edge Cases
- Empty items array with reduce mode
- Single item in reduce mode
- Large number of iterations (performance)
- Accumulator containing special characters/JSON
