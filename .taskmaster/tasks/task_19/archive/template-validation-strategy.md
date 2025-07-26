# Template Validation Strategy - Decision Importance: 4/5

The current template validation system uses flawed heuristics to guess which variables come from initial_params vs shared store, causing false validation failures. We need to decide how to fix this for Task 17's implementation.

## Context:

Task 18 implemented template variables (`$var`) that can be resolved from two sources:
1. **initial_params** - provided by the planner/CLI upfront
2. **shared store** - written by nodes during execution

The validator tries to ensure all templates have values before execution, but it doesn't know what nodes write to shared store. It guesses based on variable names (e.g., `$content` → shared store, `$input_file` → initial_params), but these guesses can be wrong.

Example where current validation fails incorrectly:
```json
{
  "nodes": [
    {"id": "setup", "type": "config-loader"},  // Writes $api_config to shared
    {"id": "call", "params": {"config": "$api_config"}}  // Uses it
  ]
}
```
The validator thinks `$api_config` must be in initial_params and fails, even though the first node provides it.

## Options:

- [ ] **Option A: Runtime Registry Parsing**
  - Validator accesses registry and parses docstrings on-demand
  - Extract interface data during validation
  - Pros: No changes to scanner/registry format
  - Cons: Performance overhead, complex parsing logic in validator

- [ ] **Option B: Enhanced Workflow IR**
  - Add interface metadata to nodes in workflow IR
  - Planner includes what each node reads/writes
  - Pros: Self-contained workflows
  - Cons: Duplicates data, larger workflows

- [x] **Option C: Extend Registry with Node IR (MVP Approach)**
  - Scanner parses interface data once during discovery
  - Registry stores structured "interface" field for each node
  - Validator uses pre-parsed data from registry
  - Pros: Parse once, use many times; clean architecture; better performance
  - Cons: Need to update scanner and re-scan nodes (one-time cost)

**Recommendation**: Option C - Create a proper "Node IR" by storing parsed interface data in the registry. This is the right MVP approach because:

1. **Simplifies Everything**: Context builder already parses this data - we're just moving the parsing to the right place
2. **No Added Complexity**: We're using the existing MetadataExtractor, not writing new parsing code
3. **Clean Break**: Since we're pre-1.0, no backward compatibility needed - just update and regenerate
4. **Multiple Benefits**: Fixes validation AND speeds up context builder AND prepares for Task 17

**MVP Scope Clarification**:
- ✅ Store full interface metadata (already parsed by MetadataExtractor)
- ✅ Update all consumers to use new format
- ❌ No backward compatibility fallbacks
- ❌ No migration strategies
- ❌ No complex error recovery beyond basic logging

This affects Task 17 because the ParameterExtractionNode can use the same interface data to validate workflow executability.
