# Loops

**Use when**: Repeat work until a condition is met — "loop until X", "repeat while Y", "keep refining until good enough", "poll until ready", "run rounds until one remains".

Pick how to repeat by **how the iteration count is decided**:

| You want | Use | Stops early? |
|---|---|---|
| A fixed number of iterations known up front | `batch:` (`parallel: false`) — see `pflow guide batch` | No — always runs all N |
| Repeat until a condition is met, optionally carrying state | **`loop:`** (below) | Yes |
| A multi-node loop body with mid-loop branches | backward edge (under the hood, below) | Yes |

## `loop:` — condition-terminated iteration

Add a `loop:` block to any node (sibling to `batch:`, mutually exclusive with it). The body runs, then a condition is checked; while it holds, the node re-runs. It is a **do-while**: the body always runs at least once.

Inside the `loop:` block, `${this-node-id.field}` refers to the loop node's **own latest output** — for a `workflow` body, that is the child's declared `## Outputs`.

### Simplest form — no carried state (e.g. polling)

```markdown
### wait
- type: workflow
- workflow: ./check-status.pflow.md   # output: pending (bool)
- inputs:
    job_id: ${job_id}
- loop:
    while: ${wait.pending}            # keep polling while still pending
    max_iterations: 20
```

**`while:` vs `until:`** — declare exactly one; the keyword carries the meaning so you never have to mentally invert it:

- `while: ${node.flag}` — keep going **while** the flag is truthy.
- `until: ${node.flag}` — keep going **until** the flag becomes truthy (stop when it turns true).

Write the one that matches the output you have. If the body reports `pending`, use `while: ${wait.pending}`. If it reports `done`, use `until: ${wait.done}`. Both express "poll until the job finishes" — pick the keyword that fits the field's polarity. The condition is a single `${...}` reference to a typed output — no operators or expressions (`${x > 0}` is not allowed); compute the boolean inside the body and reference it.

**The loop reads the body's output to decide whether to continue.** Design the body to finish each round and report its status as a typed output (`more`, `failing`, `satisfied`, …) — handle expected failures inside the body and emit the outcome as a field the condition reads, so a failing round becomes data the loop can act on.

### Carrying state across iterations

To feed one iteration's output into the next, add `carry:` — a map of `body-input: ${this-node-id.output}`. The node's own `inputs:` seeds the first iteration; `carry:` overrides the carried inputs from the second iteration on.

```markdown
### run-rounds
- type: workflow
- workflow: ./judge-round.pflow.md     # input: contenders ; outputs: survivors, more
- inputs:
    contenders: ${candidates}            # round-1 value
- loop:
    carry:
      contenders: ${run-rounds.survivors}   # next round: contenders <- this round's survivors
    while: ${run-rounds.more}
    max_iterations: 10
```

`carry:` reads exactly like `inputs:` — the key is the body input (where the value goes), the value is where it comes from (`${this-node-id.output}`). An input listed in `carry:` evolves each round; an input that appears only in `inputs:` (a constant) is passed unchanged every round.

When the body is a `shell` or `llm` node, reference the carried key as `${key}` in its `command`/`prompt` text — that's how the carried value reaches the body. (`workflow` and `code` bodies receive it automatically as a declared input.)

After the loop, the node's output is the final iteration's output: downstream, `${run-rounds.survivors}` is the last round's survivors.

### A complete example you can run

The bodies above are sub-workflows, but the loop body can be a single `code` node — a self-contained loop with nothing external to set up. This one adds to a running total each round, carries it forward, and stops when it reaches the target (a `code` node exposes its values under `result`, so the carry and condition read `${count-up.result.…}`):

````markdown
# Count Up

Add one to a running total each round until it reaches the target.

## Steps

### count-up

Add one to the running total, then decide whether to stop.

- type: code
- inputs:
    total: 0
- loop:
    carry:
      total: ${count-up.result.total}
    until: ${count-up.result.done}
    max_iterations: 10

```python code
total: int
result: dict = {"total": total + 1, "done": total + 1 >= 3}
```
````

### Rules

- **`max_iterations:`** is an integer or a `${template}` resolving to one. Optional — defaults to a built-in cap. Reaching the cap is not an error: the run stays successful, and the node's output carries `loop_stopped` — `"condition"` when the condition ended the loop, `"max_iterations"` when the cap did. Read `${this-node-id.loop_stopped}` downstream to tell which way it ended.
- **`${__iteration__}`** (1-based) is available inside the loop body. It is cleared on loop exit, so post-loop nodes can't read it.
- **`--only <loop-node>`** runs a single iteration (for inspecting one pass), not the whole loop. Run the workflow normally to watch it run to completion.

## Worked examples

**Refine until good enough** — carry the draft plus the verdict:

```markdown
### refine
- type: workflow
- workflow: ./improve-and-critique.pflow.md   # in: draft ; out: draft, satisfied
- inputs:
    draft: ${first-draft.response}
- loop:
    carry:
      draft: ${refine.draft}
    until: ${refine.satisfied}
    max_iterations: 5
```

**Run elimination rounds until one remains (tournament)** — the body pairs and judges, keeps winners:

```markdown
### run-rounds
- type: workflow
- workflow: ./judge-round.pflow.md     # in: contenders ; out: survivors, more
- inputs:
    contenders: ${candidates}
- loop:
    carry:
      contenders: ${run-rounds.survivors}
    while: ${run-rounds.more}
    max_iterations: 10
```

**Validate, fix, re-validate until green** — the state being changed lives on disk, so there's nothing to carry; the round count is free via the cap:

```markdown
### validate-and-fix
- type: workflow
- workflow: ./validate-fix-once.pflow.md   # out: failing (bool)
- inputs:
    repo: ${repo}
    check: ${check_command}
- loop:
    while: ${validate-and-fix.failing}
    max_iterations: 5
```

## Under the hood: backward edges (multi-node loop bodies)

`loop:` covers a single node — which can be a whole sub-workflow, so most loops fit it. When the loop body genuinely spans **multiple top-level nodes with mid-loop branching**, route a later node back to an earlier one with `- next: <earlier-node>` (a backward edge); a checker node decides via dynamic `next` whether to loop again or move on (see `pflow guide branching` for `next` routing). Prefer `loop:` unless you need that mid-loop branching.

**Visit guard:** each node may be visited at most 100 times per run (loop-runaway protection). Override with `PFLOW_MAX_NODE_VISITS`.

## Choosing the style

The deciding question is whether the iteration count is known up front. Fixed count → `batch:` (`parallel: false`), which always runs all N. Stop-when-done → `loop:`, the only one that exits early. Drop to a backward edge only for a multi-node body with mid-loop branching.
