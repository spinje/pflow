"""Control-flow regression guard for the plan-to-code harness example.

The shipped harness at ``examples/agent-orchestration/plan-to-code/`` is a tree of
``.pflow.md`` workflows whose *agents* (``claude-code``) cost real money and are
non-deterministic, so they can't run in CI. But the harness's value is its
**control flow** — the loops, early-exit, and gating that orchestrate those agents
— and that control flow is pure ``code``/routing that CAN run deterministically.

This test reproduces that topology with ``code`` stand-ins for every agent (each
returns the same shape the real node would) and asserts the orchestration behaves:

  branch-setup → plan-review-fix → breakdown
    → [segment loop]  implement each segment → per-segment validate gate (auto-fix),
                      sequentially, early-exit on no-commits OR a gate that can't go green
    → [review loop]   whole-codebase review-fix, ≤ max_review_rounds, stop on diminishing returns
        (skipped entirely when max_review_rounds == 0 — the cost dial)
    → simplify (1-lens, fix-capable) → verify → final validate gate (auto-fix) → push → ship

It guards the "validates ≠ runnable" failure class: a topology that compiles but
mis-routes (e.g. cost dial that still runs one round, early-exit that ships anyway,
review loop that ignores the cap, a red validate gate that ships anyway). It is NOT
a test of the agent prompts.

Maintenance contract: this mirrors the control flow of
``execute-plan/execute-plan.pflow.md`` + ``implement-chunk/implement-chunk.pflow.md``
+ ``validate-fix/validate-fix.pflow.md``. If you change the harness routing (loop
wiring, gate conditions, stage order), update the stand-in workflow below to match.
A ``sim`` marker on each segment drives the deterministic outcomes the real agents
would produce. (The validate-fix sub-workflow's INTERNAL fix loop is its own concern;
here the gate is a single stand-in returning ``ok`` so this test targets execute-plan's
routing, not the fix loop's plumbing.)
"""

from pathlib import Path

from pflow.core.markdown_parser import parse_markdown
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner

# A single-file stand-in that reproduces the harness's control flow. The real harness
# splits this across execute-plan + implement-chunk + validate-fix sub-workflows; nesting
# is proven separately (spike S1). Here we keep it one file so the test targets ROUTING,
# not sub-workflow plumbing. Each agent stage is a `code` node appending to a log file and
# returning the real node's output shape, driven by the `scenario` fixture.
HARNESS_SKELETON = """\
# Plan-to-Code Harness (control-flow skeleton)

Deterministic stand-in for the plan-to-code harness topology. Every agent is a `code`
node; a `scenario` input selects the segment set + per-segment outcome so each routing
branch can be exercised.

## Inputs

### scenario

Which control-flow case to exercise: `happy` (2 segments ok, review converges),
`fail-mid` (segment 1 has no commits -> early-exit), `seg-gate-fail` (segment 0's
validate gate can't go green -> early-exit), `final-gate-fail` (final validate gate
can't go green -> no ship), `cap` (review never converges -> hits the round cap),
`skip-review` (max_review_rounds 0 -> review loop skipped).

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
- next: seg-gate
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

### seg-gate

Stand-in per-segment validate gate (the real one is the validate-fix sub-workflow). It
runs after every segment; `ok` is false only in the `seg-gate-fail` scenario (segment 0
can't be made green within the fix cap).

- type: code
- next: check-groups
- inputs:
    index: ${group-tick.result.index}
    scenario: ${scenario}
    log: ${log}

```python code
index: int
scenario: str
log: str
ok = not (scenario == "seg-gate-fail" and index == 0)
with open(log, "a") as f:
    f.write(f"seg-gate:seg{index}:ok{ok}\\n")
result: dict = {"ok": ok}
```

### check-groups

Loop to next segment, advance to review (or skip to simplify when cap==0), or abort on
no-commits OR a gate that couldn't go green.

- type: code
- next: group-tick, review-round, simplify, end
- inputs:
    commits: ${implement-chunk.result}
    gate_ok: ${seg-gate.result.ok}
    is_last: ${group-tick.result.is_last}
    index: ${group-tick.result.index}
    cap: ${max_review_rounds}

```python code
commits: int
gate_ok: bool
is_last: bool
index: int
cap: int
if commits == 0:
    result: dict = {"next_index": index, "status": f"ABORTED no-commits at segment {index}"}
    next: str = "end"
elif not gate_ok:
    result: dict = {"next_index": index, "status": f"ABORTED gate at segment {index}"}
    next: str = "end"
elif is_last:
    result: dict = {"next_index": index, "status": "implemented"}
    next: str = "simplify" if cap == 0 else "review-round"
else:
    result: dict = {"next_index": index + 1, "status": "continuing"}
    next: str = "group-tick"
```

### review-round

Stand-in whole-codebase review-fix round, as a single `loop:` node — mirrors the real harness,
which collapsed review-tick/review-round/check-rounds into one looped agent. The `cap` scenario
never converges (loops to max_review_rounds); others converge after round 1. `${__iteration__}`
is the 1-based round number; the backward edge lives in the loop block, not the graph.

- type: code
- next: simplify
- loop:
    while: ${review-round.result.continue}
    max_iterations: ${max_review_rounds}
- inputs:
    round: ${__iteration__}
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
- next: final-gate
- inputs:
    log: ${log}

```python code
log: str
with open(log, "a") as f:
    f.write("verify\\n")
result: str = "ok"
```

### final-gate

Stand-in final validate gate (the real one is the validate-fix sub-workflow), over the
whole result after verify. `ok` is false only in the `final-gate-fail` scenario.

- type: code
- next: check-final
- inputs:
    scenario: ${scenario}
    log: ${log}

```python code
scenario: str
log: str
ok = scenario != "final-gate-fail"
with open(log, "a") as f:
    f.write(f"final-gate:ok{ok}\\n")
result: dict = {"ok": ok}
```

### check-final

Ship only if the final gate is green; otherwise abort without shipping.

- type: code
- next: push
- inputs:
    ok: ${final-gate.result.ok}
    log: ${log}

```python code
ok: bool
log: str
if ok:
    result: dict = {"status": "shipping"}
    next: str = "push"
else:
    result: dict = {"status": "ABORTED final-gate"}
    next: str = "end"
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

- source: ${check-final.result.status ?? check-groups.result.status}
- stdout: true
"""


