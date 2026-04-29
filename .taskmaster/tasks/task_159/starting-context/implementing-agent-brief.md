# Task 159 — Implementing Agent Brief

> Read this document fully before taking any action. State your understanding before writing code.

## Your role

You are the implementing agent for ONE segment of Task 159 (Prompt Caching for pflow workflows). The plan is closed; the architecture is decided; six review rounds are done. Your job: **implement your assigned segment, stop at the firebreak, log thoroughly, surface to the user.**

The user decides at each firebreak whether the same agent continues into the next segment OR a fresh agent picks up. You do NOT auto-continue. Stopping is mandatory.

## Files to read (in this order, in full)

Before writing any code:

1. **`.taskmaster/tasks/task_159/task-159.md`** — the spec (contract). DDs, requirements, output formats, warning catalog.
2. **`.taskmaster/tasks/task_159/implementation/implementation-plan.md`** — the HOW. Read in full once; re-read your specific phase sections at patch time.
   - Pay special attention to: "Architectural backbone — `CacheRenderContext`" near the top, "Shared cache-rendering helpers — module placement" right below it, "Cross-cutting reads before any phase," and "Spike contingencies" near the bottom.
3. **`.taskmaster/tasks/task_159/starting-context/agent-handoff.md`** — operational style, working-with-this-user notes, paid spike protocols, hedged claims.
4. **`.taskmaster/tasks/task_159/starting-context/braindump-2026-04-28-plan-writing-and-review.md`** — tacit knowledge from 6 review rounds. Sections "What §35 doesn't capture," "What I'd tell myself if starting over," and "For the next agent" are highest-value.
5. **`.taskmaster/tasks/task_159/implementation/progress-log.md`** §31–§35 — the planning journey. §35 covers the diminishing-returns analysis and the decision to switch to code-review per phase merge from here.
6. **`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`** — IF prior implementing agents have run, read all their entries. This is where YOU will also log your work.
7. **`CLAUDE.md`** at the project root — pflow's epistemic manifesto and operational guidelines.
8. **The CLAUDE.md files in any directory you'll touch** (`src/pflow/runtime/CLAUDE.md`, `src/pflow/runtime/engine/CLAUDE.md`, `src/pflow/nodes/CLAUDE.md`, `tests/CLAUDE.md`, etc.).

After reading: **state your understanding** (the key architectural decisions, what's been done, what you'll do, where the load-bearing risks are) and **wait for the user's confirmation** before writing code.

## The four agent segments

The 13 sub-phases split into 4 segments at the strongest tacit-knowledge firebreaks (see progress log §35 for the analysis):

| Segment | Sub-phases | ~LOC | ~Tests | Tacit ownership |
|---|---|---|---|---|
| **1: Foundations + Parser/Validator** | B1.1, B1.2, B2.1, B2.2, B2.3 | ~345 | ~69 | Parser state-machine quirks; validator semantic rules |
| **2: Memo-hash gate** | B3.1, B3.2, B3.3, B3.4 | ~355 | ~53 + golden fixture | Byte-identity invariant; sentinel filter; baseline fixture coverage |
| **3: Rendering + Prewarm + Trace** | C1.1, C1.2, C2, C3, D, E | ~450 | ~55 | Per-provider TTL quirks; prewarm 5-tuple destructure; trace 2.1.0 channels |
| **4: Analyzer + Docs** | F1, F2, F3, G | ~520 | ~72 | Catalog dispatch logic; analyzer composition; MCP parity |

**You are Segment N** — the user tells you which N when invoking you. Implement only that segment. Stop at the end.

## Before you start coding

### Agent 1 (Foundations + Parser/Validator)

Three pre-authorized paid spikes (~$0.30 total) must run BEFORE B1.1:
- **Spike 1**: Gemini explicit cache_control verification (Phase C0 entry — informs C2)
- **Spike 2**: OpenAI prompt_cache_key parallel-batch routing (Phase D — informs D.2)
- **Spike 3**: Anthropic per-TTL pricing precision via `litellm.completion_cost` (Phase E entry — informs E.1, only matters if 1h TTL ships)

Pattern (per `agent-handoff.md` "In-phase paid spikes"):
1. Write a minimal Python file under `scratchpads/` that calls `litellm.completion()` directly. Inject API keys via `from pflow.core.settings import SettingsManager; for k, v in (SettingsManager().load().env or {}).items(): if v and k not in os.environ: os.environ[k] = v`.
2. Run each spike. Record outcomes (token counts, response shapes, observed behavior) as a **§36 progress-log entry**.
3. Consult the **Spike contingencies** table at the bottom of `implementation-plan.md` (just before "Deferred items the implementing agent should still verify"). For each spike outcome:
   - If outcome **confirms** encoded plan decision: continue.
   - If outcome **contradicts** encoded plan decision: update the relevant plan section per the table BEFORE B1.1 patches start.
