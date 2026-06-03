"""Control-flow regression guard for the plan-to-code harness example.

The shipped harness at ``examples/agent-orchestration/plan-to-code/`` is a tree of
``.pflow.md`` workflows whose *agents* (``claude-code``) cost real money and are
non-deterministic, so they can't run in CI. But the harness's value is its
**control flow** — the loops, early-exit, and gating that orchestrate those agents
— and that control flow is pure ``code``/routing that CAN run deterministically.

This test reproduces that topology with ``code`` stand-ins for every agent (each
returns the same shape the real node would) and asserts the orchestration behaves:

  branch-setup → plan-review-fix → breakdown
    → [segment loop]  implement each segment, sequentially, early-exit on no-commits
    → [review loop]   whole-codebase review-fix, ≤ max_review_rounds, stop on diminishing returns
        (skipped entirely when max_review_rounds == 0 — the cost dial)
    → simplify (1-lens, fix-capable) → verify → push → ship

It guards the "validates ≠ runnable" failure class: a topology that compiles but
mis-routes (e.g. cost dial that still runs one round, early-exit that ships anyway,
review loop that ignores the cap). It is NOT a test of the agent prompts.

Maintenance contract: this mirrors the control flow of
``execute-plan/execute-plan.pflow.md`` + ``implement-chunk/implement-chunk.pflow.md``.
If you change the harness routing (loop wiring, gate conditions, stage order), update
the stand-in workflow below to match. A ``sim`` marker on each segment drives the
deterministic outcomes the real agents would produce.
"""

from pathlib import Path

from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner

# A single-file stand-in that reproduces the harness's control flow. The real harness
# splits this across execute-plan + implement-chunk sub-workflows; nesting is proven
# separately (spike S1). Here we keep it one file so the test targets ROUTING, not
# sub-workflow plumbing. Each agent stage is a `code` node appending to a log file and
# returning the real node's output shape, driven by the `scenario` fixture.
HARNESS_SKELETON = """\
# Plan-to-Code Harness (control-flow skeleton)

Deterministic stand-in for the plan-to-code harness topology. Every agent is a `code`
node; a `scenario` input selects the segment set + per-segment outcome so each routing
branch can be exercised.

## Inputs

### scenario

Which control-flow case to exercise: `happy` (2 segments ok, review converges),
`fail-mid` (segment 1 has no commits -> early-exit), `cap` (review never converges ->
hits the round cap), `skip-review` (max_review_rounds 0 -> review loop skipped).

- type: string
- required: false
- default: happy

### max_review_rounds

Hard cap on whole-codebase review rounds (0 = skip review).

- type: integer
- required: false
- default: 3

### log

Path to the ground-truth control-flow log this run appends to.

- type: string
- required: true

## Steps

### branch-setup

Stand-in for the git branch-setup shell node.

- type: code
- next: plan-review-fix
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("branch-setup\\n")
result: str = "ok"
```

### plan-review-fix

Stand-in for the plan-hardening agent (read-only here).

- type: code
- next: breakdown
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("plan-review-fix\\n")
result: str = "ok"
```

### breakdown

Stand-in for the breakdown agent: emit the segment set from the scenario.

- type: code
- next: group-tick
- inputs:
    scenario: ${scenario}
    log: ${log}

```python code
scenario: str
log: str
if scenario == "fail-mid":
    segments = [{"phases": ["P0"], "sim": "ok"}, {"phases": ["P1"], "sim": "fail"}, {"phases": ["P2"], "sim": "ok"}]
elif scenario == "cap":
    segments = [{"phases": ["P0"], "sim": "ok"}]
else:
    segments = [{"phases": ["P0", "P1"], "sim": "ok"}, {"phases": ["P2"], "sim": "ok"}]
with open(log, "a") as f:
    f.write(f"breakdown:{len(segments)}segments\\n")
result: dict = {"segments": segments}
```

### group-tick

Pick the current segment + compute the delta. Routing target of check-groups' loop-back.

- type: code
- next: implement-chunk
- inputs:
    segments: ${breakdown.result.segments}
    prior: ${check-groups.result.next_index ?? 0}

```python code
segments: list
prior: int
index = prior
seg = segments[index]
is_last = index + 1 >= len(segments)
result: dict = {"index": index, "sim": seg["sim"], "is_last": is_last}
```

### implement-chunk

Stand-in implement fork: append a marker; `commits_made == 0` when sim is "fail".

- type: code
- next: check-groups
- inputs:
    index: ${group-tick.result.index}
    sim: ${group-tick.result.sim}
    log: ${log}

```python code
index: int
sim: str
log: str
commits = 0 if sim == "fail" else 2
with open(log, "a") as f:
    f.write(f"implement:seg{index}:commits{commits}\\n")
result: int = commits
```

### check-groups

Loop to next segment, advance to review (or skip to verify when cap==0), or abort on
no-commits.

- type: code
- next: group-tick, review-tick, simplify, end
- inputs:
    commits: ${implement-chunk.result}
    is_last: ${group-tick.result.is_last}
    index: ${group-tick.result.index}
    cap: ${max_review_rounds}

```python code
commits: int
is_last: bool
index: int
cap: int
if commits == 0:
    result: dict = {"next_index": index, "status": f"ABORTED at segment {index}"}
    next: str = "end"
elif is_last:
    result: dict = {"next_index": index, "status": "implemented"}
    next: str = "simplify" if cap == 0 else "review-tick"
else:
    result: dict = {"next_index": index + 1, "status": "continuing"}
    next: str = "group-tick"
```

### review-tick

Review-round counter. Routing target of check-rounds' loop-back.

- type: code
- next: review-round
- inputs:
    prior: ${check-rounds.result.next_round ?? 1}

```python code
prior: int
result: int = prior
```

### review-round

Stand-in whole-codebase review-fix round. `cap` scenario never converges; others
converge after round 1.

- type: code
- next: check-rounds
- inputs:
    round: ${review-tick.result}
    scenario: ${scenario}
    log: ${log}

```python code
round: int
scenario: str
log: str
with open(log, "a") as f:
    f.write(f"review:round{round}\\n")
keep = scenario == "cap"
result: dict = {"round": round, "continue": keep}
```

### check-rounds

Continue review only if the round wants to AND under the cap; else advance to verify.

- type: code
- next: review-tick, simplify
- inputs:
    keep: ${review-round.result.continue}
    round: ${review-round.result.round}
    cap: ${max_review_rounds}

```python code
keep: bool
round: int
cap: int
if keep and round < cap:
    result: dict = {"next_round": round + 1}
    next: str = "review-tick"
else:
    result: dict = {"next_round": round}
    next: str = "simplify"
```

### simplify

Stand-in simplicity pass (fix-capable; runs after review, before verify).

- type: code
- next: verify
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("simplify\\n")
result: str = "ok"
```

### verify

Stand-in adversarial verify (last code-touching stage).

- type: code
- next: push
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("verify\\n")
result: str = "ok"
```

### push

Stand-in deterministic push (shell node in the real harness; immune to claude-code settings).

- type: code
- next: ship
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("push\\n")
result: str = "ok"
```

### ship

Stand-in ship.

- type: code
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("ship\\n")
result: str = "shipped"
```

## Outputs

### summary

Why the run ended.

- source: ${check-groups.result.status}
- stdout: true
"""