def _run(tmp_path: Path, scenario: str, max_review_rounds: int = 3) -> list[str]:
    """Run the skeleton and return the ground-truth control-flow log as a list of lines."""
    wf = tmp_path / "harness_skeleton.pflow.md"
    wf.write_text(HARNESS_SKELETON, encoding="utf-8")
    log = tmp_path / "flow.log"
    result = WorkflowRunner().run(
        str(wf),
        {"scenario": scenario, "max_review_rounds": max_review_rounds, "log": str(log)},
        RunnerConfig(),
    )
    # The run must SUCCEED for the log to be a trustworthy control-flow trace — including the
    # abort scenarios, whose `next: end` is a *clean* termination, not a crash. Without this, a
    # routing regression that raises after writing the early log lines would still satisfy the
    # negative assertions (e.g. "ship" not in flow) simply because execution crashed early.
    assert result.success, f"skeleton run failed ({scenario}): {[d.message for d in result.errors]}"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def test_happy_path_runs_full_pipeline(tmp_path: Path) -> None:
    """2 segments: implement + per-segment gate each, review converges, verify, final gate, ship."""
    flow = _run(tmp_path, "happy")
    assert flow == [
        "branch-setup",
        "plan-review-fix",
        "breakdown:2segments",
        "implement:seg0:commits2",
        "seg-gate:seg0:okTrue",
        "implement:seg1:commits2",
        "seg-gate:seg1:okTrue",
        "review:round1",
        "simplify",
        "verify",
        "final-gate:okTrue",
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


def test_per_segment_gate_runs_after_each_segment_before_review(tmp_path: Path) -> None:
    """The validate gate runs once per segment, and every gate precedes the review loop."""
    flow = _run(tmp_path, "happy")
    gates = [i for i, x in enumerate(flow) if x.startswith("seg-gate:")]
    first_review = next(i for i, x in enumerate(flow) if x.startswith("review:"))
    assert len(gates) == 2  # one per segment
    assert all(i < first_review for i in gates), flow
    # each gate immediately follows its segment's implement
    assert flow.index("seg-gate:seg0:okTrue") == flow.index("implement:seg0:commits2") + 1


def test_hard_failure_early_exits_and_does_not_ship(tmp_path: Path) -> None:
    """Segment 1 produces no commits -> abort; later segment + review + ship never run."""
    flow = _run(tmp_path, "fail-mid")
    assert "implement:seg0:commits2" in flow
    assert "implement:seg1:commits0" in flow
    assert "implement:seg2:commits2" not in flow  # dependent segment skipped
    assert not any(x.startswith("review:") for x in flow)
    assert "simplify" not in flow
    assert "verify" not in flow
    assert "final-gate:okTrue" not in flow
    assert "push" not in flow
    assert "ship" not in flow


def test_segment_gate_failure_aborts_without_review_or_ship(tmp_path: Path) -> None:
    """A segment whose validate gate can't go green aborts the run before review/ship."""
    flow = _run(tmp_path, "seg-gate-fail")
    assert "implement:seg0:commits2" in flow
    assert "seg-gate:seg0:okFalse" in flow  # gate red, fix cap exhausted
    assert "implement:seg1:commits2" not in flow  # next segment never runs
    assert not any(x.startswith("review:") for x in flow)
    assert "simplify" not in flow
    assert "verify" not in flow
    assert "push" not in flow
    assert "ship" not in flow


def test_final_gate_failure_does_not_ship(tmp_path: Path) -> None:
    """If the final validate gate can't go green, the run must NOT push or ship."""
    flow = _run(tmp_path, "final-gate-fail")
    # everything up to and including the final gate runs...
    assert "verify" in flow
    assert "final-gate:okFalse" in flow
    # ...but the deterministic gate blocks shipping a red tree.
    assert "push" not in flow
    assert "ship" not in flow


def test_review_loop_honors_the_cap(tmp_path: Path) -> None:
    """Review that never converges runs exactly max_review_rounds rounds, then simplify/verify."""
    flow = _run(tmp_path, "cap", max_review_rounds=3)
    review_rounds = [x for x in flow if x.startswith("review:round")]
    assert review_rounds == ["review:round1", "review:round2", "review:round3"]
    assert "simplify" in flow  # simplicity pass runs after the review loop
    assert "verify" in flow  # proceeds after the cap
    assert "final-gate:okTrue" in flow
    assert "push" in flow
    assert "ship" in flow


def test_cost_dial_skips_review_entirely(tmp_path: Path) -> None:
    """max_review_rounds == 0 must run ZERO review rounds (the cost dial)."""
    flow = _run(tmp_path, "skip-review", max_review_rounds=0)
    assert not any(x.startswith("review:") for x in flow), flow
    assert "simplify" in flow  # the cost dial skips the review LOOP, not the simplicity pass
    assert "verify" in flow
    assert "final-gate:okTrue" in flow
    assert "push" in flow
    assert "ship" in flow


# --- Structural guard on the REAL shipped .pflow.md files (not the skeleton copy above) ---
#
# The skeleton above is a hand-maintained mirror of the routing, so a change made to the real files
# but NOT mirrored here would pass silently (the "synthetic fixture matching code" risk —
# tests/CLAUDE.md #19). These tests parse the actual shipped workflows and pin their load-bearing
# routing + output contract, so such drift fails loudly without spending a cent on agents.

_HARNESS_DIR = Path(__file__).resolve().parents[2] / "examples/agent-orchestration/plan-to-code"


def _successors(pflow_path: Path) -> dict[str, set[str]]:
    """Map each node id to the set of its successor node ids in the real .pflow.md."""
    ir = parse_markdown(pflow_path.read_text(encoding="utf-8")).ir
    succ: dict[str, set[str]] = {}
    for edge in ir["edges"]:
        succ.setdefault(edge["from"], set()).add(edge["to"])
    return succ


def test_real_execute_plan_routing_matches_skeleton() -> None:
    """The shipped execute-plan.pflow.md keeps the gate/loop routing the skeleton asserts.

    The ``end`` abort sentinel is not a node, so it is never a declared edge target — assert the
    concrete successors only (aborts route via the check-* code bodies' ``next = "end"``).
    """
    ir = parse_markdown((_HARNESS_DIR / "execute-plan/execute-plan.pflow.md").read_text(encoding="utf-8")).ir
    succ: dict[str, set[str]] = {}
    for edge in ir["edges"]:
        succ.setdefault(edge["from"], set()).add(edge["to"])
    # Per-segment validate gate sits between the implement worker and the loop checker.
    assert succ["implement-chunk"] == {"seg-gate"}
    assert succ["seg-gate"] == {"check-groups"}
    # Segment-loop gate: loop back, advance to the review loop, or skip-to-simplify (cost dial).
    assert succ["check-groups"] == {"group-tick", "review-round", "simplify"}
    # The review loop is now a single `loop:` node (review-tick/check-rounds collapsed away). Its
    # backward edge lives in the loop block, not the graph, so its only forward successor is simplify.
    assert succ["review-round"] == {"simplify"}
    review_round = next(n for n in ir["nodes"] if n["id"] == "review-round")
    assert review_round.get("loop") == {
        "while": "${review-round.result.continue}",
        "max_iterations": "${max_review_rounds}",
    }, review_round.get("loop")
    # End-stage chain: verify (last code-touching stage) → final validate gate → ship-or-abort.
    assert succ["simplify"] == {"verify"}
    assert succ["verify"] == {"final-gate"}
    assert succ["final-gate"] == {"check-final"}
    assert succ["check-final"] == {"push"}  # green → push; red aborts via `next = "end"`
    assert succ["push"] == {"ship"}


def test_real_validate_fix_is_a_ground_truth_loop() -> None:
    """The reusable validate-fix gate loops fix-tests → run-validate on the command's exit code."""
    succ = _successors(_HARNESS_DIR / "execute-plan/validate-fix/validate-fix.pflow.md")
    assert succ["run-validate"] == {"check-validate"}
    assert succ["check-validate"] == {"fix-tests"}  # red → fix; green/cap route via `next = "end"`
    assert succ["fix-tests"] == {"run-validate"}  # backward edge: re-check after every fix
    ir = parse_markdown(
        (_HARNESS_DIR / "execute-plan/validate-fix/validate-fix.pflow.md").read_text(encoding="utf-8")
    ).ir
    assert "ok" in ir["outputs"], list(ir["outputs"])  # callers branch on the gate's verdict


def test_real_implement_chunk_exposes_commits_made() -> None:
    """The parent loop's hard-failure early-exit depends on implement-chunk's commits_made output."""
    ir = parse_markdown(
        (_HARNESS_DIR / "execute-plan/implement-chunk/implement-chunk.pflow.md").read_text(encoding="utf-8")
    ).ir
    assert "commits_made" in ir["outputs"], list(ir["outputs"])
