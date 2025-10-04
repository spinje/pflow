# Checkpoint Persistence Options for External Agent Repair

**Context**: When using `--no-repair` flag, agents handle repair externally. Currently, cache is lost between runs because `resume_state=None` always. This analysis explores options for preserving checkpoint data.

**Date**: 2025-10-02

---

## Current State: How Caching Works

### Internal Repair (Built-in Auto-Repair)
```python
# workflow_execution.py - Lines 341-489
def _execute_with_repair_loop():
    # Initial execution
    result = executor.execute_workflow(...)

    # If fails, repair and resume
    if not result.success:
        repaired_ir = repair_workflow(...)

        # KEY: Resume with previous shared_store
        result = executor.execute_workflow(
            workflow_ir=repaired_ir,
            resume_state=result.shared_after  # ← Cache preserved!
        )
```

**Cache Flow**:
1. Node1 executes → `shared["__execution__"]["completed_nodes"] = ["node1"]`
2. Node2 fails → `shared["__execution__"]["failed_node"] = "node2"`
3. Repair fixes node2 → Repaired workflow created
4. Resume with `resume_state=result.shared_after` → Node1 CACHED!

### External Agent Repair (--no-repair)
```python
# main.py - Line 1732
result = execute_workflow(
    workflow_ir=ir_data,
    execution_params=enhanced_params,
    enable_repair=False,  # --no-repair
    resume_state=None,  # ← ALWAYS None, cache LOST!
)
```

**Cache Flow**:
1. **First run**: Node1 executes → Error at node2 → Exit
2. Agent fixes workflow → Saves fixed version
3. **Second run**: `resume_state=None` → Node1 re-executes (NOT cached!)

**Problem**: Every external agent repair iteration re-executes ALL nodes from scratch.

---

## The Core Question

**How can external agents preserve checkpoint data between runs to benefit from caching like internal repair does?**

---

## Option 1: Checkpoint File Persistence

**Concept**: Save `shared["__execution__"]` to disk after each run.

### Implementation Approach

**A. Automatic Checkpoint Files**
```python
# ~/.pflow/checkpoints/<workflow-hash>.json
{
  "workflow_ir_hash": "abc123...",  # MD5 of workflow IR
  "checkpoint": {
    "completed_nodes": ["node1", "node2"],
    "node_actions": {"node1": "default", "node2": "default"},
    "node_hashes": {"node1": "hash1", "node2": "hash2"},
    "failed_node": "node3"
  },
  "timestamp": "2025-10-02T10:30:00",
  "ttl": 3600  # Cache for 1 hour
}
```

**CLI Changes**:
```python
# New flag: --resume or --checkpoint
uv run pflow --no-repair --resume workflow.json

# Or automatic (risky)
uv run pflow --no-repair workflow.json  # Auto-loads checkpoint if exists
```

**Pros**:
- ✅ Transparent to agents (automatic)
- ✅ Simple UX (just add --resume flag)
- ✅ Works exactly like internal repair
- ✅ Can set TTL for cache expiration

**Cons**:
- ❌ Race conditions (multiple parallel runs)
- ❌ Stale checkpoints (workflow changed but hash same)
- ❌ Disk I/O overhead
- ❌ Security (checkpoint files could contain sensitive data)
- ❌ Cleanup (old checkpoints accumulate)

**Cache Invalidation Issues**:
- What if agent modifies nodes 1-2 but checkpoint still has them?
- Hash collision if only node3 params changed
- No way to know if checkpoint is valid for modified workflow

**Complexity**: MEDIUM-HIGH

---

## Option 2: Explicit Checkpoint I/O via JSON

**Concept**: Export checkpoint in JSON output, agent provides it back.

### Implementation Approach

