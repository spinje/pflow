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

There are three ways to repeat work; pick by **how the iteration count is decided**:

| You want | Use | Stops early? |
|---|---|---|
| A fixed number of iterations known up front | `batch:` (`parallel: false`) — see `pflow guide batch` | No — always runs all N |
| Repeat a step until a condition is met, capped | **`loop:`** (below) | Yes |
| Full manual control over the backward edge | backward-edge worker/checker (under the hood, below) | Yes |

#### `loop:` — condition-terminated iteration (recommended)

Add a `loop:` block to any single node (sibling to `batch:`, mutually exclusive with it). The engine re-runs that node until a truthiness condition over its **own typed output** says to stop, or an iteration cap is hit. It is a **do-while**: the body runs once, then the condition is checked.

````markdown
### run-cycle

Do one unit of work; re-run while there's more.

- type: workflow
- workflow: ./run-cycle/run-cycle.pflow.md
- inputs: { base_branch: ${base_branch} }
- loop:
    while: ${run-cycle.issues_planned}   # this node's own typed output
    max_iterations: ${max_cycles}        # int OR ${template}; optional
````

- **Exactly one of `while:` or `until:` is required.** `while: ${step.more}` means truthy → re-run, falsy → stop. `until: ${step.done}` means falsy → re-run, truthy → stop. Use `until:` for polling and approval-style "wait until done" loops so you never mentally negate the condition. If an `until:` source is absent at runtime, pflow keeps looping until the cap instead of silently exiting after one pass.
- **Conditions are single `${...}` references to the loop node's own output.** Truthiness is type-aware: a list drains to empty, a number counts to 0, a boolean flips to `false`. The source must be a typed output — a raw string source (e.g. `${step.stdout}`) is **rejected at validation** because a non-empty string like `"0\n"` is truthy and would never stop the loop. Comparisons/arithmetic (`${x > 0}`) are not supported — compute a boolean in the body and reference it (`while: ${step.has_more}` or `until: ${step.done}`).
- **`carry:` feeds state from round N output to round N+1 input.** Keys are body input names; values must reference this loop node's latest output. The node's normal `inputs:` mapping is the round-1 seed. From round 2 onward, `carry:` overrides only the carried keys; non-carried inputs stay constant.
- **`max_iterations:`** is an integer or a `${template}` resolving to one. Optional — defaults to the visit guard (100). Reaching the cap is **not** an error: the run stays SUCCESS, a non-degrading INFO advisory is emitted, and the loop node's output carries `loop_stopped: "max_iterations"` (vs `"condition"` on a clean drain). Read `${loop-node.loop_stopped}` from a downstream node to branch on *why* it stopped.
- **`${__iteration__}`** (1-based) is available in the loop body, mirroring batch's `${__index__}`. It is cleared on loop exit, so post-loop nodes can't read it.
- **Re-entry is one node end-to-end** — it behaves exactly like a backward-edge revisit (in-process completion is cleared and the memo cache is bypassed each iteration, so the body re-executes against fresh state), but you author and see a single node.
- **For `shell` and `llm` nodes, carried inputs must be referenced by the executable text.** `carry:` updates the node's `inputs:` map. Code and workflow nodes consume those inputs directly; shell/llm nodes only observe them when `command`, `prompt`, or `system` contains `${key}`. Validation warns when a carried shell/llm key is not referenced.
- **`--only <loop-node>` runs a single iteration with round-1 seed inputs, not the whole loop** — `--only` is for inspecting one node's output, so carried state does not advance. To watch a loop run to completion, run the workflow normally.

Stateful loop example:

````markdown
### run-rounds

Run tournament rounds until only one contender remains.

- type: workflow
- workflow: ./judge-round.pflow.md
- inputs:
    contenders: ${initial_lineup}       # round-1 seed
- loop:
    carry:
      contenders: ${run-rounds.survivors}
    while: ${run-rounds.more}
    max_iterations: 100
````

Polling example:

````markdown
### wait

Poll until the child says the job is done.

- type: workflow
- workflow: ./check-status.pflow.md
- inputs:
    job_id: ${job_id}
- loop:
    until: ${wait.done}
    max_iterations: 60
````

#### Under the hood: the backward-edge worker/checker

`loop:` is sugar over pflow's lower-level mechanism: **backward edges** — a node routes back to an earlier node, which re-executes. Reach for this directly only when you need full control over routing across multiple sibling nodes (for example, mid-loop branches that cannot live inside a sub-workflow). Use a **worker/checker** pair: the worker does the work, the checker decides (via dynamic `next`) whether to loop again or exit.

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

**The worker can be any node type.** Make the worker a `workflow` node and the loop body becomes an entire sub-workflow that repeats until the condition is met — the checker just branches on one of the child's declared `## Outputs` (e.g. `${worker.remaining}`). That same shape is exactly what `loop:` expresses in one node: a `loop:` on a `workflow`-type node gives a heavyweight per-iteration body — a whole sub-workflow — that still exits the moment the work is done, which the fixed-count batch pattern cannot. Prefer `loop:` unless you need a multi-node loop body or mid-loop branching.

**Choosing the loop style:** the deciding question is whether the number of iterations is known up front — not how heavy each iteration is. Use `batch:` (`parallel: false`) for a fixed iteration count; it always runs all N. Use `loop:` when iterations continue until a condition is met, since only it can stop early. Drop to the manual backward-edge form only when the loop body spans multiple nodes or needs mid-loop branching the single-node `loop:` can't express. See `pflow guide sub-workflows` → Bounded iteration.
