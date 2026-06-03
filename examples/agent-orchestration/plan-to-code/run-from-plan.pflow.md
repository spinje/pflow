# Run From Plan

Manual entry point for the plan-to-code harness: invoke it by hand with a path to an
implementation plan (and optionally a spec). It resolves the target repo, fails fast if any
required review-lens dependency is missing or the repo has uncommitted changes, then runs the
invocation-agnostic `execute-plan` core: harden the plan (review+fix) → break it into segments →
implement every segment (segmentation is for context-window management, not review) → review-fix
the whole codebase → simplify the integrated whole → adversarially verify → open a PR.

**Target repo:** pass `repo_dir` to point at the repo where code should be written, or leave it
empty to use the git root of the current directory. The plan can live anywhere (e.g.
`~/.claude/plans/`) — it is independent of the target repo. Run against a **clean working tree**;
a fresh `git worktree` is the recommended isolation (and the only safe way to run against a repo
that has uncommitted changes).

**Prerequisites:** `gh` authenticated with push + PR rights on `origin`; the review-lens
subagents named in `plan_lenses`/`review_lenses` must exist as `.claude/agents/<name>.md` in the
target repo (preflight verifies). Claude runs on your subscription by default (no API billing;
opt into Anthropic Console billing per-node with `use_api_key: true`).

## Inputs

### repo_dir

Absolute path to the TARGET repository — where code gets written and committed. Independent of
where the plan lives (a plan in `~/.claude/plans/` can target any repo) and of where pflow was
launched. Leave empty to default to the git root of the current directory (the common case:
`cd` into your project, then run). Override to target a different repo or a worktree.

**Run against a clean working tree** (no uncommitted changes) — the harness commits here, so a
dirty tree would let agents sweep up unrelated work. A fresh `git worktree` is the recommended
isolation, and the only safe way to run against a repo that has uncommitted changes.

- type: string
- required: false
- default: ""

### plan

Path to the implementation plan to execute.

- type: string
- required: false
- default: ./PLAN.md

### spec

Optional complementary spec for complex tasks.

- type: string
- required: false
- default: ""

### progress_log

Path to the shared progress log (the carried-forward understanding across forks). Defaults next
to the plan; override to place it elsewhere.

- type: string
- required: false
- default: ./progress-log.md

### base_branch

Branch the PR targets, and that the work branch is based on.

- type: string
- required: false
- default: main

### work_branch

Name of the branch the harness creates and implements on.

- type: string
- required: false
- default: agent/plan-to-code

### plan_lenses

Comma-separated plan-review lens subagent names. Must exist as `.claude/agents/<name>.md`.
Default is what this repo ships.

- type: string
- required: false
- default: review-plan

### review_lenses

Comma-separated code-review lens subagent names for the whole-codebase review-fix loop.
Must exist as `.claude/agents/<name>.md`. Default is the repo's general-purpose code lenses.

- type: string
- required: false
- default: review-silent-failures, review-test-fidelity, review-impact-completeness, review-validation-consistency

### simplify_lens

Single simplicity-review lens subagent for the final simplicity pass (runs after the review-fix
loop, before verify). Must exist as `.claude/agents/<name>.md`.

- type: string
- required: false
- default: review-simplicity

### verify_recipe

Path to a project-specific recipe for running/exercising the system in adversarial verify
("" → the verify agent infers commands from the repo).

- type: string
- required: false
- default: ""

### max_review_rounds

Hard cap on rounds in the whole-codebase review-fix loop (0 = skip review — the cost dial).
Default is the cap; the review agent's diminishing-returns judgment normally exits first.

- type: integer
- required: false
- default: 3

## Steps

### resolve-repo

