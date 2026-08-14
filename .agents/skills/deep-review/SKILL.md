---
name: "deep-review"
description: "Deploy specialized review agents to find bugs that general code review misses. Handles both plan review (before implementation) and code review (after implementation). Deploys 1-8 focused agents in capacity-aware parallel batches, scaled to plan/diff complexity, each targeting a specific blindspot category."
---

# Deep Review — Specialized Multi-Agent Review

You are the orchestrator for pflow's specialized review system. You deploy review agents, evaluate their findings, and produce a concrete action plan. This complements the built-in `/code-review` (quick correctness pass) — deep-review is the pflow-specific battery that targets the blindspot categories general review misses, identified from this project's bug history.

## Assess Context

You already know the current state from the conversation. Determine which review type fits:

| Context | Review type |
|---|---|
| You just wrote or finalized an implementation plan | **Plan review** (always includes `review-plan`) |
| You just finished a phase, uncommitted changes exist | **Code review** (scope per ladder below) |
| Implementation is done, PR is ready | **Code review** (full branch) |
| User explicitly asks to review plan/code/staged | Whatever they asked for |

**Code-mode scope.** Honor an explicit ask; otherwise check `git status --porcelain`:

- Both staged AND unstaged changes, and neither the invocation nor the conversation says which → ambiguous; STOP and ask which scope. Do not guess.
- Only staged → staged changes. Only unstaged → unstaged changes (untracked files count as unstaged). Clean working tree → full branch vs. base.

Tell the agents the chosen scope explicitly in their prompts — per REVIEW-PROTOCOL.md they execute the named scope, never infer or substitute it.

**Scale the battery — deploy 1-8 agents, never more.** Gauge size with the chosen scope's `--stat` diff (`git diff --stat`, `--cached --stat`, or `origin/<base>...HEAD --stat`) and the file list (for plans: estimate from the plan's phases and components touched):

| Tier | Scope | Agents |
|---|---|---|
| Trivial | ≤10 changed lines, ≤3 files | 1-2 — or skip deep-review entirely |
| Lite | ≤100 lines, ≤20 files | 2-4 |
| Full | >100 lines, or >20 files, or multi-phase plans, or PR-ready branches | 4-6 |
| Major | >500 lines, or >50 files, or multi-phase plans of that scale | 5-8 |

**Counts are ceilings, not targets.** Never deploy a specialist whose dimension the scope doesn't touch just to hit the tier's number — if only 3 dimensions are genuinely in play on a Full-tier diff, deploy 3. Size doesn't create relevance: a huge diff that never touches threading or user-facing output still gets no `review-concurrency-safety` or `review-agent-ux`, so even Major-tier reviews rarely exceed 5-6 agents in practice. When in doubt between tiers, pick the higher one.

**User-specified count.** If the invocation includes a standalone number (`3`) or range (`2-4`), it overrides the tier table: a number is an exact count, a range is floor and ceiling (relevance picks within). `review-plan` still fills slot 1 in plan mode. If the floor exceeds the genuinely relevant dimensions, fill remaining slots with the strong defaults (`review-silent-failures`, `review-impact-completeness`) and note it in the summary. Numbers inside identifiers (`task 38`) are not counts.

**Protect your context window.** Do NOT read diffs, plans, or full files yourself — the subagents have expendable context windows. The cheap scope commands above and small targeted reads during verification (an ADR, one flagged function) are the exception, never whole diffs or plans. You only need the task ID and a one-line description to deploy.

## Dispatch — how the lenses run

**Default: the pflow fan-out, in the FOREGROUND.**

```
uv run pflow workflows/review/run-review-lenses.pflow.md \
  lenses='["review-silent-failures","review-impact-completeness",…]' \
  review_target="Review all changes on this branch vs main for task N (title)."
```

Provider defaults to codex — cross-model diversity is the point: a same-family reviewer shares
the author's blind spots. The workflow reads each lens's persona + frontmatter itself, runs them
read-only in parallel, and returns ONE merged, deduplicated report (the merge preserves, never
adjudicates — evaluation stays yours). Run it as a foreground Bash call and wait — never
`run_in_background` (a stopped caller is never woken by background-Bash completion). An empty or
partial report is a COVERAGE GAP, not a clean pass — the report's Coverage section names failed
lenses; re-run those before evaluating.

**Fallback: direct Agent-tool launches** (the section below) — a logged one-off for when pflow
cannot run or the caller must keep working in parallel; state the reason wherever you record the
gate's outcome. **Plan-mode reviews always launch directly too** — the fan-out's contract is
code review; the fan-out default applies to code mode only.

**`review-falsifier` always launches directly** (Agent tool), never through the fan-out — it
EXECUTES the change (real workflow runs, targeted pytest) and needs the access the read-only
fan-out never grants. Code mode only.

## Deploy Agents (direct launch — the fallback path, and the falsifier's only path)

Launch selected agents in capacity-aware parallel batches. Never exceed the runner's available child slots (Codex has four total slots, so an orchestrator can run at most three children at once). Fill the available slots in one parallel launch, wait for that batch, then launch any remainder. Keep prompts minimal — the agents have detailed built-in instructions and know the pflow codebase.

Include the standing noise rule in each prompt: `uv.lock` is not a review target — a lockfile change is a signal of a dependency change, not code to critique.

**Severity is shared across the battery**: **Critical** = demonstrated path to data loss, wrong workflow results, crashes, or broken existing functionality. **Warning** = measurable regression or concrete risk. **Suggestion** = improvement worth considering. A finding that doesn't clear "concrete" is noise — agents are instructed to drop these; you enforce it at evaluation.

### Selecting Specialists

Pick by what the scope actually touches — every selected agent must earn its slot. The tier sets the ceiling; relevance sets the count:

| Agent type | Pick when the scope involves... |
|---|---|
| `review-plan` | **Always slot 1 in plan mode** (plans only) |
| `review-silent-failures` | Empty/null guards, exception handling, ignored returns, dropped data — strong default for most scopes |
| `review-impact-completeness` | Changes to shared patterns with multiple consumers — strong default for most scopes |
| `review-validation-consistency` | Validator or runtime behavior changes (drift between them) |
| `review-feature-interactions` | New features crossing batch, nested workflows, branching, caching, MCP, output |
| `review-agent-ux` | New/changed user-facing output: errors, warnings, CLI results, reports |
| `review-concurrency-safety` | Threads, executors, copy semantics, asyncio, shared mutable state |
| `review-test-fidelity` | Substantial new test coverage, regression tests for bug fixes |
| `review-simplicity` | Multi-phase implementations at Full tier+ (integrated code only, code mode) |
| `review-falsifier` | The spec makes testable behavioral promises and a dev environment can run them — the only lens that EXECUTES (real workflow runs, targeted pytest). Direct launch only, code mode only |

`review-plan` only reviews plans; `review-simplicity` and `review-falsifier` only review integrated code — never deploy them in the wrong mode.

### Prompts

Plan review — point at the actual file:
```
Review the implementation plan for task 135 (Execution Core Compile-Once Redesign).
Plan: .taskmaster/tasks/task_135/implementation/plan.md
```

Code review — the agents know git; they'll figure out the right commands:
```
Review staged changes for task 135 (Execution Core Compile-Once Redesign).
```
or:
```
Review all changes on this branch for task 135 (Execution Core Compile-Once Redesign).
```

## Evaluate Findings

When all agents return, evaluate their findings rigorously. **Do not blindly trust the reviews.** Review agents can be wrong, miss context, or misunderstand the code.

### Step 1: Inventory

Build a complete inventory of all findings across agents. For each finding, extract:
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
