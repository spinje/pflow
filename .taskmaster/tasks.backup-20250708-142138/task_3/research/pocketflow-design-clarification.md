# PocketFlow Design Clarification

## Important: Parameter Overwriting is NOT a Bug

The parameter handling behavior in PocketFlow that initially appeared to be a "bug" is actually **intentional design** for supporting BatchFlow operations.

## PocketFlow's Parameter Philosophy

PocketFlow follows a hierarchical parameter model where parameters flow from parent to child:

1. **Parent controls child parameters** - This enables dynamic parameter injection
2. **Runtime over compile-time** - Parameters are meant to be set at execution time
3. **Clean slate per run** - Each execution gets fresh parameters

## Why This Design Exists

### BatchFlow Use Case
```python
class ProcessFilesBatch(BatchFlow):
    def prep(self, shared):
        # Return different params for each iteration
        return [
            {"filename": "doc1.txt"},
            {"filename": "doc2.txt"},
            {"filename": "doc3.txt"}
        ]

# The flow runs 3 times with different parameters
# Each run MUST have clean parameters, not accumulated ones
```

If parameters were merged instead of replaced, run 2 would have parameters from run 1, causing contamination.

## pflow's Different Use Case

pflow uses parameters as **static configuration** set at compile time:
- Parameters are part of the workflow definition (JSON IR)
- They don't change between executions
- They're more like node properties than runtime parameters

## The Temporary Solution

For the MVP, we've modified PocketFlow to conditionally set parameters:
```python
if params is not None:
    curr.set_params(p)
```

This works because:
- pflow's Flow objects have empty params by default
- BatchFlow explicitly passes params, so it still works
- It's clearly marked as temporary with TODOs

## Future Considerations

When implementing BatchFlow support in pflow:
1. Consider using a wrapper for standard flows
2. Or detect BatchFlow context and behave differently
3. Or redesign pflow's parameter model to align with PocketFlow

## Key Takeaway

What seemed like a "bug" is actually a well-reasoned design decision for PocketFlow's primary use case. The mismatch occurs because pflow uses the framework differently than intended - which is fine for the MVP but will need proper resolution later.
