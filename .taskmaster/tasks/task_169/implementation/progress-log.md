# Task 169 — Progress Log (design & planning)

> **What this file is:** the tacit knowledge from the design + planning process — *why* decisions
> landed where they did, what was tried and rejected, and what nearly bit us. It is the complement
> to the other three artifacts; it deliberately does **not** restate them:
> - `task-169.md` — the spec (what/why, requirements).
> - `implementation/implementation-plan.md` — the how (endpoints, resolver, phases, tests, anchors).
> - `context/CONTEXT.md` — the glossary (Viewer, Point, Watch, Auto-update).
>
> Read those for *what to build*. Read this for *why it's shaped this way and where the bodies are
> buried*. Status as of this entry: **planned + deep-reviewed, not yet implemented.**

---

## 2026-06-19 — Planning & design session (no code yet)

### The one decision a future agent will most want explained: resolution lives in the SERVER

The plan says "the server parses the target → resolves to a structural `RFRef` → the browser maps it
via `sameRef`." That is **not** the obvious choice, and we arrived at it by reversing an earlier one.
The journey, so nobody re-treads it:

1. **First instinct:** validate the node server-side (build the graph, check it exists).
2. **Rejected → "resolve in the frontend only":** the frontend already has `resolveNodeFlatId`/
   `sameRef`; re-implementing node addressing in Python would be a *second source of truth* that
   drifts — exactly the validation-vs-runtime drift this codebase hunts for. So: server stays a dumb
   pipe, broadcasts the opaque target string, the browser resolves. Agent learns the result by
   *screenshot* (the "see" leg already exists).
3. **Reversed → "resolve in the server, to a structural `RFRef`":** the frontend-only design forces
   the agent to screenshot-and-eyeball to learn "did it hit? how many matched?". For an agent-first
   tool that's worse than a structured answer. The key unlock: the server resolves the *agent's text*
   to a **structural identity** (`node_id`+`ancestor_path`+`port`), and the browser maps *that* to its
   on-screen flat id via its **existing** `sameRef` — so there is still only **one notation parser**
   (Python), no drift, the report is **synchronous + structured**, and the parser is unit-testable
   without a browser. The browser became a dumb display after all, just keyed on structure not text.

**Load-bearing principle that fell out of this:** flat ids (`n3`/`g2`/`e7`) are positional and
unstable, and the server's fresh render ≠ the browser's live render. **Only structural identity is
valid currency between two independently-rendered views.** If you ever find a flat id crossing the
SSE wire, that's a bug.

### The insight the deep-review forced (and the lesson for the deferred work)

The agent-facing **address string was lossier than the `RFRef` it described** — it dropped `port`
(IO in/out) and `batch_index`. Consequence: an input `data` and an output `data` both stringified to
`data`; batch items 0 and 1 both stringified to `fanout.gen`. The "ambiguous → here are the qualified
scopes → re-point" loop then dead-ends, because the qualify list is *identical strings*. Fixed in the
plan (`in:`/`out:`, `[batch_index]`).

**Reusable lesson (applies to every deferred fast-follow too):** an agent-facing identity string must
carry **everything** the structural identity carries, or self-correction can't converge. When you add
standalone-row or control-edge addressing later, re-check this invariant first.

### The design philosophy that drove half the small decisions: the self-correcting loop

The user articulated it as *"agents see this happening and can prefix with the subworkflow name if
they need to."* The agent doesn't have to be precise on the first point — it points, observes (the
structured report's qualified scopes, or a screenshot), and re-points. This single idea decided:
- **ambiguous → report, never guess** (a wrong point is worse than no point);
- the **qualify list must round-trip** (each entry resolves to exactly 1 — now a required test);
- **structured/parseable output** matters more than a pretty point, because the *report* is the
  feedback channel that closes the loop.

### Scope calls and the reasoning the spec doesn't carry

