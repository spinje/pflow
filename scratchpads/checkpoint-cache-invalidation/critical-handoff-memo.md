# Critical Handoff Memo: Cache Invalidation Implementation

## ⚡ The One Thing You Must Understand

**This bug makes the entire repair system useless for shell commands**. Without this fix, the brilliant checkpoint/repair system from Phase 2 is fundamentally broken. A shell node that returns "error" gets cached with that error forever, even after repair adds `ignore_errors: true`.

## 🔥 What I Discovered That Isn't In The Specs

### The 27-Attempt Nightmare
The current system can attempt repair up to **27 times** on the same error:
- 3 runtime attempts × 3 validation attempts × 3 repair attempts each
- This cache bug is part of why - cached errors keep triggering repair
- Once you fix this, also implement loop detection (10 lines in workflow_execution.py)

### Shell Nodes Are Aggressive
Shell nodes return "error" for ANY non-zero exit code except:
- grep (exit 1 is normal for no matches)
- ls with globs (exit 1 for no matches)
- Explicitly safe patterns

This means `jq` failing with exit code 5 (JSON parse error) returns "error" action. This is the exact scenario in test3-multi-node.json that exposed the bug.

### The Three Success States (Critical Insight)
The system conflates three different types of "success":
1. **Execution Success**: Code ran without exception
2. **Action Success**: Node returned "default" not "error"
3. **Business Success**: Node achieved desired outcome

The cache should ONLY store nodes with all three successes. Currently it caches #1 regardless of #2 and #3.

## ⚠️ Gotchas That Will Bite You

### 1. Backward Compatibility Trap
Existing checkpoints don't have `node_hashes` field. Your code MUST handle:
```python
# This will exist in production
shared["__execution__"] = {
    "completed_nodes": ["step1"],
    "node_actions": {"step1": "default"}
    # NO node_hashes field!
}
```
If you don't handle this, you'll break every existing workflow.

### 2. Multiple Wrapper Layers
Nodes are wrapped like Russian dolls:
```
InstrumentedNodeWrapper
  -> NamespacedNodeWrapper
    -> TemplateAwareNodeWrapper
      -> ActualNode
```
Your `_compute_node_config()` must traverse ALL layers to reach the actual node. The spec shows how, but know WHY - you need the real node's params, not wrapper configuration.

### 3. The String Check
The error action is literally the string "error". Not None, not False, not 0. Check explicitly:
```python
if result != "error":  # NOT if result or if not result
```

### 4. Hash Determinism
The hash MUST be identical across runs for the same config. That's why:
- Sort dictionary keys
- Use JSON serialization
- Don't include timestamps or random values

## 🧩 How This Connects to Everything Else

### Phase 2 Context
You're fixing a bug in the checkpoint system that was JUST added in Task 68 Phase 2. The implementer discovered template errors weren't failing properly and made them fatal. But that exposed THIS bug - nodes that fail can't be repaired because they're cached.

### Enables API Warning System
Once cache invalidation works, we can build the API warning system on top (see scratchpads/api-warning-system/). That system needs to mark certain errors as non-repairable, which only makes sense if repairable errors can actually be retried.

### The Repair System Flow
1. Workflow fails at step3 (shell returns "error")
2. Repair adds `ignore_errors: true` to step3
3. **WITHOUT YOUR FIX**: step3 returns cached "error", workflow fails again
4. **WITH YOUR FIX**: step3 re-executes with ignore_errors, succeeds

## 📍 Specific Files and Lines

### The Test That Matters
`test-repair-scenarios/test3-multi-node.json` - This MUST pass after your fix

### Where The Bug Lives
`src/pflow/runtime/instrumented_wrapper.py`:
- Line 307-318: Cache check that doesn't validate
- Line 333-335: Caching that includes error nodes
- Line 302: Checkpoint initialization

### Where Shell Returns Error
`src/pflow/nodes/shell/shell.py` line 393 - See why shell is so aggressive about errors

## 🎯 Success Criteria Beyond Tests

### Observable Behavior
When you run the test workflow:
1. **First run**: step3 fails, returns "error"
2. **After repair**: step3 shows re-executing (NOT "↻ cached")
3. **Log shows**: "Node step3 configuration changed, invalidating cache"
4. **Final result**: Workflow succeeds

### What NOT to See
- step3 showing "↻ cached" after repair modified it
- Infinite repair loops
- "Flow ends: 'error' not found" repeating

## 💡 Implementation Wisdom

### Don't Over-Engineer
The specs might tempt you to add:
- Sophisticated cache strategies
- SHA256 instead of MD5
- Partial cache invalidation
- TTL-based expiry

**DON'T**. Just fix the bug. MD5 is fine for config change detection.

### Test With Real Failures
Mock tests won't expose the real issue. You need:
- Actual shell commands that fail
- Real repair attempts
- The full checkpoint/resume cycle

### The Simplest Fix
At its core, this is just:
1. Don't cache nodes that return "error"
2. Validate cache entries with config hash
That's it. Everything else is implementation detail.

## 🔗 Related Documentation

### Must Read
- `scratchpads/checkpoint-cache-invalidation/problem-analysis.md` - Deep dive into the bug
- `scratchpads/checkpoint-cache-invalidation/implementation-spec.md` - Your implementation guide
- `.taskmaster/tasks/task_68/implementation/progress-log.md` lines 184-337 - Phase 2 implementation context

### Useful Context
- `scratchpads/api-warning-system/` - What this enables
- `src/pflow/planning/nodes.py` lines 2882-3387 - RuntimeValidationNode that was removed

## ❓ Questions That Might Arise

**Q: Why not just clear all cache on repair?**
A: Would cause unnecessary re-execution of successful nodes. We want surgical invalidation.

**Q: Why MD5 not SHA256?**
A: This isn't cryptographic security, just change detection. MD5 is faster.

**Q: Should template resolution failures be cached?**
A: No, but they throw exceptions so they don't hit the caching code anyway.

**Q: What about nodes with random outputs?**
A: Config hash only includes params, not outputs. Random outputs are fine.

## 🚨 The One Test That Proves It Works

```bash
# This command sequence MUST work after your fix:
uv run pflow test-repair-scenarios/test3-multi-node.json

# Should fail at step3
# Repair should modify step3
# Resume should re-execute step3 (not cache)
# Workflow should complete successfully
```

If this works, you've fixed the core issue.

## Final Critical Warning

**This is blocking production usage of the repair system**. Every shell command that fails is currently unrepairable due to this bug. The Phase 2 implementer's beautiful checkpoint/repair system is crippled without your fix.

But also: don't panic. The fix is straightforward. The spec is complete. Just follow it carefully, handle the edge cases, and test with real workflows.

You're fixing the foundation that everything else builds on. Make it solid.

---
*Written by: The architect who discovered this was why repair wasn't working*
*Task context: Task 68 Phase 2 - Repair System Implementation*
*Date: 2025-01-24*