**JSON Output Includes Checkpoint**:
```json
{
  "success": false,
  "execution": {
    "steps": [
      {"node_id": "node1", "status": "completed", ...},
      {"node_id": "node2", "status": "failed", ...}
    ]
  },
  "checkpoint": {
    "completed_nodes": ["node1"],
    "node_actions": {"node1": "default"},
    "node_hashes": {"node1": "abc123..."},
    "failed_node": "node2"
  }
}
```

**Agent Passes Checkpoint Back**:
```bash
# Agent extracts checkpoint from previous run
CHECKPOINT=$(jq '.checkpoint' previous_output.json)

# Agent passes it back
uv run pflow --no-repair --checkpoint "$CHECKPOINT" fixed-workflow.json
```

**OR via file**:
```bash
# Save checkpoint to file
uv run pflow --no-repair workflow.json 2>&1 | \
  jq '.checkpoint' > /tmp/checkpoint.json

# Resume with checkpoint
uv run pflow --no-repair --resume-from /tmp/checkpoint.json fixed-workflow.json
```

**Pros**:
- ✅ Explicit (agent controls caching)
- ✅ No automatic state management
- ✅ Agent decides when to use checkpoint
- ✅ No disk persistence needed
- ✅ Stateless (follows pflow philosophy)

**Cons**:
- ❌ Complex agent workflow (extract, store, pass back)
- ❌ Easy to misuse (stale checkpoint with wrong workflow)
- ❌ Verbose (checkpoint data in every response)
- ❌ Agent needs to parse and manage JSON

**Complexity**: MEDIUM

---

## Option 3: Session-Based Checkpoints

**Concept**: Use session ID to track related repair attempts.

### Implementation Approach

**First Run** (generates session):
```bash
uv run pflow --no-repair --session workflow.json
# Output includes: "session_id": "abc-123-def"
```

**Subsequent Runs** (resume session):
```bash
uv run pflow --no-repair --session abc-123-def fixed-workflow.json
```

**Session Storage**:
```
~/.pflow/sessions/
  abc-123-def/
    checkpoint.json
    workflow-v1.json
    workflow-v2.json (repaired)
    execution-log.jsonl
```

**Pros**:
- ✅ Clear intent (session means "related attempts")
- ✅ Automatic cleanup (sessions expire)
- ✅ Debug friendly (all attempts logged)
- ✅ Agent-friendly (simple session ID)

**Cons**:
- ❌ Complexity (session management system)
- ❌ Race conditions (parallel sessions)
- ❌ Cleanup logic needed
- ❌ More moving parts

**Complexity**: HIGH

---

## Option 4: No Caching for External Agents (Status Quo)

**Concept**: Accept that external repair = fresh execution.

### Rationale

**Design Philosophy**:
- Internal repair: Fast iteration (cache helps)
- External repair: Deliberate, slow (agent thinking time >> execution time)

**Reality Check**:
- Agent spends 5-30s analyzing error and fixing workflow
- Node re-execution takes 0.1-5s typically
- **Caching saves < 10% of total time**

**Pros**:
- ✅ Simple (no changes needed)
- ✅ Predictable (every run is fresh)
- ✅ No stale cache issues
- ✅ No complexity

