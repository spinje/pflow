# session-08 — 2026-09-28

## [2026-09-28] main orchestrator — boot + reality diff

- Booted per the role prompt (post-parity-fold contract: ORCHESTRATION/DECISIONS/CURRENT-STATE/
  session-07/STANDING-KNOWLEDGE/RECURRENCE). Sessions 04–07 carry no `## Braindump`; boot fork
  (1b) skipped per its own gate.
- Reality vs CURRENT-STATE: **PR #626 MERGED** (`72059a34`, head `8773c045`, closes #616 —
  CLOSED); no open PRs; only the main worktree; no live agents; 136 open issues; board check
  clean (167 files). CURRENT-STATE's "In flight" was stale — corrected the one line at boot.
- User focus for the session: `scratchpads/handoffs/braindump-issues-620-625.md` (triage of
  #620–#625); user warns the process contract is freshly rewritten — catch rough edges and fix
  them as they surface.

## [2026-09-28] main orchestrator — #620–#625 pick-time verification (two native searchers)

- #620 VERIFIED + one extra defect: the resolver's sequential `str.replace` corrupts `$${x}`
  when `${x}` also appears unescaped. Validator file is `runtime/template_validation/validator.py`
  (`_PERMISSIVE_PATTERN` :50 lacks the lookbehind; `count("${")` :683). Behaviour fork: docs
  (`template-variables.mdx:326`) say `$${X}` → `${X}`; `runtime/CLAUDE.md:58`, the test at
  `test_template_resolver.py:200` and Task 170's behaviour-freeze say the extra `$` is retained.
- #625 PARTIAL: the MCP node already JSON-parses text content that is entirely JSON
  (`mcp/node.py:546-593`); nothing extracts a fenced block. #625 duplicates #551.
- #624 VERIFIED: one pool per run (`runner.py:198`, shut down at :901-907); `probe` opens a
  throwaway connection per call; no persistent session anywhere.
- #622 PARTIAL: validator passes skip non-string `code`; the TypeError fires in
  `compiler.py:319-322` (annotation extraction), not the node; `function` is not in
  `FILE_RESOLVABLE_PARAMS`; lists of file refs are passed through unchanged.
- `guide/nodes/mcp.md` has no `timeout:` param and no `structuredContent` (#623 claims hold).
- Task 170 carries a 2026-06-12 plan (pre-Task-177, pre-"every task gets a planner") — stale by
  rule; its spec freezes the `$$` behaviour #620 wants changed → semantic collision, serialize.

## [2026-09-28] main orchestrator — [RULING] triage of #620–#625 accepted as recommended

- User: *"yes go ahead with this, note that the worktree script has never ran before so take
  care"*. Rulings taken: #620 → code matches docs (`$${…}` any content → literal `${…}`, lane B);
  #621/#550 deferred to after Task 170 (constraints into the 170 spec); #625/#551 → opt-in
  fenced-JSON extraction param on MCP nodes, dedupe; #622 bug now (lane B), feature parked;
  #623 docs lane after #625; #624 → task spec later; docs-snippet validation issue → file it.

## [2026-09-28] main orchestrator — lanes launched: #620, #622-bug (first live `scripts/worktree` runs)

- `./scripts/worktree new … --no-open` ran clean twice (base 72059a34, `make install` ok,
  `pflow --version` ok). Observed: with `core.hooksPath` set, pre-commit hooks are NOT
  installed in worktrees (`make check` is the gate — the lane runs it before the PR).
- Two Opus lanes launched in parallel; the #620 packet carried a fail-closed hand-back on any
  `runtime/engine/` edit — which is exactly where it later stopped (the mechanism worked).
- Observation (rough edge, benign): fresh worktrees resolve to Python 3.14.0 (`uv sync` picks
  the newest installed interpreter; no `.python-version`), main's venv is 3.13.4. CI's matrix
  covers 3.10–3.14, so lane gates on 3.14 are a valid sample, not a drift risk. Third lane
  (#625) launched into `feat-issue-625-mcp-json-block`; #551 closed as its duplicate, ruling
  posted on #625.
- Filed **#629** (docs `.mdx` snippets unvalidated — extend the guide example validator; 5
  snippets in 2 files measured; ordered after #620). Rough edge: `gh issue create` with a
  non-existent label aborts the whole create — the repo has only GitHub's default labels.

## [2026-09-28] main orchestrator — #625 ESCALATED (2/5): registry declaration of the new param

- Lane stopped before `mcp/registrar.py` (outside its ownership list): validation rejects any
  undeclared MCP param; entries are written only at `pflow mcp sync` and the auto-resync hashes
  server config only. Verified the precedent it cited: `registry/registry.py:143-161`
  `_normalize_mcp_output_namespaces` (idempotent in-memory repair on load, shared constant) and
  the inline `timeout` entry at `registrar.py:350-356`. No sibling lane touches either file.
- Resolved here, 2/5: option A — one `MCP_NODE_PARAMS` constant in `registry/constants.py`,
  registrar appends it, load-time repair adds missing keys. Precondition handed down: the
  repair must be key-matched, idempotent, MCP-entries-only, never overwriting a tool-schema
  param of the same name (mirror the precedent) — anything else hands back.

## [2026-09-28] main orchestrator — #620 ESCALATED (3/5, settled answer): engine check trips on a correct escape

- Lane built the fix without an engine edit (`has_templates` now routes `$${` through resolution;
  single-pass interpolation fixes the corruption) — It
  stopped on `engine/template_resolution.py:237-249`: strict mode re-scans OUTPUT for original
  variable names, so `echo "${g} | $${g}"` errors "unresolved" (executed by the lane).
- Resolved here per the standing rule (engine = lane A, never a lane-B expansion): ship as
  built; the engine fix is Task 170's "existence and resolution cannot disagree" requirement.
  Filed the follow-up issue (below); lane adds the pointer to the 170 spec. The single-pass
  change also turns one silent re-substitution (`B B`) into a loud error — recorded there.
- Filed **#630** (strict-mode unresolved check re-scans output; engine seam → Task 170). Lane
  #620 resumed with option 1 + extra ownership (two stale "no lookbehind" claims) + a bounded
  `## Cache`-block probe (fix only if ≤ ~10 lines reusing its helper; else comment on #630).
- [MEASURED] first live gpt-6-astra review fan-out: the #622 lane ran
  `run-review-lenses` on Codex — 2/2 lenses in 117 s, trace
  `workflow-trace-3c66a4c4-run-review-lenses-20260928-210451`; "cost unavailable" cosmetic as
  recorded. User asked whether lanes use the pflow fan-out rather than built-in subagents: yes.

## [2026-09-28] main orchestrator — MERGED #622 bug part: PR #631 → `1e0dbe6a`

- #622 stays OPEN for the parked feature. The lens's proposed fix was replaced with a
  compiler-side `CompilationError` so every compile path — UI pre-flight included — gets the
  diagnostic. First live `scripts/worktree rm`.
- Sibling gaps recorded in the PR body, not fixed: `- command: 42` passes validation and dies
  at run (`AttributeError`) — Task 112's class, no new issue; UI pre-flight compiles only;
  RunForm omits `node_id` on pre-flight diagnostics.
- Cost-warning investigation (user question): the "pricing data missing" line for gpt-6-astra
  is the agent backend's `cost_usd: None` (subscription-billed) counted as unpriced by
  `metrics.py:137-147` — a misleading message, not missing data; gpt-6-astra is also absent
  from litellm 1.86.1's map (estimate side). Offered a lane-B issue; awaiting the user's word.

## [2026-09-28] main orchestrator — [RULING] cost summary: show the API-equivalent estimate, label subscription billing

- User: *"if possible I think we should output the cost it would cost with api even when using
  subscription but note in the output somehow that its on the subscriptions"* → *"yes go
  ahead"* on the shown before/after. Measured first: `pflow report` on the fan-out trace already
  prints `API-equivalent estimate: $5.9507` (upstream litellm map has gpt-6-astra; the locked
  bundled map does not) — only the CLI line and the report header mislabel it.
- Filed **#634**; lane B (Opus) launched into `fix-issue-634-cost-summary-subscription` off
  `1e0dbe6a`. Files disjoint from #620/#625. Hand-back gate: any new trace field.

## [2026-09-28] main orchestrator — MERGED #620: PR #632 → `adf32649` (closes #620)

- The lane's untracked `.lane620/` blocked teardown (its `rm -rf` and mine were denied; the user
  deleted it). Gate: one disputed finding (output `source:` garbling — pre-existing, run on both
  branches), one downgraded (escape-only values defer static checks — under-check only).
- `## Cache` probe outcome (c): `$${HOME}` in a cache block fails validation; touches chunk
  spans/hash content → measured result posted on #630, not fixed. Task 170 spec now carries the
  freeze-line rewrite, the :190 correction and a Parity line pointing at #630.
- Task 170 spec: added the "Deferred by design" block (#621/#550 as one language ruling after
  phase 5; Task 118 collision named); #621 commented with the deferral. Board check clean.
- Rough edge (n=2 this session — lane and me): `rm -rf` of an untracked scratch dir INSIDE a
  worktree is denied by the permission layer (the worktree is outside the working directory);
  the teardown's clean-tree check then refuses. Fix candidate for close: lane scratch goes under
  the worktree's gitignored `scratchpads/`, never an ad-hoc dot-dir. Teardown of the #620
  worktree waits on the user deleting `.lane620/`.

## [2026-09-28] main orchestrator — [RULING] teardown script: user asked "warning when dirty with --force?"

- Shaped it as: refusal lists dirty paths; `-f` discards local state but still verifies the
  merge and deletes the branch; lane scratch under gitignored `scratchpads/`. User: *"great, go
  ahead"*. Filed **#635**, lane B launched (files disjoint from #625/#634; the script is run
  only by the main orchestrator, so mutating it mid-flight breaks no producer).

## [2026-09-28] main orchestrator — MERGED #625: PR #633 → `f9fb7f7f` (closes #625)

- Its scratch lived under the gitignored `scratchpads/` — the right shape, no teardown block.
- Residuals from the PR body: pflow-level MCP params shadow a tool's same-named args (pre-existing
  for `timeout`); duplicated usage-snippet generators (`cli/commands/mcp.py:988-1003`,
  `registry/context_builder.py:662-680`) show `result_format: ${…}` placeholders; the example
  `clean` node is now replaceable (→ folded into #623's packet); MCP image detection
  duck-types `hasattr(content, "image")` — verify then file.
- Filed **#636** (MCP content-block type detection duck-types attributes the SDK blocks lack;
  measured the SDK field lists myself). Lane-B shaped; not launched — three lanes live.

## [2026-09-28] main orchestrator — MERGED #635: PR #637 → `f08b9ca4` (closes #635)

- First run of the changed `rm` on a real worktree: clean. Residual: ORCHESTRATION step 6's
  "`-f` skips the checks and keeps the branch" — corrected by me (process doc, mine).

## [2026-09-28] main orchestrator — MERGED #623: PR #638 → `9b346c68` (closes #623)

- Salvage caveat EXECUTED by the lane against a single-threaded stdio server; three example workflows
  moved to `result_format: json_block` and run for real against a pinned chrome-devtools 1.7.0.
- Residual with blast radius: every `examples/real-workflows/screenshot-pflow-web-ui/` workflow
  fails on the `chrome-devtools` (`@latest`) registration — `evaluate_script` now requires
  `pageId`; failure is in the shared `open-and-settle` sub-workflow. This is the
  `screenshot-pflow-web-ui` skill's substrate (UI lanes verify through it) → issue filed.
- Filed **#639** (screenshot example suite + the `screenshot-pflow-web-ui` skill broken on
  `chrome-devtools-mcp@latest`; measured: the `chrome-devtools` registration is `@latest`, the
  isolated one is pinned 1.7.0). Class: unpinned upstream server under a verification tool.
  Recommended to the user as the next lane — no UI lane is live, so no producer is blocked yet.

