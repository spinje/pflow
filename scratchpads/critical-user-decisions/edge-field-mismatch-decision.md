# Critical Decision: Edge Field Name Mismatch Resolution

## 1. Edge Field Name Format - Decision importance (5)

The IR examples in the `examples/` directory use `"from"/"to"` for edge definitions, but the current compiler implementation expects `"source"/"target"`. This is a critical mismatch that will prevent integration tests from using any existing IR examples.

### Options:

- [x] **Option A: Update compiler to accept both formats**
  - The compiler would accept both `from/to` and `source/target` field names
  - Pros:
    - Maintains backwards compatibility
    - Allows use of existing examples for testing
    - Common pattern in evolving APIs
    - Minimal code changes (just update edge parsing)
  - Cons:
    - Adds slight complexity to handle two formats
    - May cause confusion about which is "correct"

- [ ] **Option B: Update all examples to use source/target**
  - Change all IR examples to match compiler expectations
  - Pros:
    - Single consistent format throughout codebase
    - No ambiguity about field names
  - Cons:
    - Requires updating many files
    - Breaks existing examples
    - Risk of missing some examples
    - Documentation may become inconsistent

- [ ] **Option C: Keep everything as-is, create new test examples**
  - Don't change compiler or examples, just create new test data
  - Pros:
    - No changes to existing code
    - Maintains current implementation
  - Cons:
    - Can't use existing examples for integration testing
    - Test examples will diverge from documentation examples
    - Duplicated effort maintaining two sets of examples

**Recommendation**: Option A - Update the compiler to accept both formats. This is the most pragmatic solution that maintains compatibility while enabling comprehensive testing with real examples.

The implementation would be simple - in `_wire_nodes()`, check for both field names:
```python
source = edge.get("source") or edge.get("from")
target = edge.get("target") or edge.get("to")
```

Please confirm your decision so I can proceed with the implementation.
