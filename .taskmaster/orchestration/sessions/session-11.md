# session-11 — 2026-10-06

## [2026-10-06] main orchestrator — boot + reality diff

- Booted per the role prompt; three sessions carry braindumps (08–10) → boot fork (1b) skipped per its gate. No
  pflow predecessor session live (the listed `main-orch-session-110` is the sibling programme's).
- Reality vs CURRENT-STATE: one drift, folded — main == origin/main == `a2d094b7` (the user committed the
  post-close #656/#714 doc edits; state said `3b342ce9`). MEASURED: tree clean, no worktrees, no open PRs, push
  CI green on `3b342ce9`, `0d935987` and `a2d094b7` (run 37515851025, all 13 jobs success); 147 open issues,
  none newer than #714; `./scripts/tasks --check` clean.
- User focus: *"lets continue where the last session left off, focusing on high value and leverage work"*.
- Task 118 spec read in full at boot — NOT launch-ready as written (Verified, `task-118.md`): the Description
  (line 5) and Open Questions (line 204) still say values bind through declared `inputs:` while the ledger
  (line 105) decided `env:`; line 118 calls the MCP identifier case "the OPEN item above" though line 111
  decides it; the refresh note and Dependencies still serialize behind #678 as an open lane (merged
  `48a9d426`). One in-place rewrite owed before any planner reads it.
- Lane facts verified for the proposal: #690 lives in `execution/resume_preflight.py` (not the engine dir);
  #503 names `runtime/engine/template_resolution.py` — the file Task 118's runtime exemption edits → never
  parallel with 118's build; #686's mechanism is in the same engine file → not lane B.

## [2026-10-06] [RULING] *"yes goahead but we dont need fable for 714, opus is fine"*

- Read as: wave approved — Task 118 (spec rewrite → spec-review battery → prep commit → Fable planner), lanes
  #690, #696+#697 (one lane, two mechanisms, same security_utils neighbourhood), #714 on **Opus** by the user's
  word (overrides the UI/Fable routing for this launch only). #686/#687 fold into Task 120 (my item 3, covered
  by the yes; reversible spec edit). Release: NOT inferred from this yes — asked again when #714 lands.
- #697 scoped to display readers; the trace-file-mode half is out (told the user at proposal time; s04 lead).
- #714 hands back BEFORE merge with screenshots (Opus on a UI surface → my visible review + shown to the user).
- LAUNCHED (three worktrees provisioned sequentially @ `a2d094b7`, verified branch + venv + clean): #690 lane
  (hand-back BEFORE building — ≥2 shapes on shipped refusals; STOP on engine / trace-field / restore change) ·
  #696+#697 lane (two commits, one PR; #697 narrowed by comment to display readers; engine reader untouched) ·
  #714 lane (Opus; hand-back BEFORE merge with before/after shots; #656 explicitly out). All Opus.
- Task 118 spec REWRITTEN in place (decided design throughout; nine "constraints the plan must settle"); Task 120
  widened to own #686 + #687 (fold comments posted on both issues); `./scripts/tasks --check` clean. Uncommitted.
- User, mid-turn: *"you can use more review subagents if you need to"* → spec battery = 8 direct Opus lenses on
  the 118 spec + ADR-0016 (architecture-fit, validation-consistency, feature-interactions, silent-failures,
  impact-completeness, agent-ux, concurrency-safety, review-plan as the context-free planner's read). Ledger:
  `scratchpads/session-11/task-118-spec-battery.md` (lists the five claims I wrote without reading code).

## [2026-10-06] #690 lane HANDED BACK (3/5) — evaluation + options, nothing built → user

- Both halves reproduce on `a2d094b7` (EXECUTED by the lane). Corrections to the issue: the common path (fix
  first, then resume) meets ONE refusal, not two; the issue's "reuse the failure category" alternative is not
  available (category never reaches the trace event; the error-prefix match is wrong in both directions).
- NEW finding (EXECUTED): `--force` waives BOTH checks, so an agent that edited the workflow never sees the
  side-effect warning — a shell step that already fired runs again with no word (`fired` written twice).
- Lane recommends 1-C (no confirmation when the entry step has no `node.start` — it never began; read-only helper
  in `runtime/resume_source.py`, outside its list) + 2-C (keep the whole-workflow check, refusal names the restored
  steps and says when `--force` re-fires a started side-effecting step); 2-A (per-step hashes in the trace meta
  line, trace 2.9.0) is the real narrowing and is task-sized → proposed as a new task. Worktree parked clean.

## [2026-10-06] Task 118 spec battery DONE — 8/8 lenses, verdict "direction holds, not ready to plan from"

- No lens refuted a DECIDED item. Convergent (ledger `scratchpads/session-11/task-118-spec-battery.md`): `env:` is
  strings-only today and auto-parses JSON leaves (7 lenses, EXECUTED: validate ✓ then TypeError); the exemption has
  ≥8 consumers, not 2 (spec AND ADR wrong); `$${` in an exempt body becomes PID + literal; report/failure block lose
  the values; `set -u` cannot be the typo guard (silent inside `$()`/pipes; would amend ADR-0013) → static check.
- OWNED: three of my five unverified claims were wrong or partly wrong (`--only`/resume read outputs, not params;
  report shows a command only when templated; dry-run shows none) and the misspelled-variable premise was only
  true for the brace form. Naming them to the lenses up front is what got them checked.
- To the user (C): scope split · non-string `env:` rule · dangerous-pattern check · MCP shadowing rule.

## [2026-10-06] [RULING] *"go ahead with all your recommendations"*

- Read as (the numbered recommendations in my last two messages; release NOT included — never inferred):
  **118 split in three** — 118 keeps shell/code bodies + `env:` binding + corpus conversion; NEW task for MCP
  code params + `|json`; NEW task for linting. **Non-string `env:` rule** = the text `${x}` produces inside any
  string today (byte-for-byte preservation; Task 120 inherits). **Dangerous-pattern check** stays on the body
  text; value-driven cases documented as no longer caught. **MCP rule tightened** (changes the 2026-10-05 ruling):
  a bare `${…}` in a code-bearing MCP param is always the embedded language; pflow values enter only as
  `${x|json}`. **#690** = option 1 (lane builds the began-check + the clearer refusal; widened by one read-only
  helper in `runtime/resume_source.py`, my 2/5) + NEW task for per-step hashes (trace 2.9.0); #690 stays open
  as that task's issue.
