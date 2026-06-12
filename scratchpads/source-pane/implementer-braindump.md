# Braindump: source-pane implementation handoff

> From the agent that wrote + review-hardened `implementation-plan.md` (same directory),
> and before that implemented the markdown/code-rendering increment this builds on.
> The plan is the spec — this file is only what ISN'T written anywhere else.

## Where I Am

The plan is final and review-hardened (4-lens plan review: review-plan /
silent-failures / impact-completeness / feature-interactions — the raw review reports
exist NOWHERE except folded into the plan; every "review-critical" / "review-caught"
marker in the plan text is a folded finding, treat them as load-bearing, not color).
Zero implementation has started. The user approved the direction conversationally but
has not formally said "go" on the plan document itself.

## THE WORKING TREE IS DIRTY — read this first

The entire markdown/code-rendering increment (~25 files: `web/src/utils/highlight.ts`,
`components/CodeBlock.tsx`, `components/Markdown.tsx`, format.ts changes, test files,
docs) is **UNCOMMITTED on this branch**. This is deliberate: the user's workflow is to
review agent changes as unstaged diffs in Cursor and stage manually as approval. So:

- NEVER `git add` / `git commit` / `git push` (standing project rule) — and on this
  branch specifically, never run `git checkout -- <file>` or `git clean`: you will
  destroy another increment's uncommitted work. I did exactly this once (checkout to
  undo a scratch mutation) and had to re-apply format.ts by hand.
- Don't assume HEAD contains the highlight seam — read files from the working tree.
- If the tree is clean when you start, the user staged/committed it — fine, proceed.

## User's Mental Model (their words)

- *"my current workflow right now is to manually stage the agents changes after it has
  applied a change im happy with (view in cursor ide), so I see small diffs at once"* —
  staging IS the approval gesture. This single message killed the diff feature and is
  why the plan's no-diff non-goal exists. If diff-shaped scope creep tempts you, the
  answer is already decided.
- The original task-168 driver: *"It's very hard for me as a human user to understand
  how this agentic workflow actually works and I NEED to have full control."* The pane
  is comprehension — closing the loop between the canvas (derived structure) and the
  file (the truth). The file's verbatim-ness is the value; that's why inline-stitching
  was rejected.
- The user is economical: they aborted 4 of my 8 review agents as overkill mid-run
  ("you can abort the agents that doesnt make sense to review here"). Match that —
  the 4-lens battery is the right size for reviews here; don't over-deploy.
- They decide fast and don't relitigate. Decisions marked "locked" in the plan are
  genuinely locked.

## Hard-Won Gotchas (cost me real time; will cost you)

1. **NUL-byte tool hazard (repo-wide, bit me 3×):** when MY tool output (Write/Edit/
   heredoc) contained the literal NUL escape sequence, it landed as a raw 0x00 BYTE —
   making the file binary to git/grep/ripgrep and invisible to searcher agents.
   `CodeBlock.tsx`'s cache key uses NUL-escape separators — if you copy that key
   pattern for SourcePane's per-file memoization, do NOT type the escape directly;
   write a placeholder char and byte-replace via python
   (`data.replace(b"\x00", b"\\u0000")`). Check `file <path>` says "text" after.
2. **jsdom lies about scroll and edges.** Assert STATE (`.src-line-active`, file
   switched), never scroll position; the plan explicitly routes scroll verification to
   the manual browser step. Any "no edge errors" assertion under jsdom is theater.
3. **Screenshot loop discipline:** rebuild (`make ui-build` or `cd web && npm run
   build`) before EVERY screenshot — the server serves the built bundle, not dev
   source; add `&v=<anything>` to bust the MCP Chrome's asset cache; `-p` makes stdout
   just the PNG path. Kill the `pflow ui` server when done (I left one running once;
   check `lsof -i :8765`).
4. **GraphView.test.tsx cross-test URL leak:** `syncUrl` uses `replaceState`, which
   persists across tests in the file. Any test setting `?source=1` MUST reset in
   try/finally (the file has the pattern at the io-card test). Also its `api/client`
   mock factory spreads `...actual` — add `fetchSource: vi.fn()` or it hits real fetch.
5. **`vi.mock("../utils/highlight")` insulation** (highlight → resolves null) in every
   jsdom suite that mounts a highlight consumer — four suites already carry it with an
   explanatory comment; copy that exact shape for SourcePane.test.
6. **Writing test `.pflow.md` fixtures:** the parser REJECTS `-` bullets in
   descriptions ("use `*` for documentation bullets") and claims ANY fenced block in a
   description as a fence-named param (→ validation error). Also: adding a `.pflow.md`
   under `examples/` auto-enrolls it in IR validation tests.