## [2026-09-28] main orchestrator — MERGED #634: PR #640 → `33a74353` (closes #634)

- Four cost-summary paths folded into ONE classifier
  (`MetricsCollector.calculate_costs`: paid / subscription / unpriced); no new trace keys; JSON
  gains `metrics.total.subscription`. Two lane calls (1–2/5, in the PR body): `total_cost_usd`
  stays null when any call lacks observed paid cost (only `pricing_available` flips);
  "unavailable for: <model>" instead of "no pricing" (Codex can also omit usage).
- Follow-ups in the PR body, not filed: `use_api_key: true` agent runs are also labelled
  subscription (needs a trace field → task-shaped); `analyze-cache --list-traces` still says
  "cost unavailable" for agent traces; `docs/reference/cli/index.mdx` key names predate the
  change; partial `total_api_equivalent_cost_usd` has no marker.

## [2026-09-28] main orchestrator — [GRANT] "all three go ahead": #639, #636, #629 as parallel lanes

- Three Opus lanes launched (#639, #636, #629); collision analysis: file-disjoint, and #636's
  dispatch fix leaves text blocks untouched so it cannot break #639's workflows at runtime.

## [2026-09-28] main orchestrator — [RULING] step-back: Task 170 next (lane A, Fable planner); #624 design talk; audit tail as lane-B filler; Task 94 after

- User: *"1. lets review the spec, fix any issues and then go ahead with fable planner? 2. yes
  lets discuss it 3. yes 4. yes sounds good"*. Task 170 Roadmap moved then → next. Launched:
  two searchers (Problem claims; References/neighbours) + one context-free Opus
  `review-architecture-fit` SPEC review + a #624 substrate searcher.
- User: *"with review, I mean deep review"* → SPEC-review battery (plan mode, direct launches per
  the skill): review-plan, validation-consistency, impact-completeness, feature-interactions,
  silent-failures + the already-running architecture-fit (6, Full tier: multi-phase,
  validator/runtime seam). Findings evaluated, not accepted; disposition A/B/C per the role
  prompt before the planner launches.

## [2026-09-28] main orchestrator — MERGED #636: PR #641 → `69b351b1` (closes #636)

- Class closed by dispatching on the SDK `type` field; nine fake-shape tests moved to real
  `mcp.types`. Follow-ups in the PR body: validation rejects `${x.result[1].data}` on MCP nodes
  (unchecked whether intended — Task 170 corpus candidate); guide silent on non-text shapes.

## [2026-09-28] main orchestrator — Task 170 spec battery complete; #624 research; issues #643/#644

- Six lenses + two searchers in; ledger at `scratchpads/session-08/task-170-spec-refresh.md`
  (local). Convergent: architecture sound (ADR-0006 holds); the freeze list is stale post-#632;
  two silent classes unnamed (dynamic-index rewritten text; loose-accepted/strict-rejected
  templates reaching nodes literally); parity one-directional; meta-test 3 unachievable as
  written; yaml_utils mask + web TS copies unnamed. June plan renamed `…-SUPERSEDED.md`.
- Filed **#643** (save vs --validate-only params construction; lane B) and **#644** (mcp SDK
  unbounded; 2.x removes streamablehttp_client — pin `<2` now, migration task later).
