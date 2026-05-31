# Parallel Planner with Review

Autonomous loop that triages open GitHub issues, implements and reviews the
unblocked ones in parallel, opens a PR for each that passes review, then repeats
— picking up newly-unblocked work each cycle — until nothing is left or a cycle
cap is hit. This file is the entry point; every node's description explains its
own role and why it is that node type.

**The loop.** A single `loop:`-configured node: `run-cycle` does the work (a whole
sub-workflow per iteration) and the engine re-runs it until its own
`issues_planned` output drains to empty (`while: ${run-cycle.issues_planned}`) or
the `max_cycles` cap is hit. It converges because `run-cycle`'s `open-prs` step
strips the `agent-ready` label from handled issues, shrinking the pool each cycle
until empty. A tiny `summarize` node turns the engine's `loop_stopped` marker into
the human-readable final status.

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

### run-cycle

Run one full plan→implement→review→open-PRs cycle against the live repo — a whole
sub-workflow per iteration. The `loop:` block re-runs this node while its own
`issues_planned` output is a non-empty list (work remains) and stops when it
drains to empty, capped at `max_cycles`. `${__iteration__}` (1-based) is available
in the body if a step needs the cycle number.

- type: workflow
- workflow: ./run-cycle/run-cycle.pflow.md
- next: summarize
- inputs:
    base_branch: ${base_branch}
    max_issues: ${max_issues}
- loop:
    while: ${run-cycle.issues_planned}
    max_iterations: ${max_cycles}

### summarize

Turn the engine's `loop_stopped` marker into the human-readable final status.
`loop_stopped` is `"condition"` when the work drained naturally, or
`"max_iterations"` when the cycle cap stopped it (a non-degrading INFO advisory
also fires in that case).

- type: code
- inputs:
    stopped: ${run-cycle.loop_stopped}

```python code
stopped: str
if stopped == "max_iterations":
    result: str = "Stopped at the cycle cap (max_cycles); unblocked work may remain."
else:
    result: str = "Done: no unblocked work left."
```

## Outputs

### summary

Final status: why the loop stopped.

- source: ${summarize.result}
- stdout: true
