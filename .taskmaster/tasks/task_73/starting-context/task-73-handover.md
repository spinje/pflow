# Task 73 Handoff Memo: Checkpoint Persistence for External Agent Repair

**From**: Context Window Agent (Task 71 + Task 73 Analysis)
**To**: Implementation Agent
**Date**: 2025-10-02
**Critical**: Read this BEFORE reading spec or starting implementation

---

## 🎯 The Core Insight That Changes Everything

**This is NOT about performance optimization. This is about CORRECTNESS.**

I initially approached this as "let's cache nodes to save time/money." The user immediately corrected me:

> "This is not really about time, and not even about costs. Its about the problem that multiple side effects are taking place and in some cases this can be a big problem"

**The Real Problem**: External agent repair loops cause **duplicate side effects**:
- GitHub issue #123 created ✅
- Agent fixes workflow, runs again
- GitHub issue #124 created ⚠️ **DUPLICATE!**
- Same for: Slack messages, database writes, API calls, file operations

This breaks idempotency. It's a **correctness bug**, not a performance issue.

Internal repair (built-in auto-repair) doesn't have this problem because it preserves cache in-memory via `resume_state=result.shared_after`. External agents have no way to do this across process invocations.

---

## 🧠 What I Know That You Need to Know

### 1. The Implementation Is Simpler Than You Think

**The plumbing already exists!** Look at:

```python
# src/pflow/execution/workflow_execution.py - Line ~460
def execute_workflow(
    workflow_ir: dict,
    execution_params: dict,
    enable_repair: bool = True,
    resume_state: Optional[dict] = None,  # ← Already supports resume!
    ...
):
```

The execution engine ALREADY handles resume. Internal repair uses this:

```python
# Lines 341-489 - Internal repair loop
result = executor.execute_workflow(...)  # First run
repaired_ir = repair_workflow(...)
result = executor.execute_workflow(
    resume_state=result.shared_after  # ← Just passes shared store!
)
```

**All you need to do**:
1. Save `result.shared_after["__execution__"]` + `result.shared_after["__cache_hits__"]` to disk
2. Load it back as `resume_state` when `--resume` flag is set
3. Validate it's compatible before using

That's it. The hard part is already built.

### 2. The Checkpoint Format Is Already Perfect

The `__execution__` dict has everything needed:

```python
# From instrumented_wrapper.py:529-535
shared["__execution__"] = {
    "completed_nodes": ["node1", "node2"],  # What succeeded
    "node_actions": {"node1": "default", "node2": "default"},  # Actions returned
    "node_hashes": {"node1": "abc123...", "node2": "def456..."},  # Config hashes
    "failed_node": "node3"  # Where it failed
}

# Also save (from Task 71 implementation):
shared["__cache_hits__"] = ["node1"]  # Which were cached
```

**Security checked**: This is SAFE to persist. It's just metadata - no user data, no secrets, no API keys.

### 3. Hash-Based Validation Strategy (Critical!)

The instrumented wrapper ALREADY computes MD5 hashes of node configs for cache validation:

```python
# instrumented_wrapper.py:554-562
def _check_cache_validity(self, shared):
    node_config = self._compute_node_config()  # Type + params
    current_hash = self._compute_config_hash(node_config)  # MD5
    cached_hash = shared["__execution__"]["node_hashes"].get(self.node_id)

    if current_hash == cached_hash:
        return True  # Cache valid
    else:
        return False  # Config changed, invalidate
```

**Reuse this exact mechanism** for checkpoint validation:

```python
def is_checkpoint_compatible(checkpoint, workflow_ir):
    # ONLY validate completed nodes (failed/not-executed can change freely)
    for node_id in checkpoint["completed_nodes"]:
        node = find_node_in_ir(workflow_ir, node_id)
        current_hash = compute_node_hash(node)
        cached_hash = checkpoint["node_hashes"].get(node_id)
        if current_hash != cached_hash:
            return False  # Node changed, checkpoint invalid
    return True
```

**Why this works**: If a completed node's config changed, its hash will differ. We can't trust the cached result. Start fresh.

**Why only completed nodes**: The failed node (and beyond) haven't executed yet, so they can change without invalidating the checkpoint.

### 4. Where resume_state=None Currently Lives

```python
# src/pflow/cli/main.py:1732
result = execute_workflow(
    workflow_ir=ir_data,
    execution_params=enhanced_params,
    enable_repair=not no_repair,
    resume_state=None,  # ← ALWAYS None - this is what you're fixing!
    ...
)
```

