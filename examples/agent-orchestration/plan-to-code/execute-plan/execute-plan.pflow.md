# Execute Plan

The reusable, invocation-agnostic core of the harness. Given an implementation plan (and
optional spec), it: hardens the plan (review → fix), breaks it into agent-handoff phase-groups,
implements each group on one shared branch as a fresh-context fork (NO review between groups —
segmentation is purely for context-window management), then runs ONE whole-codebase review-fix
loop, a single simplicity pass that simplifies the integrated whole, an adversarial verify pass
(the LAST code-touching stage, so the simplifications it follows are verified), and opens a PR.
It knows nothing about issues, worktrees, or swarms — callers (manual entry, or a future
issue-swarm) supply `repo_dir` and a plan; the core just executes.

Every agent reads its artifacts (`plan`, `spec`, `progress_log`) BY PATH and runs with
`cwd: ${repo_dir}`. Context never accumulates across stages — each fork is a fresh process; the
progress log + git history are the only state carried forward.

The group loop is a backward-edge worker/checker pair: `group-tick` (index) → `implement-chunk`
(sub-workflow worker, implement-only) → `check-groups` (loop / finish / abort). Groups run
STRICTLY SEQUENTIALLY on the shared branch — group N sees group N-1's commits. A group that
produces no commits is a hard failure → early-exit, nothing shipped. Review is whole-codebase and
runs ONCE after the loop, not per group.

## Inputs

### plan

Path to the implementation plan.

- type: string
- required: true

### spec

Optional path to a complementary spec for complex tasks ("" if none).

- type: string
- required: false
- default: ""

### progress_log

Path to the shared progress log — the carried-forward understanding across forks.

- type: string
- required: true

### repo_dir

