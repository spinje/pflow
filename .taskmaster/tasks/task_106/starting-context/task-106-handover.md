# Task 106 Handoff: Automatic Workflow Iteration Cache

## How We Got Here

This task emerged from a real pain point discovered while building the `examples/real-workflows/generate-changelog/` workflow. During iteration:

1. Run workflow → Nodes 1-12 succeed, node 13 fails
2. Fix node 13's prompt
3. Run workflow again → **All 36 LLM calls re-execute** ($0.09, 50 seconds wasted)
4. Repeat...

The conversation evolved:
- Started discussing `--stop-at` for debugging
- User asked: "Is this what Task 44 was about?"
- I investigated Task 44 (node caching) and Task 73 (checkpoint persistence)
- User pointed out the paradigm shift: pflow should expose **primitives for AI agents**, not build complex internal systems
- User emphasized: **"too verbose, should be as easy to use as possible by AI agents"**
- Result: Task 106 synthesizes and supersedes both Task 44 and Task 73

## Critical User Requirements (Verbatim)

1. **"using a checkpoint dir would be too verbose"** → NO explicit paths or directories
2. **"this should be as easy to use as possible by AI agents to use with no friction"** → NO flags like `--resume`
3. **Saved workflows should NEVER be modified by agents** → Iteration cache only for file-based workflows
4. **"agents should copy it to the current pwd and iterate on it there"** → The iteration workflow

## The Paradigm Shift You MUST Understand

The user explicitly called out a philosophical shift in pflow's design:

**Old paradigm (rejected):**
- pflow has internal caching system
- pflow has internal repair system
- Complex internal features the user doesn't control

**New paradigm (required):**
- pflow exposes simple primitives
- AI agents orchestrate using those primitives
- Zero configuration, automatic behavior

Task 106 must embody this: **automatic, invisible, zero-friction**.

## Relationship to Task 89 (CRITICAL)

Task 89 implemented "Structure-Only Mode" - a DIFFERENT concern:

| Aspect | Task 89 | Task 106 |
|--------|---------|----------|
| **Phase** | Workflow CREATION | Workflow TESTING |
| **Purpose** | Token efficiency + security | Cost efficiency + correctness |
| **What AI sees** | `${customer.name}: string` (no data) | Error messages, traces |
| **What's cached** | Node output STRUCTURE | Node output VALUES |
| **Scope** | `registry run` (single node) | `pflow workflow.json` (full workflow) |

**They are COMPLEMENTARY, not competing:**
1. AI uses Task 89 (structure-only) to BUILD workflows without seeing sensitive data
2. AI uses Task 106 (iteration cache) to TEST/FIX workflows without re-running completed nodes

### Task 89 Files to Study

These contain reusable patterns:

- `src/pflow/core/execution_cache.py` - **START HERE**
  - `ExecutionCache` class structure
  - `generate_execution_id()` pattern
  - Binary data encoding (`_encode_binary`, `_decode_binary`)
  - Atomic writes (temp file → rename)

- `.taskmaster/tasks/task_89/task-review.md` - **READ THIS**
  - 584 lines of implementation wisdom
  - Patterns established (formatter pattern, MCP service pattern)
  - Anti-patterns to avoid
  - Edge cases discovered

- `src/pflow/core/settings.py` - Settings integration pattern for cache TTL

## Scope: File-Based vs Saved Workflows

This distinction is CRITICAL and easy to get wrong:

```python
# File-based (CACHE ENABLED)
pflow ./workflow.json              # relative path
pflow /absolute/path/workflow.json # absolute path
pflow workflow.json                # relative, no ./

# Saved workflows (NO CACHE)
pflow my-saved-workflow            # just a name, no path
```

**Why this distinction?**
- Saved workflows are **production artifacts** - validated, tested, ready
- File-based workflows are **being iterated on** - the agent is debugging/fixing
- Caching saved workflows would be confusing (they should always run fresh)

**Detection logic needed:**
```python
def is_file_based_workflow(arg: str) -> bool:
    # Has path separator or file extension
    return '/' in arg or '\\' in arg or arg.endswith('.json')
```

## Cache Invalidation Strategy

The task spec describes cascade invalidation, but here's the nuance:

**Hash based on NODE CONFIG, not inputs:**
```python
hash(node.id + node.type + json.dumps(node.params) + json.dumps(node.batch))
```

**Why not include inputs?**
- Inputs come from upstream nodes
- If upstream node re-runs, it will invalidate downstream anyway
- Including inputs would require re-running upstream just to check cache validity

**Cascade logic:**
1. Check if node config hash matches cached hash
2. If not → invalidate this node + all downstream
3. If yes → check if ALL upstream nodes are cache hits
4. If any upstream is cache miss → this node is also cache miss

## Integration Point: workflow_executor.py

The main integration is in `src/pflow/runtime/workflow_executor.py`. Study how it:
- Iterates through nodes in order
- Executes each node
- Updates shared store with outputs

You'll need to inject cache check BEFORE execution and cache save AFTER success.

**Current pattern (simplified):**
```python
for node in workflow.nodes:
    result = node.run(shared)
    shared.update(result.outputs)
```

**With iteration cache:**
```python
for node in workflow.nodes:
    if iteration_cache.should_use_cache(node.id, workflow_ir):
        cached = iteration_cache.load_node(node.id)
        shared.update(cached.outputs)
        continue  # Skip execution

    result = node.run(shared)

    if result.success:
        iteration_cache.save_node(node.id, result.outputs, workflow_ir)

    shared.update(result.outputs)
```