7. **Phase 1 touches Python** → `make test` + `make check` required there (the
   frontend phases only need `npx vitest run` + `npm run build`).

## Assumptions & Uncertainties

- **NEEDS VERIFICATION (unresolved contradiction):** one searcher claimed bullet
  params carry `- key:` source lines (cited run-cycle fixture, command param →
  line 44); the review-plan agent contradicted (markdown_parser:1666/1673 are OUTPUT
  source lines; bullet params ship `line=None`). I did NOT resolve this — v1 maps
  node lines only, so nothing depends on it. If you ever add param-row→line sync,
  verify against the parser first; the plan's Facts wording is deliberately hedged.
- **ASSUMPTION (70%):** shiki's `codeToHast` on a 1,100-line / 32k-char markdown file
  is fast enough on the main thread (<100ms-ish). Never timed it. Memoize-per-file
  bounds it to once per file per session; if it janks on the harness, measure before
  reaching for a worker.
- **UNCLEAR (implementer judgment):** the plan says the source fetch lives in
  "GraphCanvas (or useWorkflowGraph)". My lean: a plain `useState`+effect in
  GraphCanvas keyed on `workflow` — do NOT thread it through `useWorkflowGraph`'s
  status machine (the pane has its own degraded states; coupling them entangles the
  canvas's loading/error banner with the pane's).
- **UNCLEAR:** `fileChainFor`'s host-from-file derivation at nesting depth >1 is
  under-specified (which member's prefix wins). Write its node-env tests FIRST against
  deep-research.json and let the cases drive the implementation; the orphan-file and
  twice-invoked-file fallbacks are specified, the happy path's exact walk isn't.

## Unexplored Territory

- **CONSIDER: line wrapping.** Long prose lines in `.pflow.md` — wrap (matches
  `.read-param-value` pre-wrap precedent) vs editor-style no-wrap + horizontal scroll.
  Never discussed with the user. Wrapping changes row heights (gutter alignment still
  fine — each row is its own div). Shoot-lab it; don't ask the user first, show them.
- **CONSIDER: narrow viewports.** Three columns on a 13" laptop is tight even with the
  symmetric clamp. A default-closed-below-width heuristic was never discussed — the
  URL param default (closed) mostly covers it; don't build more without observed pain.
- **MIGHT MATTER:** the pane is GraphView-only by construction (CatalogView has no
  workflow) — fine, but `App.tsx` gating was never explicitly discussed.
- **UNEXPLORED:** scroll-position sync (scrolling the source highlighting canvas
  nodes) — never discussed; do not build.

## What I'd Tell Myself

- Implement Phase 1 first and verify against the REAL example immediately
  (`/api/source?workflow=examples/agent-orchestration/plan-to-code/run-from-plan.pflow.md`
  — it spans parent + execute-plan + prompt-referencing nodes); the deep-research
  contract fixture is the sourceMap test bed (4 files, the score-host vs score-port
  collision, batch copies).
- The plan's review markers are the distilled review — when an instruction seems
  oddly specific (iterate-until-resolves, scroll-in-own-effect, the `## Inputs`
  fixture requirement), it's because a reviewer proved the naive version fails.
  Don't simplify them away.
- Run the `/code-review` battery after gates pass (repo practice; the plan's Phase 4
  step 4) and append a progress-log entry to
  `.taskmaster/tasks/task_168/implementation/progress-log.md` (or a new task's log if
  the user spins one up) with deviations + reasons — the no-handwaving bar.
- The user left a scratch `md-render-test` workflow in `~/.pflow/workflows` from my
  session; not yours to clean (an `rm` there was permission-denied for me — don't
  attempt destructive ops in their home).

## Relevant Files & References

- The plan (THE spec): `scratchpads/source-pane/implementation-plan.md`
- Frontend canon: `web/CLAUDE.md` (incl. the new "Authored text rendering" bullet —
  the highlight seam you'll consume); server contract: `src/pflow/ui/CLAUDE.md`
- The seam you consume, do not fork: `web/src/utils/highlight.ts` (its header names
  this pane as its next consumer); `codeChildren()` is your line-extraction entry
- Prior journey + standing learnings: task-168 progress log, the 2026-06-12
  "Markdown + code rendering" entry (the NUL learning lives there too)
- Screenshot loop: `.claude/skills/screenshot-pflow-web-ui/SKILL.md`

---

> **Note to next agent**: Read this document fully before taking any action. When
> ready, confirm you've read and understood by summarizing the key points, then state
> you're ready to proceed.