**Your change**:
```python
# Load checkpoint if --resume flag set and compatible
resume_state = None
if ctx.obj.get("resume_flag"):
    checkpoint = load_checkpoint()
    if checkpoint and is_checkpoint_compatible(checkpoint, ir_data):
        resume_state = {
            "__execution__": checkpoint["execution_state"],
            "__cache_hits__": checkpoint["cache_hits"]
        }
    elif checkpoint:
        click.echo("⚠️  Checkpoint incompatible (workflow changed), starting fresh", err=True)

result = execute_workflow(
    resume_state=resume_state,  # ← Now can be loaded from disk!
    ...
)
```

---

## 🔍 The 5 Options Analysis (Don't Revisit This)

I thoroughly analyzed 5 approaches with the user. We settled on **Option 5: Hybrid --resume Flag**. The analysis is in:

**`scratchpads/task-71-agent-experience/checkpoint-persistence-options.md`**

**Why Option 5**:
- Simple agent UX (just add `--resume`)
- Minimal code changes
- Agent controls caching (explicit, not magic)
- Automatic validation prevents stale cache
- Stateless (no session management complexity)

**Why NOT the others**:
- Option 1 (Auto file): Race conditions, stale cache risks
- Option 2 (Explicit JSON I/O): Too complex for agents
- Option 3 (Sessions): Over-engineered
- Option 4 (No caching): Breaks correctness for side effects

**Don't reinvent this wheel.** Implement Option 5 as specified.

---

## ⚠️ Critical Edge Cases & Gotchas

### 1. Atomic Writes Are Non-Negotiable

**WRONG**:
```python
with open(checkpoint_path, 'w') as f:
    json.dump(checkpoint, f)  # If process crashes here, corrupted!
```

**RIGHT**:
```python
import tempfile
import os

# Write to temp file first
fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(checkpoint_path))
with os.fdopen(fd, 'w') as f:
    json.dump(checkpoint, f)
    f.flush()
    os.fsync(f.fileno())  # Force to disk

# Atomic rename (POSIX guarantee)
os.rename(temp_path, checkpoint_path)
```

**Why**: If the process crashes mid-write, you get a corrupted checkpoint. Temp + rename is atomic on POSIX systems.

### 2. The "Last Execution" Limitation

The checkpoint manager stores **one checkpoint** at `~/.pflow/checkpoints/last-execution.json`.

**This means**:
- Works great: Single agent, single workflow, iterative repair
- Breaks: Agent switches between workflows without finishing first
- Breaks: Parallel agent executions on different workflows

**This is ACCEPTABLE for MVP**. Document as known limitation. Don't over-engineer.

**Why "last" not "per-workflow"**: Simpler to implement, covers 90% of use cases, can enhance later if needed.

### 3. What Happens on Incompatibility

When checkpoint is incompatible:
1. ⚠️ Warn the user (stderr)
2. Set `resume_state=None` (start fresh)
3. Continue execution normally
4. Save NEW checkpoint at the end

**Don't error out!** Incompatibility is expected when agent modifies completed nodes. Just gracefully fallback.

### 4. When to Save Checkpoint

**Save on BOTH success AND failure**:

```python
try:
    result = execute_workflow(...)
finally:
    # Save checkpoint even if failed!
    save_checkpoint(result.shared_after, ir_data, workflow_name)
```

**Why save on failure**: Agent needs checkpoint to resume after fixing the failure. That's the whole point!

---

## 🔗 Critical Code References

### Files You MUST Read

1. **`src/pflow/execution/workflow_execution.py`**
   - Lines 460-496: `execute_workflow()` signature and resume_state handling
   - Lines 153-176: `_prepare_shared_store()` - shows how resume_state is used
   - Lines 341-489: Internal repair loop (shows resume_state in action)

2. **`src/pflow/runtime/instrumented_wrapper.py`**
   - Lines 529-539: `__execution__` initialization
   - Lines 541-567: `_check_cache_validity()` - hash computation and comparison
   - Lines 257-262: Hash computation for caching (`_compute_node_config()`)
   - Lines 598-601: `__cache_hits__` tracking (from Task 71)

3. **`src/pflow/cli/main.py`**
   - Line 1732: Where `resume_state=None` currently lives (your integration point)
   - Lines 1547-1597: `execute_workflow()` call site with all context

4. **`scratchpads/task-71-agent-experience/checkpoint-persistence-options.md`**
   - Complete analysis of all 5 options
   - Security considerations
   - Cost/benefit analysis
   - Implementation effort estimates

### Integration Points

**CLI → Execution** (one direction only):
```
main.py:execute_json_workflow()
  → loads checkpoint if --resume
  → passes as resume_state
  → execute_workflow() in workflow_execution.py
  → saves checkpoint in finally block
```