- Mine (1–2/5, stated to the user, no objection): static validation check instead of `set -u`; `inputs:`
  unchanged on shell; one code-body predicate for all walks; failure block + report show body + bound values;
  retitle 118, rename the ADR file, note on Task 101.
- #690 lane RESUMED with the ruling (PR is `Refs #690`, not closing; fail-closed precondition: every path where
  a step can have fired writes a top-level `node.start` first — sub-workflow host / retried / loop iteration ≥2 /
  parallel batch EXECUTED before shipping, else STOP).
- #714 lane HANDED BACK (2/5) → resolved here: **A** — the header truncation rule on the shared
  `.node-callout-subtitle` joins the PR (a long snake_case id pushes the ✕ out of the panel — same class as the
  hidden buttons); preconditions: grep every consumer, full id readable without hover, (c2) a permanent case.
  Accepted its own calls: sticky footer (no shared-shell restructure); escalation option cards keep scrolling.
  Lane observed two Task-181 frictions first-hand (JS `${…}` read as a template; boolean arrives as `True`).
- Specs written from the ledger (all uncommitted): 118 rewritten + retitled; ADR-0016 rewritten and renamed
  `0016-118-code-bodies-untemplated-env-binding.md` (nothing referenced the old filename — grep); NEW Task 180
  (resume per-step identity, `next`, governed by #690), Task 181 (MCP code params + `|json`, `next`, after 118),
  Task 182 (linting, `then`); Task 101 note; `./scripts/tasks --check` clean (172 files).
- Context-free re-read LAUNCHED before the prep commit (ADR-FORMAT's rule for a conversation-born ADR): a fresh
  planner's read of 118 (executes the non-string rule) + an adversarial read of ADR-0016 / 180 / 181 / 182.

## [2026-10-06] Task 118 planner LAUNCHED (Fable, plan-only) — prep commit `82341e2b` pushed

- Two context-free re-reads folded first (ADR-FORMAT rule): the non-string rule now names
  `core/templates.to_string` (my "compact JSON" gloss was WRONG — executed `{"a": 1, "b": [1, 2]}`); the dict/list
  block RETIRES (moving it onto `env:` would forbid what the ruling allows); the leftover-reference rule lists its
  five undecidable cases for the planner; Task 181 gains "`$${` stays `$${` on code params" (the parser would
  collapse it) and the allowlist-growth hazard; Task 180: the engine already has a per-node `config_hash`, just
  not in the trace.
- Prep commit (DECISIONS #5, covered by the launch approval): 118, 120, 101, 181, 182 specs + ADR-0016 rename/rewrite.
  NOT in it: Task 180's spec, CURRENT-STATE, this file — they wait for the user's word.
- Worktree `feat/task-118-shell-env-binding` @ `82341e2b`, ledger copied in (verified). Packet: diagnostics
  BEFORE/AFTER + hard cases (a)–(e) as ONE embedded user checkpoint file; phasing proposal (A/B/C) at hand-back;
  the two tooling workflows merge in a quiet moment; Windows claims flagged UNVERIFIED.
- For the user: after 118 ships, old-form shell workflows in their saved library (`~/.pflow/workflows/`) fail
  validation with the fix shown — converting them is their call.

## [2026-10-06] #690 lane STOPPED on its fail-closed precondition (as designed) → resolved here (2/5): **A**

- EXECUTED by the lane: a BATCHED `type: workflow` host writes no top-level `node.start` (`engine.py:1368` skips
  `begin_node` for every `WorkflowExecutor`; batch items never `descend`) → the began-check would have let a host
  whose child already fired resume with no confirmation (`fired a` written twice). Less safe than `a2d094b7`.
- Ruled A: never trust the never-began proof for a `workflow`-type entry (keeps today's behaviour there; strictly
  conservative). FINAL SHAPE = every step that begins writes `node.start` (engine + trace content) → written into
  **Task 180's spec** ("In scope by ruling"), whose closing step deletes A's guard. A is NOT part of the final shape.
- Lane's gate also found + fixed a Critical (an earlier pre-exec failure hiding a later interrupted attempt).
- TO FILE after the lane merges: web resume panel drops the stale refusal's diagnostics and "Resume anyway" sends
  `force: true` (`web/src/components/resumeAnswer.tsx:67-69`) — browser users never see the re-fire warning.

## [2026-10-06] MERGED #696 + #697 — PR #715 → `b2cd92e3` (closes both — verified `closingIssuesReferences`)

- Lane: `settings show` masks every `env` value (same call as `list-env`; name-based helper deleted); `pflow report`
  redacts through `security_utils.redact_sensitive` (the web UI's redactor moved to a shared home, now used by
  both). Third reader closed in passing: a batch-item file-name fallback could pick a token. Trace untouched;
  resume/`--only` still restore raw (EXECUTED). Gate: 6 codex lenses (0 Critical/Warning) + falsifier (all held).
- **Lane 2/5 rider, re-rated → FLAG FOR THE USER:** the report now also redacts sensitive-named keys in node
  OUTPUT (parity with the UI panel), so the name rule's false positives (`token_count`) read `<REDACTED>` in
  reports too. Reasonable (one rule, two readers); user-visible.
- Teardown: `worktree rm` refused on a hung `ugrep … | wc -l` (44 min, reading stdin) the lane left behind — four
  PIDs, cwd MEASURED inside that worktree → killed by PID, then removed; main ff'd to `b2cd92e3`.
- Sent the 118 planner the MEASURED file delta + the `redact_sensitive` pointer (its report requirement builds on it).
- Filed (verified by me first): **#716** Cookie/Set-Cookie not in the sensitive-name rule (EXECUTED) · **#717** MCP
  agent instructions say `workflow_execute` persists no trace (read: it returns `trace_path`).
  Not filed: sensitive batch alias in report labels (needs the alias in the trace; PR body is the record).

## [2026-10-06] [GRANT] capacity — *"yes but I think opus for 181 and 120 is reasonable here, we can launch more planners this session, we have alot of opus limits to burn"*

- Read as a per-launch routing exception (DECISIONS #24 row NOT rewritten — no standing change was stated):
  **Opus planners** for Tasks 181, 120, 182 and the #656 task; **Fable** stays for 118 (running) and 180. More
  planners may launch THIS session (widens "no new starts" for planners only); builds still next session.
- My sequencing (collision analysis, stated to the user): 180 after #690 merges (disjoint surface: resume/trace/
  `engine.py:1368`); the #656 task after #714 merges; 181 and 120 only once 118's PLAN is committed — both edit
  `template_resolution.py` and 181 reuses the classification 118 introduces, so planning them now would be
  planning against a contract that does not exist yet. 182 held (lowest value; a plan parked in `then` rots).
- Wrote Task 183's spec (the #656 work as a small task: iteration "of N" on every pause surface + "Approve all
  remaining" in the web UI; engine contact via `GateRequest`; governed by #656; launches after #714 merges).
- LAUNCHED an Opus investigation for Task 120's spec rewrite (read-only + execution): classify the stale spec,
  map every hop a declared input crosses, reproduce the three breaks and hunt for a fourth, re-derive the
  simplest final design, name the user-level decisions. I rewrite the spec from it; planner after 118's plan lands.

## [2026-10-06] [GRANT] *"run as far as you can without me tonight, end to end, you have the grant. also im switching you to opus right now as the main orchestrator model"*

Written BEFORE the model swap (main orchestrator Fable → Opus): every pending item with its settled handling, so
the post-swap orchestrator executes rulings rather than re-deriving them. Post-swap posture: resolve ≤3/5 ONLY
where the spec / plan / ADR / a ruling below gives the answer; anything borderline PARKS with options.

**State at the grant.** main == origin/main == `b2cd92e3`. Uncommitted on main: CURRENT-STATE (boot fold), this
file, Task 180 spec, Task 183 spec. Worktrees: `feat/task-118-shell-env-binding` (Fable planner, plan-only, live) ·
`fix/issue-690-fix-then-resume` (Opus lane, live, building option A) · `fix/issue-714-gate-panel-actions` (Opus
lane, live, stops BEFORE merge). Also live: an Opus read-only investigation for Task 120's spec rewrite.

**IN scope tonight (in order of trigger):**
1. #690 lane → it merges itself after CI. Then: verify `closingIssuesReferences` is EMPTY for #690 (PR is
   `Refs`), teardown, ff main, file the web-resume-panel issue (`web/src/components/resumeAnswer.tsx:67-80`: the
   stale refusal keeps only `hash_known`; "Resume anyway" sends `force: true` — READ by me today).
2. #714 lane hand-back (screenshots) → the user checkpoint COLLAPSES to my visible review: open every AFTER shot +
   the measurement JSON; pass = action row and ✕ inside the viewport in all cases incl. (c2), preview still
   scrolls. Pass → resume the lane to merge. COPY the shots to `scratchpads/session-11/issue-714/` BEFORE teardown
   and show them to the user at next contact (s10 lesson). Anything that looks off → PARK un-merged.
3. Task 180 planner (**Fable**, plan-only) once #690 has merged: prep-commit the Task 180 spec (DECISIONS #5 —
   covered by the user's "launch more planners"), provision, launch. Packet: read the #690 lane's PR first;
   engine + trace format → plan-mode deep-review mandatory; open questions that are USER decisions (which edits
   refuse) come back as a checkpoint → PARK those, do not rule them.
4. Task 183 planner (**Opus**) once #714 has merged: first ONE context-free `review-architecture-fit` read of the
   183 spec (new agent-facing field on the pause payload), fold, prep-commit, provision, launch. UI phase is
   design-bearing → its tier is the user's per-launch call (they said Opus for #714 only): plan states the tier,
   I do not launch a 183 BUILD tonight.
5. Task 118 planner hand-back → GROUND-TRUTH (`git log`/`git status` in the worktree). Its diagnostics BEFORE/AFTER
   file is an embedded user checkpoint → collapses to my visible review against the ledger's agent-ux findings
   (`scratchpads/session-11/task-118-spec-battery.md`, UX1–UX4, UX-W1..W3) and the spec's Requirements; record the
   review on the BRANCH (never main's copy of the spec — s10 n=1). Hard cases (a)–(e): accept the planner's rule
   where the spec's constraints decide it; a case that changes what existing workflows mean beyond the ledger →
   PARK. Before the planner is released: ask it ONE thing — what it dismissed on documentation alone and what it
   would tell the builder — and have it write that into the task's progress log.
6. Then launch the Task 118 **build** (Opus `task-orchestrator`, implement-from-plan, same worktree). Phases,
   gates, PR are its. Relay MEASURED file deltas when main moves. The two tooling workflows merge only when no
   lane/planner is running the fan-out.
7. Tasks 181 and 120 planners (**Opus**) once 118's plan is committed — packet: 118's PLAN is the contract-to-be,
   every dependency on it marked "re-verify at build". 120 ONLY after I rewrite its spec from the investigation
   AND a context-free read; any user-level decision the investigation names → PARK 120's planner with options.
8. Close ritual when everything launched has drained or parked (`/close-orchestrator-session`) — everything but
   the commit.

**OUT / PARKS (no grant covers these):**
- **Release** — never under a grant. **Task 118's MERGE is held PR-ready until the user rules on v0.16.0** (my own
  recommendation was "release before 118 merges"; merging it tonight would foreclose that) — unless the user
  answers the question I am asking now.
- Builds for 180 / 181 / 120 / 183: not tonight (engine seam serializes behind 118's unmerged PR; 183 also needs
  the user's eye on new UI before merge).
- Any 4–5/5 fork; anything contradicting DECISIONS / an ADR / a spec ledger; force-push, branch or data deletion
  beyond standard teardown; main commits other than the prep commits named above.
- Model routing is unchanged by the swap: explicit `model` on every launch — Fable for the 180 planner, Opus for
  everything else named above. If a Fable agent dies on a tier cap: never resume it; a replacement at Opus into
  the SAME worktree, resuming from spec + whatever is committed (ORCHESTRATION "Limit recovery").

### Pre-swap thinking (Fable) — frames for the judgment calls Opus will meet tonight. Hypotheses, not rulings.

**118 diagnostics checkpoint — how to judge it.** Pass when every message (1) names the step and the exact
fix in one step (`env:` for shell, `inputs:` for code), (2) is produced by a STATIC check so `--validate-only`
and the run agree, (3) has a BEFORE captured by execution. For the leftover-reference rule and hard cases
(a)–(e) my expected answer is ONE principle: *a `${…}` in a body is flagged only when its root is a name in
pflow scope for that step (input, step id, `inputs:`/carry key, batch alias, `__index__`/`__iteration__`);
everything else belongs to the shell.* That resolves (a) pflow wins → the error says rename; (b) same; (c) an
undeclared name is the shell's (silent, as today for `$ENDPONT`); (d) JS inside a body is fine unless its root
is in scope → rename; (e) same. Its known cost: a leftover with a TYPO'D root (`${fech.response}`) is not
flagged and falls to sh ("bad substitution", silent inside `$(…)`). If the planner proposes "dotted is always an
error" instead, (d) has no way to be written while `$${` is also an error → that pair is a contradiction to hand
BACK to the planner, not to accept. A rule that needs a shell parser, or that changes what an unconverted
workflow means without an error, PARKS.
**118 phasing and the release hold.** If the plan ships phase A (`env:` accepts non-strings, no auto-parse of
`env:` leaves, binding failures before spawn) as its own PR, A MAY merge tonight — it turns a crash into working
behaviour and breaks nothing. The hold applies to the breaking part (exemption + conversion). Launch the build
only if: plan-mode deep-review ran and its Criticals are folded (ask, do not read the plan), no user decision is
open in the hand-back, and the plan names the phase that first exercises `tests-windows`.
**Task 120 — frame for the rewrite (test it against the investigation, do not write it from this).** Likely
final shape: the declared type is enforced ONCE where the value enters (CLI / stdin / MCP / UI form / sub-workflow
input), the value is typed from then on, and nothing downstream re-infers it. The crux is #686: template
resolution auto-parses JSON-looking strings and cannot tell "an upstream step printed JSON" (the guide PROMISES
auto-parse there) from "a declared-`string` input holds JSON text" (must stay a string). Whatever carries the
declared type to that site is the design. USER-level by nature (PARK, with options): any change to what an
existing workflow receives (a string input that today arrives parsed), and how strict boolean/number forms are
(`0`, `no`, `1e3`, `007`). Planner-level: where the check lives, the error format (shared with Task 112 via
`TypeSpec.accepts` if it exists — the investigation says). 118's `env:` rule (`to_string`, no auto-parse of leaves)
is the same question from the shell side; the two must be one mechanism or a stated two.
**Load.** At most TWO planners beside the 118 build at any time (each runs its own plan-mode lens battery).
Order when triggers coincide: 180 → 181 → 120 → 183.
**Residue for the close braindump (write it out there, do not lose it to a context summary):**
- The user this session: approved numbered bundles in one line twice (*"go ahead with all your
  recommendations"*); offered capacity unprompted (*"you can use more review subagents if you need to"*, *"we
  have alot of opus limits to burn"*); asked for the drain list themselves (*"what do you suggest we finish"*,
  naming my context size) and then WIDENED instead of narrowing — read their capacity remarks as "use it".
- OWNED: I wrote "compact JSON" into a DECIDED ledger line and the ADR from a lens summary; the fresh reader
  executed it and it was wrong (`{"a": 1, "b": [1, 2]}`). Same family as RECURRENCE's "mechanism from a summary"
  (now a 4th instance); also "SC2154 catches it" in Task 182, caught by a reviewer. The fix that worked: name the
  FUNCTION (`to_string`), not a hand-written table of its outputs.
- Worked: telling the lenses WHICH of my claims were unverified (3 of 5 refuted); a second context-free read
  AFTER the rewrite (found a requirement contradicting a ruling); the fail-closed precondition on #690 (the lane
  stopped on a real unsafe path twice).
- Dead end: `./scripts/worktree rm` refused on a hung `grep | wc` a finished lane left behind (cwd in the tree).

## [2026-10-06] Swapped to Opus (user `/model`). Questions 1 (118 merge before release) and 2 (180 planner tier) UNANSWERED → defaults: 118's breaking part held PR-ready; 180 planner = Fable.

- Task 120 investigation DONE (Opus, EXECUTED, 13 breaks incl. the three known): declared type read at ONE
  lenient site (`prepare_inputs`); CLI `infer_type` runs before declarations are known (#687's cause); resolver
  re-infers and cannot tell a declared input from upstream output; sub-workflow supplied inputs never coerced;
  `TypeSpec.accepts` exists with zero callers. No in-tree workflow relies on a declared input arriving parsed.
- Task 120 spec REWRITTEN (uncommitted) with seven USER decisions (a)–(g), each with my recommendation →
  **120 planner PARKED per the grant** (user-level decisions named). Not a 3/5 I may resolve: (a)–(c) change what
  existing invocations receive or reject.
- Relayed to the 118 planner as a CLAIM: express the `env:` no-parse rule as a per-leaf predicate the resolver
  consults (Task 120 extends it), not a `key == "env"` branch.

## [2026-10-06] #714 lane hand-back (PR #718, CI green) → my visible review PASSED (grant: checkpoint collapses)

- Opened after-(b) narrow, (c2) narrow, (d) default: answer row visible as a deliberate footer, ✕ reachable,
  header id ellipsized, preview/options scroll. Measurement JSON (12 after cases): only `false`s are
  `bodyHorizontalOverflow` (good) and `fullIdReadableInEyebrow` on the 2 scrolled shots (expected). Evidence COPIED
  to `scratchpads/session-11/issue-714/` (shots, measure, falsifier fixtures) — SHOW THE USER at next contact.
- Lane's falsifier found + lane fixed W1 (long inline error made the pinned footer cover the step). Lane resumed
  to merge.
- Filed **#720** (gate strings ≥1 KB reach `/api/gate` as unresolved `$pflow_blob` → viewer crash / unreadable
  approval command; pre-existing; read `run_tailer.read_run_trailer` myself). Not filed (PR body records them):
  long unbroken option label overflows; panel above the screen at 557×400 (canvas-space; not worse than main).
- Falsifier left 9 paused runs + 1 failed run under the user's real `~/.pflow` (ids in the lane hand-back).
  Harmless; list for tidying at close.
- MERGED #714 — PR #718 → `eecbcd5d` (closes #714 only — verified; #656 OPEN). Teardown clean; main ff'd.
- Task 183: context-free `review-architecture-fit` read of its spec LAUNCHED (grant item 4) before prep-commit.
- Task 183 spec read (architecture-fit, Opus) → folded: "of M" premise REFUTED (no loop is fixed-count — every
  loop has `while:`/`until:` checked before the cap) → always "of up to M", omit when the cap is the engine's
  safety limit, button names no count; cap not available at iteration 1's gate today (lazy `loop_caps`); it IS a
  trace-format change (`gate_request` in trailer + pause line; 2.8.0 precedent); four renderers, not one; resume
  list JSON added; escalation gates excluded from the bulk action. FLAG FOR USER: the "of M" wording change
  (accuracy, keeps their intent). Prep commit `706b292c` (183 spec only). Worktree provisioned + verified.
- LAUNCHED Task 183 planner (**Opus** by the capacity grant; plan-only; UI phase tier = Fable pending the user's
  per-launch word; engine + trace → plan-mode deep-review mandatory; serializes with Task 180's trace bump).

## [2026-10-06/07] Task 118 PLAN DONE (Fable planner, 595k by metadata) — `1024a83e` + rulings `beeb23b9` (ground-truthed: log + clean tree)

- Plan-mode deep-review: 9 lenses, 5 Criticals verified + folded (biggest: a failing child's `env` rode the
  child-failure bundle into unredacted batch error records → one display-safe copy at the source). Corpus measured
  by a kept script: 428 bodies / 128 files. Seam note adopted (`parses_leaves` / `binds_as_text` predicate).
- CP-1 (diagnostics, 9 rulings) — COLLAPSED to my visible review under the grant; read the whole file
  (`implementation/diagnostics-checkpoint.md`): all 9 accepted as recommended. Its rule = my pre-swap frame
  (scope-based) + a WARNING for unknown-root pflow-only shapes, which resolves the (d)/`$${` contradiction. One
  correction sent: "compact JSON" in §6 (same error I made this morning). SHOW THE USER the checkpoint file.
- PR shape RULED: two PRs. Part 1 (P0+PA: `env:` working channel + the two tooling workflows in a form that runs
  identically today) non-breaking → may merge tonight in a quiet moment. Part 2 (the flip + corpus) PR-ready, NOT
  merged until the user rules on the release. CONTEXT.md nouns deferred to Part 2's merge.
- Planner's spec-error reports applied to main: Task 181 citation, Task 112 Pass 7 row → commit `ebf7cab2` (also the
  181 prep commit).
- LAUNCHED Task 181 planner (**Opus**, plan-only, reads 118's plan from the branch as contract-to-be; STOP if 118's
  classification can't serve it without reshaping).
- Asked the 118 planner the release question (dismissed-on-docs + builder notes into the log). Build launch waits
  for that commit (one agent per worktree).
- 118 planner RELEASED after builder notes (`7012eb22`; 600k by metadata — resume only for "what did the plan mean").
- LAUNCHED Task 118 **Part 1** build (Opus task-orchestrator, implement-from-plan): P0 + PA + the two tooling
  workflows; hands back at create-pr — I merge (shared tooling, quiet moment). Part 2 not started; no task-review
  for Part 1 (plan §4.0 exception). Measured main delta sent (6 files, none on its surface).

## [2026-10-07] MERGED #690 lane — PR #719 → `2464e43c` (`Refs #690`; `closingIssuesReferences` EMPTY — verified; #690 OPEN for Task 180)

- Lane merged itself after CI. PR body MEASURED `begin_node` has one skip (`engine.py:1368`); falsifier ran THREE
  rounds (2 more Criticals found + fixed: on-error back edge re-fire; a `restored` re-record read as never-started);
  round 3 held across 15 executed attacks. Batched sub-workflow host protected by the carve-out until Task 180.
- Teardown: `worktree rm` refused on a hung `eza -t` (the shell's `ls` alias) a finished lane left (cwd in its
  scratchpad, 1h39m) → killed by PID, removed. SECOND instance today (#696 lane: hung `ugrep | wc`).
- Filed the web resume-panel issue (refusal text dropped; "Resume anyway" answered blind).
- Task 180 planner: TRIGGER MET (#690 merged) but HELD on load — two planners (181, 183) already beside the 118
  build (my pre-swap cap). Launches when either planner hands back.

## [2026-10-07] Task 183 PLAN DONE (Opus planner, ~354k by metadata) — `d01b9b61` on its branch (ground-truthed)

- 7-lens plan-mode review, 0 Critical; two lens findings changed the design (a `??` cap template made "up to 2"
  while the engine ran 5 → "unknown" decided from the template's references; back edge → "iteration 4 of up to 3"
  → helper drops the clause past the cap). Gate computes the cap itself from the step's loop config + store (no
  new engine state); `max_iterations` = `null` (not absent) for non-loop/uncapped/unknown; `/api/resume` refuses
  unknown body fields. All within planner authority (2/5) — accepted.
- PARKED FOR THE USER: **R1** (add an "approve all remaining" hint line to CLI/MCP loop-gate pause output;
  default not built; drafted in `implementation/pause-surfaces-before-after.md`) · **R2** (show the button when
  the cap is unknown; default shown with a tooltip) · **P4 tier** (Fable design-bearing vs Opus) · the
  show-before-code file itself. ADR-0010/0009 one-line amendments: written by P3 at build (in-task).
- Task 180 spec got the trace-version collision note; prep commit `2a3f73ef`; worktree provisioned + verified.
- LAUNCHED Task 180 planner (**Fable**, plan-only): starts from PR #719; deletes its carve-out; which edits
  refuse = a USER checkpoint file, not decided by the planner.

## [2026-10-07] Task 181 PLAN DONE (Opus planner, ~414k own; 7 lenses ~1.2M) — `924b7d94` on its branch (ground-truthed)

- Design: `${x|json}` suffix in the one parser + `scan.ts`; Task 118's `param_mode` gains `"embedded"` for four JS
  params matched by tool-name suffix; one `embedded_code` policy view over the single parse; `|json` elsewhere is a
  validation error; web reads a per-param `mode` from Python and closes #683. 0 design flaws; message fixes folded.
- PARKED FOR THE USER (no build tonight — gated on 118 PART 2 merging): CP-1 rulings R1–R6 + **R8 (nouns "Embedded
  code", "JSON insert" — a wire-contract name, `RFParam.mode`)** in
  `implementation/diagnostics-checkpoint.md` on its branch; ADR-0016 amendment (why `|json` is an exact word, not a
  filter position; cite ADR-0015:28) — mine to write when 181 builds. Merge-time user-visible changes with no
  diagnostic: JS written with `$${` now sends the `$`; a JSON insert of stdout arrives as a JS string.
- **For 118 PART 2's packet (next session):** two requests from 181 — a named helper for the per-step scope rule
  (181 reuses only that, not `body_references`), and an "add to used" hook in the unused-input pass.
- Filed the MCP value-blocklist issue (read `validation.py:51-64` + its three call sites myself). Not filed (record
  only): MCP nodes miss the `mcp` colour/icon (inferred, unverified); `pflow mcp describe` splits hyphenated server
  names (unverified); `_CODE_BLOCK_TAG_TO_PARAM` dead code (`markdown_parser.py:104-120`, unverified).

## [2026-10-07] Task 180 PLAN DONE (Fable planner, ~349k by metadata) — `0f813b2b` on its branch (ground-truthed)

- Design: mint `step_identity(ir)` (NOT the engine `config_hash` — per-iteration variance, omits loop/edges/
  approval); one meta key `{start, steps: {id: {hash, next}}}`; trace 2.9.0 (collides with 183 — second takes
  2.10.0); old traces keep the whole-hash compare by key absence; `begin_node` for every node.
- **Delta from my ruling, ACCEPTED (2/5, strictly safer):** #719's `workflow` carve-out is NARROWED to traces without
  `step_identity`, not deleted — deleting it unconditionally would skip the confirmation for a failed batched host
  on every 2.3–2.8 trace (verified by the planner at `resume_source.py:393`). Ruling intent met.
- PARKED FOR THE USER: `implementation/show-before-code.md` on its branch — 16 scenarios; rulings: (1) inserted
  upstream step / reroute / renamed-removed steps refuse; (2) edited input default passes + guide sentence;
  (3) **a paused-approval step edited after approval REFUSES** — a consent hole the whole-hash gate was closing by
  accident (`--approve yes` matches by step name only, `gate_prompt.py:84-89`); (4) `--force` stays one flag.
  P1 (engine `node.start`) can build before the ruling; no build tonight.
- Corrected Task 179's task-review line ("a sub-workflow host emits no node.start" → BATCHED host only).
- To file at close (planner's follow-ups): child-workflow file edits invisible to both hashes; optional resume
  input advisory. CONTEXT.md **Resume** + ADR-0010 amendment texts in plan §5 P4 — written when 180 builds.

## [2026-10-07] Task 118 Part 1 — PR #723, CP-2 (Windows) → resolved here (2/5): **(a)** document + pin

- `tests-windows (core-cli-nodes)` — the job that executes the change — answered D8: native Windows path in `env:`
  readable as-is; `{Path: X}` → one PATH; quotes/`$`/backticks byte-identical; Windows binds 200 KB, Linux refuses
  >128 KiB per value (now in the guide). ONE red row: `{Temp: …}` beside inherited `TEMP` → Git Bash upper-cases
  and POSIX-converts the value; a non-special name (`PflowD8`) keeps spelling (probe pushed). Not the "translate
  values" fork → (a) guide line stating only OBSERVED names (TEMP, PATH) + per-platform pin. Lane resumed.
- Gate: 8 lenses through the CONVERTED fan-out with a `cwd` override (the spec's real-run requirement) + falsifier
  (no Critical); `make test-all-local` 10536 passed on the merged result.
- Follow-ups: file at merge (surrogate value masked by the trace writer's codec error; encode failure via `stdin:`
  → "exit code -2"); fold into Task 120's spec (numeric YAML literals in `env:` rewritten — `1.10`→`1.1`, `0755`→`493`;
  CLI `007`→`7` already break 6).
- Merge-time note for the user: a paused/failed run of either tooling workflow started before the merge needs
  `pflow resume --force` (the `resolve-cwd` step changed).

## [2026-10-07] MERGED Task 118 PART 1 — PR #723 → `012f358c` (quiet moment: no live agents; checks JSON-verified incl. all 3 Windows jobs; `--match-head-commit eedbf587`; closes NOTHING — #59/#621 OPEN for Part 2)

- CP-2 applied (guide states only observed names TEMP/PATH; per-platform pin). Worktree torn down; main ff'd.
- `env:` is now a working channel: non-strings bind via `to_string`, no leaf auto-parse, binding errors before spawn
  (never swallowed by `ignore_errors`); both tooling workflows converted (identical across 9 cwd cases; a `$`/`"` path
  now works). Paused/failed runs of either tooling workflow from before the merge need `pflow resume --force`.
- Filed the trace-writer surrogate-masking issue (W1 + stdin exit -2; lines read by me). Task 120 got the YAML-literal
  break (12). Task 118 spec Status stays `in progress` (Part 2 owns task-review + done).

## [2026-10-07] Close (unattended, end of the grant) — small promotions APPLIED (≤2, sentence-sized)

- `context/adr/ADR-FORMAT.md` "Review before commit": the reviewer re-derives every mechanism from the cited code;
  name the function, not a list of its outputs (RECURRENCE n=4).
- `.claude/agents/lane-implementer.md` Ship step 4: kill, by PID, any shell left alive in the tree before stopping
  (RECURRENCE n=2, both this session); mirrors synced.
- No DECISIONS row: the capacity grant was per-launch, not a standing routing change.

## Braindump

_Tacit residue only — rulings, ships and parked checkpoints live above and in CURRENT-STATE._

**The user this session — their words, and what they did with them**

- Approved numbered bundles in one line, twice: *"go ahead with all your recommendations"*. Each bundle had a
  recommendation per item and a stated "mine vs yours" split — that split is what made a one-line yes safe.
- Offered capacity unprompted, twice: *"you can use more review subagents if you need to"* and *"we have alot of
  opus limits to burn"* — then, when I proposed a drain list because my context was at ~400k, they WIDENED
  (*"run as far as you can without me tonight, end to end"*) instead of narrowing. Read their capacity remarks as
  "use it"; read a drain question from them as "what can we still fit", not "stop".
- *"im considering if we could run any of these planners on opus 5.5"* → they picked tasks themselves (181, 120)
  against my split. They weigh capacity against risk per task, not by a blanket rule; a per-task table with a
  one-line reason each is what they answered.
- *"anything you need to plan or think through before I switch you to opus 5.5?"* — the sibling-standing model-swap
  move. Writing the frames for every pending judgment call into the session file BEFORE the swap worked: the Opus
  half executed the 118 checkpoint review, two CP rulings and four launches without re-deriving anything.
- They never answered: the release (asked in my opening message and at the grant — 4th/5th time overall), the
  merge-before-release question, the 180-planner tier. Defaults held; nothing irreversible hung on them.

**Overturned or corrected, owned**

- I wrote "compact JSON" into a DECIDED ledger line and the ADR from a lens summary; a fresh reader EXECUTED it
  (`{"a": 1, "b": [1, 2]}`). Fourth instance of the mechanism-from-a-summary pattern → now an ADR-FORMAT sentence.
  The fix that works: name the FUNCTION (`to_string`), never transcribe its outputs. "SC2154 catches it" (Task 182)
  was the same error, caught the same way.
- My first 118 rewrite had a requirement (move the dict/list block onto `env:`) that contradicted the user's own
  ruling two paragraphs up. Only the SECOND context-free read caught it — the 8-lens battery reviewed the earlier
  text. A rewrite is a new document; it gets its own fresh reader.
- I told the 183 spec "of 3 for a fixed-cap loop" — no loop is fixed-count (every loop has `while:`/`until:` checked
  before the cap). Came from the #656 reopen comment (my own predecessor's prose), not from the code.
- My pre-swap ruling "delete #719's carve-out" was narrowed by the 180 planner on evidence (old traces). Accepting a
  producer's narrowing of my ruling when it is strictly safer and keeps the intent is the right reflex.

**Mechanisms that worked — reuse them**

- **Spec battery with my unverified claims NAMED in the brief.** 3 of 5 refuted. A lens told "these were written
  without reading code" checks them; a lens not told skims past them.
- **Fail-closed precondition naming the SET** ("every path where a step can fire writes `node.start`; if any does
  not, STOP") — the #690 lane stopped on a real unsafe path (batched host), then its falsifier found two more over
  three rounds. Third session in a row this mechanism stopped a guess.
- **A seam note relayed as a CLAIM to a live planner** (118's `env:` no-parse as a predicate 120 can extend) was
  adopted as `parses_leaves` — cheap, and it pre-shaped two later tasks.
- **Two-PR split for a breaking task** (non-breaking channel first, flip later) let tonight ship value without
  touching the release question — and gave `tests-windows` a run on the Windows unknowns before 400 sites moved.
- Planners: Opus planners (181, 183) produced plans of the same shape and review depth as Fable's; each ran a 7-lens
  plan battery and found real design defects (a `??` cap template; a back-edge "4 of up to 3"). n=2, small sample.

**Dead ends — don't repeat**

- `git rev-parse --short main origin/main` fails ("Needed a single revision") and short-circuits a `&&` chain — use
  it without `--short` for two refs.
- A task-notification "completed" can arrive BEFORE the agent's hand-back message, and a second one after a resume;
  query `gh`/`git` directly instead of waiting for the message (#690's merge was found that way).

**Seams noticed, not yet forced**

- Three plans on branches that all touch `runtime/engine/` (118 Part 2, 180, 183) plus 181 and 120 behind them: a
  five-deep engine queue. 180 and 183 both bump the trace format; their plans agree "second takes the next number".
- 181's P0 runs six checks against 118 Part 2's shipped shapes — if Part 2's plan changes `param_mode`, 181's plan is
  stale. Send 181's two requests in Part 2's packet.
- 120's decision (g): booleans render `True` in a command/`env:` but `true` on shell stdin — 118 ruled the first;
  nobody has ruled the inconsistency.
- #720 (gate blob crash) will bite 183's own fixtures over 1 KB — its plan says keep them small.

**Local-only artifacts**

- Branches `feat/task-180-…`, `feat/task-181-…`, `feat/task-183-…` exist ONLY locally (not pushed) with their worktrees
  under `../pflow-worktrees/`. If lost: the plans are gone; the specs on main survive.
- `scratchpads/session-11/` (main checkout, gitignored): `task-118-spec-battery.md` (the ledger), `issue-714/` (shots,
  measurements, falsifier fixtures incl. `f3-blob-crash.pflow.md` for #720).
- Session scratchpad (`/private/tmp/claude-501/…/scratchpad/`): `t118/`, `t120/` probe workflows (the 120
  investigation's executed breaks), issue drafts. Disposable.
- `~/.pflow/`: the #714 falsifier left 9 paused runs + 1 failed run (harmless; tidy if wanted).

**Markers**

- ASKED-NOT-ANSWERED: release v0.16.0; may 118 Part 2 merge before it; 180 planner tier (Fable used).
- ASSUMPTION: `TMP`/`HOME`/`TMPDIR` behave like `TEMP` under Git Bash (Cygwin docs; only `TEMP` observed).
- UNCLEAR: whether the user wants the collapsed checkpoints (118 diagnostics, #714 shots) re-shown or just reported.
- NEEDS VERIFICATION: 181 planner's unfiled findings (MCP nodes miss the `mcp` icon; `pflow mcp describe` splits
  hyphenated server names; dead `_CODE_BLOCK_TAG_TO_PARAM`) — inferred from code, not run.
