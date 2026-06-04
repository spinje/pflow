# Validate and Fix

A reusable deterministic test/quality **gate with an auto-fix loop**. It runs the project's full
validation command (`validate_command`, e.g. `make test && make check`) and, if it fails, forks a
fresh agent to fix the failures, then re-runs — looping until validation passes or `max_fix_rounds`
is reached.

**The loop's exit condition is GROUND TRUTH** — the command's exit code — not an agent's `{continue}`
claim. This is the cleanest loop in the harness: it cannot be fooled by an agent reporting success,
so it needs no soft-fail handling. (Contrast the review-fix loop, whose checker reads an agent claim.)

The caller branches on `ok`: `true` = validation passes (possibly after fixes); `false` = still
failing after the cap, so the caller MUST abort the run (never ship code that fails the project's own
test/lint/type gate). When `validate_command` is empty the gate passes trivially — but then the
harness can no longer GUARANTEE green, so callers should supply a command.

The fix fork is a fresh fork scoped by the failures themselves (it runs the command to see them),
consistent with the artifact-replay model — NOT a resume of a prior session.

## Inputs

### repo_dir

Absolute repo root; the validation command and every fix fork run here.

- type: string
- required: true

### validate_command

The project's full validation command (tests + lint + types), e.g. `make test && make check`.
Empty → the gate passes trivially (the harness then cannot guarantee the code is green).

- type: string
- required: false
- default: ""

### plan

Path to the implementation plan (the fix fork reads it for intended behavior).

- type: string
- required: true

### progress_log

Path to the shared progress log the fix fork appends to.

- type: string
- required: true

### base_branch

Base branch; the fix fork diffs `git diff ${base_branch}...HEAD` to see the whole change.

- type: string
- required: false
- default: main

### max_fix_rounds

Hard cap on fix attempts before giving up (returns `ok: false`).

- type: integer
- required: false
- default: 5

## Steps

### run-validate

Run the project's validation command in `repo_dir` and report pass/fail BY EXIT CODE — the
deterministic ground truth that drives the loop. It also carries the fix-round counter forward (a
code node can't read its own prior output, so the counter rides on this node and is incremented by
the checker). An empty `validate_command` passes trivially. This is the loop's entry AND the target
of `fix-tests`'s backward edge, so it re-runs after every fix.

- type: code
- next: check-validate
- inputs:
    validate_command: ${validate_command}
    repo_dir: ${repo_dir}
    prior_round: ${check-validate.result.next_round ?? 0}

```python code
import subprocess
validate_command: str
repo_dir: str
prior_round: int
cmd = validate_command.strip()
if not cmd:
    result: dict = {"ok": True, "round": prior_round, "tail": "(no validate_command; gate skipped)"}
else:
    proc = subprocess.run(cmd, shell=True, cwd=repo_dir, capture_output=True, text=True)
    combined = (proc.stdout + "\n" + proc.stderr).strip()
    result: dict = {"ok": proc.returncode == 0, "round": prior_round, "tail": combined[-2000:]}
```

### check-validate

Decide the loop on the command's REAL result: pass → done (`ok: true`); fail and under the cap →
fork a fix agent; fail at the cap → done (`ok: false`, the caller aborts). Never reads an agent
claim — only the exit code from `run-validate`.

- type: code
- next: fix-tests
- inputs:
    ok: ${run-validate.result.ok}
    round: ${run-validate.result.round}
    cap: ${max_fix_rounds}

```python code
ok: bool
round: int
cap: int
if ok:
    result: dict = {"ok": True, "rounds": round, "summary": f"Validation passed (after {round} fix round(s))."}
    next: str = "end"
elif round < cap:
    result: dict = {"ok": False, "next_round": round + 1, "summary": f"Validation failing; fix round {round + 1}."}
    next: str = "fix-tests"
else:
    result: dict = {"ok": False, "rounds": round, "summary": f"Validation STILL failing after {cap} fix round(s)."}
    next: str = "end"
```

### fix-tests

A fresh fix fork. The failures are the artifact that scopes its work: it runs `validate_command`
itself to see exactly what's red, fixes the ROOT CAUSE (never weakening or deleting a test to
silence it), re-runs to confirm locally, commits the fix, and appends a progress-log entry. Then
control returns to `run-validate`, which re-checks deterministically.

- type: claude-code
- prompt: ./prompts/fix-tests.prompt.md
- cwd: ${repo_dir}
- max_turns: 60
- timeout: 1800
- next: run-validate
- inputs:
    repo_dir: ${repo_dir}
    validate_command: ${validate_command}
    plan_path: ${plan}
    progress_log_path: ${progress_log}
    base_branch: ${base_branch}
    round: ${check-validate.result.next_round}
- allowed_tools:
    - Bash
    - Read
    - Edit
    - Write
    - Glob
    - Grep

## Outputs

### ok

True if validation passes (possibly after fixes); false if still failing after the cap (caller aborts).

- source: ${check-validate.result.ok}

### summary

Why the gate ended.

- source: ${check-validate.result.summary}