**Checkpoint Manager** (new component you're building):
```
checkpoint_manager.py:
  - save_checkpoint(shared_after, workflow_ir, workflow_name)
  - load_checkpoint() → dict or None
  - validate_checkpoint(checkpoint, workflow_ir) → bool
  - clear_checkpoint()
```

---

## 💡 Patterns to Follow (From Task 71)

Task 71 established these patterns for agent features:

1. **Explicit flags, not automatic behavior**: `--resume` (not auto-load)
2. **Agent-friendly errors**: Clear warnings when checkpoint invalid
3. **JSON output alignment**: Task 71 added `execution.steps` to JSON - this SHOWS the caching problem to agents
4. **Stateless design**: No sessions, no background state management

**Follow these patterns.** Don't introduce magic or complexity.

---

## 🐛 Subtle Bugs to Avoid

### Bug 1: Don't Include Full Shared Store in Checkpoint

**WRONG**:
```python
checkpoint = {
    "shared_store": result.shared_after  # NO! May have secrets!
}
```

**RIGHT**:
```python
checkpoint = {
    "execution_state": result.shared_after.get("__execution__", {}),
    "cache_hits": result.shared_after.get("__cache_hits__", [])
}
```

**Why**: `shared_after` might contain API keys, tokens, user data. Only persist metadata.

### Bug 2: Don't Validate Failed/Not-Executed Nodes

**WRONG**:
```python
# Validates ALL nodes in workflow
for node in workflow_ir["nodes"]:
    if node_hash_changed(node):
        return False
```

**RIGHT**:
```python
# Only validates COMPLETED nodes
for node_id in checkpoint["completed_nodes"]:
    if node_hash_changed(node_id):
        return False
```

**Why**: Agent is SUPPOSED to modify the failed node - that's the repair! Only completed nodes need to stay unchanged.

### Bug 3: Race Condition on Concurrent Writes

**Problem**: Two agents running concurrently, both write `last-execution.json`.

**Solution**: Document as limitation (acceptable for MVP). Last write wins. Don't over-engineer with locking.

**Future enhancement**: Per-workflow checkpoints or session IDs. Not worth the complexity now.

---

## 🎨 Design Decisions Already Made

### Why ~/.pflow/checkpoints/?

Follows existing pflow conventions:
- `~/.pflow/workflows/` - saved workflows
- `~/.pflow/debug/` - trace files
- `~/.pflow/checkpoints/` - checkpoint files

Consistent with user expectations.

### Why last-execution.json?

Single checkpoint simplifies implementation:
- No cleanup needed (just overwrites)
- No per-workflow tracking complexity
- Agent typically works on one workflow at a time
- Clear naming (user can inspect manually)

### Why Not Include Checkpoint in JSON Output?

We considered adding checkpoint to `--output-format json` (Option 2 from analysis). Decided against it because:
- Too verbose (checkpoint in every response)
- Agent would need to parse and pass back
- Extra complexity for marginal benefit

**The --resume flag is simpler**: Agent just adds flag, checkpoint loaded automatically.

---

## 🧪 Test Strategy Insights

### Key Test Scenarios

1. **Side Effect Deduplication** (THE critical test):
```python
def test_external_agent_repair_no_duplicate_side_effects():
    # Create workflow with observable side effect (e.g., file write counter)
    # Run 1: Fails at node 3, side effect occurred once
    # Agent fixes workflow
    # Run 2 with --resume: Nodes 1-2 cached, side effect NOT duplicated
    assert side_effect_count == 1  # Not 2!
```

2. **Checkpoint Compatibility**:
```python
def test_modified_completed_node_invalidates_checkpoint():
    # Run 1: Node 1 succeeds with param X, node 2 fails
    # Modify node 1 to have param Y
    # Run 2 with --resume: Checkpoint invalid, node 1 re-executes
```

3. **Graceful Fallback**:
```python
def test_corrupted_checkpoint_proceeds_fresh():
    # Manually corrupt checkpoint file
    # Run with --resume: Warns, starts fresh, succeeds
```

### Don't Test Concurrent Execution

It's a documented limitation. Save the complexity for when users actually need it.

---

## 📋 What You Don't Need to Build

**Out of scope for MVP** (resist feature creep):

- ❌ Multiple checkpoints per workflow
- ❌ Named checkpoints (--resume <name>)
- ❌ Checkpoint expiration (TTL)
- ❌ Checkpoint in JSON output (--output-format json)
- ❌ --resume-from <file> parameter
- ❌ Session-based checkpoints
- ❌ Concurrent execution support
- ❌ Checkpoint cleanup/garbage collection

**Only build**:
- ✅ Single "last execution" checkpoint
- ✅ --resume flag (boolean)
- ✅ Basic hash-based validation
- ✅ Atomic file writes
- ✅ Graceful fallback on errors

---

## 🔐 Security: Already Handled

The checkpoint data is **safe to persist**:

```python
# What's in the checkpoint (SAFE):
{
  "workflow_hash": "abc123...",  # MD5 of IR
  "execution_state": {
    "completed_nodes": ["node1"],  # Just IDs
    "node_actions": {"node1": "default"},  # Just action strings
    "node_hashes": {"node1": "hash"},  # Just hashes
    "failed_node": "node2"  # Just ID
  },
  "cache_hits": ["node1"],  # Just IDs
  "timestamp": "2025-10-02T10:30:00",
  "workflow_name": "my-workflow"
}
```

**What's NOT in checkpoint**:
- ❌ Full `shared` store (may have API keys, tokens)
- ❌ `__llm_calls__` (may have prompts/responses)
- ❌ Node outputs (may have PII, sensitive data)
- ❌ User parameters

**No security review needed.** It's just metadata.

---

## 🚨 Critical: Don't Over-Think This

The tendency will be to make this more complex than it needs to be. **Resist!**

**Simple truth**:
- Internal repair already works with resume_state
- Checkpoint is just `__execution__` + `__cache_hits__`
- Save to file, load from file, validate hashes
- Done

**Core files to create**:
1. `src/pflow/core/checkpoint_manager.py` (~150 lines)
2. CLI integration in `main.py` (~30 lines)
3. Tests (~200 lines)

**That's it.** Don't architect a whole checkpoint system. Just persist the dict and load it back.

---

## 📊 Success Metrics

**You're done when**:

1. Agent can run workflow → fail → fix → resume without duplicate side effects
2. Checkpoint is validated and invalidated correctly
3. All tests pass (especially side effect deduplication test)
4. `make test` and `make check` pass
5. Documentation clearly explains --resume flag and limitations

**Evidence of success**:
```bash
# Agent workflow
pflow --no-repair --output-format json workflow.json
# → Fails at node 3
# → execution.steps shows node 1-2 completed

# Agent fixes node 3
# Agent resumes
pflow --no-repair --resume --output-format json workflow.json
# → execution.steps shows node 1-2 cached (from execution metadata)
# → Only node 3+ execute
# → No duplicate side effects!
```

---

## 🎁 Parting Gifts

### Things That Will Save You Time

1. **Hash computation already works**: `_compute_node_config()` and `_compute_config_hash()` in instrumented_wrapper.py. Don't rewrite this.

2. **Resume state just works**: `_prepare_shared_store()` in workflow_execution.py handles resume_state. It literally just uses it as-is.

3. **CLI flag pattern**: Look at `--no-repair` implementation for how to add `--resume`. Same pattern.

4. **Atomic writes**: Use the tempfile → rename pattern. Don't try to be clever with locks.

### Things That Will Waste Your Time

1. **Don't build per-workflow checkpoints** (yet). Last execution is fine.
2. **Don't add checkpoint to JSON output** (yet). The --resume flag is sufficient.
3. **Don't solve concurrent execution** (yet). Document as limitation.
4. **Don't add cleanup/TTL** (yet). Single checkpoint doesn't need it.

### The Hidden Insight

The user's mental model: **Internal repair and external repair should behave the same.**

Internal repair caches → no duplicate side effects.
External repair should cache → no duplicate side effects.

Make external repair work like internal repair. That's the whole task.

---

## ✅ Final Checklist Before You Start

Before implementing, verify you understand:

- [ ] Why this is about correctness (side effects), not performance
- [ ] That resume_state plumbing already exists in execute_workflow()
- [ ] What's in the checkpoint (`__execution__` + `__cache_hits__`)
- [ ] Why we only validate completed nodes (not failed/not-executed)
- [ ] How hash-based validation prevents stale cache
- [ ] Why atomic writes (temp + rename) are required
- [ ] That "last execution" single-checkpoint is the MVP scope
- [ ] Where resume_state=None currently lives (main.py:1732)
- [ ] The 5 options were analyzed, Option 5 chosen (don't revisit)
- [ ] Security is handled (checkpoint is metadata-only)

**If any of these are unclear, re-read this handoff or ask for clarification.**

---

## 🏁 Ready to Begin?

When you're ready to implement:

1. **Read the task spec** (task-73.md) for formal requirements
2. **Read the options analysis** (checkpoint-persistence-options.md) for full context
3. **Read the code files** listed in "Critical Code References" section
4. **Create implementation plan** based on your understanding
5. **Start with checkpoint_manager.py** (core functionality)
6. **Then CLI integration** (main.py changes)
7. **Then tests** (especially side effect deduplication)

**Good luck!** This is simpler than it looks. The hard parts are already built.

---

**Important**: Do NOT begin implementing yet. Read this handoff, read the spec, read the referenced code, THEN create your implementation plan and confirm you're ready to begin.