## Edge Cases the User Didn't Mention But You Should Handle

1. **Batch nodes**: Cache the ENTIRE batch result, not individual items. If batch config changes, re-run entire batch.

2. **Side effects**: The whole point is preventing duplicate side effects (GitHub issues created twice, emails sent twice). The test should include a mock node with a counter to verify it's only called once across iterations.

3. **LLM usage tracking**: Cached nodes should NOT contribute to `__llm_calls__` or cost metrics for that run. They weren't actually executed.

4. **Display**: Show `(cached, 12ms)` vs `(2.3s)` so the user knows what was cached.

## What NOT to Do

1. **Don't add `--resume` or any flag** - The user explicitly rejected this as "too verbose"

2. **Don't cache saved workflows** - Only file-based workflows in iteration mode

3. **Don't require configuration** - It should "just work" with sensible defaults

4. **Don't store sensitive data warnings** - Task 89's review shows they decided to just use file permissions (600) rather than filtering. Same approach here.

5. **Don't implement concurrent execution support** - Documented as limitation, "last write wins" is acceptable for MVP

## Questions to Investigate

1. **How does `main.py` currently distinguish file-based from saved workflows?**
   - Check `src/pflow/cli/main.py` for the resolution logic
   - There's likely already a `WorkflowManager.resolve()` pattern

2. **MCP integration needed?**
   - Task 89 has MCP tools (`registry_run`, `read_fields`)
   - Does Task 106 need MCP tools or is it CLI-only?
   - Probably CLI-only since MCP agents use `execute_workflow` tool which already runs file-based workflows

3. **Interaction with existing repair system?**
   - There's an internal repair system in `src/pflow/execution/repair_service.py`
   - Task 106 should work orthogonally - cache is checked before any repair logic

## Files Summary

**Must read:**
- `.taskmaster/tasks/task_89/task-review.md` - Patterns, anti-patterns, lessons
- `src/pflow/core/execution_cache.py` - Reusable cache patterns
- `src/pflow/runtime/workflow_executor.py` - Integration point

**Probably useful:**
- `src/pflow/cli/main.py` - How workflows are resolved
- `src/pflow/core/workflow_manager.py` - Workflow resolution logic
- `.taskmaster/tasks/task_73/task-73.md` - The deprecated approach (for context on what NOT to do)

**The generate-changelog workflow that sparked this:**
- `examples/real-workflows/generate-changelog/workflow.json` - 15 nodes, good test case
- `examples/real-workflows/generate-changelog/README.md` - Documents the iteration pain

## Alternative Considered: `--run-node` Flag

During development of the generate-changelog workflow, an alternative approach was discussed: explicit node isolation via `--run-node=node_id`. This would let you run a specific node in isolation, either with cached predecessor outputs or mocked inputs.

**Why Task 106's automatic caching was preferred:**

| Aspect | `--run-node` flag | Task 106 automatic cache |
|--------|-------------------|-------------------------|
| AI agent friction | Requires flag awareness | Zero - invisible |
| Configuration | Needs `--input` for mocks | None needed |
| Coverage | Single node | Full workflow iteration |
| Use case | Debugging specific node | General iteration |

**When `--run-node` might still be valuable:**
1. Testing a node with different mock data (cache only stores real outputs)
2. Avoiding cache lookup overhead during rapid single-node iteration
3. Debugging a node's behavior in complete isolation

This is documented in Future Enhancements. If Task 106's caching proves insufficient for certain debugging workflows, consider adding `--run-node` as a complementary feature. But start with automatic caching - it solves 90% of iteration pain with zero friction.

## Concrete Example: Shell Command Development

During generate-changelog development, adding a new shell command required this workflow:

**Without Task 106 (current friction):**
```
1. Write shell command in bash terminal to test it
2. Verify it works
3. Copy to workflow.json (escape \n, quotes, etc.)
4. Run full workflow to verify it works in context
5. If escaping broke it → back to step 1
```

The agent tests externally because running the full workflow is expensive (time + cost).

**With Task 106 (automatic cache):**
```
1. Write shell command directly in workflow.json
2. Run workflow → predecessors cached (instant), only new node runs
3. Fails? Fix command, run again → still cached
4. Iterate until correct
```

**With `--run-node` (explicit isolation):**
```
1. Write shell command in workflow.json
2. pflow workflow.json --run-node=get-docs-diff --input resolve-tag.stdout="v0.5.0"
3. Fails? Fix command, run again
4. Iterate until correct
```

Both approaches eliminate the "test in bash first" step. Task 106 is automatic and covers full workflow iteration. `--run-node` is explicit and useful when you want to test with specific mock data.

**Key insight:** The cache removes the penalty for "getting it wrong the first time" - so agents can write directly in the workflow and iterate there.

## Final Reminder

The user's core philosophy: **pflow exposes primitives, AI agents orchestrate**. Task 106 is not about building a complex caching system - it's about making iteration **invisible and automatic**.

If an AI agent has to think about caching, you've failed. It should just work.

---

**Do not begin implementation yet.** Read this document, read Task 89's review, examine the relevant files, and confirm you understand the scope and constraints. Reply that you are ready to begin when you have absorbed this context.