**Cons**:
- ❌ Wastes computation on expensive nodes (LLM calls, API calls)
- ❌ Slower for workflows with many nodes
- ❌ Inconsistent UX (internal repair caches, external doesn't)

**When This Works**:
- Workflows with cheap nodes (< 1s each)
- Agents that fix on first attempt
- Low iteration count scenarios

**When This Fails**:
- Expensive nodes (LLM, API calls costing $$)
- Complex workflows (10+ nodes, only last one fails)
- Iterative refinement scenarios

**Complexity**: ZERO (status quo)

---

## Option 5: Hybrid - Explicit Resume Flag Only

**Concept**: Minimal intervention - just add `--resume` flag that loads last checkpoint.

### Implementation Approach

**Checkpoint Auto-Save**:
```python
# Always save checkpoint after execution
~/.pflow/checkpoints/last-execution.json
```

**Resume Flag**:
```bash
# First run
uv run pflow --no-repair workflow.json  # Fails, saves checkpoint

# Agent fixes workflow
# ...

# Resume run (loads last checkpoint)
uv run pflow --no-repair --resume fixed-workflow.json
```

**Smart Invalidation**:
```python
# Check if checkpoint is compatible
if workflow_hash_changed_for_completed_nodes:
    warn("Checkpoint invalid, starting fresh")
    resume_state = None
else:
    resume_state = load_checkpoint()
```

**Pros**:
- ✅ Simple agent UX (just add --resume)
- ✅ Minimal code changes
- ✅ Agent controls when to use cache
- ✅ Automatic invalidation on incompatibility

**Cons**:
- ❌ "Last execution" assumption (what if multiple workflows?)
- ❌ Still needs disk persistence
- ❌ Invalidation logic complexity

**Complexity**: MEDIUM

---

## Comparative Analysis

| Option | Agent UX | Correctness | Performance | Complexity | Recommended |
|--------|----------|-------------|-------------|------------|-------------|
| 1. Auto File | Easy | Medium | High | Med-High | ⚠️ Risky |
| 2. Explicit JSON | Complex | High | High | Medium | ⭐ Safe |
| 3. Sessions | Medium | High | High | High | ❌ Over-engineered |
| 4. No Caching | Easy | High | Low | Zero | ✅ MVP |
| 5. Hybrid --resume | Easy | Medium | High | Medium | ⭐ Balanced |

---

## Recommended Approach: Phased Implementation

### Phase 0: MVP (Current - Option 4)
**Ship Task 71 without caching for external agents**

**Rationale**:
- No users yet, no real-world data on pain
- Implementation risk vs unclear benefit
- Can always add later

**Decision criteria for Phase 1**:
- Real agent complains about re-execution cost
- Workflows with expensive nodes become common
- Clear use case emerges

### Phase 1: Add --resume Flag (Option 5)
**If and when external caching becomes necessary**

**Implementation**:
```python
# Add to execute_json_workflow()
if ctx.obj.get("resume_flag"):
    resume_state = load_last_checkpoint_if_compatible(ir_data)
else:
    resume_state = None
```

**Checkpoint Format**:
```json
{
  "workflow_hash": "md5-of-workflow-ir",
  "execution_state": {...},
  "timestamp": "...",
  "workflow_name": "..."
}
```

**CLI**:
```bash
pflow --no-repair --resume workflow.json
```

### Phase 2: Explicit Checkpoint I/O (Option 2)
**If agents need fine-grained control**

**Add checkpoint to JSON output**:
```python
if output_format == "json":
    result["checkpoint"] = shared_storage.get("__execution__")
```

**Add --resume-from parameter**:
```bash
pflow --no-repair --resume-from checkpoint.json workflow.json
```

---

## Critical Questions to Answer

### 1. Cache Invalidation
**Q**: How do we know if a checkpoint is valid for a modified workflow?

**A**: Hash-based validation
```python
def is_checkpoint_compatible(checkpoint, workflow_ir):
    # Only check hashes for completed nodes
    for node_id in checkpoint["completed_nodes"]:
        node_config = get_node_config(workflow_ir, node_id)
        current_hash = compute_hash(node_config)
        cached_hash = checkpoint["node_hashes"].get(node_id)

        if current_hash != cached_hash:
            return False  # Node changed, invalid

    return True  # All completed nodes unchanged
```

### 2. Race Conditions
**Q**: What if agent runs multiple workflows concurrently?

**A**: Options:
- Per-workflow checkpoints (keyed by IR hash)
- Session IDs (explicit isolation)
- Don't support concurrent resume (error if conflict)

### 3. Security
**Q**: Can checkpoints leak sensitive data?

**A**: Yes! Checkpoint contains:
- `shared` store data (may have API keys, tokens)
- Node outputs (may have PII)

**Mitigation**:
- Only store `__execution__` metadata (not full shared store)
- Never store `__llm_calls__` or sensitive keys
- Warn users if detected

### 4. Cost vs Benefit
**Q**: Is caching worth the complexity?

**A**: Depends on workflow characteristics:

**High Value** (caching helps):
```
10 cheap nodes (0.1s each) → 1 expensive LLM node (30s, $0.01)
- Without cache: 30s + $0.01 per iteration
- With cache: 0.1s + $0 per iteration after first
- **Savings: 99% time, 100% cost** per iteration
```

**Low Value** (caching doesn't help):
```
3 cheap nodes (0.5s each)
- Without cache: 1.5s per iteration
- With cache: 0.5s per iteration
- **Savings: 33% time, $0**
```

**Decision Heuristic**:
- If any node > 5s OR > $0.001 → Caching valuable
- If all nodes < 1s AND < $0.001 → Caching optional

---

## Security Considerations

### Sensitive Data in Checkpoints

**What's in `shared["__execution__"]`**:
```python
{
  "completed_nodes": ["node1"],  # ✅ Safe
  "node_actions": {"node1": "default"},  # ✅ Safe
  "node_hashes": {"node1": "abc123"},  # ✅ Safe
  "failed_node": "node2"  # ✅ Safe
}
```

**What's NOT included**:
- ❌ `shared["api_key"]` (user data)
- ❌ `shared["__llm_calls__"]` (may have prompts/responses)
- ❌ Node outputs

**Verdict**: `__execution__` is metadata-only, safe to persist.

### Cache Hits List

**What's in `shared["__cache_hits__"]`**:
```python
["node1", "node2"]  # ✅ Just node IDs, safe
```

**Verdict**: Safe to persist.

---

## Implementation Effort Estimate

| Option | Backend | CLI | Tests | Docs | Total |
|--------|---------|-----|-------|------|-------|
| 1. Auto File | 4h | 1h | 2h | 1h | 8h |
| 2. Explicit JSON | 2h | 2h | 2h | 1h | 7h |
| 3. Sessions | 8h | 2h | 4h | 2h | 16h |
| 4. No Caching | 0h | 0h | 0h | 0h | 0h |
| 5. Hybrid --resume | 3h | 1h | 2h | 1h | 7h |

---

## Final Recommendation

### For Task 71 (Now)
**Ship with Option 4: No Caching**

**Reasoning**:
1. ✅ Zero implementation risk
2. ✅ Simple, predictable behavior
3. ✅ No users yet → No real pain data
4. ✅ Can add caching later without breaking changes
5. ✅ Focus energy on completing Task 71 core features

**Document the limitation**:
```markdown
## Known Limitation: External Agent Repair Performance

When using `--no-repair`, checkpoint data is not preserved between runs.
Each agent repair iteration re-executes the entire workflow from scratch.

**Impact**: Workflows with expensive nodes (LLM calls, API requests) will
incur full cost/time on each iteration.

**Workaround**: Minimize repair iterations by using `--validate-only` before
execution to catch errors early.

**Future**: Checkpoint persistence may be added in a future release if this
becomes a significant pain point for users.
```

### For Post-MVP (If Needed)
**Implement Option 5: Hybrid --resume Flag**

**Trigger Conditions**:
- Real user feedback about re-execution cost
- Agent workflows averaging >3 repair iterations
- Workflows with expensive nodes (>5s or >$0.01 per node)

**Implementation**:
1. Save `__execution__` + `__cache_hits__` after each run
2. Add `--resume` flag to load last checkpoint
3. Validate compatibility via node config hashing
4. Warn and invalidate if incompatible

---

## Conclusion

**Current Answer**: Don't implement caching for external agents in Task 71.

**Future Path**: Add `--resume` flag if real-world usage shows it's needed.

**Key Insight**: Agent thinking time (5-30s) dominates execution time (<5s) for most workflows. Caching is optimization for a problem we don't yet have.

**Recommendation**: Ship Task 71 without external caching, revisit based on user feedback.
