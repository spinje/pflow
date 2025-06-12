# Runtime Behavior Specification

This document defines how pflow handles node execution safety, performance optimization, and error recovery through its caching, retry, and side-effect management systems.

> **Note**: This document focuses on runtime behavior specifics. For architectural context, see [Shared Store + Proxy Design Pattern](./shared-store-node-proxy-architecture.md) and [CLI Runtime Specification](./shared-store-cli-runtime-specification.md).

## Side-Effect Declaration and Node Safety

pflow uses an **opt-in purity model** rather than comprehensive side-effect enumeration. This approach aligns with pflow's curated node ecosystem and user-confirmed execution model.

### Core Principle

> All nodes are treated as impure unless explicitly marked `@flow_safe`.\
> There is no need to list or predict side effects. We only verify and certify purity.

### Node Classification

- **Impure (default)**\
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

## Failure and Retry Semantics

### Core Failure Behavior

- All flows fail fast — any node failure aborts the flow
- Complete trace always written including failure context, params, and partial shared store state
- Integration with pocketflow's existing retry mechanism via `max_retries` parameter

### Retry Configuration

**Built-in pocketflow Integration**:

```python
class Node(BaseNode):
    def __init__(self, max_retries=1, wait=0):
        # Standard pocketflow retry support
```

**IR Structure**:

```json
{
  "id": "fetch-url",
  "params": {"url": "X"},
  "execution": {"max_retries": 3, "wait": 1.0}
}
```

**CLI Configuration**:

```bash
# Execution config categorized during CLI resolution
pflow fetch_url --url=X --max_retries=3 >> summarize
```

**Requirements**:

- Only `@flow_safe` nodes can be retried
- Same inputs and params used for all retry attempts
- Full retry history logged in trace
- No global retry flags — node-specific configuration only

### Retry Integration

Retries leverage pocketflow's existing `max_retries` mechanism:

- Configured via node constructor from IR `execution` field
- Integrated with `prep()`/`exec()`/`post()` execution pattern
- Compatible with NodeAwareSharedStore proxy when mappings defined

### Error Recovery

- Retried failures logged with attempt count, timing, and outcome
- After retry exhaustion: flow halts with `FAILED` status
- No downstream nodes executed after failure
- `pflow trace` includes failure markers and retry timeline

## Integration Notes

### Framework Compatibility

- All runtime behaviors work within pocketflow's execution model
- Caching and retry respect proxy mappings when defined in IR
- Trust model validation occurs during planner phase
- CLI parameter resolution follows established data injection vs params override pattern

### Future Expansion

When retry logic becomes default or flows are shared across users, a comprehensive side-effect declaration schema may be introduced with `scope`, `target`, and `mode` modeling for external effects.

Until then: **`@flow_safe` is the contract. Everything else is opaque by design.**

## Flow Immutability During Execution

### Static Execution Model
Flows are immutable during execution. No runtime modification of:
- Node composition or ordering
- Edge definitions or action mappings
- Shared store schema or key mappings
- Node parameter definitions

### Prohibited Runtime Mutations
- Adding or removing nodes mid-execution
- Changing node transitions based on data
- Dynamic proxy mapping modifications
- Flow topology alterations

### Benefits of Static Execution
- **Predictable behavior**: Flow execution follows predetermined path
- **Auditability**: Complete flow structure captured in lockfile
- **Reproducibility**: Identical flows produce identical execution patterns
- **Debugging**: Clear execution model for trace analysis

## Testing Framework

### Built-in Testing Requirements

pflow provides built-in testing capabilities to ensure node reliability and flow correctness:

### Node Testing
**Test Structure:**
```python
def test_yt_transcript_node():
    node = YTTranscript()
    node.set_params({"language": "en"})

    # Setup test shared store
    shared = {"url": "https://youtu.be/test123"}

    # Execute node
    node.run(shared)

    # Assert expected changes
    assert "transcript" in shared
    assert len(shared["transcript"]) > 0
```

**Test Requirements:**
- Minimal setup (≤5 lines per test)
- No mocks or scaffolding required
- Test `params` and known `shared` dict
- Assert expected shared store mutations

### Flow Testing
**Test Structure:**
```python
def test_video_summary_flow():
    flow = create_video_summary_flow()
    shared = {"url": "https://youtu.be/test123"}

    flow.run(shared)

    assert "summary" in shared
    assert shared["summary"].startswith("Summary:")
```

### CLI Testing Interface
```bash
# Test individual nodes
pflow test yt-transcript
pflow test summarize-text

# Test complete flows
pflow test video-summary-flow

# Validate flow definitions
pflow validate flow.json
pflow validate my-flow.lock.json
```

### Testing Principles
- **Behavior verification**: Ensure shared store changes match expectations
- **Schema safety**: Validate interface compatibility
- **Agent flow auditability**: Test AI-generated flows for correctness
- **Minimal complexity**: Simple, direct testing without infrastructure

## Future: Resilience and Recovery Features

### Long-Lived Flow Resumption (Planned)

**Capability Overview:**
Support for flows that can be paused, interrupted, and resumed from checkpoints.

**Implementation Approach:**
- Serialize `shared` store state at node completion boundaries
- Track completed nodes in execution metadata
- Resume from last successful checkpoint on restart

**CLI Interface (Planned):**
```bash
# Resume interrupted flow
pflow resume job_2024-01-01_abc123

# Create checkpoint-enabled flow
pflow run my-flow.json --enable-checkpoints

# List resumable flows
pflow list --resumable
```

**Requirements for Resumability:**
- All nodes in resumable flows must be `@flow_safe`
- Shared store state must be serializable
- External side effects must be idempotent or trackable

### User Memory and State (Explicitly Not Supported)

**Design Decision:**
pflow does not support per-user persistent memory or cross-flow state sharing in core system.

**Rationale:**
- Breaks composability and flow isolation
- Introduces hidden dependencies
- Complicates reproducibility and testing

**Alternative Patterns:**
- **Explicit context injection**: Load user context via preparatory nodes
- **External storage**: Use dedicated storage nodes for persistence
- **Flow composition**: Chain flows that explicitly pass context

**Example:**
```bash
# CORRECT: Explicit context loading
pflow load-user-context --user=alice >> process-request >> save-result

# WRONG: Implicit user memory (not supported)
pflow process-request  # Would magically know about Alice
```

### Checkpointing Architecture (Future)

**Technical Approach:**
- Checkpoint creation at node completion boundaries
- Shared store serialization to disk or external storage
- Node completion tracking in execution metadata
- Resume logic that skips completed nodes and restores state

**Integration with Caching:**
- Checkpoints complement but don't replace caching
- Cache provides performance optimization
- Checkpoints provide failure recovery
- Both require `@flow_safe` nodes for safety
