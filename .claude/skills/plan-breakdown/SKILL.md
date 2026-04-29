---
name: plan-breakdown
description: Analyze an implementation plan and identify optimal handoff breakpoints for splitting work across multiple agents based on size and tacit-knowledge dependency
argument-hint: [plan-path]
allowed-tools: Read, Write, Glob, Grep, Bash(wc:*), Bash(grep:*), Bash(mkdir:*)
---

# Plan Breakdown — Find Optimal Agent Handoff Points

Analyze an implementation plan and recommend where to split it across multiple agents. The goal: identify natural firebreaks where context can be handed off via documentation alone (vs spots where tacit knowledge accumulates and same-agent continuity matters).

## Input

Plan file path (optional): **$ARGUMENTS**

If empty, ask the user which plan to analyze. Common locations: `.taskmaster/tasks/task_*/implementation/*.md`, `docs/plans/*.md`, etc.

## The Core Question

For each pair of adjacent phases: **can a fresh agent pick up phase N+1 from reading files alone, or does phase N build tacit knowledge that doesn't transfer cleanly?**

- **Strong firebreak**: docs are sufficient. Fresh agent reads phase N's output (code, tests, docs) and continues.
- **Weak firebreak**: same agent benefits. Tacit "I just wired this; here's what feels wrong" intuition would be expensive to re-derive.

Strong firebreaks are where you split.

## Method

### 1. Read the plan

Read the plan file in full. Skim associated context (spec, progress logs, prior braindumps) only if needed to understand a phase's scope.

### 2. Size each phase

For every phase / sub-phase, estimate:

| Field | What you're estimating |
|---|---|
| **Production LOC** | New + modified source code lines (exclude tests) |
| **Tests** | Test count + complexity (golden fixtures, integration, parametrized) |
| **Cognitive load** | LOW / MED / HIGH / VERY HIGH — novel decisions, cross-cutting concerns, subtle invariants |
| **Risk** | LOW / MED / HIGH / VERY HIGH — what fails silently if this is wrong |

Use plan-section length as a rough proxy if production LOC isn't explicit. Don't over-engineer the estimate — order-of-magnitude is enough.

### 3. Identify tacit-knowledge dependencies between adjacent phases

For each pair of adjacent phases (N → N+1), classify the dependency:

- **● TIGHT**: same agent strongly preferred. Examples: shared invariant builds incrementally (byte-identity, concurrency safety); fixture vocabulary informs schema design; per-provider quirks easier to keep coherent in one head.
- **○ LOOSE**: docs sufficient. Examples: phase N produces a typed dataclass + tests; phase N+1 consumes it via the public interface.
- **║ FIREBREAK**: structural locking via tests/types/docs makes the dependency irrelevant. Examples: shared helper documented + meta-test-locked; trace format pinned by version constant + consumer gate.

The strongest firebreaks are usually where:
- A shared abstraction is structurally locked (frozen dataclass, immutable type, divergence-injection meta-test).
- The phase produces a typed public interface (a dataclass, a JSON schema, a documented function signature).
- A regression gate is in place (golden fixture, baseline test).

### 4. Identify the highest-risk phase

What's the single most-load-bearing phase? If it goes wrong, what's the silent-failure class? Examples of high-leverage phases:
- Memo/cache hash determinism (silent stale-result class).
- Parser state-machine extension (downstream IR shape).
- Schema migration (data-shape drift).
- Concurrency surface (deadlocks, races).

**The highest-risk phase MUST stay with one agent.** Splitting it across agents is the riskiest move in the whole task. Build the segment boundaries around keeping it intact.

### 5. Propose segment options

Offer 2–3 split options at different agent counts. Typical shapes:

- **N=3 agents** (low-handoff, large segments): each agent owns 4–6 phases. Maximum architectural coherence. Requires tolerance for ~600+ LOC per agent session.
- **N=4 agents** (balanced): each agent owns 3–5 phases. The high-risk phase is its own agent if size warrants. Recommended default.
- **N=5+ agents** (high-handoff, small segments): each agent owns 1–3 phases. Smaller blast radius per agent; more handoff overhead.

For each option, provide a table:

| Agent | Phases | ~LOC | ~Tests | Tacit ownership |
|---|---|---|---|---|

Followed by:
- Which firebreaks each handoff lands on (and why each is sufficient).
- Which handoff is the riskiest, and what mitigates the risk.
- One-sentence recommendation.

### 6. Surface the irreducible tacit knowledge

Some knowledge genuinely doesn't transfer via docs. Enumerate what they are for this task. Examples:
- "Why a particular fixture covers shape X but not Y" — coverage rationale.
- "Which workflow variant exposes a subtle bug" — fixture-selection logic.
- "What feels fragile about the engine path you just touched" — instincts.

For each, propose a mitigation: extra test coverage, a regression baseline, an `xfail` tripwire, a documented invariant in CLAUDE.md.

## Where to write the output

Detect from the plan path:

- **If the plan lives under `.taskmaster/tasks/task_<id>/...`** (task-associated): write to `.taskmaster/tasks/task_<id>/implementation/plan-breakdown.md`. Create the `implementation/` directory if it doesn't exist. If a previous breakdown exists at that path, append a new dated section rather than overwriting.
- **Otherwise** (loose plan, scratchpad work): write to `scratchpads/plan-breakdown-<short-descriptive-name>.md`. Pick the descriptive name from the plan's filename or top-level title.

State the chosen output path to the user before writing.

## Output Format

Keep it scannable:

```markdown
## Phase sizes

[table: phase × LOC × tests × cognitive × risk]

## Tacit-dependency map

[ASCII sketch showing ● / ○ / ║ between adjacent phases, with firebreak strength labeled]

## High-risk phase

[name + why it must stay with one agent]

## Split options

### Option A: N=<count> agents
[table: agent × phases × LOC × tests × tacit ownership]
[rationale paragraph]

### Option B: N=<count> agents
[same shape]

### Option C (if applicable): N=<count> agents
[same shape]

## Recommendation

[one-paragraph recommendation, naming the high-risk phase as the pivot]

## Irreducible tacit knowledge (mitigation strategies)

[bullet list: tacit thing → how to preserve via docs/tests/types]
```

## Rules

- **Don't recommend splitting a high-risk phase across agents.** If the highest-risk phase is small, it might still warrant being its own agent (segment of 1). Splitting it across two agents is the worst outcome.
- **Don't over-engineer the LOC estimate.** Reading the plan section + applying judgment is enough. Don't trace every patch.
- **Don't recommend 6+ agents** unless the task is genuinely huge. Each handoff costs 30+ minutes of context-rebuilding for the receiving agent. Above 5 agents, the handoff overhead exceeds the per-agent savings.
- **Surface uncertainty.** If a firebreak is "weak" (docs probably sufficient but with caveats), say so explicitly. Don't pretend boundaries are clean when they're not.
- **Recommend N=3 or N=4 by default.** N=5 only when a context-window budget forces smaller segments.

## What you DO NOT do

- Don't write the segment briefs (that's a separate skill / task).
- Don't run /code-review or other review skills on the plan.
- Don't propose changes to the plan content. Your job is to identify split points based on the plan as written.
- Don't claim a firebreak is strong without naming what structurally locks it (a frozen type, a meta-test, a documented invariant). Hand-waved "the docs are good" is not a firebreak.
