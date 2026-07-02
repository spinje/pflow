# Braindump: Task 125 handoff — Phases 1–2 done, you implement Phases 3–7

> Written 2026-07-02 at the owner-directed review boundary. Read order: this file →
> `../implementation/implementation-plan.md` (the authoritative spec for what you build;
> deep-reviewed by 7 agents, corrected against implementation) →
> `../implementation/progress-log.md` (what happened, deviations, intermediate states).
> The 48 tests in `tests/test_core/test_approval_field.py`,
> `tests/test_runtime/test_approval_gate.py`, `tests/test_runtime/test_gate_trace.py`
> ARE the behavior spec for the substrate you're building on. Everything below is ONLY
> what those files don't say.

## ⚠️ Standing-order changes from the owner (this session, verbatim-ish)

1. **"from now on we should NOT use fable for subagents"** — this SUPERSEDES the
   2026-07-02 decision-session braindump's "in this harness use fable for delegated
   work". Use the normal default models for `pflow-codebase-searcher` / review agents /
   `test-writer-fixer`; do not pass a fable model override.
2. **Phased human review is the cadence now.** The owner's exact instruction pattern:
   "only implement phase 1 and 2 and then stop for review... by review I mean human
   review, so stop and dont continue at all after phase 2 is completed and you are FULLY
   happy with the implementation so far with no loose ends." ASSUMPTION (unconfirmed):
   the same applies to you — propose a stopping point (I'd suggest: Phase 3 complete)
   and get explicit approval before continuing. Do not run Phases 3→7 in one shot
   without asking.
3. Nothing is committed. One-big-PR convention (the whole task = one PR at the end).
   NEVER git add/commit/push without explicit instruction.

## Where I am / where you start

Phases 1–2 are complete, green (8331 unit + 43 e2e, `make check` clean), human review of
them is pending or done by the time you read this. Your work is Phases 3→7 in the plan.
Everything you need consumes three frozen contracts — `GateRequest`/`GateResolution`
(`src/pflow/core/gate.py`, the docstring is the resolver contract), the
`__gate_resolver__`/`__gate_prompt_allowed__` shared-store protocol, and the two gate
exceptions in `core/exceptions.py`. **Nothing remaining requires reopening
`_execute_node`** — if you find yourself editing the engine seams, stop and re-read the
plan; you're probably re-solving something.

## User's mental model (this session's words)

- Escalation inclusion: **"yes escalation, we implemented a retry fix for claude code
  agents on schema fail"** — i.e., the schema-retry self-heal is WHY the
  structured-output marker trigger is trusted. If escalation reliability ever comes up,
  that retry mechanism (`claude_code.py` `schema_retries` + coercion) is the load-bearing
  assumption to check.
- The agent-as-operator concern (their scenario framing): "the human just asks the human
  then resumes... but there is nothing stopping the agent from skipping to ask the human
  and just continue anyway." Accepted resolution: the gate is **deliberate + visible +
  auditable** against the operating agent, not enforcement; `resolved_via` on the gate
  resolution event is the audit hook; real convenience arrives with Tasks 171+176. The
  analysis is recorded in `task-176.md` "The agent-operated run".
- Recurring standard (they restated it when scoping this handoff): simplicity of the
  FINAL code / top-10%-of-similar-codebases / no over-engineering / "optimized for AI
  agents to understand and add features to."
- Interaction style: they sometimes go AFK — two `AskUserQuestion` calls timed out this
  session. Substantive prose messages get answered; prefer presenting
  findings-with-recommendation in text over blocking question dialogs.
- They DENIED a command that deleted files under `~/.pflow` — never touch the user's
  home artifacts without asking.

## Tacit knowledge for Phase 3 specifically

- **Show the prompt UX before wiring it.** The mocks in the plan (§3.3) were shown in
  chat but never explicitly approved as final renderings. The project norm (CLAUDE.md
  "Show Before You Code") + the split-session braindump both demand it. Render the four
  states (approval prompt, escalation prompt, denied line, non-interactive error) and
  get a nod first.
- **`__progress_callback__` wiring is asserted, not traced.** The plan says "mirror
  `__progress_callback__` end-to-end" for installing the resolver. NEEDS VERIFICATION:
  I never read the exact hop from `cli/commands/run.py:309` (callback creation) into the
  runner into the shared store. Trace it before copying the pattern — searcher reports
  said "threaded via shared['__progress_callback__']" but the plumbing site is unread.
- **Exit-code truth**: a `GateNotInteractiveError` run exits 1 today (verified live).
  Only DENIED gets the new exit 3. Click owns exit 2.
- **The denied JSON emitter gap is real, not theoretical** — I confirmed live that the
  denied branch as planned bypasses `output_error` (the only path to the JSON emitter).
  The plan's §3.2 denied-JSON document spec is the fix; don't "simplify" it away.
- **`run.py` swallows unknown flags as workflow params.** `--validate` (no `-only`)
  got parsed as a workflow input named `validate` with a did-you-mean error. When adding
  `--auto-approve`, test the misspelling behavior — an agent typo'ing the flag should
  get something sane.
- **C901 is at the boundary in this codebase.** Three functions tripped 10→11 from ONE
  added branch in Phase 2. `run.py`'s and `runner.py`'s big functions may be similarly
  close. House rule: fold/extract (see `_stash_child_buffer`,
  `_suggest_for_general_error` for the pattern), never `noqa`.
- **Pre-commit ruff gave a false green mid-session** (cached). Always run a fresh
  `make check` at the very end, not just after each edit burst.
- **The trailer channel is belt-and-braces**: `record_gate` sets
  `collector.gate_outcome` AND the engine's gate-exception arm re-stamps it at every
  engine level (root last). Phase 3's runner arms do NOT need to set it — but if you see
  a denied run with a wrong trailer in some exotic nesting, that's where to look.

## Small pending item (10 minutes, do it early)

The plan's Phase 4 bullet "integration test: a CHILD workflow's gate events land in the
run's streamed trace" is NOT yet written — my trace tests cover top-level gates only.
The machinery works (NEW-path children share the run collector), it just lacks a pin.

## Environment gotchas (cost me real time)

- The shell is **zsh**: unquoted `$VAR` does NOT word-split; `python` doesn't exist
  (use `python3` / `uv run python`); `$?` after a pipe is the LAST command's status.
- **NEVER `git stash` to mutation-verify** — untracked files don't stash, and my `pop`
  applied the owner's pre-existing `commit3-wip` stash from another branch (recovered,
  no loss — details in progress log). Mutation-verify with a temporary Edit + revert.
