# Braindump: Issue #382 trace interning — discussion context for the next agent

> **This is tacit knowledge ONLY.** Everything factual — the verdict table, file:line anchors, the
> design, constraints, phased plan, test strategy, forward-compat with jsonl — is already written in
> **`scratchpads/issue-382-shrink-trace-interning/HANDOFF-AND-PLAN.md`**. Read that first. This file
> captures what is *not* in any document: the user's mental model, how the decision actually got
> made, what almost tripped me up, and what I'd warn my future self about.

---

## Where I am

Research + design done, **zero code written, nothing committed.** The approach is decided and the
user has signed off on the two load-bearing decisions (interning-only; no gzip; must stay
searchable). Phase 1 (the pure `intern_blobs`/`resolve_blobs`/`load_trace_file` functions + unit
tests) is fully unblocked. I never got to write a single line of implementation — I was kept in
"discuss / verify / plan" mode the whole time, *deliberately, by the user*.

---

## The user's mental model (in their words — this matters more than the plan)

This user **reasons with you; they don't want to be handed a multiple-choice answer.** Twice I
offered structured options and twice they redirected toward *thinking*:

- On "how should we scope Change A?" they answered: **"I want to understand the real problem and the
  tradeoffs between our options? anything we havent considered?"** — They didn't pick. They wanted
  the analysis and, crucially, a check that I'd considered alternatives outside the issue's framing.
  That "anything we haven't considered?" is a recurring probe — it's how they caught that I hadn't
  yet surfaced compression. **Expect this. Volunteer the alternative you're tempted to skip.**

- Their core engineering value, verbatim: **"We should prioritize simplicity of the FINAL code, not
  how easy it is to get there… whats the right solution that the top 10% of codebases similar to
  this one would implement, have we considered it yet?"** — then immediately the guardrail:
  **"What this doesnt mean is overfitting to 'top 10% of codebases' and overengineering, this is
  about more simple code that is optimized for AI agents to understand and add features to."**
  Read that twice. The north star is **AI-legibility**, not cleverness, not enterprise patterns,
  not maximal compression. "Simple enough that a future agent reads it in 30 seconds and extends it
  safely" beats "smallest file." This is *why* the encapsulated two-pure-functions design won over
  scattered resolution.

- The final decision came as: **"we DONT gzip, and agent should be able to 'search it'."** Note the
  word **"search"** — not "read," not "open." Their mental model of the trace is *a thing an agent
  greps/queries while debugging*. That single word is the entire justification for interning over
  compression. If anyone later argues "just gzip it, it's 10× smaller," the answer is: the artifact
  must be searchable by an agent in plaintext. Don't relitigate it.

- They are **viscerally aware that docs/comments go stale.** They explicitly asked the task-review
  miner to "note that the information might be stale." They asked me to read the Task 133 decision
  record **"YOURSELF"** (their caps energy) rather than trust a subagent's summary of it. And when I
  hit a stale *code comment* (see below), it validated their instinct. Treat every doc, every task
  review, and even code comments as suspect until checked against runtime behavior.

- They built the baseline infrastructure themselves and feel the pain firsthand:
  **"we had to manually remove and clean the [trace] from an original trace to make it even feasible
  to have in a git repo… trying to remove as much duplication as possible while keeping it ok to use
  as baseline trace."** The committed 9.4 MB `live-gemini-lyrics-generator.trace.json` is *their*
  hand-cleaning work. This is emotional as much as technical — they've personally suffered the
  duplication. Respect that artifact; don't casually regenerate/overwrite it (it's a baseline
  oracle).

