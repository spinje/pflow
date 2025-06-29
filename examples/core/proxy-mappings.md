# Proxy Mappings Example

## Purpose
This example demonstrates the NodeAwareSharedStore proxy pattern for handling incompatible node interfaces. It shows:
- How to map between different key names nodes expect
- Input and output transformations
- Enabling node reuse without modification

## Use Case
Proxy mappings are crucial when:
- Integrating nodes with different naming conventions
- Reusing nodes designed for different contexts
- Building adapters between incompatible components
- Creating clean interfaces between workflow stages

## Visual Flow
```
[csv-reader] → [sentiment-analyzer] → [report-generator]
     ↓                ↓                      ↓
csv_content ──┐    text              analysis_results
              └─►  sentiment_scores ──┐      data
                                     └─►  metadata ← csv_metadata
```

## Node Interfaces
1. **csv-reader** outputs:
   - `csv_content`: The text data from CSV
   - `csv_metadata`: File metadata

2. **sentiment-analyzer** expects:
   - Input: `text` (but reader provides `csv_content`)
   - Output: `sentiment_scores` (but formatter needs `analysis_results`)

3. **report-generator** expects:
   - `data`: The analysis results
   - `metadata`: Additional context

## Mapping Configuration
```json
"mappings": {
  "analyzer": {
    "input_mappings": {
      "text": "csv_content"  // analyzer.text = shared["csv_content"]
    },
    "output_mappings": {
      "sentiment_scores": "analysis_results"  // shared["analysis_results"] = analyzer.sentiment_scores
    }
  }
}
```

## How Proxy Mappings Work
1. **Before node execution**: Input mappings transform shared store keys
2. **After node execution**: Output mappings transform node outputs
3. **Transparent to nodes**: Nodes don't know about the mappings

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('proxy-mappings.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Should pass without errors
```

## Common Variations
1. **Multiple input sources**: Map multiple shared keys to one node input
2. **Output fanout**: Map one output to multiple shared keys
3. **Nested mappings**: Handle complex object transformations
4. **Conditional mappings**: Different mappings based on node state

## When to Use Proxy Mappings
- **DO**: When integrating existing nodes with different interfaces
- **DO**: To create cleaner workflow interfaces
- **DON'T**: For simple workflows where nodes naturally connect
- **DON'T**: When it adds unnecessary complexity

## Notes
- Mappings are optional - only use when needed
- Each node can have both input and output mappings
- Mappings reference shared store keys, not node IDs
- The proxy pattern enables maximum node reusability
