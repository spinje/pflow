# Conditional Branching

**Use when**: Different paths based on data or errors — "if X then Y", "handle failures", "retry on error". Default flow is top-to-bottom; branching overrides it.

**Error routing** — any node can route failures to a handler:
````markdown
### call-api

Fetch data from the API.

- type: shell
- on-error: handle-error

```shell command
curl -f https://api.example.com/data
```

### process

Process the result.

- type: code
- inputs: { data: "${call-api.stdout}" }
- next: end

```python code
data: str
result: dict = {"processed": True}
```

### handle-error

Log the failure.

- type: shell
- next: end

```shell command
echo "API call failed" >&2
```
````

**Data-driven routing (literal)** — a `code` node sets `next` to pick the path. When all targets are string literals, pflow detects them automatically:
````markdown
### classify

Route based on input size.

- type: code
- inputs: { items: "${fetch.result}" }

```python code
items: list
if not items:
    raise ValueError("No items to process")
result: int = len(items)
if len(items) > 100:
    next: str = "bulk-process"
else:
    next: str = "simple-process"
```

### simple-process

Handle small batches.

- type: shell
- next: end

```shell command
echo "Small batch: ${classify.result} items"
```

### bulk-process

Handle large batches.

- type: shell
- next: end

```shell command
echo "Large batch: ${classify.result} items"
```
````

**Data-driven routing (dynamic)** — when the target comes from a variable, declare all possible targets with `- next:`:
````markdown
### route

Pick path based on category.

- type: code
- inputs: { category: "${analyze.result}" }
- next: path-a, path-b

```python code
category: str
result: str = category
next: str = category
```

### path-a

Handle category A.

- type: shell
- next: end

```shell command
echo "A: ${route.result}"
```

### path-b

Handle category B.

- type: shell
- next: end

```shell command
echo "B: ${route.result}"
```
````

**Routing rules:**
- `- next: node-id` — override default successor (any node)
- `- next: end` — terminate flow (no successor)
- `- on-error: node-id` — route on failure (any node)
- `next: str = "node-id"` — dynamic routing (code nodes only)
- `next: str = "end"` — terminate from code (code nodes only, e.g., skip optional steps)
- `"end"` is a reserved keyword — do not use it as a node ID
- No `next` set in code → continues to next node in document order

**Required: Branch targets MUST have explicit `- next:`**
- Every node reached via `- on-error:` or named routing action MUST declare `- next: end` or `- next: <node-id>`
- Without this, branches fall through to the next node in document order (silent bug)
- If code uses dynamic routing (`next = variable`), the code node MUST declare `- next: target-a, target-b` listing all possible targets
- Literal routing (`next: str = "target"`) does NOT need `- next:` on the code node — pflow detects targets automatically

**When to use**: Error handling, classification/routing, skip-ahead, retry loops. NOT for parallel execution (use batch for that).

**Branch convergence** — use `??` to reference "whichever branch ran": `${branch-high.stdout ?? branch-low.stdout}`. Tries left-to-right, first operand that resolves wins. Works in any node type — no merge node needed. Operands can also be JSON literals as a final default: `${optional_step.value ?? 0}`, `${a ?? "none"}`.

`??` falls through whenever the left side **isn't there** — whether the **node didn't run** (branch not taken, or node failed) OR the **field is absent** on a node that did run. So `${ran_node.optional_field ?? "default"}` yields `"default"` when `optional_field` isn't present. A **bare** `${node.field}` with no `??` fallback still errors on a missing field, so genuine typos are caught loudly — add a fallback only where absence is expected.

### Loops

Loops are supported via **backward edges** — a node routes back to an earlier node, which re-executes. Use a **worker/checker** pair: the worker does the work, the checker decides (via dynamic `next`) whether to loop again or exit. A node can't reference its own previous output (the store excludes a node's self-namespace), so the counter lives across the two nodes.

With literal operands (`??` accepts JSON literals), the counter seeds from a literal `0` on the first visit — no separate seed node needed:

````markdown
### worker

Increment the running count. `worker` is a branch target of `checker`'s
loop-back edge, so it needs an explicit `- next:`.

- type: code
- inputs:
    prior: ${checker.result ?? 0}
- next: checker

```python code
prior: int
result: int = prior + 1
```

### checker

Decide whether to loop or finish.

- type: code
- inputs: { count: "${worker.result}" }
- next: worker, done

```python code
count: int
result: int = count
if count >= 3:
    next: str = "done"
else:
    next: str = "worker"
```

### done

Report the final count.

- type: shell
- next: end

```shell command
echo "Looped ${worker.result} times"
```
````

Keep the counter one type end-to-end. Here it is `int` throughout, so the
literal seed is `0` (an int); the first visit (when `checker` hasn't run yet)
falls through `${checker.result ?? 0}` to `0`, and later visits read the int
`checker.result`.

**Behavior on revisit:** when a node is reached again via a backward edge, its in-process completion tracking is cleared and the persistent memo cache is bypassed for that node — so it re-executes with the new inputs each iteration.

**Visit guard:** each node may be visited at most 100 times per run (loop-runaway protection). Override with the `PFLOW_MAX_NODE_VISITS=200` environment variable.

**The worker can be any node type.** Make it a `workflow` node and the loop body becomes an entire sub-workflow that repeats until the checker's condition is met — the checker branches on one of the sub-workflow's `## Outputs`. This is how you get a heavyweight per-iteration body that still stops the moment the work is done:

````markdown
### process-chunk

The loop body — a whole sub-workflow run as one node. It handles the next chunk
of pending work and exposes a `remaining` output (a declared `## Output` of the
child). As a loop target it declares an explicit successor.

- type: workflow
- workflow: ./process-chunk.pflow.md
- next: check-remaining

### check-remaining

Loop while work is left; stop the instant it drains. There is no iteration
count — the loop exits on the condition, which the batch pattern cannot.

- type: code
- inputs: { remaining: "${process-chunk.remaining}" }
- next: process-chunk, end

```python code
remaining: int
result: int = remaining
if remaining > 0:
    next: str = "process-chunk"
else:
    next: str = "end"
```
````

**Choosing the loop style:** the deciding question is whether the number of iterations is known up front — not how heavy each iteration is. Use the sub-workflow batch pattern (`parallel: false`) for a fixed iteration count; it always runs all N. Use this backward-edge loop when iterations continue until a condition is met, since only it can stop early. Both can carry a substantial per-iteration body and read state from disk. See `pflow guide sub-workflows` → Bounded iteration.