Resolve the TARGET repo AND absolutize the artifact paths, so everything downstream is anchored
correctly no matter where pflow was launched. The repo is `repo_dir` if provided, else the git root
of the current directory; it fails clearly if neither is found — so the harness never silently
targets the wrong place (the root cause of an early bug: it used to resolve pflow's own launch dir).

It also resolves `plan`/`spec`/`progress_log` to ABSOLUTE paths (relative to the launch directory)
before they are threaded to agents that all run with `cwd: ${repo_dir}`. Without this, a relative
artifact path — and the defaults `./PLAN.md` / `./progress-log.md` are relative — would be resolved
by those agents against the repo root, not the launch dir, so they would read/edit the wrong file
(or fail to find it). The plan can live anywhere, independent of the repo, precisely because it is
absolutized here.

- type: code
- next: preflight
- inputs:
    repo_dir: ${repo_dir}
    plan: ${plan}
    spec: ${spec}
    progress_log: ${progress_log}

```python code
import os
import subprocess
repo_dir: str
plan: str
spec: str
progress_log: str

def _abs(p):
    # Absolutize relative to the launch cwd; leave an empty (optional) path empty.
    return os.path.abspath(os.path.expanduser(p)) if p.strip() else p

candidate = repo_dir.strip()
if candidate:
    root = os.path.abspath(os.path.expanduser(candidate))
    if not os.path.isdir(os.path.join(root, ".git")):
        # could be a worktree (.git is a file) or a subdir — resolve via git
        proc = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"repo_dir '{candidate}' is not inside a git repository.")
        root = proc.stdout.strip()
else:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "No repo_dir provided and the current directory is not a git repository. "
            "Pass repo_dir=/path/to/target-repo, or run from inside the target repo."
        )
    root = proc.stdout.strip()
result: dict = {
    "repo": root,
    "plan": _abs(plan),
    "spec": _abs(spec),
    "progress_log": _abs(progress_log),
}
```

### preflight

Fail fast on two preconditions, before any agent runs: (1) every declared review lens exists,
and (2) the target repo's working tree is clean. A dirty tree is rejected because the harness
commits to this repo — uncommitted changes would let agents sweep up unrelated work (this is
exactly what bit an early run). Use a fresh `git worktree` to run against a repo with uncommitted
changes.

**DO NOT add an `- on-error:` edge to this node.** A `raise` in a `code` body becomes
`action="error"`, which HARD-STOPS the run (non-zero exit) only when there is no error
successor; adding `on-error` would route to a handler and let the run continue as DEGRADED.
pflow even prints a warning suggesting you add `on-error` here — that suggestion is wrong for a
precondition gate. (Verified by spike S2.)

- type: code
- next: execute-plan
- inputs:
    repo_dir: ${resolve-repo.result.repo}
    plan_lenses: ${plan_lenses}
    review_lenses: ${review_lenses}
    simplify_lens: ${simplify_lens}

```python code
import os
import subprocess
repo_dir: str
plan_lenses: str
review_lenses: str
simplify_lens: str
# (1) required lenses exist
names = [n.strip() for n in (plan_lenses + "," + review_lenses + "," + simplify_lens).split(",") if n.strip()]
missing = [n for n in names if not os.path.exists(os.path.join(repo_dir, ".claude/agents", n + ".md"))]
if missing:
    raise RuntimeError(
        "Preflight failed — required review-lens files are missing under "
        f"{os.path.join(repo_dir, '.claude/agents')}:\n  "
        + "\n  ".join(n + ".md" for n in missing)
        + "\nThe harness cannot review without its lenses. Add them or adjust "
        "plan_lenses/review_lenses. Aborting."
    )
# (2) clean working tree
status = subprocess.run(["git", "-C", repo_dir, "status", "--porcelain"],
                        capture_output=True, text=True)
if status.stdout.strip():
    raise RuntimeError(
        f"Preflight failed — target repo '{repo_dir}' has uncommitted changes:\n"
        + status.stdout.rstrip()
        + "\nThe harness commits to this repo; run against a clean tree or a fresh "
        "`git worktree` so agents don't sweep up unrelated work. Aborting."
    )
result: str = "ok"
```

### execute-plan

Run the invocation-agnostic core. `repo_dir` is threaded down (the core never resolves it
itself — `cwd` is rejected on workflow nodes).

- type: workflow
- workflow: ./execute-plan/execute-plan.pflow.md
- inputs:
    plan: ${resolve-repo.result.plan}
    spec: ${resolve-repo.result.spec}
    progress_log: ${resolve-repo.result.progress_log}
    repo_dir: ${resolve-repo.result.repo}
    base_branch: ${base_branch}
    work_branch: ${work_branch}
    plan_lenses: ${plan_lenses}
    review_lenses: ${review_lenses}
    simplify_lens: ${simplify_lens}
    verify_recipe: ${verify_recipe}
    max_review_rounds: ${max_review_rounds}

## Outputs

### pr_url

The PR opened by the run (or "none" if it aborted before ship).

- source: ${execute-plan.pr_url}

### summary

Why the run ended.

- source: ${execute-plan.summary}
- stdout: true
