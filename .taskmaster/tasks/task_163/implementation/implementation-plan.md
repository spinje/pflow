# Plan: Task 163 — Plan-to-Code Agentic Coding Workflow Harness

## Context

Build a tree of `.pflow.md` files (a *composition* of existing pflow primitives — no pflow
source changes) that takes an implementation plan and drives it to a PR: plan-review →
implement (per phase-group, fresh-context forks) → multi-lens review-fix → final
code-quality review → adversarial verify → ship. Shipped as a reference example under
`examples/agent-orchestration/`, like the precursor `parallel-planner-review/`.

**Read first (do NOT re-derive what's in them):**
- `../task-163.md` — spec: what/why, all design decisions, 8 verified capability facts with
  file:line citations, inputs table, v1/v1.1 scope.
- `./progress-log.md` — the journey + GH-issue ledger + precursor lessons + the **spike
  results** (S1–S4) that this plan is grounded in. Append to it as you build.
- `../starting-context/braindump-harness-design.md` — tacit context: how the user thinks,
  the corrections made during design, what's still genuinely open.
- `.taskmaster/tasks/task_161/task-review.md` + `task_162/task-review.md` — the cache/loops
  groundwork the harness stands on (read before touching caching or loops).

**The single most important habit (the precursor's hardest lesson — "validates ≠ runnable"):**
build the WHOLE topology with `code` stand-ins and trace the FULL multi-group + multi-round
flow for $0 BEFORE swapping in any agent. A single-cycle run AND `--validate-only` both
passed while the precursor's multi-cycle loop was fundamentally broken. Spikes S1–S4 already
proved the hard parts; Phase 1 extends that to the whole graph.

## What's already verified (Phase 0 — DONE, see progress-log)

- **S2:** preflight `code` `raise` with no `on-error` edge → CLI exit 1, downstream skipped,
  message surfaced. The preflight mechanism works.
- **S1:** nested backward-edge loops across a sub-workflow boundary work; inner loop resets
  fresh each outer iteration; agent-`{continue}` exit AND hard `round<3` cap coexist.
- **S3 (folded into S1):** state accumulates correctly on shared cwd; revisit re-executes.
- **S4:** `resume` is linear continuation, cannot fork → **artifact-replay confirmed**, no
  claude-code change needed.

Spike files at `/tmp/t163-spikes/` are reference templates for the loop wiring. Note Task 162
shipped the `loop:` config block (verified working) — prefer it over hand-wired
backward-edge worker/checker where it fits (see Authoring Notes).

## Authoring notes (gotchas that cost retries — internalize before writing nodes)

1. **Artifacts by PATH, never templated content.** The `claude-code` `prompt` 10k cap is
   POST-interpolation and fails only at RUNTIME (passes validate/save/compile/`--dry-run`).
   Every agent prompt says "read the plan at `${plan_path}`", never "here is the plan:
   `${plan_content}`". Only scalars (paths, branch, phase numbers, the delta) are templated.
2. **In `code` nodes, EVERY type annotation declares an input.** Locals must be unannotated
   (`keep = True`, not `keep: bool = True`) or pflow demands an `inputs:` entry.
3. **Output entities need a description** under the `### name` heading, same as nodes.
4. **`claude-code` `output_schema` SOFT-FAILS** (sets `result` to a raw string, flips run to
   DEGRADED, does NOT route `on-error`). Any schema'd agent node needs an `isinstance(result,
   str)` guard branch, or use an `llm` node when the structure is load-bearing.
5. **`loop:` authoring** (Task 162): a `code` loop body outputs only `result`, so emit a dict
   and reference `${node.result.<field>}` in `while:`; use engine-injected `${__iteration__}`
   (1-based) for the counter, not a self-reference. Cross-iteration in-store state is a
   non-feature — carry state via filesystem/git/progress-log.
6. **Sub-workflow contract:** `cwd` is REJECTED on a `workflow` node (thread `repo_dir` as an
   input → set as each agent's `cwd:`); undeclared inputs are REJECTED at parse+runtime (rely
   on this; don't duplicate validation); outputs accessed as `${node-id.declared-output}`;
   external prompts (`- prompt: ./x.md`) resolve relative to the WORKFLOW FILE.
7. **`find-repo`** (`git rev-parse --show-toplevel`) is the ONLY way to reach
   `./.claude/agents/review-*.md` reliably (no repo-relative resolution; bare paths resolve
   against launch cwd). Resolve at the entry-point tier, thread `${find-repo.stdout}` down.

## Target file tree (v1)

```
examples/agent-orchestration/plan-to-code/
├── run-from-plan.pflow.md                 TIER 3 entry: find-repo → preflight → execute-plan
├── prompts/                               (entry-level prompts, if any)
└── execute-plan/                          TIER 2 core (invocation-agnostic)
    ├── execute-plan.pflow.md              plan-review → fix-plan → breakdown → impl-loop → final-review → verify → ship
    ├── prompts/
    │   ├── plan-review.prompt.md
    │   ├── fix-plan.prompt.md
    │   ├── breakdown.prompt.md            (llm; emits phase-group breakpoints)
    │   ├── final-review.prompt.md
    │   ├── verify.prompt.md
    │   └── ship.prompt.md
    └── implement-chunk/                   TIER 1 per phase-group body
        ├── implement-chunk.pflow.md       implement-fork → review-fix loop
        └── prompts/
            ├── implement.prompt.md
            └── review-fix.prompt.md
```
(`review-plan`/`fix-plan`/`ship` may start as nodes inside `execute-plan` with external
prompts; promote to their own sub-workflow folders only if they grow. Keep flat until a unit
earns a folder — "elegance must be earned".)

## Phase 1 — Full skeleton with `code` stand-ins ($0, the load-bearing phase)

**Goal:** the ENTIRE topology runs end-to-end with every agent replaced by a deterministic
`code` node returning the same schema, traced over a multi-group fake plan. This phase
defines the contracts every later leaf must satisfy. Do NOT write a single agent prompt yet.

Build order:
1. `execute-plan.pflow.md` with stand-ins: plan-review/fix-plan = no-op passthrough;
   `breakdown` = `code` returning a fixed `groups: [[0,1],[2]]`; impl-loop = the S1 nested
   loop wiring with `implement-chunk` as a sub-workflow worker; final-review/verify/ship =
   no-op `code` returning their schemas.
2. `implement-chunk.pflow.md` with stand-ins: implement = `code` that appends a line to a
   fake `progress-log` file and a fake `diff` file (proves the state bridge); review-fix loop
   = the S1 inner loop, `{continue}` driven by a per-group fixture to exercise both exits.
3. `run-from-plan.pflow.md`: `find-repo` (shell) → `preflight` (code, no on-error edge) →
   `execute-plan`.

**Trace these scenarios (all $0) — this is the acceptance gate for Phase 1:**
- Multi-group plan → groups run SEQUENTIALLY, group N's appended state visible to group N+1
  (the shared-branch model; S3 confirmed the mechanism, this confirms our wiring).
- A simulated hard implement failure → impl-loop EARLY-EXITS with a clear "group K broke"
  report; later groups do NOT run.
- review-fix loop honors `{continue:false}` (diminishing returns) AND the `round<3` cap.
- `max_review_rounds: 0` → per-group review skipped entirely.
- preflight with a missing required file → CLI exit ≠ 0, execute-plan never starts.
- `--validate-only` on `run-from-plan.pflow.md` passes (validates the whole tree recursively).

**Phase 1 deliverable doubles as the regression test** (Phase 4 wires it into CI as a
code-stand-in skeleton test, à la `tests/test_integration/test_loop_example.py`).

## Phase 2 — Perfect the leaves in isolation (real agents + prompts)

Swap stand-ins for real agents one unit at a time, each runnable standalone against the
Phase-1 contract. Source prompts from the user's existing artifacts where they fit; vendor +
adapt where the agent-definition framing doesn't (check ONE `review-*.md` as a subagent before
assuming all 8 work as-is).

Dependency order (each builds on the prior's verified contract):
1. **`breakdown`** (llm) — defines the phase-group shape everything downstream consumes.
   Structured `output_schema`; logic drawn from `.claude/skills/plan-breakdown/SKILL.md`
   (size + tacit-knowledge dependency). Emits groupings ONLY, never a task list.
2. **`implement` fork** — reads `{plan, spec, progress log}` + delta ("phases X done; do Y,
   then STOP"); implements; commits; self-review ("fully happy? loose ends?"); writes a
   SUBSTANTIVE progress-log entry (load-bearing — the only state bridge to the review fork).
   May internally parallelize mechanical work via its Task tool (accepted opacity); codes
   deep-context work itself. Prompt mirrors the user's real manual prompt.
3. **`review-fix` fork** — fresh; reads `{plan, spec, progress log}` + delta ("phases Y done —
   review + fix"); deploys ~4 relevant `./.claude/agents/review-*.md` lenses as subagents
   (it picks which); ADJUDICATES each finding (real? critical? not false-positive?) against
   git/code, not at face value; fixes real-critical; commits; logs; emits `{continue, reason}`.
4. **`verify`** — adversarial: try to break the integrated result, fix what breaks, ADD
   regression tests. Recipe from `.agents/skills/pflow-sandbox-testing/SKILL.md` (taken as an
   input path so the harness isn't pflow-locked). Use the user's verify prompt framing
   ("your value is the last 20%", "test suite results are context not evidence").
5. **`plan-review` + `fix-plan`** — plan-review deploys plan-focused lenses (incl.
   `review-plan.md`) over the plan; fix-plan applies the review and writes the hardened plan.
   v1 = single pass (default `max_plan_review_rounds: 1`).
6. **`final-review`** — whole-branch code-quality review; MAY refactor for simplicity (reuse
   the review-fix sub-workflow scoped to the full diff with a simplicity lens set).
7. **`ship`** — push branch + `gh pr create` (never merge to base). One PR for the run.

Per leaf: run standalone with a tiny real input, confirm its output matches the Phase-1
contract schema, iterate the prompt. Keep agent spend low (small fixtures; `--report` to see
rendered prompt + cost).

## Phase 3 — Integrate + one small live run

1. Swap all real leaves into `execute-plan`; re-run the Phase-1 skeleton scenarios with agents
   where cheap, stand-ins where not, to confirm wiring still holds.
2. **One real end-to-end run** against a throwaway repo with a tiny 2-phase plan:
   - implement → review-fix → final-review → verify (writes a regression test) → PR opened,
     base branch untouched.
   - Confirm the progress log accumulates ONE substantive entry per fork.
   - **Plant two findings** to prove adjudication: a false-positive (must be dismissed) and a
     real bug (must be fixed). This is the core "findings are claims" guarantee.
   - Capture the cost ledger (per-stage, via `pflow report`/trace) — the user tracks to the cent.

## Phase 4 — Polish

- Skeleton regression test (Phase-1 stand-ins) wired into `make test` (in-process, not e2e).
- Generated `README.md` via `pflow visualize ... -o README.md` (precursor pattern). Note the
  drift-guard test is still an open follow-on on the precursor — consider adding here.
- Cost legibility pass: ensure each stage's cost is visible from traces; document
  `max_review_rounds: 0` as the cost dial.

## Out of scope (v1.1 — the swarm refactor, optimize the core FOR it but build later)

Rewire `parallel-planner-review` so its per-issue body IS `execute-plan`
(find-issues → plan-each → per-issue worktree → execute-plan). This PROVES reuse (the swarm
loses its bespoke implement/review logic). Keep `execute-plan` invocation-agnostic from day
one (no single-plan assumptions baked in), but validate via the manual path first. Note the
#188 batch-input-coercion caveat lands here (per-item fields arrive as strings), not on the
manual path.

## Open implementation-time items (resolve as you hit them, none block Phase 1)

- **ASSUMPTION:** the 8 `review-*.md` lens files work as claude-code subagent prompts with
  light/no adaptation. Check one in Phase 2 before assuming all.
- **GH #443** (`--only` re-fires side-effecting upstream): only relevant if you iterate a node
  with side-effecting upstream via `--only`; otherwise ignore.
- **Auto-stage hook** stages Writes in this repo — watch it; unstage anything not meant for a
  commit (bit the precursor session). NEVER commit unless the user says so.
- **`loop:` vs hand-wired loop** for the review-fix + impl loops — both verified; pick `loop:`
  where it reads cleaner, hand-wired (S1 pattern) where you need explicit control. Decide per
  loop during Phase 1.

## Verification (acceptance criteria)

Maps to `../task-163.md` → Verification. Summary gates:
- **Phase 1:** all six skeleton scenarios pass for $0; `--validate-only` clean on the tree.
- **Phase 2:** each leaf produces contract-matching output standalone.
- **Phase 3:** the live 2-phase run opens a PR, base untouched, one log entry per fork, planted
  false-positive dismissed + planted real bug fixed.
- **Phase 4:** skeleton test green in `make test`; `make check` clean; README generates.