4. Surface §36 entry to user, get confirmation, then begin B1.1.

### Agent 2+ (B3, C+D+E, F+G)

Read `progress-log.md` §36 (spike outcomes) AND the prior implementing agent's `implementation-progress-log.md` entry. Verify any plan updates from spike contradictions landed. If a prior agent surfaced a decision the user hasn't resolved, do NOT proceed — escalate.

## Operating principles

- **TDD where it fits.** B3 is canonical TDD-shaped: the `golden_config_hashes.json` baseline-fixture-before-B3.1-patches gate is a failing test waiting for the implementation. Other surfaces with red→green: F1 catalog (pure data + helper), B2.3 validators (pure functions of IR), B3.3 byte-identity helpers (pure functions). Write the test, watch it fail, implement, watch it pass.
- **Verify-don't-trust applies to your own work, not just reviewer claims.** When the plan says "all consumers use X pattern" or "function Y has signature Z," grep before encoding. Round 5 made this mistake (said `_PROPAGATED_KEYS` had 5 entries; actual is 7). Round 6 caught it. Don't repeat.
- **Read the actual code before writing pseudo-code that depends on its signature.** The plan's "Cross-cutting reads before any phase" section enumerates the relevant files with line numbers. Re-verify before patching — small drifts may have accumulated.
- **The single load-bearing gate** for the whole feature: B3.4's no-`prompt_cache` hash regression test (DD#19). STOP if it fails. Surface to user. Silent stale cache is the #1 risk.
- **`test_plan_drift.py` stays green throughout.** Phases B3, C, D, E touch surfaces it watches. If it goes red, the planner lies about what will execute.
- **`make test` and `make check` pass before every commit.**
- **One commit per sub-phase** OR per logical chunk. Don't ship a B3.1+B3.2+B3.3+B3.4 mega-commit; reviewers can't bisect that.

## Implementation cycle (per sub-phase)

1. **Read the plan section for this sub-phase + its declared cross-cutting reads.**
2. **Re-verify plan claims about line numbers, signatures, consumer counts** via `grep -rn` and `Read`. The plan was written via 6 review rounds against pflow's then-current code; small drifts may have accumulated since.
3. **Write the failing test FIRST** for TDD-shaped surfaces. For others, write tests as you go.
4. **Implement.** Use stdlib before reaching for external patterns (`MappingProxyType`, frozen dataclasses, etc.).
5. **Run `make test` (full) + `make check` (lint, mypy).** Both must pass.
6. **`git add` your changes.**
7. **Run `/code-review` skill** (auto-detects code-review mode against staged changes; 7 agents, no `review-plan`).
8. **Triage findings.** Verify Critical/High via `grep` + `Read` before encoding fixes — don't blindly trust review agents (per the §35 verify-don't-trust discipline).
9. **Apply fixes.** Re-run tests + lint.
10. **Commit.**

## At each firebreak: STOP and log

After your segment's last sub-phase merges and tests are green, you MUST stop. Do NOT auto-continue into the next segment.

### Step 1: Run final segment checks

- `make test` — full suite green.
- `make check` — lint, mypy clean.
- `test_plan_drift.py` — green (verify explicitly even if `make test` covers it).
- For Segment 2 (B3): the no-`prompt_cache` hash regression test must pass against `golden_config_hashes.json`.

### Step 2: Write the implementation-progress-log entry

Append to `.taskmaster/tasks/task_159/implementation/implementation-progress-log.md` under a new section header:

```
## Segment <N> — <Segment name> (YYYY-MM-DD)
```

The entry **must** include the following sections, in order:

#### What I implemented

Concrete summary:
- Sub-phases shipped (B1.1, B1.2, ...).
- Files modified (full paths).
- Tests added (file paths + count).
- Total LOC delta (`git diff --stat <prior-segment-commit>..HEAD`).
- Commit SHAs (one line per commit).

#### Deviations from plan

For each deviation, document:
- **What** changed vs the plan.
- **Why** — which plan claim was wrong, what new info surfaced, what the user decided mid-implementation.
- **Where** in code — file path + line numbers.
- **What follow-up agents need to know.**

If the plan said "function X has signature Y" and you found Z, that's a deviation. If a Round-N fix didn't apply cleanly to actual code, that's a deviation. Don't paper over them — explicit deviations are how the next agent avoids re-deriving why something looks different from the plan.