- #624 research (user: *"there has been a new version of 'stateless' mcp standard"*): MCP spec
  2026-07-28 removed sessions + initialize (SEP-2567/2575); state = explicit handles; SDK 2.0.0
  2026-07-28 (pflow locked 1.26.0). Root cause of the filer's page/cookie loss is Playwright's
  per-MCP-session browser lifecycle (+ pflow's `terminate_on_close=True` DELETE), not pflow —
  shape 1 stands with a proxy that keeps ONE child (mcp-proxy), never Playwright's own `--port`;
  shape 2 only as a holder process; shape 3 dropped. Report:
  `scratchpads/session-08/mcp-stateless-research.md` (local).

## [2026-09-28] main orchestrator — MERGED #629: PR #642 → `871ae780` (closes #629)

- One extractor over two corpora (guide `.md` + docs `.mdx`, incl.
  fences indented inside MDX components — 192 of them); found and fixed a sixth broken example
  in `docs/changelog.mdx`. Correction to my issue text (owned): the #620 escape example is a
  single-node FRAGMENT (no `## Steps`) — this mechanism would not have caught it; the class
  closed is "complete workflow examples". Fragments remain unvalidated (mechanism unclear;
  not filed).
- Process slip, lane-reported: main moved (#641) between its last check and the squash; it ran
  the gates on the merged result afterwards — `make check` green, `make test` 4/5 green with one
  unidentified failure on the first run (flake, unnamed). RECURRENCE candidate: "unidentified
  first-run failure" n=1. Checked CI on main post-merge (below).
- Misread, owned: I first read `gh run list --branch main` as "no push CI on main"; the
  unfiltered listing shows push runs on every merge today — `871ae780` Main + Docs both
  green (20:11Z). The merged-result gate (#4) IS covered by CI; the lane's unidentified
  local flake stays an n=1 RECURRENCE candidate only.

## [2026-09-28] main orchestrator — [RULING] "go ahead with your recommendations"

- Taken as: #624 → docs lane (corrected long-lived pattern, proxy caveat); #644 → pin `<2`
  (lane B); Task 170: (1) strict grammar wins — validator ERROR for loose-accepted/
  strict-rejected shapes; (2) dynamic index = one reference (type-preserving; any failure inside
  ⇒ unresolved) — the task's deliberate user-visible delta set; (3) cache-block escape option (a)
  unescape at render, symmetric at hash+prep (ADR bar → record); (4) Task 118 moves behind 170,
  blocked-by in both specs; (5) #628 → reject at validation (lane B). Audit trio #615/#617/#618
  approved earlier — next wave after these merge (seam attention, not capacity).
- Task 170 spec REWRITTEN in place (490 lines; provenance header; decision ledger with the five
  rulings; Sanctioned deltas 1–6; converse parity; meta-tests narrowed + allowlist; phases
  re-cut with #630 in phase 2 and `scan.ts` beside `scope.py`; June plan renamed SUPERSEDED).
  Task 118 → `then`, blocked-by 170 recorded. ADR-0006 amended (allowlist, operand classifier,
  converse parity); ADR-0015 written (cache-block escape, option a) — fresh-agent adversarial
  review before the prep commit (ADR-FORMAT "Review before commit").

## [2026-09-28] main orchestrator — MERGED #644 part 1: PR #645 → `fa49816c` (#644 stays open for part 2)

- Lane EXECUTED the probe: mcp 2.2.0 renames `streamablehttp_client` → `streamable_http_client`;
  bound `<2` holds the upgrade at 1.30.0. Sibling gap noted:
  `claude-agent-sdk>=0.2.82` is 0.x unbounded (not measured broken). Part 2 = migration task,
  to be filed via create-task when the user wants it scheduled.
- ADR review (context-free Opus): 3 factual errors in ADR-0015 (no prose interpolator — prose is
  concatenated verbatim at hash/prep; the silent `$${topic}` mis-render was missing; consequence
  is validation breakage, not only a new key) + the unescape-location rationale (IR stays
  escaped: graph build re-emits `cached_prefix` as template text) + 0006's commit misattribution
  (fix lives in `4516cd72`). All folded. Prep commit `7dc5ad5d` pushed to main (#5 exception:
  spec 170, spec 118, renamed plan, ADR-0006, ADR-0015; orchestration state NOT included).
  Observed: the push bypassed main's required-status-check rule (admin) — CI runs on push anyway.

## [2026-09-28] main orchestrator — Task 170 planner LAUNCHED (first live Fable-planner → Opus-orchestrator run)

- Fable `task-planner` launched plan-only (explicit `model: fable`) with the battery ledger copied
  into the worktree's gitignored `scratchpads/session-08/`.

## [2026-09-28] main orchestrator — #628 ESCALATED (2/5 ×2): demo example + namespacing-off consequence

- Lane implemented `source` as schema-required (covers every entry point) + a compile-path twin
  for compile-only callers; stopped on: (1) `examples/output_validation_demo.pflow.md` exists
  only to show the warning being removed → ruled DELETE (measured: zero live references outside
  task archives); (2) `enable_namespacing: false` (inline-IR only, undocumented) loses its one
  "working" output form → ACCEPTED; the pre-existing validator defect filed separately (below).
  Lane resumed. User ruling in force: no new launches — this is a drain, not a start.
- #624: research summary + ruling posted on the issue (user: *"yes go ahead"*); reopen trigger
  recorded there.

## [2026-09-28] main orchestrator — MERGED #624: PR #647 → `d459f60c` (closes #624)

- Lane EXECUTED the research's claim: behind `mcp-proxy` (one child kept alive) the open page,
  localStorage and a session cookie survive across probes, an idle gap and a run; Playwright's
  own `--port` still loses the page. Drift found: `uvx mcp-proxy` 0.12.0 crashes on import
  under mcp 2.x (upstream #235) → documented as `uvx --with 'mcp<2' mcp-proxy`. Flake sample
  n=1: `test_real_compilation_performance_scales_with_nodes` 203.75 ms vs a 200 ms limit.

## [2026-09-28] main orchestrator — MERGED #628: PR #649 → `ebdbd015` (closes #628)

- `source` is schema-required + a compile-path twin for compile-only callers. Left open in the
  PR body: `$x` source rejected by the validator but resolvable (Task 170);
  formatter tests build sourceless output dicts that never hit the schema (invalid IR, passing).
- Task 170 note for the successor's packet: #628 merged BEFORE the build; the planner's
  worktree is at `7dc5ad5d` and must merge main (`ebdbd015`+) before phase 1.

## [2026-09-28] main orchestrator — MERGED #639: PR #646 → `7d7ffd44` (closes #639)

- Local `chrome-devtools` registration now pinned `@1.10.1` (one-line diff, measured). Cause: chrome-devtools-mcp 1.8.0 made page-id routing default; the shared
  sub-workflow now extracts the `[selected]` page id (loud on ≠1 match — the lens found a
  title-collision case, fixed). The suite requires ≥1.8 (the 1.7.0 isolated registration
  rejects `pageId` at validation).
- Gaps reproduced, not fixed (PR body): `--validate-only` misses a MISSING REQUIRED MCP param;
  `settle` returns the default viewport after its 8 s limit → `visual-invariants` can report
  `passed: true, dotsChecked: 0` with exit 0 under load (a silent-success class in the
  verification tool — candidate issue for the successor); click/hover exit 0 on target-not-found;
  `pflow mcp describe` splits the server name at the first hyphen. Flakes under load average
  140–217 (n=2 timing benchmarks this session).

## [2026-09-28] main orchestrator — Task 170 PLAN COMMITTED (planner handback); build parked for the successor

- Planner head `33f6d79f` (draft plan → merged main `7d7ffd44` as `c07acb4d` → folded plan);
  seven-lens self-review, four Criticals folded by execution (resolve() must not auto-parse
  top-level strings; a `Resolution.issues` channel; `inputs` resolved per key; inner
  dynamic-index refs are dependencies). Phases: 1 → 2+3 bundled → 4a (engine) → 4b → 4c → 4d
  (needs `npm ci` in `web/`) → 5; all Opus; mid-task reviews after 2, 4a, 4b. Baselines on the
  merged head: `make test` 9276, freeze harness 812.
- Planner token usage ~597k (notification metadata). Its offer to implement phase 1 DECLINED
  on the user's "no new starts" ruling (not on merits — note for the successor: the window is
  spent regardless). Four open questions resolved 2/5 (error-unless-all-absent-coalesce; remove
  the runtime-only `$node.x` source form; reject `??` cache vars at parse; R12 kept + file at
  completion); planner resumed once to record them in the spec ledger on the branch.

## Braindump

_Tacit residue only — state, rulings and ships live above and in CURRENT-STATE._

**The user this session — their words, and what they did with them**

- Opened with: *"alot of updates has been done to your main orchestrator instructions and the
  process in general … there might be rough edges and we need to catch them gracefully and fix
  them as we go"* and *"note that the worktree script has never ran before so take care"*. They
  expect the FIRST run of any new mechanism to be treated as its test — and they name which
  one is untested. Every rough edge I logged in the moment went into a home at close; that
  cadence is what they wanted.
- They audit whether a gate RAN, not what shipped: *"are the lanes using astra pflow reviews?
  thats how deep review is setup right? (not using builtin subagents right?)"* — answered by
  MEASURING (the lane's stderr file + trace id), and that satisfied them. Pattern from s07
  ("have you read all current reviews?") repeated → the STANDING-KNOWLEDGE line already holds.
- *"with review, I mean deep review"* — when they say review of a spec they mean the whole
  battery, not the "natural spec lens". Folded into the role prompt at close (small edit).
- *"it doesnt feel 100% right any of this, there has been a new version of 'stateless' mcp
  standard coming in the last months, can you put a research subagents to understand
  everything about this"* — their instinct beat my three-shape analysis: I had designed around
  session semantics the spec had just REMOVED. Lesson shape: before designing around a protocol
  or SDK, check the upstream standard's LAST 12 MONTHS — a research agent with web access is
  cheap and the user asked for it before I thought of it. They phrase this as a feeling
  ("doesnt feel 100% right") — treat that phrasing as a hard "go verify upstream".
- *"can you explain what the 624 task spec is simply"* — they want plain-language explanations
  before deciding; the explanation I gave (what breaks, why it matters, what the spec must
  settle) was accepted without spec text.
- *"what are the highest value/leverage lanes to work on after this? lets take a step back"* —
  the step-back came from them, mid-flight, while three lanes were live. They answered the
  four-option message tersely by number ("1. … 2. yes … 3. yes 4. yes sounds good").
- *"lets not start any more new things in this session, what do you sugest we finish before we
  handover to the next main orch?"* — they close sessions deliberately and ask for the
  drain list. Every "yes go ahead" after that was scoped to finishing, and I read the planner's
  implement-offer as a new start under that ruling (not on merits).

**Overturned or corrected, owned**

- ADR-0015 as I first wrote it described a "prose interpolator" that does not exist — I wrote
  the mechanism from a review lens's summary, not from the code. The context-free ADR review
  (ADR-FORMAT's rule) caught it; the real worst case was SILENT (`$${topic}` with a declared
  `topic` validates and sends a stray `$`). Rule for me: read the cited function before an
  ADR/spec states its mechanism (RECURRENCE n=1).
- I read `gh run list --branch main` as "no push CI on main" — the unfiltered listing showed
  push runs on every merge. The `--branch` filter output was misleading; use the unfiltered
  list with `event`/`headBranch` columns.
- My #629 issue text claimed the mechanism would have caught #620; the lane showed the #620
  docs example is a single-node FRAGMENT (no `## Steps`). Fragments are still unvalidated.
- The role prompt's boot step ("correct it first") and ORCHESTRATION's "never patched
  incrementally" contradicted each other on my first boot — resolved as: the boot fold of
  stale In-flight lines is the one sanctioned mid-session edit (applied).

**Mechanisms that worked — reuse them**

- **A ledger file per battery** (`scratchpads/session-08/task-170-spec-refresh.md`): each
  lens/searcher report appended with disposition codes (A fold / B RESOLVE-AT-START / C user /
  D disputed) as it lands, then ONE spec rewrite from the ledger. Six lenses converged on the
  same criticals from different angles; the ledger made convergence visible and the rewrite
  a single pass. Copy the ledger into the planner's worktree (gitignored) — the planner used it.
- **Fail-closed hand-back conditions in lane packets** ("the fix needs `runtime/engine/` →
  STOP") — #620 and #625 both stopped exactly there; neither grew. Name the measurement the
  lane must take to test the condition, not just the condition.
- **Measure before packeting**: SDK field lists (`model_fields`), the registration args, the
  PyPI JSON — a packet built on a searcher's report plus one command of my own never misled
  a lane this session; the one time I skipped it (ADR-0015) it bit.
- `git merge --ff-only origin/main` for the main checkout (pull rebases and refuses over the
  uncommitted state files). `gh issue create --label X` with a label the repo lacks aborts the
  whole create — the repo has only GitHub's defaults (bug/documentation/enhancement/…).
- The worktree script's `rm` is now the teardown of record; a lane's ad-hoc scratch dot-dir is
  the only thing that blocked it — and `rm -rf` of it is denied to me too (outside the
  working dir). Ask the user for `! rm -rf <path>`; the #635 lane def fix should prevent it.

**Seams noticed, not yet forced**

- Everything template-shaped now routes through Task 170 (#630, #643, #648, #621/#550, Task
  118, Tasks 112/120's type-matrix home). Any lane touching `template_validation/`,
  `engine/template_resolution.py` or the output-source validator while 170 builds will
  collide semantically even when diffs merge.
- The screenshot skill (UI verification substrate) has a silent-success mode: `settle` returns
  the default viewport after its 8 s limit and `visual-invariants` reports `passed: true,
  dotsChecked: 0`. Under host load this WILL happen. Not filed (user's no-new-things).
- Host load: at peak I had 3 lanes + 6 lenses + 1 planner on this machine (load average
  140–217 per a lane); two timing benchmarks flaked. Keep parallelism ≤3 lanes + 1 planner.
- The planner's window is spent (~600k tokens by the notification metadata). It committed the
  plan and its four rulings; resume it only to ask what the plan MEANT, never to build.

**Local-only artifacts (gitignored / machine state)**

- `scratchpads/session-08/task-170-spec-refresh.md` (the battery ledger, also copied into the
  170 worktree) and `mcp-stateless-research.md` (URLs, quotes, SDK file:line for #624/#644).
  If missing: the spec + ADRs + the #624 comment carry the conclusions; the trail is gone.
- `/tmp/pflow-shots/issue-639/{final,merged2,merged3}/` — the #639 lane's screenshot evidence.
- `~/.pflow/mcp-servers.json`: `chrome-devtools` pinned `@1.10.1` (was `@latest`); temp
  registrations from #624's lane removed. The `-isolated` registration stays at 1.7.0.

**Markers**

- ASSUMPTION: the planner's in-authority spec edits on its branch do not contradict the
  decision ledger (it said so; I never read the plan, per the role). The task orchestrator's
  packet should say "spec on the BRANCH is the truth, not main's `7dc5ad5d` copy".
- NEEDS VERIFICATION (by the 170 build, phase 1): the batch warm-up `system` path drops a
  user system prompt containing `$${x}` (read, not executed, by a lens).
- UNCLEAR: whether `use_api_key: true` agent runs should carry a billing marker in the trace
  (task-shaped; nobody has asked for it yet — observed-problems rule).
- ASKED-NOT-ANSWERED: none. Everything the user asked got an answer in-session.
