# Runtime Behavior Specification

This document defines how pflow handles node execution safety, performance optimization, and error recovery through its caching, retry, and side-effect management systems.

## Side-Effect Declaration and Node Safety

pflow does not require or implement a full side-effect declaration schema in its MVP. Instead, we invert the responsibility: side effects are assumed by default. The system distinguishes safe from unsafe behavior through explicit opt-in purity markers.

### Core Principle

> All nodes are treated as impure unless explicitly marked `@flow_safe`.\
> There is no need to list or predict side effects. We only verify and certify purity.

### Node Classification

- **Impure (default)**\
   Nodes may write files, make network calls, mutate external state. These are permitted but untrusted, uncacheable, and un-retryable unless the user inspects and accepts them.

- **Pure (`@flow_safe`) nodes**:
   - Are deterministic and idempotent
   - Have no observable side effects outside the flow
   - Only touch `shared` keys via declared `params`
   - Are safe to retry, cache, and use in agent-generated flows
   - Must pass validation before being accepted as `flow_safe`

- **No side-effect enumeration**\
   Nodes do not declare `scope`, `target`, or `mode` of mutations. pflow does not attempt to predict or map real-world effects.

### Safety Enforcement

- All retryable nodes must be `@flow_safe`
- All cacheable nodes must be `@flow_safe`

### Design Rationale

This approach is acceptable because:

1. **pflow only allows curated nodes** (e.g., MCP wrappers), and they are by nature:
   - Externalized
   - Inspectable
   - Known to the user before execution

2. **Every flow is confirmed by the user pre-run**\
   No hidden effects, no agent autonomy, no implicit execution.

### Future Expansion Plan

When:
- Retry logic becomes default
- Agent-generated flows are reused across users
- Audit or policy enforcement is required
- Flows are composed from untrusted sources

Then:
- A side-effect declaration schema may be introduced
- It will model external effects with `scope`, `target`, `mode`
- This will enable dry-run, plan, rollback, and consent layers

Until then:
> `@flow_safe` is the contract. Everything else is opaque by design.

## Caching Strategy (MVP)

### Purpose

Provide an **opt-in**, **node-level** caching mechanism for pure nodes, preserving correctness and modularity while enabling performance gains on expensive, deterministic operations.

### Mechanism

- Nodes must be decorated with `@flow_safe` decorator to be eligible for caching.

- On execution, `pflow` computes a fingerprint hash using:
   - Node type (class name)
   - The full `params` object (as declared in IR)
   - Values at referenced `shared` input keys (as specified in `params`)
   - Matching node version (`namespace/name@version`)

- If a matching cache entry exists, `exec()` is skipped and both `output` and `shared` mutations are restored from cache.

`@flow_safe` marks a node as deterministic, side-effect-free, and fully parameterized via declared shared keys—making it eligible for caching, retries, and safe reuse within any flow context.

### Requirements

- Cacheable nodes must access shared memory only via keys declared in `params`.
- Caching is limited to pure nodes with no side effects.

### CLI Interface

- `--use-cache`: Enable cache lookup for cacheable nodes (default: off)
- `--reset-cache`: Clear relevant cache entries

### Storage

- MVP uses local filesystem: `~/.pflow/cache/<hash>.json`

## Failure and Retry Semantics

### Core Failure Behavior

- All flows fail fast. If any node fails, the flow aborts.

- The trace is always written, including:
   - Node where the failure occurred.
   - Exception or error message.
   - Value of `params` and inputs at time of failure.
   - Partial state of `shared` up to failure.

### Retry Configuration

- No retries unless explicitly enabled on the node via a `retries` argument (integer ≥ 0). Default is 0.
- Retried nodes use same inputs and params; no dynamic backoff or jitter in MVP.
- Retried failures are logged with full history: attempt count, time, outcome.
- If a node fails after all retries, flow halts with status `FAILED`. No downstream nodes are run.
- `pflow trace` includes a failure marker and retry timeline if applicable.
- Retries are only applicable for nodes marked with `@flow_safe` decorator.

### Retry Architecture

No internal retry logic inside nodes. Retry is flow-driven and node-declared only. No global retry flags in MVP.

Retry must be explicit, deterministic, and localized to the flow executor. It is not part of the data model, not part of the node interface, and not allowed to mutate global state without declaration. Retry scaffolding must be compatible with future checkpointing, flow resumption, and distributed execution.

### CLI Syntax and Internal Representation

**From the CLI, users can specify retries like this:**

```
pflow fetch_url --url X --retries 3 >> summarize
```

This is correct **at the syntax level**, and should remain supported.

However, **retries are not node parameters**. Even though they appear alongside `--url`, they must be treated differently internally.

- `--url` → part of the node's `params`; used inside `exec()`.
- `--retries` → **execution directive** to the flow engine; controls how many times to wrap and retry the node on failure.

Internally, `pflow` must separate these in the flow IR:

```json
{
  "type": "FetchURL",
  "params": { "url": "X" },
  "exec": { "retries": 3 }
}
```

Not:

```json
{
  "type": "FetchURL",
  "params": { "url": "X", "retries": 3 }
}
```

This preserves modularity, testability, and flow-wide introspection.

**Conclusion:**\
Retries should be configurable via CLI, but architecturally treated as **flow-level metadata**, not node configuration. Syntax unification is fine; semantic separation is required. 