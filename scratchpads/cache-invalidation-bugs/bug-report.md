# Bug Report: Cache Does Not Invalidate on Sub-Workflow Changes + Cached Runs Report Phantom Cost

Two related caching bugs discovered while iterating on a production pipeline (241 LLM calls, 6 sub-workflows). Both affect the iteration workflow that caching is designed to speed up.

---

## Bug 1: Sub-Workflow File Changes Don't Invalidate Cache

### Summary

When a sub-workflow file (referenced via `- type: workflow`) is modified, the parent workflow's cache does not invalidate. The cache returns stale results from before the sub-workflow was changed. This also applies to external prompt files referenced by sub-workflows.

The cache correctly invalidates when the **parent** workflow file changes (inline prompts, node config), but does NOT track changes to:
- Sub-workflow `.pflow.md` files referenced by `- workflow: ./path.pflow.md`
- External `.prompt.md` files referenced within those sub-workflows

### Impact

Any iteration on sub-workflow internals silently returns stale results. The user sees `[cached]` and assumes their changes had no effect, when in reality the changes were never executed. This is particularly dangerous because:
- The output looks correct (it was correct for the previous version)
- There's no warning that the cache key doesn't include sub-workflow content
- `--no-cache` is the only workaround, which defeats the purpose of caching

### Steps to Reproduce

**1. Create a child workflow (`test-cache-child.pflow.md`):**

```markdown
# Cache Test Child

Sub-workflow that generates a greeting.

## Inputs

### name
A name to greet.
- type: string

## Steps

### say-hello
Generate a greeting.
- type: llm
- prompt: Say hello to ${name} in exactly one sentence.

## Outputs

### greeting
The generated greeting.
- source: ${say-hello.response}
```

**2. Create a parent workflow (`test-cache-parent.pflow.md`):**

```markdown
# Cache Test Parent

Calls the child sub-workflow.

## Inputs

### name
A name to greet.
- type: string
- default: "World"

## Steps

### greet
Call the sub-workflow to generate a greeting.
- type: workflow
- workflow: ./test-cache-child.pflow.md
- name: ${name}

## Outputs

### greeting
The generated greeting.
- source: ${greet.greeting}
```

**3. Run the parent workflow:**

```bash
pflow test-cache-parent.pflow.md name='Bob'
# Output: "Hello, Bob!" — executes normally
```

**4. Run again (verify caching works):**

```bash
pflow test-cache-parent.pflow.md name='Bob'
# Output: "Hello, Bob!" — [cached], instant. Correct.
```

**5. Change the child workflow prompt:**

Change `Say hello to ${name}` to `Say goodbye to ${name} in exactly one sentence. Be very sad about it.`

**6. Run the parent workflow again (same inputs):**

```bash
pflow test-cache-parent.pflow.md name='Bob'
# Output: "Hello, Bob!" — [cached], instant.
# BUG: Should have re-executed with "goodbye" prompt. Returns stale "hello" result.
```

### Expected Behavior

Run 6 should detect that `test-cache-child.pflow.md` was modified and invalidate the cache for the `greet` node. The LLM should be called with the new "goodbye" prompt.

### Suggested Fix

Include the content hash of all referenced sub-workflow files (and their referenced prompt files, recursively) in the cache key. When any file in the dependency tree changes, the cache should invalidate for that node and all downstream nodes.

---

## Bug 2: Cached Runs Report Historical Cost as Current Cost

### Summary

When all nodes return from cache (0 LLM calls executed), pflow reports a non-zero cost. This appears to be the sum of the original costs from when the cached nodes were first executed, not the actual cost of the current run.

### Impact

Users see a cost like `$0.0349` on a run that made zero LLM calls. This is confusing — it looks like they were charged for a cached run. For a production pipeline (~$1.80/run), a user iterating with cache might think each cached re-run costs money when it doesn't.

### Steps to Reproduce

**1. Run any workflow to populate cache:**

```bash
pflow test-cache-parent.pflow.md name='Bob'
# Cost: $0.0005, 1 node executed
```

**2. Run again (fully cached):**

```bash
pflow test-cache-parent.pflow.md name='Bob'
# Output shows: 💰 Cost: $0.0005, 0 executed, 1 cached
# BUG: Should show $0.00 or no cost line, since no LLM calls were made
```

**Observed in production:** A 15-node pipeline with all nodes cached showed `$0.0468`. A `--only` run with 10 cached nodes and 0 executed showed `$0.0349`. The difference ($0.012) corresponds to the 5 skipped nodes — confirming pflow is summing historical costs of cached results.

### Expected Behavior

Either:
- **Option A:** Report `$0.00` for cached runs (actual cost of this run)
- **Option B:** Separate the display: `Cost: $0.00 (cached results originally cost $0.0468)`
- **Option C:** Only show cost for nodes that actually executed in this run

Option A is simplest and clearest.

---

## Environment

- pflow version: latest (as of 2026-03-26)
- Discovered while iterating on a 15-node orchestrator with 6 sub-workflows
- Both bugs confirmed with minimal reproduction cases