- Two leftover demo traces in the user's real `~/.pflow/debug/`
  (`workflow-trace-*gated-demo*`). Owner declined deletion; leave them unless asked.
- Code-node test fixtures: inputs need type annotations in the code string
  (`i: int\nresult: ...`); engine-direct tests must NOT declare workflow `inputs:`
  (that forces runner-style seeding) — seed `shared` directly.

## Suspicions / judgment calls you may need to defend

- **Escalation can't fire from a dynamic-`next:` routing node** (clean-success actions
  only — `""`/`"default"`/`"end"`). I believe this is RIGHT (mirrors the api-warning
  "node's verdict stands" rule) and matches the harness shape (agent escalates, guard
  routes), but the owner hasn't explicitly blessed it. It's in the progress log's
  "behavioral note" — surface it during the Phase 1–2 review if they haven't seen it.
- **`resolve_gate` hard-fails on a non-`GateResolution` return** ("broken resolver
  installation"). Deliberate: a broken resolver silently approving would be the worst
  failure mode. If Phase 3's resolver tests find this annoying, the strictness is the
  point.
- CONSIDER: the run-start non-interactive warning (plan §3.4) can only see top-level
  gates — documented limitation, but when you write the guide (Phase 6) make sure the
  limitation text survives; reviewers flagged it twice.
- UNEXPLORED: what `pflow ui`'s run form should do about gated workflows pre-176
  (today: launch → fail at gate with the browser-launched non-TTY error). Nobody asked
  for UI-side warnings; don't build them, but the owner may ask.

## What I'd tell myself starting Phase 3

Start with the status ripple (§3.2) — it's pure wiring against an enumerated consumer
map and unlocks the denied CLI tests. Then the resolver + flags (§3.3/3.4) with the
UX-mock checkpoint. MCP param + parity test next (`test_cli_mcp_parity.py` — the
split-session braindump called MCP "the non-TTY case in production"). Web arms last
(tiny; verify with `screenshot-pflow-web-ui`). Then 5 → 6 → 7 are small. Finish with
`/verify` on a real TTY (tests cannot exercise a real prompt) and the deep-review
battery — pair `review-silent-failures` + `review-impact-completeness` on the diff (the
pairing that caught what five other passes missed, twice now).

> **Note to next agent**: Read this document fully before taking any action. When
> ready, confirm you've read and understood by summarizing the key points, then state
> you're ready to proceed.