- **Edges are in v1 by the user's explicit choice, against my recommendation to defer.** Verification
  showed edges are the costliest target (no field-level structural identity; a frontend edge-by-
  endpoints lookup the existing code deliberately marked *"deferred"*; and a collapse/re-anchor case
  where the discrete edge doesn't exist). I recommended shipping nodes+containers+IO and fast-
  following edges; the user chose to include edges. So the cost is **known and accepted**, not
  overlooked — budget for the real-browser verification of the `data.from`/`data.to` keying.
- **Why standalone body-rows are deferred (not just "later"):** `RFRef` has no field-level identity —
  it reaches node + in/out side, not "the `prompt` row of `summarize`." Addressing a row *alone* needs
  a richer descriptor. (Rows are still reachable *as edge endpoints* — that's why edges work but
  standalone rows don't.)
- **Why control/branch edges are deferred:** they have no `${ref}` to name them by, and they hit the
  same collapse/re-anchor fragility. The `data_flow`-only restriction is coherent, not arbitrary.
- **Per-window visibility is full (not count-only)** because it serves the *originating* "I can't find
  it" moment directly — "it's in a backgrounded tab, switch over" is the actual help. The cost is one
  conn-id + a tiny visibility POST, which we needed for registry cleanup anyway.
- **Watch buffer is one global tagged ring, not a per-workflow dict** (the spec says "per workflow").
  Observably equivalent, less structure; supports the "what did the user just touch, anywhere" case.

### The concurrency landmine (most important thing for whoever writes the SSE endpoint)

The "all handlers async → single loop → no locks" claim is **correct for the design and the shipped
stack**, verified at ASGI level. But the disconnect cleanup has a **latent, version-dependent trap**:

- A bare `try/finally` around `await queue.get()` only fires on a silently-dropped tab when
  `StreamingResponse` runs under ASGI **`spec_version < 2.4`**. Today's stack (plain `uvicorn` 0.35,
  h11 → spec 2.3) takes that branch, so it *works today*.
- The moment anyone installs `httptools` / `uvicorn[standard]` / bumps uvicorn to a 2.4+ path, the
  generator blocks on `queue.get()` forever and **connections leak** — silently inflating the very
  delivery counts this feature exists to report. The `>=0.30` floor does **not** pin this.
- Fix (in the plan): a periodic **keepalive `yield`**, which forces a `send()` so a dead socket
  surfaces on *either* ASGI version. **Do not "simplify" it to `request.is_disconnected()`** — on the
  spec<2.4 path `StreamingResponse` already consumes `receive()`, and a second consumer is undefined.
- **Testing trap:** Starlette's `TestClient` **cannot** deliver `http.disconnect` to an infinite SSE
  generator, so a `client.stream(...)` "cleanup" test passes **green without testing cleanup**. Test
  cleanup via `_Hub` units + a raw-ASGI disconnect injection. (This is exactly the kind of
  synthetic-fixture-matches-happy-path false confidence to avoid.)

And the future-facing one: the no-locks invariant is **unenforced**. A later "stats" endpoint written
as a sync `def` that reads `app.state.hub` would run in a threadpool and race the loop. The plan puts
a hard comment naming this failure at `_Hub` and the route list — keep it.

### Spec-vs-code discrepancies found (trust boundary — don't trust the spec's specifics blindly)

The spec is directionally right but had stale specifics. Verified against code:
- "no-CORS security comment ~line 126" → actually **`server.py:279-287`** (line 126 is an unrelated
  400 branch). And that comment *already* anticipated "any mutating/live-run endpoint must revisit
  this" — it foresaw us.
- "the `?focus=` URL param exists" → yes in the **frontend**, but the **CLI never emits it** today;
  `--open` adds it.
- "focus produces incoming/outgoing edge highlighting" → imprecise. Focus does **symmetric** incident
  reveal/dim + a per-edge source/target *fade hint*, not separate in/out edge sets. Substance (the
  connected edges light up) holds.
- A `--no-watch` serve flag existed that the spec never mentioned — found during exploration, now
  renamed `--no-auto-update`.
- `WorkflowManager.get_path(name)` does **not** raise on a bad name — it returns a *phantom* resolved
  path for any string. Gate name→key normalization with `exists()`, or a typo silently maps to a key
  no window will ever match (reported as a misleading "0 windows").

### Smaller rejected alternatives (so they're not re-proposed)

- **Plain `@click.group` + positional `WORKFLOW`** — the obvious restructure. It's *broken in Click*
  (reproduced in review: both the new verbs and the existing `pflow ui <wf> --no-open` fail). Must use
  a custom `UiGroup` mirroring `PflowCLI`. Don't retry the plain group.
- **WebSocket** — nothing needs a bidirectional socket; SSE (down) + plain POST (up) is enough and is
  the transport shape the overlay was always named for.
- **`navigator.sendBeacon`** for the interaction report — rejected: it sends a CORS-safelisted content
  type, which would *bypass* the `application/json`-forces-preflight cross-origin defense. Use
  `fetch(keepalive:true)` with a JSON content-type.
- **`--output-format json`** on the verbs — there's no such convention for subcommands; the repo idiom
  is a boolean `--json` + inline `json.dumps` (like `list.py`).

### Why this is also the overlay's transport (don't let it rot)

This channel is the live-run overlay's (Task 133) future transport. The single rule that keeps the two
tracks decoupled: **the SSE envelope stays vocabulary-agnostic** (`{type, ...}`) and this task defines
**no run-event schema**. If you find yourself baking interaction-message assumptions into the bus
plumbing, stop — the overlay adds its own `type`s over the same pipe later.

### For implementation: do Phase 0 (the ADR) before code

The server going stateful + push reopens a *recorded* "read-only, stateless, no side effects" decision
(`server.py:279`, `ui/CLAUDE.md`, ADR-0005). Write the amendment first, or a future validation-
consistency review will (correctly) flag the stateful server as an unjustified regression.

---

## 2026-06-19 — Apply model: the "sent vs shown" correction (and why there is NO ack channel)

A contradiction surfaced after the deep-review (the user caught it; it was *my* planning over-reach):
the plan reported a command's outcome at the moment the message was **queued** to the SSE connections,
yet *also* promised browser-determined outcomes back in the command response — e.g. it literally said
"the command's window entry notes 'target hidden'". There was **no channel** for the browser to report
that, and the word "delivered" quietly conflated **queued** with **shown**. So the CLI could report
success while the user's screen showed nothing.

We considered building command **acknowledgments** (command id → each Viewer POSTs applied/failed →
the CLI waits a bounded time and returns per-window outcomes). **We deliberately did NOT.** The cleaner
resolution — which the user steered — is two rules that make the report honest without a protocol:

1. **The server validates before sending** → a bad target never broadcasts; it returns a *great error*
   (not-found + fuzzy suggestions / ambiguous + qualified scopes / 0 windows). All server-knowable.
2. **The browser always reveals a resolvable target** (total apply: focus/edge/frame expand collapsed
   ancestors; edge focus un-hides in beautiful). So "exists in the view → shown" holds without a
   confirmation round-trip.

The report now says **`sent_to` N windows (+ per-window visible/backgrounded)** — never "shown".

**The insight that makes acks unnecessary in v1: the human is the acknowledgment.** This is a
*conversation* — the agent points, says "see it?", and the human says yes/no. Two corollaries a future
agent must not forget:
- The screenshot skill drives the **agent's own** headless browser, **not the user's window** — so it
  can never confirm the point landed in the user's Viewer. Don't reach for it as proof.
- The only residual gap is a **stale browser view** (~1.5s after an edit, before Auto-update
  refreshes): a just-validated target may not be in that window yet → nothing shows. It **self-heals**
  on the next poll and the human re-points. A transient, not a failure mode worth a protocol.

**When acks WOULD be worth building (deferred fast-follow):** an autonomous/no-human flow that must
programmatically confirm "shown", or the run-overlay (which would define its own confirmation). Until
such a consumer exists, building it would violate the same "build it when a consumer exists" discipline
that deleted the original SSE stub. The envelope is generic, so an `applied`/ack message type is purely
additive later — no rework.

**Meta-lesson for the next agent:** don't add a confirmation protocol when a human closes the loop.
"Validate hard up front + always reveal + report honestly" beats "do it blind, then build machinery to
check whether it worked."

---

## 2026-06-20 — Phase 1 implementation started

Scope is intentionally server-only: the in-memory hub, target resolver, five interaction endpoints,
security note, and Python tests. Baseline before code: `tests/test_cli/test_ui.py` plus the React Flow
renderer suite produced **73 passed, 3 failed**; all three failures require binding a localhost socket,
which this sandbox denies (`PermissionError`) before project code runs. Phase 0's ADR-0007 was the only
pre-existing worktree change and is being preserved.

Phase 1 complete. The hub is per-`create_app()` and loop-owned; SSE uses a 15-second keepalive send so
disconnect cleanup is ASGI-version-independent. Name/path subscriptions converge on one resolved key,
and Point validation resolves only to structural refs. One necessary plan correction: edge descriptors
now include `source_path`. Existing `RFEdge.output_path` is part of edge identity, so omitting it made
distinct sub-key edges resolve to different addresses but become indistinguishable after broadcast.
No frontend or CLI code was changed; their wiring and user-facing docs remain in their planned later
phases rather than documenting a partial surface.

Verification: **21 focused tests passed** (including real nested/batch renders and raw-ASGI SSE
broadcast+disconnect), **94 relevant regressions passed**, pre-commit/Ruff, full mypy (237 files), and
deptry passed. Near-full sandbox run: **8030 passed, 18 skipped** after excluding ten environment-only
cases (Homebrew `uv` panics before Python or localhost socket binds denied); an unfiltered run confirmed
the four additional exclusions fail inside Homebrew `uv`, not project code.

---

## 2026-06-20 — Phase 2 implementation started

Scope is frontend-only: the SSE/reporting API seam, structural target mapping, total reveal before
focus/frame, and deliberate-interaction reporting. Lockfile dependencies restored with `npm ci`;
baseline before edits is **40 test files / 509 tests passed** plus a clean TypeScript typecheck. Real
browser verification is required after the bundle build because jsdom does not render edge geometry or
prove camera behavior.

Phase 2 complete. `events.ts` validates the vocabulary-agnostic SSE envelope, tracks reconnect-issued
connection ids/visibility, and makes interaction POST failures inert. Graph mapping uses full `RFRef`
identity; Point expands collapsed ancestor chains before focus/frame, edge focus reveals both endpoints,
and frame is camera-only and paint-deferred when reveal changes layout. User clicks, row/chip focus,
clear, view toggles, and workflow open report structural + local flat identity; agent commands do not
echo into Watch.

Two implementation refinements from seam verification: (1) subscription starts only after the graph is
loaded, so `--open` cannot count a Viewer that is not yet able to apply its first command; (2) edge
resolution first finds the browser's contract `RFEdge` by original endpoint refs + fields + full
`source_path`, then focuses that local edge id after reveal. This is simpler than searching the current
FlowEdge by render anchors and preserves the plan's load-bearing rule: re-anchored `edge.source/target`
are never used as identity.

Verification: **41 frontend files / 521 tests passed** (baseline +12), TypeScript typecheck and two
production `make ui-build` runs passed, plus **94 Python UI/renderer regressions**. A real headless Chrome
run successfully subscribed, accepted focus/frame commands (`HTTP 200`), dispatched a real node click,
and produced `/private/tmp/pflow-shots/task169-phase2-live-200.png`; the final image shows the clicked
`process-small` selection/panel after the command sequence. Its final result-aggregation node had a local
MCP-result type mismatch; the corrected rerun was blocked by the environment execution quota, so the
intermediate focus-vs-frame DOM JSON could not be recovered. Unit/jsdom tests directly pin that state
transition; the remaining live-verification limitation is explicit rather than inferred away.

---

## 2026-06-21 — Phases 3–4 complete

The CLI now preserves bare `pflow ui [workflow]` through a custom `UiGroup` while adding `focus`,
`frame`, `clear-focus`, and `user-activity`; all verbs support structured JSON failures and actionable
no-server/zero-window output. Unresolved, ambiguous, zero-window, and open-timeout Point outcomes exit
nonzero so shell/agent callers cannot mistake a no-op for success. `--no-watch` is renamed
`--no-auto-update` without changing the private
`?watch=0` contract. Server/frontend/CLI docs now describe the stateful hub, target grammar, security,
and deferred boundaries; Task 169 is marked done.

One plan deviation was necessary after seam verification: `focus --open` re-posts every target after
the Viewer subscribes, not only edges. Load-time `focus=` accepts bare node/flat ids but not qualified
nested or `in:`/`out:` addresses; retrying the already-validated structural command keeps one parser and
makes all target types reliable. Review also found and fixed reconnect-stale visibility, stale deferred
camera frames, non-round-trippable nested IO output, blocking graph builds on the hub loop, unbounded
connection queues, unknown-workflow Watch ambiguity, and production-inaccurate fixtures. Control-edge
identity remains deferred by plan; data-edge `frame` remains camera-only, while `focus` reveals the line.

Verification: **76 focused Python UI tests passed** (including localhost lifecycle tests), **523 frontend
tests passed**, production build/typecheck passed, and the full non-LLM suite passed **8077 tests** after
excluding one confirmed Homebrew-`uv` environment failure (`test_dry_run_json_mode_emits_no_stderr`;
`uv` cannot spawn `pflow` from its temporary cwd). Pre-commit, full mypy (237 files), deptry (240 files),
and docs tests passed. Phase 2's real Chrome Point/Watch run remains the live-browser evidence; the final
same-page rerun also passed using `scratchpads/task169-live-rerun/point-watch-rerun.pflow.md`: CLI
clear/focus each reported `sent_to: 1`, a real pointer drag moved the canvas, repeated focus restored the
node on-screen with its focus ring/panel, and Watch returned the real `node_click` with structural ref,
flat id, and view state. An earlier false negative mutated only the viewport DOM style (desynchronizing
React Flow's internal camera state); replacing it with a real pointer drag made the check production-faithful.

---

## 2026-06-21 — Independent review pass + post-review fixes (PR #527)

The staged implementation was reviewed independently (not by its author): four specialist agents in
parallel (concurrency, agent-ux, feature-interactions, test-fidelity) plus a direct read of `server.py` +
`targets.py`. Verdict: faithful to the plan, **0 Critical**, and — notably — the three self-reported
deviations all held up and each closed a real PLAN gap:
- the edge descriptor's `source_path` (without it the plan would broadcast sub-key edges indistinguishably);
- `--open` re-posting *every* target, not just edges (load-time `?focus=` can't parse qualified addresses);
- subscribing only after the graph loads (so `--open` can't count a not-yet-ready Viewer).
The reviews confirmed the load-bearing claims in the actual code: async-only/no-locks holds, the SSE
keepalive disconnect is correct, the address grammar carries full identity, and the tests are real
(raw-ASGI disconnect — not TestClient theater; qualify round-trips; production-faithful fixtures).

Three fixes applied on top (commit `378cd952`):
1. **Edge-dedup "shown-nothing"** (the one review Warning). The frontend FlowEdge dedup key excludes
   `output_field`/`output_path`, so two field-level data edges between the same nodes collapse to one
   line in beautiful — and a Point at the deduped-away one focused an id that was never rendered →
   nothing lit. Fixed at the dedup seam: the build records dropped ids on the kept edge's
   `data.mergedIds`, and `applyFocus` matches a focused id against `e.id` OR `mergedIds`. Paint-safe;
   GraphView needed no change. A synchronous fallback in `applyPoint` was rejected — at apply time the
   `edges` snapshot is pre-reveal, so it can't tell "deduped, stays deduped" from "collapsed, reveal
   will build it".
2. **CLI second-grammar drift** (test-fidelity finding). The Watch display re-implemented the address
   grammar in `ui.py` — the exact "two sources of truth" the plan's one-parser rule forbids. Moved it
   into `targets.py` (`_format_ref`/`_format_target` + tolerant `address_for_*`); `ui.py` delegates.
   Byte-identical (existing tests green) + a new round-trip drift guard.
3. **Keepalive coverage.** Added a raw-ASGI test that an idle connection emits the `:` keepalive (what
   surfaces dropped sockets on ASGI ≥2.4). Deliberately NOT a send-failure-finalization test — that
   path depends on asyncio async-gen finalization subtleties and would be fragile/theater.

Skipped, per the reviewers' own guidance: moving `render_react_flow` off-loop (the concurrency reviewer
judged the current split better than the plan's wording), the stdout/stderr split (defensible), and an
off-loop-build *behavior* test (low marginal value over the mechanism assertion).

Correction to an earlier note in this log: the Phase-1 "sandbox denies localhost socket binding" claim
was the *original implementer's* environment — **verified false here**. The full Task 169 Python set
(78 tests, including the socket/port-probe ones) passes in this environment with 0 skipped.

Verification: ruff + mypy clean; **78 Task 169 Python tests pass**; tsc clean; **524 web vitest pass**.
Shipped as **PR #527** (`04faa88e` implementation + `378cd952` review fixes). The distilled
invariants / patterns / gotchas now live in `task-review.md`.

---

## 2026-06-22 — Post-merge dogfooding: Point address grammar aligned to the file's vocabulary

Rebased the branch onto `main` (linear; only `CLAUDE.md` roadmap conflict — `main` had reorganized the
overlay track into 172→169→173) and force-pushed. Then **used the feature as a fresh agent** against
`examples/advanced/content-pipeline.pflow.md` and immediately tripped on the address grammar — the
exact failure the spec exists to prevent, hit by its own author.

### The root cause (the one thing the next agent must internalize)

The Point grammar had invented a **parallel naming notation** that diverged from the `.pflow.md` the agent
already reads:
- the file says `source_file` under `## Inputs`; the grammar demanded `in:source_file`.
- the file shows `read_source` consuming `${source_file}`; the grammar's `source.field -> target.input`
  shape gave no hint the input end keeps its `in:` prefix.

So the mistakes were **translation errors between the file's vocabulary and a made-up second notation**,
not missing information. This is the *same* "two sources of truth" drift this codebase hunts elsewhere —
here, "what is this element called" had two answers.

### First instinct was a bandaid; the real fix is subtractive

I initially added a `pflow ui targets <wf>` command to *list* the addresses (so an agent could read them
instead of guess). The task owner correctly called it a bandaid: **the `.pflow.md` IS the target list** —
a command that re-prints it fails the deletion test. The honest fix is to *delete the divergence*, not add
a surface that bridges it. So `targets` was **added then removed** (don't re-add it without reading this).

### What changed (all in `src/pflow/ui/targets.py` + `cli/commands/ui.py`)

- **Bare IO names resolve** (`_node_addresses` now returns the full alias set incl. the unprefixed name;
  the canonical prefixed/scoped form stays as the `qualified`/report value). `in:`/`out:` only surfaces in
  the **qualify list** when an input and output genuinely share a name — same self-correcting loop as a
  bare node name duplicated across two sub-workflows. Edges compose from the unprefixed endpoints, so
  `source_file -> read_source.file_path` (my original miss) now resolves.
- **Shape-aware not-found suggestions** (`resolve_target` 0-match arm): an edge attempt (`a -> b`) is
  fuzzy-matched against real **connections**; a name attempt against **all** node/IO names (the old pool
  excluded ports → an input typo used to suggest a random step).
- **Orientation hint on the dead-end** (`_render_dispatch`): when there is **no** near-miss, append
  "Targets are names from the workflow file: a step, input, or output, or a connection `source -> target`"
  — rescues the fundamental-mismatch case that used to print a bare "not found." (a real typo still gets the
  terse `Did you mean: …`).
- **`--json` → project-standard `--output-format [text|json]`** (default `text`) via a tiny `_wants_json`
  callback that maps onto the existing internal `output_json: bool` — zero signature/body churn. The CLI was
  split (6 commands on `--output-format` incl. flagship `run`; 3 on `--json`); the plan's rationale for
  `--json` ("no `--output-format` subcommand convention") was **inaccurate** (`probe`/`settings` use it).
  `list`/`mcp` remain on `--json` → tracked in **GH issue #528** (option B: ui now, sweep the rest later).
- **`workflow key:` → `workflow:`** in agent-facing output (internal-vocabulary leak), + the empty
  `user-activity` message.
- **Docs** now say it outright — guide `visualization.md`, `ui/CLAUDE.md`, CLI reference: *"a target is the
  name you already read in the `.pflow.md` — there is no separate notation to learn."* Per-command `--json`
  mentions stripped (it's an assumable universal escape hatch; text is the agent's read surface, JSON is for
  scripting — don't push agents toward JSON).

### Verification

- `make check` clean (ruff, ruff-format, mypy 237 files, deptry); **`make test` 8055 passed**.
- **Fresh-agent cold-use test** (a context-free general-purpose agent, docs+help only, barred from source):
  focused a step, an input, AND an edge **all first-try, zero misses** — "it was easy." Its one honest flag:
  the guide's input-edge example happens to be drawn from the same workflow it was tested on, so the example
  doubles as the answer; it verified the rule held independently. (Left as-is; the guide also carries the
  generic `gen.response -> summarize.prompt`.)
- Real browser Point/Watch confirmed live (step/input/edge focus, per-window visible-vs-backgrounded
  reporting). A **background-tab apply glitch** was reported once ("not highlighted correctly") but did **not
  reproduce** under a controlled edge→node-while-hidden repro — concluded transient (rAF throttled in hidden
  tabs frames the camera late), not a deterministic bug. Not formally closed; re-test if it recurs.

### Sub-workflow addressing (answered for the record)

Reference a nested element by the **container step's name**: `create.echo`, ports `in:create.data` /
`out:create.data`, batched `create[0].name`; or just try the bare name and let the ambiguous→qualify list
hand you the scoped forms. The scope segment is the `### create` `type: workflow` step — read from the file.

**Standalone fields are NOT addressable alone** (deferred body-rows): `read_source.file_path` typed bare →
"not found, did you mean: read_source" (redirects to the step). The field is only addressable as a connection
endpoint (`X -> read_source.file_path`). Left as-is — the redirect is the sensible recovery.

Status: **committed on `feat/agent-browser-interaction` (single follow-up commit), not yet pushed.** These
changes sit on top of the rebased PR #527.

---

## 2026-06-22 — Dogfooding polish round 2 (F1/F2/F4/F5/F6) + two agent-UX reviews → pushed

> Same day as the grammar entry above, separate session. That entry's "not yet pushed" is now resolved: the
> grammar commit (`3bb89fd5`) shipped together with this polish as `ab891ad2 [skip review]` — **PR #527 now
> has 7 commits.** Trust boundary: the implementation and the A2 debunk are **[authored/verified]** here; the
> two reviews are `review-agent-ux` subagent passes (read end-to-end, conclusions re-checked against code).

### The method, because it paid off: a before/after review sandwich
Drove the feature cold as a fresh agent, then ran **two `review-agent-ux` passes** — one on the **committed
baseline** (read `HEAD` via `git show`, NOT the working tree, so it's a true pre-change picture) and one on
the **changes**. Baseline scored **3.5/5**, the changes **4.5/5**. The split is the point: the baseline review
caught a leak my own (contaminated) read missed (F6 below). Reviewing only your own diff is grading your own
homework — the baseline pass is what makes the delta honest.

### What landed and the why that isn't in the spec
- **F2 — the success *report* must speak the file's vocabulary, not just resolution.** Typing the file's bare
  `source_file` resolved fine, but the echo said `resolved 1 (in:source_file)` — re-teaching the exact
  `in:`/`out:` notation the grammar fix worked to delete, and `in:output_file` (an input literally named
  `output_file`) read as a contradiction. Fix: on a unique match, drop the side-prefix **iff the bare form
  still resolves to exactly one element** (`targets.py` `_drop_side_prefixes` + a uniqueness guard in
  `resolve_target`). The guard is load-bearing — naively stripping breaks the collision case (a typed
  `in:data` in an in/out collision must stay `in:data` or it stops round-tripping). The qualify list keeps the
  prefix where it disambiguates.
- **F1 + F6 — two complementary `None`-repr leaks in `_render_activity`, found by different eyes.** I caught
  `workflow: None` (no-arg `user-activity`); the **baseline review** caught `· focus None` (any unfocused
  Watch event — the most common one). Same class, same function, neither of us saw both alone. Fix:
  `_echo_workflow_key` suppresses the null line; view-state fields fall back to `none`/`unknown`.
- **F4 — `pflow guide ui` was a dead topic; the command name and its docs disagreed.** Same "two names for
  one thing" smell as F2. Renamed the topic `visualization → ui` (canonical, matches the command), kept
  `visualization` as an alias (the existing `_TOPIC_ALIASES` idiom; it's still the accurate concept word),
  aligned the H1 + `entry.md` menu. `ui` was *already* a reserved workflow name (it's a CLI command) — the
  linter deleted my redundant add to the reserved set, which is the correct signal, not a problem.
- **F5 — the visible/backgrounded line was a *stat*, not an *instruction*.** The user's "can we explain this
  better?" wasn't about the vacuous `(0 visible, 0 backgrounded)` at 0 windows (dropped that too) — it was
  that the report never said what to *do* about "all backgrounded." Added the actionable hint ("the Viewer is
  a background tab — tell the user to switch to it"). Delivery report extracted to `_render_delivery` (the new
  branch tripped C901; the split also reads better — dispatch decides not-found/ambiguous/delivered, delivery
  owns the who-got-it report).

### The most important judgment call: A2 was a non-bug — verify the reviewer
The baseline review's one "critical" finding: `focus --open` timeout "exits 0 while nothing was delivered."
The user approved fixing it. **It's false.** `_dispatch_failed` returns True on `sent_to==0` (ui.py:209) and
runs on *every* path including the timeout (ui.py:483) → it exits **1**. The reviewer misread the control
flow. Verified by direct read before touching code; did **not** implement the approved "fix." Lesson
(reinforcing the manifesto): a same-model reviewer cites well but you own the conclusions — and "the user
approved it" does not override "the code says otherwise." A2's other sub-points are defensible (text output
goes to stdout like the rest of the report; `target!r` correctly quotes edge targets that contain spaces).

### Left deliberately (so they're not re-litigated)
- **Focus-echo vs activity-display prefix asymmetry**: `focus` now echoes `source_file`, but `user-activity`
  still shows `in:source_file` for a clicked port. Both round-trip into `focus` (verified); the activity line
  has no graph to run the uniqueness check against, so the prefixed form is the safe default. Review B: leave.
- **F3 exit-code granularity** (bad-target vs resolved-but-0-windows both exit 1): left. The *message*
  distinguishes them crystal-clearly in text AND JSON; the exit code is a coarse "did it land" backstop. The
  user settled it: an agent reads the message, not just `$?`.
- Review-A minors untouched: generic JSON/server-error fallbacks (A4/A5, only `ConnectError` is gold-standard),
  mid-edit-held guide note (A7), clear-focus-to-0-windows exit code (A8/F3-adjacent).

### Verification
`make check` clean (ruff, mypy 237, deptry); **`make test` 8063 passed** (+4 regression tests: F2 prefix-
retention guard, F1 no-None, F5 ×2, F6, F4 alias). F1/F2/F4/F5 confirmed live on a fresh server; F6 pinned by
a unit test (a real focus-null event isn't reproducible from the CLI). Shipped `ab891ad2 [skip review]`,
pushed; PR #527 → 7 commits.

### Still standing (unchanged by this detour)
The real next increment remains the live-overlay track: **172 (emit-time streamable trace producer — the
keystone every downstream task, incl. 173/164/125, consumes) → 173 (overlay UI on 169's SSE bus).** This whole
session was polish on a done feature.

---

## 2026-06-22 — SSE reconnect robustness: investigated, the "simple fix" was the wrong lever, reverted + handed off

While dogfooding Point/Watch live, the server was hot-swapped (restarted) to load the polish build. The user's
**backgrounded** browser tab then **silently stopped receiving Point** (`focus` reported `0 windows`) while
**Watch kept working** — clicks still showed up. Root cause: `web/src/api/events.ts` `subscribe()` relies
**entirely on native EventSource auto-reconnect** (no `onerror`), and a tab whose stream drops while hidden/frozen
does not reliably re-register its SSE subscription. Watch survives because its reports are **connectionless POSTs**;
Point needs the **live SSE registration**. Recovery today needs a manual page reload.

**Tried (and reverted):** a `visibilitychange → if visible && readyState===CLOSED, re-subscribe` patch in
`events.ts` (+ a jsdom regression test). It unit-tested green, but **live verification killed it** — and that's the
lesson: the CLI cannot see the browser's EventSource state, so this is unverifiable from here, and the live run was
**confounded**. Two findings:
1. **`visibilitychange` is the wrong lever.** Switching to the terminal usually keeps the tab **`"visible"`** (the
   Page Visibility API tracks the browser's foreground tab + non-minimized window, *not* which OS app has focus;
   Chrome-macOS occlusion only flips it on a *full* cover) — so the event may never fire in a browser-plus-terminal
   workflow, and the patch never runs.
2. **`CLOSED` is likely the wrong state.** A server restart leaves the EventSource in **`CONNECTING`** (native
   retrying), not `CLOSED`, so even if the event fired the check would skip.

**The reframe (user's, and it's right):** this is **not** a rare edge case for where the UI is heading — a
**persistent viewer that agents discover and reuse**. Two foundational capabilities fall out, both belonging to the
**live-overlay track (172/173, ADR-0008)**, where the SSE stream becomes *load-bearing* (a dropped connection =
missed **run events**, not just a missed point):
- **(A) Robust live connection** — driven by **`onerror`, not visibility**: reconnect to a live server when the
  stream drops *for any reason* (sleep/wake, network blip, tab freeze, restart). Trigger-agnostic.
- **(B) Server discovery / reuse** — an agent should **probe the port and reuse** a running viewer rather than
  spawn a new one (or fail on port-in-use). No discovery exists today.

**Decision:** reverted the patch (working tree clean again; the committed polish `ab891ad2` never included it),
bundle rebuilt clean. **Not fixed in this context window** (Task 172 is already in progress in another worktree).
Written up for the next agent: `scratchpads/handoffs/ui-sse-reconnect-and-discovery.md` — to be solved **properly,
real-browser-verified** (headless Chrome where `readyState`/`visibilityState`/console are observable), folded into
the overlay design. **Meta-lesson:** a browser-behavior fix that can't be verified from the CLI must be verified in
a real browser *before* shipping — a green unit test over a wrong assumption is worse than no test.

---

## 2026-06-22 — Bot-review evaluation + polish commit (PR #527, pre-merge)

Evaluated the two `claude[bot]` reviews on PR #527 (`#issuecomment-4763394321` pre-polish, `…4770265223`
post-polish). User flagged them as possibly stale — verified every finding against current code (3 parallel
`pflow-codebase-searcher` passes + direct reads of `server.py`/`ui.py`/`types.ts`/`GraphView.tsx`). Staleness
was real but only shifted **line numbers**; none of the pre-polish findings had been silently fixed. **8 findings:
6 confirmed + applied, 1 deferred, 1 disputed.**

### Applied (one commit, `[skip review]`)
- **R1-W1 — dropped the inoperative `path.suffix == ".pflow.md"` clause** (`server.py` `_workflow_key`). `Path.suffix`
  is only `.md`, so the clause was always False; behavior already rested on `path.exists()`. Took the reviewer's
  fix **(a)** (drop it), *not* (b) (`value.endswith`) — (b) would have *changed* behavior to accept non-existent
  paths as phantom keys, worse than the current "non-existent → not found." Behavior-identical; added the missing
  branch test (`_workflow_key("/no/such/x.pflow.md") is None`).
- **R2-S2 — `clear-focus` at 0 windows no longer prints the circular "→ open the workflow first"** (open a window
  only to clear focus on it?). Threaded a `clearing` flag through `_render_dispatch`/`_render_delivery`; clear now
  says "→ no Viewer open — nothing to clear." `frame`'s "open first" is left (not circular). +CLI test.
- **R1-S2 — whitelisted the recorded interaction fields** (`server.py` `interaction()`) to `(type, target,
  view_state)` instead of passing through every client key. Verified safe: `InteractionReport` is exactly those
  three (`types.ts:175`) and the GraphView callsite sends only them, so it's a no-op for the real client and only
  filters unexpected extras → predictable Watch shape for the consuming agent. +endpoint test (junk key dropped).
- **R1-S3 / R1-Nit / R2-S3 — three clarity comments only** (no behavior change): the deliberate `workflow_key=None`
  fire-and-forget choice in `interaction()` (vs `command`/`activity` 404), the `err=output_json` stdout-cleanliness
  idiom in `focus --open` timeout, and that `not opened` intentionally suppresses the background-tab nudge.

### Deferred → GH #529
- **R1-S4 — `focus --open` re-POSTs the full (graph-rebuilding) command ~60× while waiting for the new window.**
  Confirmed, but benign on the localhost `--open`-only path; the reviewer's fix (poll a cheap connection-count,
  send once) needs exactly the lightweight count/health endpoint #529's discovery/probe work introduces. Folded
  there rather than adding surface now.

### Disputed → kept as-is (user decision)
- **R2-S1 — docs no longer mention `--output-format json` for the `ui` commands.** Technically true, but the omission
  was a **deliberate** earlier decision (text is the agent's read surface; JSON is an assumable universal escape
  hatch — *don't push agents toward JSON*). The bot lacked that intent. Not staleness; the reviewer disagreeing with
  a settled call. Left removed.

Verification: `make check` clean (ruff, ruff-format, mypy 237, deptry 240); **`make test` 8066 passed** (8063 +3
new regression tests); the four Task 169 Python suites 90 → 93. No frontend change (no `make ui-build` needed).
