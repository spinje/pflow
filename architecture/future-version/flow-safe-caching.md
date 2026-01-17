# Flow-Safe Decorator and Caching

> **Status**: Post-MVP feature (v2.0+)
>
> This document describes the `@flow_safe` decorator and associated caching/retry mechanisms. These features are documented for architectural completeness but are not implemented in the current release.

## Side-Effect Declaration and Node Safety

pflow uses an **opt-in purity model** rather than comprehensive side-effect enumeration. This approach aligns with pflow's curated node ecosystem and user-confirmed execution model.

### Core Principle

> All nodes are treated as impure unless explicitly marked `@flow_safe`.
> There is no need to list or predict side effects. We only verify and certify purity.

### Node Classification

- **Impure (default)**
   Nodes may write files, make network calls, mutate external state. These are permitted but untrusted, uncacheable, and un-retryable unless the user inspects and accepts them.

- **Pure (`@flow_safe`) nodes**:
  - Are deterministic and idempotent
  - Have no observable side effects outside the shared store
  - Access shared store via natural interfaces (`shared["text"]`, `shared["url"]`)
  - Are safe to retry, cache, and use in agent-generated flows
  - Must pass validation before being accepted as `flow_safe`

### Safety Enforcement

- All retryable nodes must be `@flow_safe`
- All cacheable nodes must be `@flow_safe`
- Nodes inherit from `pocketflow.Node` and use standard `prep()`/`exec()`/`post()` pattern

### Design Rationale

This approach works because:

1. **pflow only allows curated nodes** — nodes are externalized, inspectable, and known to users
2. **Every flow is confirmed by the user pre-run** — no hidden effects or implicit execution
3. **Framework integration** — leverages pocketflow's existing safety patterns

> **Implementation**: See [Node Reference](../reference/node-reference.md) for how to implement `@flow_safe` nodes

## Caching Strategy

### Purpose

Provide **opt-in**, **node-level** caching for pure nodes, preserving correctness while enabling performance gains on expensive, deterministic operations.

### Eligibility Requirements

All conditions must be met for caching:

1. Node marked with `@flow_safe` decorator
2. Flow origin trust level ≠ `mixed` (per planner trust model)
3. Node version matches cache entry
4. Effective params match cache entry
5. Input data hash matches cache entry

### Cache Key Computation

Cache key: `node_hash ⊕ effective_params ⊕ input_data_sha256`

Where:

- `node_hash`: Node type + version
- `effective_params`: Runtime params from `self.params`
- `input_data_sha256`: Hash of values from referenced shared store keys. This includes the content of `shared["stdin"]` if the node is designed to read from it.

### Mechanism

- On cache hit: Skip `exec()`, restore both output and shared store mutations
- On cache miss: Execute normally, store results for future use
- Cache validation occurs during planner validation phase

### Storage

MVP uses local filesystem: `~/.pflow/cache/<hash>.json`

## Retry and Safety Requirements

### Retry Eligibility

- Only `@flow_safe` nodes can be retried
- Same inputs and params used for all retry attempts
- Full retry history logged in trace
- No global retry flags — node-specific configuration only

### Configuration

```json
{
  "id": "fetch-url",
  "params": {"url": "X"},
  "execution": {"max_retries": 3, "wait": 1.0}
}
```

> **Complete Details**: See [Execution Reference](../reference/execution-reference.md#retry-mechanisms) for full retry behavior

## Integration Notes

### Framework Compatibility

- All runtime behaviors work within pocketflow's execution model
- Caching and retry respect proxy mappings when defined in IR
- Trust model validation occurs during planner phase
- CLI parameter resolution follows established data injection vs params override pattern

### Future Expansion

When retry logic becomes default or flows are shared across users, a comprehensive side-effect declaration schema may be introduced with `scope`, `target`, and `mode` modeling for external effects.

Until then: **`@flow_safe` is the contract. Everything else is opaque by design.**

> **Execution Details**: See [Execution Reference](../reference/execution-reference.md) for flow immutability, testing framework, and future resilience features

## See Also

- [Execution Reference](../reference/execution-reference.md) - Complete execution model
- [Shared Store](../core-concepts/shared-store.md) - Node communication pattern
- [IR Schema](../reference/ir-schema.md) - Runtime configuration in Flow IR
