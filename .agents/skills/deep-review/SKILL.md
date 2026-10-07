---
name: "deep-review"
description: "Deploy specialized review agents to find bugs that general code review misses. Handles spec review (before planning), plan review (before implementation), code review (after implementation), and the standing dogfood pass (not diff-scoped). Every lens whose trigger fires runs — selection is by what the change DOES, never by diff size — each targeting a specific blindspot category, scoped per seam when a change spans several."
---

# Deep Review — Specialized Multi-Agent Review

You are the orchestrator for pflow's specialized review system. You deploy review agents, evaluate their findings, and produce a concrete action plan. This complements the built-in `/code-review` (quick correctness pass) — deep-review is the pflow-specific battery that targets the blindspot categories general review misses, identified from this project's bug history.

## Assess Context

You already know the current state from the conversation. Determine which review type fits:

| Context | Review type |
|---|---|
| A task spec is being refreshed or written ahead of its planner (main orchestrator) | **Spec review** (see "Spec review mode") |
| You just wrote or finalized an implementation plan | **Plan review** (always includes `review-plan`) |
| You just finished a phase, uncommitted changes exist | **Code review** (scope per ladder below) |
| Implementation is done, PR is ready | **Code review** (full branch) |
| User explicitly asks to review plan/code/staged | Whatever they asked for |
| Before a release, or after roughly every ten merges to `main` (main orchestrator) | **Dogfood pass** — not diff-scoped (see "The standing dogfood pass") |

**Code-mode scope.** Honor an explicit ask; otherwise check `git status --porcelain`:

- Both staged AND unstaged changes, and neither the invocation nor the conversation says which → ambiguous; STOP and ask which scope. Do not guess.
- Only staged → staged changes. Only unstaged → unstaged changes (untracked files count as unstaged). Clean working tree → full branch vs. base.

Tell the agents the chosen scope explicitly in their prompts — per REVIEW-PROTOCOL.md they execute the named scope, never infer or substitute it.

**An empty target diff is a dispatch error, not a clean result** — when the chosen scope's `--stat`
(below) is empty, stop and fix the scope before launching anything: a lens over nothing returns
clean, and that clean gets read as coverage.