- They think about **how this fits the roadmap over time** (their last two questions were "are
  baselines enough to prove we didn't break it?" and "how does this relate to the future jsonl
  streaming refactor?"). They want a fix that doesn't paint the streaming work into a corner. They
  are not just trying to close a ticket.

**Real priority beneath the stated request:** a clean, simple, AI-legible change that (a) keeps the
trace a *usable, searchable debug artifact*, (b) doesn't break the baseline test infra they invested
in, and (c) leaves a small, well-understood seam for the deferred jsonl/streaming work. Raw byte
reduction is the *means*, not the goal.

---

## The decision journey (so you don't re-walk it)

1. The issue frames two co-equal changes: **A** (honest model — drop "dead" duplicate prompt fields)
   and **B** (interning). I started treating them as co-equal.
2. **A cross-agent contradiction blew up Change A.** One searcher *empirically ran a workflow* and
   found `node_output.prompt` present; another *inferred from a stale code comment* that it's never
   written. I resolved it by reading the source myself: `LLMNode.post` **does** write
   `shared["prompt"]`/`["system"]` (`nodes/llm/llm.py:1240-1249`) — it's the **parallel-batch
   capture seam**. So `node_output.prompt` is **load-bearing, not dead.** Change A's "drop two dead
   fields" is wrong on one of the two.
3. The user's simplicity directive + my own measurement then collapsed the decision:
   **interning subsumes Change A** (the dupes become refs to one blob), and Change A's *only*
   independent benefit (peak memory) is **theorized, not observed** (and interning-at-dump wouldn't
   fix it anyway). ⇒ **interning-only.** Field surgery = permanent complexity for a non-problem.
4. I surfaced **compression (gzip)** as "the thing the issue glossed over" — it's strictly simpler
   and smaller. The user killed it on the **searchability** requirement. Clean, principled rejection.
5. Discovering **`minimize-trace-fixture.py`** (the 135-line, ~60-hardcoded-key hand minimizer) was
   the clincher: it's a lossy, workflow-specific, hand-maintained version of *exactly* what
   interning does generically and losslessly. Its existence is the argument for the feature. It also
   gave me a real file to measure on.

---

## Hard-won / things that almost tripped me up

- **`pflow-codebase-searcher` does NOT exist as an agent type in this harness**, even though CLAUDE.md
  mandates it and forbids `Explore`. Available types: `claude, claude-code-guide, Explore,
  general-purpose, Plan, statusline-setup`. I used **`general-purpose`** as the searcher (same tools,
  keeps file dumps out of context). You'll hit this too — do the same; do NOT use `Explore`.
- **Subagents can die mid-run.** One of mine returned `API Error: socket connection closed` after 15
  tool calls with no result. I re-ran it. If you fan out, check that each actually returned content.
- **Code comments lie here too.** `workflow_trace.py:554-555` literally says "The LLM node does NOT
  write 'prompt' to shared" — and it's *false* (contradicted by `llm.py:1240`). This caused the
  cross-agent confusion. The manifesto's "trust code over docs" extends to **trust code over code
  comments.** (I noted in the plan you might fix this comment while in the file.)
- **The L-8 "53MB→12MB" number is unreproducible prose.** No committed raw trace, no committed trim
  script. Do not cite it as fact. The real, measured number is in the plan (§2): ~40% of large-leaf
  bytes are exact dupes *on the already-cleaned 9.4 MB file* — so the raw win is bigger.
- **The interning threshold is a non-issue.** I measured 256 B vs 2 KB and it barely moves. Don't
  let anyone turn threshold-tuning into a research project. ~1 KB, one constant, done.

---

## Assumptions & uncertainties (verify during implementation)

- **NEEDS VERIFICATION — purity:** make `intern_blobs` return a *copy* (don't mutate `trace_data`).
  I'm ~90% sure `save_to_file` builds `trace_data` fresh so mutation would be harmless, but a pure
  function is safer and matches the "blobs only exist on disk, in-memory always plain" invariant the
  whole design rests on. If interning ever mutates in-memory data, the literal-content assertion
  tests (`test_trace_integration.py`, etc.) will break — and that breakage is your signal that the
  encapsulation leaked.
- **ASSUMPTION — the 3 read sites are the only disk trace readers.** Searchers grepped and found only
  `workflow_trace.py:105`, `trace_loading.py:159`, `trace_report.py:633` (+ filename/metadata-only
  globs + an MCP `trace_path` echo with no content read). Re-grep `json.load` / `workflow-trace` /
  `glob` / `~/.pflow/debug` before you finalize, in case the tree drifted.
- **ASSUMPTION — committed fixtures won't change.** Their leaves are < 1 KB so interning likely emits
  `blobs: {}` and identical events. I did NOT run `_generate` to confirm. The drift-guard test
  (`test_trace_tree.py:308`) will tell you. Regenerate+commit only if they actually change.
- **UNCLEAR — empty-blobs convention:** always emit `"blobs": {}` vs omit when empty? Either works;
  I lean "always emit" (simpler, one code path). Pick one, test it, move on.

---

## Unexplored territory / might matter

- **MIGHT MATTER — pathological user content shaped like a ref.** `resolve_blobs` keys off a dict
  whose keys are exactly `{"$blob"}`. If a workflow legitimately produces a dict `{"$blob": "x"}` as
  output, resolve could misfire. Astronomically unlikely, but the issue *chose* the literal `"$blob"`
  key. If you want zero doubt, a more unique sentinel (e.g. `"$pflow_blob"`) costs nothing — but
  deviate from the issue only deliberately and note it.
- **CONSIDER — `json_output` and `warnings` top-level fields** are also large and *will* be interned
  by the generic walk. That's fine/desirable, just be aware they're in scope (don't add special-case
  exclusions for them — generic recursion is the point).
- **MIGHT MATTER — future MCP "read trace" tool.** Today the MCP server only echoes `trace_path`. If
  anyone adds a tool that reads trace *content*, it must go through `load_trace_file`, or it'll see
  raw `{"$blob"}` refs. The single-loader design is what protects against this — preach it.
- **UNEXPLORED — the misleading-comment fix at `workflow_trace.py:554-555`.** Worth correcting while
  you're there; it actively misleads (it misled a subagent).
- **CONSIDER — peak-memory pushback.** Someone reading the issue/braindump may insist Change A is
  required "for peak memory." Be ready: the *observed* problem is 100 MB files; peak memory is
  theorized with no evidence; interning-at-dump doesn't address it anyway; it's a separate
  producer-side change *if* ever measured. Don't get talked into field surgery.

---

## What I'd tell myself / for the next agent

- **Start from `HANDOFF-AND-PLAN.md`, not from the issue.** The issue has three factual errors
  (5 gates not 4; fixtures on 2.2.0 not 2.4.0; `node_output.prompt` not dead). The plan corrects
  them.
- **Do NOT re-run the 6 searchers.** Their verified output is already distilled. Re-deriving wastes a
  context window. Only re-grep the specific things flagged "verify" above.
- **Honor "Show Before You Code" (CLAUDE.md).** For Phase 1, show the user a tiny before/after of a
  trace snippet (inline content → `{"$blob": h}` + a `blobs` entry) *before* or *with* the
  implementation. This user wants to see the concrete shape; they think in examples.
- **Match this user's register: reason out loud, surface alternatives, flag what you didn't check.**
  Don't present a finished plan and ask yes/no. They want to think with you and they reward "here's
  what we haven't considered."
- **The simplicity bar is real and specific:** two pure functions, one write choke point, one read
  choke point, generic recursion, no consumer/`TraceTree` changes. If your design grows special
  cases or touches many files, you've drifted from what the user asked for — stop and simplify.
- **Don't touch git** without explicit instruction (hard CLAUDE.md rule; user commits, never the
  agent).

---

## Relevant files (only the ones that carry tacit weight; the rest are in the plan's reference card)

- `scratchpads/issue-382-shrink-trace-interning/HANDOFF-AND-PLAN.md` — **the** factual source. Start here.
- `.taskmaster/tasks/task_133/task-133.md` + `starting-context/braindump-storage-architecture-session.md`
  — the architecture decision record the user told me to read myself. Most authoritative on scope
  (merge rejected; #382 = interning on current tree; streaming deferred).
- `.../task_159/baseline/10-live-recordings/05-gemini-lyrics-generator/minimize-trace-fixture.py`
  — the hand-rolled precedent. Read it once; it makes the whole feature click.
- `nodes/llm/llm.py:1240-1249` — the batch seam that makes `node_output.prompt` load-bearing (the
  thing the issue got wrong).

---

> **Note to next agent**: Read this document *and* `HANDOFF-AND-PLAN.md` fully before taking any
> action. When ready, confirm you've read and understood by summarizing the key points (especially:
> interning-only / no-gzip / searchable; `node_output.prompt` is load-bearing; the user wants
> simple-for-AI code and reasons *with* you), then state you're ready to proceed.