def _run(tmp_path: Path, scenario: str, max_review_rounds: int = 3) -> list[str]:
    """Run the skeleton and return the ground-truth control-flow log as a list of lines."""
    wf = tmp_path / "harness_skeleton.pflow.md"
    wf.write_text(HARNESS_SKELETON)
    log = tmp_path / "flow.log"
    WorkflowRunner().run(
        str(wf),
        {"scenario": scenario, "max_review_rounds": max_review_rounds, "log": str(log)},
        RunnerConfig(),
    )
    return log.read_text().splitlines() if log.exists() else []


def test_happy_path_runs_full_pipeline(tmp_path: Path) -> None:
    """2 segments, both implement, review converges in 1 round, then verify/gate/ship."""
    flow = _run(tmp_path, "happy")
    assert flow == [
        "branch-setup",
        "plan-review-fix",
        "breakdown:2segments",
        "implement:seg0:commits2",
        "implement:seg1:commits2",
        "review:round1",
        "simplify",
        "verify",
        "push",
        "ship",
    ]


def test_segments_implement_sequentially_before_any_review(tmp_path: Path) -> None:
    """Review must NOT happen per-segment: both implements precede the first review."""
    flow = _run(tmp_path, "happy")
    first_review = next(i for i, x in enumerate(flow) if x.startswith("review:"))
    implements = [i for i, x in enumerate(flow) if x.startswith("implement:")]
    assert all(i < first_review for i in implements), flow
    assert len(implements) == 2


def test_hard_failure_early_exits_and_does_not_ship(tmp_path: Path) -> None:
    """Segment 1 produces no commits -> abort; later segment + review + ship never run."""
    flow = _run(tmp_path, "fail-mid")
    assert "implement:seg0:commits2" in flow
    assert "implement:seg1:commits0" in flow
    assert "implement:seg2:commits2" not in flow  # dependent segment skipped
    assert not any(x.startswith("review:") for x in flow)
    assert "simplify" not in flow
    assert "verify" not in flow
    assert "push" not in flow
    assert "ship" not in flow


def test_review_loop_honors_the_cap(tmp_path: Path) -> None:
    """Review that never converges runs exactly max_review_rounds rounds, then verify."""
    flow = _run(tmp_path, "cap", max_review_rounds=3)
    review_rounds = [x for x in flow if x.startswith("review:round")]
    assert review_rounds == ["review:round1", "review:round2", "review:round3"]
    assert "simplify" in flow  # simplicity pass runs after the review loop
    assert "verify" in flow  # proceeds after the cap
    assert "push" in flow
    assert "ship" in flow


def test_cost_dial_skips_review_entirely(tmp_path: Path) -> None:
    """max_review_rounds == 0 must run ZERO review rounds (the cost dial)."""
    flow = _run(tmp_path, "skip-review", max_review_rounds=0)
    assert not any(x.startswith("review:") for x in flow), flow
    assert "simplify" in flow  # the cost dial skips the review LOOP, not the simplicity pass
    assert "verify" in flow
    assert "push" in flow
    assert "ship" in flow