**Select by what the change DOES, never by how big it is.** Every lens whose trigger fires runs;
relevance is the only limit, there is no numeric cap, and the counts below are **floors**. The
fan-out merges and deduplicates, so an extra relevant lens costs a few minutes of Codex time while
a missed one costs a lane. Gauge the scope with the chosen scope's `--stat` diff (`git diff
--stat`, `--cached --stat`, or `origin/<base>...HEAD --stat`) and the file list only to see
**which triggers fire** — not to pick a count.

| The change… | …runs (in addition to the floor) |
|---|---|
| touches any **sensitive path** — the engine (`src/pflow/runtime/engine/`), the trace format (`src/pflow/runtime/workflow_trace.py`, `src/pflow/core/trace_io.py`), shell and code node execution (`src/pflow/nodes/shell/`, `src/pflow/nodes/python/`), the MCP server surface (`src/pflow/mcp_server/`), resume/gate semantics | the **full floor** (`silent-failures`, `impact-completeness`, `feature-interactions`, `test-fidelity`, and `falsifier` by direct launch) regardless of diff size — a 5-line engine change outranks a 500-line UI change, and on these paths the falsifier runs even for a "pure refactor": "existing behavior unchanged" is itself a promise worth executing against |
| changes **user-facing text or output shape** (errors, warnings, suggestions, CLI/JSON/report output, `pflow guide` text) | `agent-ux` + `falsifier` (falsifier: code mode only) |
| changes a **validator** or a **runtime behavior the validator mirrors** (parse, resolve, coerce, type-check) | `validation-consistency` — on BOTH sides, always — + `falsifier` ("validate-only and run agree" is a testable promise; code mode only) |
| changes a **shared helper, pattern, or contract with more than one consumer** (a formatter, a reserved key, a store key, a diagnostic field, a settings reader) | `impact-completeness` |
| **deletes or consolidates** (a ratchet, a migration, folding N sites into one) | `simplicity` (any size, lanes included — emergent duplication hides in ratchets) + `spec-conformance` when a task's spec and plan exist to compare against; both code mode only |
| touches an **error or exception path**, a guard, a fallback, an empty-result branch | `silent-failures` |
| is a **task completion gate** (a multi-phase implementation with a spec and plan to compare against) | `simplicity` + `spec-conformance` — both code mode only; emergent duplication across separately-built phases and spec drift are invisible until every phase exists, and final-code simplicity is the governing lens, so neither waits for a consolidation trigger |
| touches **subprocess, threads, executors, asyncio, copy semantics, shared mutable state** | `concurrency-safety` |
| is a **bug fix** of any size | `test-fidelity` (a regression test on the exact buggy path — this floor is never waived, a one-line fix included) + `falsifier` (code mode only) |
| crosses **batch, nested workflows, branching, caching, MCP, approval gates, or output routing** | `feature-interactions` |
| adds or changes an **on-disk or agent-facing contract** in a plan or spec (trace field, reserved key, CLI flag, node interface, resume token shape) | `architecture-fit` (plan/spec mode only) |
| is **docs-only** | no battery — `make check` and the docs tests are the gate; say so where the gate is recorded |
| changes **CI, shared tooling (Makefile, pre-commit, the review fan-out), or a security boundary** | floor of one lens, never zero (`impact-completeness` or `silent-failures` by what it touches) |

**Floors by mode** (the minimum when the triggers above fire nothing extra):
- **Code mode, any non-trivial diff**: `silent-failures` + `impact-completeness` + `test-fidelity`, plus `falsifier` whenever the diff makes any user-facing promise. A genuinely one-line fix runs `test-fidelity` alone at minimum — never zero; record the choice.
- **Plan mode**: `review-plan` always in slot 1, plus every trigger the plan's phases fire except the code-only lenses (`falsifier`, `simplicity`, `spec-conformance` — those become completion-gate lenses the plan names); engine or trace contact makes the plan battery MANDATORY (ORCHESTRATION "Review policy").
- **Spec mode** and the **dogfood pass**: see their sections below.

**Scope lenses per seam when a change spans several.** A diff that touches the engine, the CLI
renderer and the web UI is three reviews, not one: a lens over the whole thing skims each part.
Use the fan-out's per-lens target (`{"name": …, "target": …}`) to point each **dimension lens** at
the slice where its dimension lives — `concurrency-safety` at the executor files, `agent-ux` at the
renderer and guide text, `validation-consistency` at the validator + the runtime twin — and run
the same lens more than once with different targets when two seams both earn it. The
**cross-cutting lenses** (`impact-completeness`, `feature-interactions`, `spec-conformance`,
`simplicity`) always see the WHOLE diff: partitioning is exactly how seam bugs hide, and those
four exist to look across seams. State the partition in the gate record so a reader can see what
each lens actually looked at.

**User-specified count.** If the invocation includes a standalone number (`3`) or range (`2-4`), it overrides the triggers upward only: a number is an exact count, a range is floor and ceiling (relevance picks within), and neither may go below the triggered floors — a sensitive-path diff keeps its full floor whatever the number says. `review-plan` still fills slot 1 in plan mode. If the number exceeds the triggered lenses, fill with the strong defaults (`review-silent-failures`, `review-impact-completeness`) and note it in the summary. Numbers inside identifiers (`task 38`) are not counts.

## Spec review mode

A task spec written ahead of its planner goes stale as a rule, and a spec battery has changed two
task designs (Tasks 94, 170) before any plan existed — it is the cheapest review this repo runs.
The main orchestrator commissions it as part of spec freshness (ORCHESTRATION "Roles"); its
`review_target` says explicitly *"SPEC review, not a code-diff review: evaluate the spec at
`<path>` against today's code — classify every claim STILL TRUE / STALE / UNVERIFIABLE, and judge
whether a planner building from it would build the wrong thing."* Lenses: `review-architecture-fit`
always (and `review-plan` when the spec already carries phase structure), plus `feature-interactions`, `silent-failures`, `impact-completeness`, and `agent-ux` when
the spec changes a user-facing surface; direct launches (plan/spec lenses never go through the
fan-out). Findings land in ONE ledger file (`scratchpads/<session>/<task>-spec-battery.md`) with a
disposition per finding — **A** fold the accuracy correction into the spec now · **B** record a
design gap as a "RESOLVE AT START" constraint (constraint stated, mechanism left to the planner) ·
**C** a genuine decision goes to the user · **D** disputed, with the counter-citation — then one
spec rewrite from the ledger. A freshness check is not a readiness verdict: citations holding and
"would a planner build the wrong thing" are different questions, and the second needs a
context-free reader.

## The standing dogfood pass (not diff-scoped)

Diff-scoped review cannot see what a new agent *experiences*: misleading suggestions,
validate-passes-run-fails, missing commands, stale guide claims accumulate across many
individually-reviewed PRs. The dogfood pass is one fresh-eyes Opus agent that starts exactly as a
new user would — `uv run pflow guide`, no source reading — and walks the core loop three times with
increasing realism (shell/code/file → http with inputs → llm + batch): author → `--validate-only` →
run → read the trace / `pflow report` → deliberately break something and read the error → `pflow
save` under a `dogfood-` prefix → run by name → `--only` / resume / gates where they apply. It logs
every friction point with the verbatim command and output and a severity (BLOCKER / MISLEAD / GAP /
PAPERCUT), tests the guide's claims one by one, and ends by removing what it created and listing
what it left behind. **Cadence:** before every release, and after roughly every ten merges to
`main` — both. **Spend:** paid LLM calls allowed on the cheapest configured model, capped (~10
small calls; the one pass so far — session 10 — made 8 calls for about $0.00004). **Output:** a report the main orchestrator
reads in full, then a verification agent re-executes each finding on `main`, checks for duplicate
issues, and drafts issue bodies (class, executed evidence, mechanism, closing mechanism, verify at
start, severity); the orchestrator files them serially after reading each. Never save anything
into the user's library without the prefix; never touch saved workflows the pass did not create.

**Protect your context window.** Do NOT read diffs, plans, or full files yourself — the subagents have expendable context windows. The cheap scope commands above and small targeted reads during verification (an ADR, one flagged function) are the exception, never whole diffs or plans. You only need the task ID and a one-line description to deploy.

## Dispatch — how the lenses run

**Default: the pflow fan-out, waited on IN-TURN.**

```
uv run pflow workflows/review/run-review-lenses.pflow.md \
  lenses='["review-silent-failures","review-impact-completeness",…]' \
  review_target="Review all changes on this branch vs main for task N (title)."