Absolute repo root (resolved by the caller; threaded to every agent's `cwd:`).

- type: string
- required: true

### base_branch

Branch the PR targets, and that the work branch is based on.

- type: string
- required: false
- default: main

### work_branch

Name of the branch to create and implement on.

- type: string
- required: false
- default: agent/plan-to-code

### plan_lenses

Comma-separated plan-review lens subagent names (verified to exist by the caller's preflight).

- type: string
- required: false
- default: review-plan

### review_lenses

Comma-separated code-review lens subagent names for the whole-codebase review-fix loop + the
final review gate.

- type: string
- required: false
- default: review-silent-failures, review-test-fidelity, review-impact-completeness, review-validation-consistency

### simplify_lens

Single simplicity-review lens subagent for the final simplicity pass (verified to exist by the
caller's preflight). Deployed by the `simplify` stage to judge — and simplify — the FINAL
integrated code (emergent duplication across segments, needless interface complexity, dead
scaffolding) after correctness review and before verify.

- type: string
- required: false
- default: review-simplicity

### verify_recipe

Path to a project-specific recipe for how to run/exercise the system in adversarial verify
("" → the verify agent infers test/run commands from the repo).

- type: string
- required: false
- default: ""

### max_review_rounds

Hard cap on rounds in the whole-codebase review-fix loop (0 = skip review). The review agent's
diminishing-returns judgment normally exits before the cap; default is the cap.

- type: integer
- required: false
- default: 3

### validate_command

The project's full validation command (tests + lint + types), e.g. `make test && make check`. Run
in `repo_dir` as a deterministic gate after each segment and after verify — its exit code, not an
agent's claim, decides whether the code is green. Empty → the gate passes trivially and the harness
CANNOT guarantee the shipped code passes the project's own checks, so supply it for real runs.

- type: string
- required: false
- default: ""

### max_fix_rounds

Hard cap on auto-fix attempts each time the validation gate is red, before the run aborts without
shipping.

- type: integer
- required: false
- default: 5

## Steps

### branch-setup

Create (or reset) the work branch off the base branch, once, before any implementation. Uses
`-B` so a re-run is idempotent. Every implement/review fork then commits on this branch.

- type: shell
- cwd: ${repo_dir}
- next: plan-review-fix
- inputs:
    work_branch: ${work_branch}
    base_branch: ${base_branch}

```shell command
git checkout -B "${work_branch}" "${base_branch}"
```

### plan-review-fix

Harden the plan before any code is written, in ONE agent: deploy plan-review lenses, adjudicate
their findings against the plan and the real codebase, and edit the plan file in place to fix
the real, material ones. The agent that judges a problem is the one that fixes it (same pattern
as the code review-fix stage) — so findings never get serialized across an agent boundary. No
`output_schema`: this stage ACTS (edits the plan in place) and nothing downstream consumes a
structured result (it's a control edge to breakdown). As with any lens-heavy review agent, it
tends to end on prose, so requesting a schema we don't use only risks a noisy soft-fail.
Its work lands in the hardened plan file + the progress log.

- type: agent
- backend: claude
- prompt: ./prompts/plan-review-fix.prompt.md
- cwd: ${repo_dir}
- max_turns: 60
- timeout: 1200
- next: breakdown
- inputs:
    repo_dir: ${repo_dir}
    plan_path: ${plan}
    spec_path: ${spec}
    progress_log_path: ${progress_log}
    available_lenses: ${plan_lenses}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep
    - Task

### breakdown

Group the (now hardened) plan's top-level phases into ordered agent-handoff segments — where
context resets between fresh agents. An `agent` node so the whole harness runs on the
Claude subscription with no API-key/LiteLLM dependency; it reads the hardened plan by path
itself. Structured output soft-fails on this node type, so `group-tick` guards the shape.

- type: agent
- backend: claude
- prompt: ./prompts/breakdown.prompt.md
- cwd: ${repo_dir}
- max_turns: 10
- timeout: 300
- next: group-tick
- inputs:
    plan_path: ${plan}
- allowed_tools:
    - Read

```yaml output_schema
type: object
properties:
  segments:
    type: array
    items:
      type: object
      properties:
        phases:
          type: array
          items: { type: string }
        label: { type: string }
        rationale: { type: string }
      required: [phases, label, rationale]
required: [segments]
```

### group-tick

Hold the segment index. Reads the next index from the checker; on first entry `??` seeds 0.
Computes the current segment and the phase-scoped delta instruction for this fork (which phases
are done, which to implement now). Routing target of `check-groups`'s loop-back edge.

- type: code
- next: implement-chunk
- inputs:
    bd: ${breakdown.result}
    prior: ${check-groups.result.next_index ?? 0}

```python code
bd: object
prior: int
# Guard agent schema soft-fail: on non-compliance `result` is a raw string, not a dict.
if not isinstance(bd, dict) or not bd.get("segments"):
    raise RuntimeError(
        "breakdown did not return a usable segments list (schema soft-fail or empty). "
        f"Got: {bd!r}"
    )
segments = bd["segments"]
index = prior
seg = segments[index]
is_last = index + 1 >= len(segments)
done = [p for g in segments[:index] for p in g["phases"]]
todo = ", ".join(seg["phases"])
done_str = ", ".join(done) if done else "none"
delta = f"Already implemented & committed: {done_str}. Now implement ONLY: {todo}. Then STOP."
result: dict = {"index": index, "delta": delta, "is_last": is_last}
```

### implement-chunk

The loop worker: a whole sub-workflow per segment (implement fork only — no review here). Runs
on the shared branch so it sees prior segments' commits. Segmentation is purely for
context-window management during implementation; review is whole-codebase, once, after the loop.

- type: workflow
- workflow: ./implement-chunk/implement-chunk.pflow.md
- next: seg-gate
- inputs:
    plan: ${plan}
    spec: ${spec}
    delta: ${group-tick.result.delta}
    progress_log: ${progress_log}
    repo_dir: ${repo_dir}

### seg-gate

Per-segment deterministic test/quality gate (with auto-fix). After each segment is implemented, run
the project's `validate_command` over the whole repo; if it's red, a fix fork repairs it (up to
`max_fix_rounds`), looping on the command's real exit code. This catches a regression at its SOURCE
— the moment the segment introduces it — so the fix is localized, later segments don't build on a
broken tree (they share the branch), and review never starts from red. A deterministic gate is NOT
review (it runs the tests, it doesn't read code), so running it per segment doesn't reintroduce the
per-segment-review cost. `ok: false` (couldn't go green within the cap) is a hard failure the next
checker aborts on. When `validate_command` is empty the gate passes trivially.

- type: workflow
- workflow: ./validate-fix/validate-fix.pflow.md
- next: check-groups
- inputs:
    repo_dir: ${repo_dir}
    validate_command: ${validate_command}
    plan: ${plan}
    progress_log: ${progress_log}
    base_branch: ${base_branch}
    max_fix_rounds: ${max_fix_rounds}

### check-groups

Decide: loop back for the next segment, or (once all segments are implemented) advance to the
whole-codebase review — skipping straight to the simplicity pass when review is disabled
(`max_review_rounds == 0`, the cost dial; `simplify` still runs) — or ABORT on a hard failure (a
segment produced no commits) so we don't run remaining dependent segments or ship.

- type: code
- next: group-tick, review-round, simplify, end
- inputs:
    commits: ${implement-chunk.commits_made}
    gate_ok: ${seg-gate.ok}
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
    result: dict = {"next_index": index, "status": f"ABORTED: segment {index} produced no commits; nothing shipped."}
    next: str = "end"
elif not gate_ok:
    result: dict = {"next_index": index, "status": f"ABORTED: segment {index} left the build failing after the fix cap; nothing shipped."}
    next: str = "end"
elif is_last:
    result: dict = {"next_index": index, "status": f"All {index + 1} segment(s) implemented and validated."}
    # max_review_rounds == 0 disables the whole-codebase review LOOP (cost dial); simplify still runs.
    next: str = "simplify" if cap == 0 else "review-round"
else:
    result: dict = {"next_index": index + 1, "status": f"Segment {index} done and validated; continuing."}
    next: str = "group-tick"
```

### review-round

One whole-codebase review-fix round (a fresh agent): deploy the relevant lenses as subagents
over the FULL implemented change, adjudicate findings (real? critical? not false-positive?), fix
the real-critical ones, commit, log, and report `{continue, reason}`. The `loop:` block re-runs
this as a fresh process (new context) while the agent reports `continue: true`, capped at
`max_review_rounds`; `{continue: false}` (diminishing returns) is the normal exit and the cap is
the runaway backstop. `${__iteration__}` (1-based) is the round number, passed to the prompt so it
can weigh prior rounds. The loop condition is a reliable bool because the node self-heals a
soft-failed `continue` — scalar coercion turns a `"false"` string into a bool, and a missing
structured result triggers one resume-retry (`agent` `schema_retries`, default 1).

- type: agent
- backend: claude
- prompt: ./prompts/review-fix.prompt.md
- cwd: ${repo_dir}
- max_turns: 60
- timeout: 1200
- next: simplify
- loop:
    while: ${review-round.result.continue}
    max_iterations: ${max_review_rounds}
- inputs:
    repo_dir: ${repo_dir}
    plan_path: ${plan}
    spec_path: ${spec}
    progress_log_path: ${progress_log}
    available_lenses: ${review_lenses}
    base_branch: ${base_branch}
    round: ${__iteration__}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep
    - Task

```yaml output_schema
type: object
properties:
  continue: { type: boolean }
  reason: { type: string }
required: [continue, reason]
```

### simplify

One focused simplicity pass over the COMPLETE implemented + reviewed change, run the same way as
the other review stages: deploy the simplicity lens, adjudicate its findings, and FIX the real
ones, then commit. It judges what a correctness reviewer doesn't — is the FINAL integrated code as
simple as it should be (emergent duplication across segments, an interface grown more complex than
its use, dead scaffolding, cross-segment inconsistency)? It runs AFTER the whole-codebase
review-fix loop (on settled code) and BEFORE verify, so its simplifying changes are adversarially
verified — verify stays the LAST code-touching stage. No `output_schema`: like plan-review-fix it
ACTS (edits + commits) and nothing downstream consumes a structured result (control edge to
verify); a lens-heavy agent would only risk a noisy soft-fail. Its work lands in git + the
progress log.

- type: agent
- backend: claude
- prompt: ./prompts/simplify.prompt.md
- cwd: ${repo_dir}
- max_turns: 60
- timeout: 1200
- next: verify
- inputs:
    repo_dir: ${repo_dir}
    plan_path: ${plan}
    spec_path: ${spec}
    progress_log_path: ${progress_log}
    available_lenses: ${simplify_lens}
    base_branch: ${base_branch}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep
    - Task

### verify

Adversarial verification of the fully-implemented, reviewed, and simplified result: try to break
it, fix genuine breaks, add regression tests. Runs after the whole-codebase review-fix loop and the
simplicity pass. Verify is the LAST code-TOUCHING stage — nothing changes code after it (it routes
to a deterministic push → ship; neither changes code), preserving "the final code is verified".

- type: agent
- backend: claude
- prompt: ./prompts/verify.prompt.md
- cwd: ${repo_dir}
- max_turns: 60
- timeout: 1800
- next: final-gate
- inputs:
    repo_dir: ${repo_dir}
    plan_path: ${plan}
    spec_path: ${spec}
    progress_log_path: ${progress_log}
    verify_recipe_path: ${verify_recipe}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep

```yaml output_schema
type: object
properties:
  breaks_found: { type: integer }
  summary: { type: string }
required: [breaks_found, summary]
```

### final-gate

Final deterministic test/quality gate (with auto-fix), over the WHOLE result. The review-fix loop,
`simplify`, and `verify` all changed code AFTER the last per-segment gate, so re-run the project's
`validate_command` and fix any regression they introduced before shipping. Same reusable gate as
`seg-gate`; `ok: false` (couldn't go green within the cap) aborts before ship. This is the hard
guarantee the harness was missing — "the shipped code passes the project's own tests/lint/types" is
enforced by the graph, not left to an agent's self-report.

- type: workflow
- workflow: ./validate-fix/validate-fix.pflow.md
- next: check-final
- inputs:
    repo_dir: ${repo_dir}
    validate_command: ${validate_command}
    plan: ${plan}
    progress_log: ${progress_log}
    base_branch: ${base_branch}
    max_fix_rounds: ${max_fix_rounds}

### check-final

Ship only if the final gate is green. If validation still fails after the fix cap, ABORT without
shipping — never open a PR for code that fails the project's own test/lint/type gate. Routes to
`push` on green, `end` (abort) otherwise.

- type: code
- next: push
- inputs:
    ok: ${final-gate.ok}
    final_summary: ${final-gate.summary}

```python code
ok: bool
final_summary: str
if ok:
    result: dict = {"status": "Validated end-to-end; shipping."}
    next: str = "push"
else:
    result: dict = {"status": f"ABORTED before ship: {final_summary}"}
    next: str = "end"
```

### push

Push the work branch to origin so `ship` can open a PR. Pushing is deterministic, not agentic, so
it is a `code` node running in pflow's OWN process — NOT an agent node. That matters: a user's
Claude Code permission rule on push (e.g. `"permissions": {"ask": ["Bash(git push:*)"]}` in
`~/.claude/settings.json`) blocks an agent's `git push` even under `permission_mode:
bypassPermissions` — bypass skips interactive prompts but does NOT override a settings `ask`/`deny`
policy rule, and non-interactively an `ask` resolves to blocked. (This is exactly what blocked an
earlier run's agentic ship.) Those rules govern agent backends only, never pflow's own
subprocess — same reason `branch-setup` is a shell node.

It distinguishes the two failure modes deliberately. A missing `origin` remote is TOLERATED — it
skips the push and continues, so `ship` then attempts `gh pr create`, fails cleanly, and reports
honestly with an empty `pr_url` (the no-remote case). A real push REJECTION, however, HARD-STOPS:
for example a non-fast-forward when this `work_branch` already exists on the remote from a prior run
(recall `branch-setup` did `git checkout -B`, rewriting the local branch). Shipping anyway would let
`gh pr create` open a PR against the STALE remote branch — one that does NOT contain the
just-verified local commits — so it stops loudly rather than ship the wrong code.

**DO NOT add an `- on-error:` edge to this node.** Like `preflight`, the hard-stop IS the raised
exception terminating the run (no error successor → non-zero exit). An `on-error` edge would route
to a handler and let a rejected push fall through to `ship` — the exact stale-PR bug this guards.

- type: code
- next: ship
- inputs:
    repo_dir: ${repo_dir}
    work_branch: ${work_branch}

```python code
import subprocess
repo_dir: str
work_branch: str
remote = subprocess.run(["git", "-C", repo_dir, "remote", "get-url", "origin"],
                        capture_output=True, text=True)
if remote.returncode != 0:
    # No origin remote — tolerate; ship will report honestly (empty pr_url).
    result: str = "no-remote: skipped push; ship will report honestly"
else:
    push = subprocess.run(["git", "-C", repo_dir, "push", "-u", "origin", work_branch],
                          capture_output=True, text=True)
    if push.returncode != 0:
        raise RuntimeError(
            f"Push of '{work_branch}' to origin was REJECTED:\n{push.stderr.strip()}\n\n"
            "Refusing to ship: a PR opened now could reflect STALE remote commits, not the "
            "just-verified local work. This usually means the branch already exists on the remote "
            "from a prior run (branch-setup rewrites the local branch with `git checkout -B`). "
            "Resolve by deleting the remote branch, choosing a fresh work_branch, or running in a "
            "clean git worktree, then re-run."
        )
    result: str = "pushed"
```

### ship

Open a PR for the work branch against the base branch. The branch is already pushed by the `push`
node; this runs `gh pr create` (never merges directly) and surfaces anything the reviews/verify
flagged for the human reviewer.

- type: agent
- backend: claude
- prompt: ./prompts/ship.prompt.md
- cwd: ${repo_dir}
- max_turns: 30
- timeout: 600
- inputs:
    repo_dir: ${repo_dir}
    plan_path: ${plan}
    progress_log_path: ${progress_log}
    base_branch: ${base_branch}
- allowed_tools:
    - Bash
    - Read

```yaml output_schema
type: object
properties:
  pr_url: { type: string }
  summary: { type: string }
required: [pr_url, summary]
```

## Outputs

### pr_url

The opened PR URL, or "none" when the run aborted before ship (branch convergence: `ship` only
runs on the success path).

- source: ${ship.result.pr_url ?? "none"}

### summary

Why the run ended (shipped after validation, a segment that aborted, or a final-gate abort).

- source: ${check-final.result.status ?? check-groups.result.status}

### segments

The phase-group breakpoints the breakdown produced. Note: no caller consumes this today
(`run-from-plan` reads only `pr_url` + `summary`) — kept as diagnostic surface for
inspecting how the plan was segmented after a run.

- source: ${breakdown.result.segments}
