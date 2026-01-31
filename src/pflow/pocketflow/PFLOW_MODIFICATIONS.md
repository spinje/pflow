# PocketFlow Modifications for pflow

This file documents modifications made to PocketFlow for pflow's use case.

## Modified Files

### 1. `pocketflow/__init__.py` - Flow._orch() method (pflow-specific)

**Line 104-105**: Added conditional parameter setting

```python
# Only override node params if explicitly passed (not for default empty flow params)
if params is not None:
    curr.set_params(p)
```

### 2. `pocketflow/__init__.py` - AsyncNode._exec() method (upstream sync)

**Line 141-146**: Aligned retry tracking with sync Node implementation

**Upstream commit**: [fd5817f](https://github.com/The-Pocket/PocketFlow/commit/fd5817fdccfed7c77b1665fce8e0f69bf4c359e1)

```python
# Changed from local variable 'i' to instance attribute 'self.cur_retry'
for self.cur_retry in range(self.max_retries):
    try:
        return await self.exec_async(prep_res)
    except Exception as e:
        if self.cur_retry == self.max_retries - 1:
            return await self.exec_fallback_async(prep_res, e)
```

**Why**: Ensures consistency between sync `Node` and `AsyncNode` retry mechanisms. Allows derived classes to access `self.cur_retry` during async execution, which is important for retry-aware logic in parallel execution scenarios.

## Rationale

PocketFlow's original design overwrites node parameters with flow parameters in `_orch()`. This is intentional for BatchFlow scenarios where parent flows control child parameters dynamically at runtime.

However, pflow uses parameters differently - as static configuration values set during workflow compilation. The modification prevents empty flow parameters from overwriting carefully configured node parameters.

## Impact

- **Positive**: Allows pflow nodes to maintain their parameters set during compilation
- **Negative**: Will break BatchFlow functionality if/when implemented in pflow
- **Risk**: Low for current MVP scope which doesn't include BatchFlow

## Future Considerations

When implementing BatchFlow support in pflow, this modification will need to be revisited. Options include:

1. **Revert this change** and use a wrapper class (like PreservingFlow) for pflow's standard flows
2. **Enhance the condition** to detect BatchFlow context and apply different behavior
3. **Redesign** how pflow handles parameters to align with PocketFlow's model
4. **Fork PocketFlow** if the use cases diverge significantly

## Related Issues

- Initial issue discovered during Task 3 implementation
- PreservingFlow wrapper was the first solution (now removed)
- This modification is a temporary pragmatic solution for the MVP

## TODO

- [ ] Add unit tests that verify parameter preservation behavior
- [ ] Document this limitation in pflow's user documentation
- [ ] Create issue to track BatchFlow implementation considerations
- [ ] Consider long-term strategy for PocketFlow integration