```

Provider defaults to codex — cross-model diversity is the point: a same-family reviewer shares
the author's blind spots. It also buys **capacity** (the lenses run outside the runner — zero of
its child slots) and **context economy** (one merged report in your window instead of N).
**Cross-model means OPPOSITE the builder**: a Claude-side caller keeps
the codex default; a Codex-side gate runner passes `provider=claude` (the claude branch runs
tool-restricted and SDK-sandboxed; the codex branch stays the mechanically read-only path). Each `lenses` entry is a bare agent name or `{"name": …, "target": …}`
giving that one lens its own review target (the mechanism for re-reviews: hand a lens its prior
findings via its per-lens target). The workflow reads each lens's persona + frontmatter itself,
runs them read-only in parallel, and returns ONE merged, deduplicated report (the merge
preserves, never adjudicates — evaluation stays yours). A battery outruns a single Bash call
(lenses run minutes to tens of minutes; a foreground call caps at 600s and past the cap
auto-backgrounds into the wake trap), so launch it **backgrounded with stdout redirected to a
declared file inside the worktree/task folder**, then **WAIT IN-TURN** for that file — a Monitor
until-loop or repeated foreground polls. **Never end your turn to wait** — a stopped caller is
never woken by background-Bash completion (ORCHESTRATION.md "Review policy"). An empty or
partial report is a COVERAGE GAP, not a clean pass — the report's Coverage section names failed
lenses; re-run those before evaluating. **Read the report file IN FULL, never through `tail`** —
a tail shows only the trailing verified-clean sections and is indistinguishable from a genuinely
clean review. The workflow's `raw` output is the per-lens audit trail when you must prove the merge
dropped nothing.

**Fallback: direct Agent-tool launches** (the section below) — a logged one-off for when pflow
cannot run or the caller must keep working in parallel. Fallback coverage is same-family, so
wherever you record the gate's outcome (a lane's PR body) state (a) that the pflow fan-out did not
start, and why, (b) which lenses ran, and (c) that they share the builder's model family — that
coverage is the FLOOR, not diversity; the main orchestrator commissions one cross-model lens for a
sensitive-path diff (the sensitive-path trigger above). Never fall back to reviewing your own diff. A Codex seat
whose sandbox cannot start pflow runs the native `.codex/agents/review-*.toml` lenses under the
same disclosure. **Plan mode dispatches through the fan-out too** — the lenses are reading lenses whatever the target, so
`review_target` names the plan file, the spec and the phases under review ("PLAN-MODE review, not a code
diff: …"); cross-model diversity matters as much for a plan as for a diff. Direct launch is the same fallback
it is in code mode, under the same disclosure.

**`review-falsifier` always launches directly** (Agent tool), never through the fan-out — it
EXECUTES the change (real workflow runs, targeted pytest) and needs the access the read-only
fan-out never grants. Code mode only. It is not a fan-out lens and runs **LAST** —
after the reading battery's confirmed fixes have landed, so it attacks the state that ships. Give it
the task spec path, plus `review-spec-conformance`'s Requirement Inventory when that lens ran.
Skip it only when the diff carries no user-facing promise to falsify (a pure refactor with no behavior change OFF the sensitive paths, docs, tooling) — a validator change always carries one ("validate-only and run agree"), and so does any bug fix with a reproducible symptom.

## Deploy Agents (direct launch — the fallback path, and the falsifier's only path)

Launch selected agents in capacity-aware parallel batches (the fan-out has no lens-count limit and runs at most 12 at once, queueing the rest; direct launches never exceed the runner's available child slots). Fill the available slots in one parallel launch, wait for that batch, then launch any remainder. Keep prompts minimal — the agents have detailed built-in instructions and know the pflow codebase.

Include the standing noise rule in each prompt: `uv.lock` is not a review target — a lockfile change is a signal of a dependency change, not code to critique.

**Severity is shared across the battery**: **Critical** = demonstrated path to data loss, wrong workflow results, crashes, or broken existing functionality. **Warning** = measurable regression or concrete risk. **Suggestion** = improvement worth considering. A finding that doesn't clear "concrete" is noise — agents are instructed to drop these; you enforce it at evaluation.

### Selecting Specialists

Pick by what the scope actually touches — the trigger table above decides; this table says what each lens is FOR:

| Agent type | Pick when the scope involves... |
|---|---|
| `review-plan` | **Always slot 1 in plan mode** (plans only) |
| `review-architecture-fit` | Plans/specs whose shapes downstream roadmap work inherits: on-disk or agent-facing contracts, trace/workflow/resume formats, store keys, node interfaces — one-way doors and trajectory fit (plan/spec mode only) |
| `review-silent-failures` | Empty/null guards, exception handling, ignored returns, dropped data — strong default for most scopes |
| `review-impact-completeness` | Changes to shared patterns with multiple consumers — strong default for most scopes |
| `review-validation-consistency` | Validator or runtime behavior changes (drift between them) |
| `review-feature-interactions` | New features crossing batch, nested workflows, branching, caching, MCP, output |
| `review-agent-ux` | New/changed user-facing output: errors, warnings, CLI results, reports |
| `review-concurrency-safety` | Threads, executors, copy semantics, asyncio, shared mutable state |
| `review-test-fidelity` | Substantial new test coverage, regression tests for bug fixes |
| `review-simplicity` | Any deletion or consolidation, lanes included, and every multi-phase implementation (integrated code only, code mode) |
| `review-spec-conformance` | Multi-phase task implementations with a spec and plan to compare against: does the integrated code do what the spec + plan asked, no less, no more — the reading counterpart of `review-falsifier` (integrated code only, code mode; never mid-task) |
| `review-falsifier` | The spec makes testable behavioral promises and a dev environment can run them — the only lens that EXECUTES (real workflow runs, targeted pytest). Direct launch only, code mode only |

`review-plan` and `review-architecture-fit` only review plans/specs; `review-simplicity`, `review-spec-conformance` and `review-falsifier` only review integrated code — never deploy them in the wrong mode.

### Prompts

Plan review — point at the actual file:
```
Review the implementation plan for task 135 (Execution Core Compile-Once Redesign).
Plan: .taskmaster/tasks/task_135/implementation/implementation-plan.md
```

Code review — the agents know git; they'll figure out the right commands:
```
Review staged changes for task 135 (Execution Core Compile-Once Redesign).
```
or:
```
Review all changes on this branch for task 135 (Execution Core Compile-Once Redesign).
```

When the target includes a named document (an ADR, a settled ruling), state in the prompt (or
`review_target`) that **SILENCE about it is a coverage gap, not a pass** — otherwise a lens skims
the `.md` and reports nothing. Carry the live settled-rulings set
(`.taskmaster/orchestration/DECISIONS.md`, `context/adr/`) into evaluation too, so a finding that
proposes to regress one is disputed by default (Step 2) rather than argued from scratch.

## Evaluate Findings

When all agents return, evaluate their findings rigorously. **Do not blindly trust the reviews.** Review agents can be wrong, miss context, or misunderstand the code.

### Step 1: Inventory

Under the default fan-out dispatch the merged report largely IS the inventory — verify its
Coverage section, then move to Step 2. For direct launches, build a complete inventory of all
findings across agents. For each finding, extract:
- **What**: The specific issue raised
- **Where**: File path and location
- **Severity**: Critical / Warning / Suggestion
- **Which agent(s)**: Who found it (multiple agents flagging the same area is a strong signal)

Merge duplicates — multiple agents often flag the same issue from different angles. Keep the version with better evidence.

An agent reporting NO findings is signal — record its dimension under "Areas Verified Clean". An agent that errored or returned nothing usable is NOT clean — name the coverage gap explicitly in the summary.

### Step 2: Verify Critical Findings

For findings classified as Critical or high-confidence Warnings, verify them before accepting:

- If a finding references specific code, deploy a `pflow-codebase-searcher` agent (or a small batch in parallel) to verify the claim against actual code. The review agent may have hallucinated a file path, misread a function, or missed surrounding context.
- Check whether the proposed fix would conflict with existing patterns or break other code. Check `context/adr/` — a finding that re-litigates a recorded decision is disputed by default; flag the conflict instead.
- Check for context the review agent may have missed — CLAUDE.md files, related tests, git history.
- **Disputing a Critical takes the same rigor as confirming one**: a searcher-verified
  counter-citation (file:line of what the reviewer misread), never reasoning from memory — a
  wrongly disputed Critical is silently final.

You don't need to verify every Suggestion — focus verification effort on findings that would change the implementation.

### Step 3: Classify Each Finding

Render a verdict for each finding:

| Verdict | Meaning |
|---|---|
| **Confirmed** | Issue is real, proposed fix is sound |
| **Confirmed, different fix** | Issue is real, but the proposed fix is wrong or there's a better approach |
| **Disputed** | Issue doesn't exist, or the reviewer misunderstood the code. State why with evidence. |
| **Needs investigation** | Can't determine without deeper analysis or user input |

### Step 4: Surface Ambiguity

Before presenting the plan, explicitly identify:
- Any findings where you're less than 90% confident in your verdict
- Any fixes that touch code you don't fully understand
- Any architectural decisions that should be made by the user, not by you
- Any findings that contradict each other

**Do not silently resolve ambiguity. Surface it.**

## Present Action Plan

### Output Format

```markdown
## Review Summary

