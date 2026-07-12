---
name: create-plan
description: Author an implementation plan another AI agent can execute in isolation without ambiguity. Verifies assumptions against the codebase, weighs edge cases, and adds a light scope/model/agent nudge per phase. Use when turning an agreed design or task into an executable plan.
argument-hint: [task-id | path | description]
---

# Create Plan — an isolation-implementable implementation plan

Turn an agreed design (or a task) into a plan **another AI agent can implement in isolation, without any ambiguity**. This skill is the *how to author a good plan* doctrine — light by design. AI agents plan naturally; this is a nudge, not a template.

## Input

What to plan — a task id, a plan/spec path, or an in-session design. If empty, ask.

## Before you write — verify, don't assume

Ambiguity is a STOP signal (CLAUDE.md epistemic manifesto): surface it and ask, never plan on a guess.

- Deploy **this codebase's** searchers — `pflow-codebase-searcher`, IN PARALLEL — to resolve assumptions, ambiguity, edge cases, and integration seams before committing to an approach. **Never `Explore` or `general-purpose`.**
- Resolve every decision the implementer would otherwise have to make. A plan that leaves a real fork open isn't isolation-implementable.

## What the plan must be

The plan is the **how**. For a task, the task spec (`task-N.md`) is the **what & why** — the implementing agent always reads it alongside the plan, so **don't restate it**: don't re-describe the goal, the problem, or decisions the spec already settled. Reference the spec and build on it; spend the plan's words on the implementation the spec doesn't cover.

- **Isolation-implementable, zero ambiguity** — a fresh agent reads it (plus the spec, for a task) and builds, with no access to this conversation. Every implementation decision resolved in-text.
- **Edge-case aware** — consider them carefully; state the expected behavior for each.
- **Simplified where it's clean** — take the simplification when the opportunity presents itself cleanly. This is about *simpler code optimized for AI agents to understand and extend* — often the fewest lines that keep correctness — **not** premature abstraction or over-engineering (avoid both).
- **Pressure-tested** — when in doubt: *what's the right solution the top 10% of codebases similar to this one would implement? Have we considered it yet?*

## Scope & routing nudge (light — one note per phase)

Break into phases only where a verification gate, a real seam, or a user checkpoint warrants one — not one phase per thought. For each phase, note:

- **Rough scope** — order-of-magnitude LOC. Judgment is enough; don't trace every line.
- **Which subagent** implements it, and a **model tier** by complexity (mechanical → lower tier, real judgment → higher). Recommend the **tier name** — `Sonnet` / `Opus` / `Fable` — never a concrete model: tier names are runner-agnostic, so one plan works whether it runs on Claude or Codex (the tier → model + effort mapping, including the Codex names, lives in ORCHESTRATION.md § Model routing). Keep **tightly-coupled and highest-risk** work in ONE agent; bundle rather than fragment — never split the highest-risk phase across agents.
- **Checkpoint?** — flag any phase that must pause for the user before the next one starts: user-visible output changes ("Show Before You Code"), a design fork with no clear winner, or anything the spec marks. Whoever runs the plan treats it as a handback.

These per-phase notes are **recommendations**, not constraints — say so in the plan. The *what* (decisions resolved, edge cases, behavior) is binding and must stay unambiguous; scope, tier, agent bundling, and checkpoint placement are advisory, and whoever runs the plan may adjust them on live judgment (re-tier, bundle differently, add or drop a checkpoint).

Tier, agent-assignment, and checkpoint doctrine are governed by `.taskmaster/orchestration/ORCHESTRATION.md` (§ Model routing, § Agent economics, § Checkpoints) — the single source of truth; point at it, don't restate.

## Output

- **Task-associated** (`.taskmaster/tasks/task_<id>/...`): write to `.taskmaster/tasks/task_<id>/implementation/implementation-plan.md` (create `implementation/` if needed).
- **Loose / in-session**: write to `scratchpads/<subject>/implementation-plan.md`.

State the chosen path before writing.

## What NOT to do

- Don't over-engineer the plan itself — no rigid mandatory sections. Match the plan's weight to the work.
- Don't specify the implementation in prose the code should own — the plan says *what and where and why*, precisely enough to remove ambiguity, then trusts the implementer.