If you made ZERO deviations, write "No deviations from plan." (and double-check, because zero is unusual at this scale).

#### Tacit knowledge for the next agent

Things that exist only in your head right now. Apply the `/braindump` filter: if it's already in a file, skip it. Capture:
- **Why a particular approach was chosen** when multiple were possible.
- **What you almost tried that didn't work** and why.
- **What feels fragile** — instincts about subsystems that might break next.
- **Subtle invariants** the code holds that aren't explicit in tests.
- **What you learned about pflow's existing code** that would have saved you time at the start.
- **The user's exact words** if they made a key decision mid-implementation.

This is the highest-leverage section. Be specific, not generic. "I noticed the parser's `_flush_yaml_item` runs at H2 transitions but NOT at EOF; if you add a new section type that emits at EOF, you'll need to extend the flush logic" beats "watch out for parser edge cases."

#### Open hedged claims and verifications still pending

Mark explicitly using these prefixes:
- **`ASSUMPTION:`** things you assumed without verifying.
- **`UNCLEAR:`** things you couldn't fully resolve.
- **`NEEDS VERIFICATION:`** things that need checking before next agent ships their work.

#### Open user decisions surfaced

If you encountered a decision point the plan or spec didn't lock, document it here. State your recommendation + tradeoffs. The user makes the call before the next agent continues.

#### What's next (for the next agent)

Concrete handoff:
- Which sub-phase of the next segment to begin.
- Which files to re-read (pointing at specific plan sections + line numbers).
- Which verifications to run BEFORE writing code (e.g., "grep `apply_memo_hit` to confirm the 3rd caller at execution/plan.py:862 still exists").
- Any paid spikes that need to run (Agent 1 only).
- Any plan updates from spike contradictions.

#### Code-review findings worth carrying forward

If `/code-review` flagged issues you addressed AND the lesson generalizes (e.g., "I noticed `MockLLMClient.set_response` callers all use kwargs after the first 3 positional, so adding new kwargs is safe"), capture the lesson here. Don't dump every review finding — only the ones that matter for the next segment.

### Step 3: Surface to user

Post a concise summary message to the user:
- "Segment N done. Wrote entry to `implementation-progress-log.md`."
- "Tests green: <list>. Deviations: <count>. Open user decisions: <count or none>."
- "Next segment is N+1: <segment name>, starting at <first sub-phase>."
- "Awaiting your call: continue as same agent, or hand off to fresh agent?"

Do not continue to the next segment. The user decides.

## Open user decisions you may need to surface DURING your segment

These are tracked in the plan but may resolve mid-implementation:

- **F2 confidence aggregation strictness** (Segment 4 — during F2): plan defaults STRICT per DD#34 line 634. If user prefers permissive, surface before F2 ships.
- **V6 sub-workflow dedup outcome** (Segment 1 — during B2.3): the `xfail`-marked test in B2.3 will fail on first run. User picks the fix shape.
- Any spike outcome that contradicts the plan's encoded decision (Segment 1 — Spike contingencies table).

## What you DO NOT do

- Don't auto-continue into the next segment. Hard stop at the firebreak. User decides.
- Don't silently weaken `xfail` tests when they fail. V6 dedup test is intentional fail-loud — the failure is the trigger for a user decision.
- Don't expand the warning catalog without DD#29 design review. Surface to user.
- Don't add spike scripts to the plan (they're operational; live in `agent-handoff.md` and `scratchpads/`).
- Don't duplicate values across docs (catalog count, threshold numbers, line citations). Cross-reference.
- Don't skip the `golden_config_hashes.json` baseline-fixture step before B3.1 patches. The regression gate is a tautology without it.
- Don't `git push` or open PRs unless the user explicitly asks.

## When you're stuck

- **Verify line numbers with `grep`.** Cite-and-fix-later is fine; cite-without-grep is not.
- **Run a `pflow-codebase-searcher` subagent** for cross-cutting questions ("does X consumer use Y pattern?"). 5 minutes, saves hours of mid-implementation rework.
- **Ask the user.** They prefer 20 turns over a wrong design. Especially when the answer involves an architectural pivot or a new abstraction.
- **Write a small spike script** (`scratchpads/`) to verify LiteLLM behavior on a specific cache scenario. ~$0.10/run. Faster than reading docs for behavior questions.

## End-of-session signal to next agent

At the bottom of your `implementation-progress-log.md` entry:

> **Note to next agent**: Read this entry fully + the prior agents' entries (if any) before taking any action. Confirm your understanding by summarizing the segment's outcomes + open decisions, then state you're ready to proceed.
