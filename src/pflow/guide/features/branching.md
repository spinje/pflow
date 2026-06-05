# Conditional Branching

**Use when**: Choose between paths based on data — "if X then Y", classify and route, pick a path based on a value. Default flow is top-to-bottom; branching overrides it. (For failures and retry, see `pflow guide error-handling`. For repeat-until, see `pflow guide loop`.)

**Error routing** — any node can route failures to a handler (resilience patterns: `pflow guide error-handling`):
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
- `- next:` (or dynamic `next`) to an **earlier** node forms a **backward edge** — that node re-runs, creating a loop. This is the low-level loop mechanism; for condition-terminated iteration with carried state, prefer `loop:` (see `pflow guide loop`)

**Required: Branch targets MUST have explicit `- next:`**
- Every node reached via `- on-error:` or named routing action MUST declare `- next: end` or `- next: <node-id>`
- Without this, branches fall through to the next node in document order (silent bug)
- If code uses dynamic routing (`next = variable`), the code node MUST declare `- next: target-a, target-b` listing all possible targets
- Literal routing (`next: str = "target"`) does NOT need `- next:` on the code node — pflow detects targets automatically

**When to use**: Error handling, classification/routing, skip-ahead, and **backward-edge loops** (route to an earlier node — the low-level loop form; prefer `loop:` for condition-terminated iteration, see `pflow guide loop`). NOT for parallel execution — use batch for that.

**Branch convergence** — use `??` to reference "whichever branch ran": `${branch-high.stdout ?? branch-low.stdout}`. Tries left-to-right, first operand that resolves wins. Works in any node type — no merge node needed. Operands can also be JSON literals as a final default: `${optional_step.value ?? 0}`, `${a ?? "none"}`.

`??` falls through whenever the left side **isn't there** — whether the **node didn't run** (branch not taken, or node failed) OR the **field is absent** on a node that did run. So `${ran_node.optional_field ?? "default"}` yields `"default"` when `optional_field` isn't present. A **bare** `${node.field}` with no `??` fallback still errors on a missing field, so genuine typos are caught loudly — add a fallback only where absence is expected.
