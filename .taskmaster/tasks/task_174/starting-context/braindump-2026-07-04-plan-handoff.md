# Braindump: Task 174 plan → implementation handoff

Written by the planning agent, 2026-07-04. Everything procedural lives in
`.taskmaster/tasks/task_174/implementation/implementation-plan.md` (execution-ready, deep-reviewed, all findings
folded in). This file is ONLY what's in my head and nowhere else. Read order: plan.md first, this
second; spec/brief only if you need rationale.

## Where I Am

Planning is DONE. Zero code written. The plan survived a 6-agent deep-review; all 4 criticals and
every warning were fixed **in the plan text** — so if you find the plan oddly specific somewhere
(currency-guarded `.catch`, structural-ref anchor, `except Exception` backstop, optional `say?`
handler), that specificity IS the fix for a real found bug. Don't simplify those away.

## User's Mental Model (their words)

- "prioritize simplicity of the FINAL code, not how easy it is to get there"
- "whats the right solution that the top 10% of codebases similar to this one would implement?"
- "more simple code that is optimized for AI agents to understand and add features to" — NOT
  over-engineering
- They want the plan executable "in isolation without any ambiguity" — if you hit genuine
  ambiguity the plan doesn't cover, that's a plan defect: stop and surface it, don't guess.
- They never contested a single locked spec decision. All my design calls (reason_kind enum,
  caption-not-latched, clear-dismisses-caption) went through deep-review, not explicit user
  ratification — they're recorded in the plan's tables; treat as settled unless the user reopens.
- Use `pflow-codebase-searcher` subagents, never Explore/general-purpose (they repeated this).

## Key Insights (hard-won, not written elsewhere)

- **The Gemini key for live testing** is at `~/.pflow/settings.json` → `env.GEMINI_API_KEY`
  (present and working — I used it). A probe costs fractions of a cent (~80 output tokens per
  short line). My probe script lived in the session scratchpad and is GONE with my session —
  rebuilding it is ~40 lines; the pinned shapes in plan.md §"Verified externals" are exact copies
  of a real 200 response, trust them.
- **One searcher subagent confidently told me `focus_cmd` doesn't exist. It was wrong** (direct
  grep disproved it in seconds). Calibration: the searchers' quotes were otherwise excellent, but
  when a subagent claim contradicts the plan/brief, grep it yourself before believing either.
- **Line anchors were verified 2026-07-04, but Task 164 is landing in parallel** on
  `feat/resume-failed-node`. If main gets merged into this branch mid-work, re-grep every anchor
  in `server.py` — 164 owns different functions in the same file (`_run_entry`, `/api/runs`).
  The collision guard in the plan (Phase 5.4) is a hard promise the orchestrator made.
- **`inject_settings_env_vars()` no-ops under `PYTEST_CURRENT_TEST`** (llm_config.py:187-189).
  So in CLI tests you can only assert it was *called* (patch it), never test its *effect* through
  the CLI path. Don't burn time wondering why env injection "doesn't work" in a test.
- **`make test` is fast here**: 8384 tests in ~32s. Run it freely; don't ration.
- **The .venv in this worktree is already built** (first `uv run` did it).
- The four criticals came from the silent-failures / feature-interactions / impact lenses — the
  structural review found the plan clean. If you deviate from the plan mid-implementation,
  re-check YOUR deviation against those three lenses specifically (what degrades silently? what
  happens when the point moves / graph rebuilds? which consumers of the interface did I miss?).

## Assumptions & Uncertainties

- **NEEDS VERIFICATION — the 30s synthesize timeout vs long inputs.** I live-tested a ~27-char
  line (instant). `_SAY_MAX_CHARS=1500` ≈ 90-100s of audio; generation is usually faster than
  realtime but I never probed a near-cap input. If a long line times out during your real-browser
  verification, bump the default `timeout` param (it's a keyword arg on `synthesize()`, one-line
  change) — do NOT shrink the cap to fit the timeout.
- **ASSUMPTION**: `wave` stdlib accepts the raw PCM byte length Gemini returns (should be
  frame-aligned for 16-bit mono; my probe's payloads decoded to even byte counts). The totality
  try/except catches it if not.
- **UNCLEAR (deliberately)**: whether the upcoming demo is pre-rendered or live-synth. Gates demo
  prep only, not this build — the plan covers both. Don't build clip caching for it (locked out).
- **MIGHT MATTER — verifying the autoplay-unlock path in a real browser is finicky.** Chrome
  remembers per-origin interaction; once you've clicked anything on localhost:8765 the block may
  never trigger again. Use a fresh incognito window to see the blocked→unlock flow. The
  `screenshot-pflow-web-ui` skill can show the caption/button but CANNOT hear audio — the audible
  check needs the user; ask them at the end, don't claim it verified.

## Unexplored Territory

- UNEXPLORED: voice quality across the 30 voices — only `Kore` was live-tested. Fine for v1
  (config-driven), but if the user asks "which voice is best," nobody has listened yet.
- UNEXPLORED: non-ASCII / emoji in `--say` (caption rendering will be fine; Gemini TTS behavior
  untested). The totality wrapper makes the worst case a caption-only degrade.
- CONSIDER: `frame_cmd` has no `--open` flag today — the plan only wires `--say` into frame's
  single request path. Don't accidentally "add --open to frame for symmetry"; not asked for.

## What I'd Tell Myself

- Implement phases in order; Phase 1 (`tts.py`) is testable standalone in minutes — get it green
  before touching the server. The seams are real: nothing in Phase 2-4 depends on Gemini specifics.
- CONTEXT.md already has the **Say** and **Caption** glossary entries — don't re-add.
- `task-174.md` Status still says "not started" — flip it and create the progress log
  (`create-progress-log` skill) when you start; record deviations there.
- NEVER git add/commit unless the user says so (project rule, and they're strict about it).
- `GraphView.test.tsx` is 1069 lines of heavy mock scaffolding — read its top ~60 lines (mock
  setup) before writing your tests; extending its patterns beats inventing new scaffolding.
  Consider `test-writer-fixer` subagents, one file at a time.
- The plan's "Recorded decisions from the plan-stage deep-review" section exists so the code-mode
  deep-review (Phase 5.6) doesn't re-litigate them. Point the reviewers at it.

## Relevant Files & References

- `.taskmaster/tasks/task_174/implementation/implementation-plan.md` — THE document. Everything else is context.
- `scratchpads/task-174-voice-narration/BRIEF.md` — collision guard vs Task 164, verification posture.
- `.taskmaster/tasks/task_174/starting-context/braindump-2026-06-23-design-discussion.md` — design
  history; mostly subsumed by the spec, but has the "caption must stay unconditional — don't
  'optimize' it later" warning and the demo-format open question.
- Baseline: `make test` = 8384 passed @ add42ffc, 2026-07-04.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
