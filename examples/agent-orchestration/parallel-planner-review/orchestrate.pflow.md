# Parallel Planner with Review

Autonomous loop that triages open GitHub issues, implements and reviews the
unblocked ones in parallel, opens a PR for each that passes review, then repeats
— picking up newly-unblocked work each cycle — until nothing is left or a cycle
cap is hit. This file is the entry point; every node's description explains its
own role and why it is that node type.

**The loop.** A backward-edge counter/checker pair: `tick` holds the cycle
counter, `run-cycle` does the work (a whole sub-workflow per iteration), and
`check-progress` decides loop-or-stop. The counter ping-pongs between the two
`code` nodes because a node cannot read its own previous output — that store rule
is why the loop needs a separate counter node. It converges because `run-cycle`'s
`open-prs` step strips the `agent-ready` label from handled issues, shrinking the
pool each cycle until empty (or `max_cycles` caps it).

**Before running.** `gh` authenticated with push + PR rights on `origin`; the
labels `agent-ready` and `agent-needs-human` must exist. Opt issues in by
labelling them `agent-ready` — if none are, the loop correctly no-ops on cycle
one. Launch from anywhere inside the repo (`find-repo` resolves the root via
`git rev-parse`).

**How it composes.** Three nested workflows: this orchestrator →
`run-cycle/run-cycle.pflow.md` (one plan→implement→review→open-PRs cycle) →
`run-cycle/implement-and-review-one/` (the per-issue body, fanned out in parallel).

**Two caveats.** (1) Work opens a *PR*, not a merge — a dependency isn't resolved
until a human merges its PR, so cross-cycle unblocking is weaker than
merge-to-main (best for independent issues). (2) Each issue is attempted once; a
review requesting changes relabels it `agent-needs-human` rather than
re-attempting, so the swarm never spins on a hard problem.

## Inputs

### base_branch

Branch the PRs target, and that new work branches are based on.

- type: string
- required: false
- default: main

### max_issues

Cap on issues planned per cycle.

- type: integer
- required: false
- default: 5

### max_cycles

Hard cap on cycles, so the loop always terminates even if work keeps
unblocking.

- type: integer
- required: false
- default: 10

## Steps

### tick

Hold the cycle counter. Reads the next cycle number from the checker; on the
first visit the checker hasn't run yet, so `??` falls through to the literal
`1`. `tick` is the routing target of `check-progress`'s loop-back edge, so it
declares an explicit `- next:`.

- type: code
- next: run-cycle
- inputs:
    prior: ${check-progress.result.next_cycle ?? 1}

```python code
prior: int
result: int = prior
```

### run-cycle

Run one full plan→implement→review→open-PRs cycle against the live repo. The
worker of the loop — a whole sub-workflow per iteration.

- type: workflow
- workflow: ./run-cycle/run-cycle.pflow.md
- next: check-progress
- inputs:
    base_branch: ${base_branch}
    max_issues: ${max_issues}

### check-progress

Decide whether to run another cycle. Stops when the cycle found no unblocked
issues (work is drained) or the cycle cap is reached; otherwise loops back to
`tick` with an incremented counter. The checker of the loop.

- type: code
- next: tick, end
- inputs:
    planned: ${run-cycle.issues_planned}
    current: ${tick.result}
    cap: ${max_cycles}

```python code
planned: list
current: int
cap: int

remaining = len(planned)
if remaining == 0:
    result: dict = {"next_cycle": current, "status": f"Done: no unblocked work left after {current} cycle(s)."}
    next: str = "end"
elif current >= cap:
    result: dict = {"next_cycle": current, "status": f"Stopped at cycle cap ({cap}); work may remain."}
    next: str = "end"
else:
    result: dict = {"next_cycle": current + 1, "status": f"Cycle {current} done; continuing."}
    next: str = "tick"
```

## Outputs

### summary

Final status: why the loop stopped.

- source: ${check-progress.result.status}
- stdout: true
