# PocketFlow Modifications for pflow

This file documents temporary modifications made to PocketFlow to support pflow's use case.

## Modified Files

### 1. `pocketflow/__init__.py` - Flow._orch() method

**Line 104-105**: Added conditional parameter setting

```python
# Only override node params if explicitly passed (not for default empty flow params)
if params is not None:
    curr.set_params(p)
```

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
