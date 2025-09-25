## ⚠️ CRITICAL: Multiple Item Processing Required

This request needs to process MULTIPLE items separately (detected 'each', 'every', or similar pattern).

**The workflow system has NO built-in iteration/loops.** You MUST handle this manually using LLM nodes to transform data.

### Required Pattern for Multiple Items:

**Step 1: Extract items as structured JSON**
Use an LLM node to extract and structure ALL items:
```json
{
  "id": "extract_items",
  "type": "llm",
  "purpose": "Extract each item as structured JSON array",
  "params": {
    "prompt": "Extract each [item] and process it. Output as JSON array:\n[{\"field1\": \"...\", \"field2\": \"...\"}, ...]\n\nData: ${previous_node.output}"
  }
}
```

**Step 2: Transform to target format**
Use another LLM node to reshape for the target operation:
```json
{
  "id": "format_for_target",
  "type": "llm",
  "purpose": "Transform JSON array into required format",
  "params": {
    "prompt": "Convert this JSON to [target format]:\n${extract_items.response}\n\nFor each item, create [appropriate structure].\nOutput: [[item1_data], [item2_data], ...]"
  }
}
```

**Step 3: Single batch operation**
Pass the formatted data to the target node:
```json
{
  "id": "batch_operation",
  "params": {
    "data": "${format_for_target.response}"  // Multiple items, not one
  }
}
```

### Common Mistakes to Avoid:

❌ **WRONG**: Combining all items into one entry
- Single row with all data: `[["timestamp", "all questions together", "all answers together"]]`
- Single message with all content: `"Here are all the summaries: ..."`

✅ **CORRECT**: Separate entries for each item
- Multiple rows: `[["timestamp", "question1", "answer1"], ["timestamp", "question2", "answer2"]]`
- Multiple messages/files/operations: Each item processed individually

### Validation Check:
Ask yourself: "If the user said 'each X', am I creating MULTIPLE Xs or just ONE X with everything inside?"
The answer should always be MULTIPLE.