**Mode**: [plan/code]
**Task**: [id — description]
**Agents deployed**: [count]
**Findings**: [N confirmed, N disputed, N needs investigation]
**Verdict**: [ship / ship after confirmed fixes / needs work]

### Action Plan (ordered by priority)

#### 1. [Title] — [Confirmed / Confirmed, different fix]
- **Found by**: [agent name(s)]
- **Issue**: [What's wrong]
- **File(s)**: [Exact paths]
- **Fix**: [Concrete description — specific enough to implement]
- **Risk**: [What could go wrong if we get this fix wrong]
- **Tests**: [What tests need adding/modifying, if any]

#### 2. ...

### Disputed Findings
#### [Title] — Disputed
- **Found by**: [agent]
- **Claimed issue**: [What the review said]
- **Why it's wrong**: [Your reasoning with code evidence]

### Needs Investigation
#### [Title]
- **Found by**: [agent]
- **Issue**: [What was raised]
- **Why it's unclear**: [What you'd need to determine]

### Suggestions
- [Finding] (from: [agent])

### Areas Verified Clean
[Summary of what was checked and found correct]
```

**The verdict rubric is biased toward ship.** Suggestions never gate. Isolated warnings don't either — "ship after confirmed fixes" lists them as follow-ups, not blockers. "Needs work" requires a confirmed Critical, or multiple confirmed warnings forming a risk pattern. Don't let volume of minor findings masquerade as severity.

### After Presenting

**If the session involves back-and-forth conversation with the user**: Present the action plan and wait for approval before implementing fixes. The user may want to adjust priorities, dispute findings, or skip items.

**If you are operating autonomously** (no conversational back-and-forth): Proceed with implementing confirmed fixes in priority order. Use your judgment on disputed findings — skip them if uncertain.

**Record the outcome.** If a progress log exists for the task (`.taskmaster/tasks/task_{N}/implementation/progress-log.md`), record confirmed findings and their fixes there once approved — review results are exactly the "decisions, discoveries, deviations" that file exists to capture.

## Re-Reviews

When reviewing a scope that already received a deep-review (same task, new commits after fixes), don't start from scratch. Give each agent its dimension's prior findings along with the scope, plus these rules:

- **Fixed findings** → omit from output; note them as resolved in your summary.
- **Unfixed findings** → re-emit even if unchanged, so they stay visible.
- **User-rejected findings** ("won't fix", or disputed with a justification) → respect the decision; re-raise ONLY if the issue has materially worsened. Do not re-litigate.
- New code gets full scrutiny; previously-verified-clean areas that didn't change don't need re-reading.

## Running Individual Agents

You can also launch a single specialist agent when you suspect a specific type of issue — no need for the full battery every time.
