# Braindump: Task 175 design discussion (the tacit half)

> The task file (`task-175.md`) has the *what/why/how* and the verified facts. This captures what it
> can't: the **journey**, the **user's mental model**, the **dead-ends I went down and got corrected
> on**, and the **soft decisions** that look settled but aren't. Read both.

## Where I Am

We did NOT write code. We had a long design discussion that started as "is the D4 launch button a
security problem?" and grew into a full feature: run a workflow from the UI, with an inputs form,
inspect/re-run. The task file is written, it's in the CLAUDE.md roadmap. Nothing is implemented. The next
move is either (a) lock the open UX decisions with the user, or (b) write an implementation plan / design
note and review-gate it (the Task-173 pattern). The user wanted "full understanding before we start
writing" — we have it now.

## The User's Mental Model (use their words)

- **The simplicity lens is THE governing principle, and it's a *specific* one.** Their exact framing:
  *"We should prioritize simplicity of the FINAL code, not how easy it is to get there… whats the right
  solution that the top 10% of codebases similar to this one would implement."* And critically, the
  guardrail against the obvious failure mode: *"What this doesnt mean is overfitting to 'top 10% of
  codebases' and overengineering, this is about more simple code that is optimized for AI agents to
  understand and add features to."* → They will reject clever/heavy solutions AND gold-plating. The
  winning move is almost always "reuse the machinery that exists, stay faithful to the CLI, add the
  smallest honest thing." I got burned twice (below) for proposing more than that.
- **They think SPATIALLY about the canvas.** When I proposed a "run-level summary" panel, they pushed
  back and sent a screenshot of the input-node card, asking why clicking *that* to see its value is hard.
  The value belongs **on the node it describes**. I dropped the run-level-summary idea entirely. The next
  agent should keep the "click any node → see its run value" uniformity and resist re-introducing a
  separate summary surface.
- **They communicate visually — they send screenshots and want mockups.** Tines form (the bookmarkable
  form aspiration), the input-node card, the Rail. If a UI decision is open, *offer an ASCII mockup or
  build-and-screenshot* rather than describing it in prose.
- **Their terminology:** "play button" (not "launch"/"run button"), "the form", "Tines-style form",
  "run" vs "rerun", "the clock" (= the RunSelector Rail icon), "the db cache" (they assumed the
  memoization cache was relevant — it's a separate SQLite store; I clarified).
- **They genuinely want the bookmarkable form.** Their words: *"having a 'form' like this, that way you
  can link to it by having a bookmark and execute simple things easily"* with the Tines screenshot. This
  is a real product desire, not a throwaway. It's sequenced LATER in the task file but don't treat it as
  hypothetical — it's where their head is.
- **They want the frontmatter store gone.** *"maybe the frontmatter can be fully deprecated after this?"*
  — that's an instinct toward consolidation/simplicity, and they're right that it's vestigial. We agreed
  to decouple it as a follow-on (because of the MCP-history cost), but the *direction* they want is
  delete-it.

## The Dead-Ends (the most valuable part — don't repeat my mistakes)

1. **I proposed a JSON inputs channel ("B", `--inputs-json`) as the RECOMMENDED way to pass inputs, on a
   type-fidelity argument.** The user stopped me cold: *"im not sure I understand why this is happening
   just because we are using the clis normal way to send params? then that would have happened the first
   time the workflow was executed as well? lets take a step back."* They were RIGHT. The `infer_type`
   coercion quirk (`01234`→`1234`) is a pre-existing property of the CLI's key=value convention — it hits
   hand-typed runs identically, so the form using key=value (channel A) is just *faithful to the CLI*, not
   broken. B would make the form behave DIFFERENTLY from the CLI (a divergence) and only fix the form.
   **Do not resurrect channel B.** If the coercion ever genuinely bites, fix it at the root in the CLI's
   coercion (so CLI + form improve together) — separate, optional, not a precondition. The user values
   "form == CLI" faithfulness highly.

2. **I said "v1: run with no inputs, fail fast."** The user: *"what do you mean 'no inputs', running
   almost any workflow without defined inputs wont work..?"* The form is NOT optional polish — it's the
   *mechanism*. Don't ship a play button without the form.

3. **I called IO-node inspection "complex" (gate surgery, etc.).** The user pushed: *"can you make sure
   the clicking io nodes is really that complex?"* On re-examination it's MODERATE and it's the *better*
   design. I'd overstated it. The actual work is small: producer `meta.inputs` (needed anyway) + a branch
   in `/api/run-node` to project IO refs from `meta`/`json_output` + a couple lines on the detail-panel
   gate. Don't let the next agent re-inflate this.

4. **The user proposed per-field cross-run input mixing** ("input A from run X, input B from run Y"). I
   pushed back (theorized need, heavy per-field provenance UI) and offered the lighter framing:
   **per-field value autocomplete** (distinct previously-used values per field, no run-provenance). They
   agreed. So: full per-field run-provenance = NO; value-autocomplete = maybe-later if combinatorial
   picking proves real. The underlying want they confirmed is *"reuse any previously-used value per
   field,"* not *"track which run each came from."*

## Key Insights (non-obvious, took the conversation to reach)

- **The whole feature is cheap ONLY because it composes with Task 173.** A detached `pflow run`
  subprocess writes a trace → the existing tailer discovers it → the overlay lights up → flock liveness
  → completion banner → replay. All shipped. The play button adds *no new observation code*. If the next
  agent finds themselves writing streaming/run-state-tracking in the server, they've gone wrong — re-read
  ADR-0008. The server stays a pure observer except for the one spawn.
- **`meta.inputs` is the keystone and it's load-bearing for THREE things at once** (inspect, re-run,
  deprecating the frontmatter inputs). It's also the thing that makes inspection work *even on
  cache-hit runs* — because a cached node's event records the pre-resolution param (GH #540), but
  `meta.inputs` is recorded at run start, cache-independent. Build it first.
- **The cache (`~/.pflow/cache/cache.db`, SQLite) is a RED HERRING for input history** — it stores an
  irreversible md5 hash of resolved inputs, not the inputs. It IS relevant in one good way: re-running
  with the same inputs reproduces cache keys → cache hits → fast/free, nodes light "cached" (already
  works). Do NOT put run/input history in the cache db (disposable side-store vs record-of-truth).
- **`json_output` (workflow result) is only recorded on `--output-format json` runs.** That's why the
  design spawns button-launched runs with that flag — so output-node inspect is reliable. This is easy to
  miss and would silently make output inspection flaky for default text-mode runs.

## Assumptions & Uncertainties

- **NEEDS VERIFICATION (small):** the secret-prefill "server-side reuse" mechanism is a *concept*, not a
  designed protocol. The client says "reuse run X's value for `api_key`" and the server fills it from the
  trace. The exact wire shape (how the client signals "reuse" vs "I typed a new value" vs "blank") isn't
  designed. Could be as simple as a sentinel, but think it through.
- **ASSUMPTION:** the open decisions (a) secret-prefill = server-side reuse, (b) placement = separate ▶,
  (c) no-input = show confirm, (d) priority = high — were NOT explicitly chosen by the user. They said
  *"yes use /create-task 175"* in response to my offer to "write the note with my recommended defaults
  and flag them for your review." So these are **soft defaults I picked, flagged in the task file as
  "(Decision — revisit…)"**. The user is highly design-engaged and showed me the Rail saying *"im open
  to suggestions"* — they will likely want to actually decide placement (probably with a mockup). Don't
  treat (a)–(d) as locked.
- **UNCLEAR:** whether Task 173's remaining closure (pin D1, `task-review.md`) should happen before/after
  175. I asked; the user went to the braindump without answering. Open thread (below).

## Unexplored Territory

- **MIGHT MATTER — trace accumulation.** Confirmed: `~/.pflow/debug` has NO cleanup/rotation/TTL/cap and
  no `pflow` clear command — traces grow unbounded. The run button makes it *much* easier to generate
  runs. We flagged it but didn't decide a retention policy. CONSIDER a fast-follow (and it's a reason the
  frontmatter store's portability/durability isn't trivially worse — see below).
- **MIGHT MATTER — `stdin: true` inputs.** Some pflow workflows route piped stdin to a designated input
  (`_find_stdin_input`, run.py). The form/`POST /api/run` design does NOT address stdin-routed inputs at
  all. A workflow whose primary input is stdin won't be runnable via the form as designed. We never
  discussed it.
- **CONSIDER — file-upload inputs.** The Tines screenshot the user loves has file upload + a URL field.
  pflow inputs are typed scalars/JSON; file upload is genuinely new (multipart, where the file lands on
  disk, how a workflow references it as a path). Explicitly deferred in the task file, but the user
  *showed* it — they may expect it sooner than "later."
- **CONSIDER — concurrency / rapid clicks.** Multiple ▶ clicks = multiple detached spawns. We called it a
  non-issue for single-user and added no guard. Fine for v1, but a dedup/disable-while-spawning is cheap
  insurance.
- **UNEXPLORED — form control mapping.** How each declared type renders (text/number/checkbox/textarea,
  JSON object inputs, multi-line, enums/choices if the schema has them) was never designed. The schema
  facts are there (`io.data_type`, etc.) but the control mapping is implementation-time work.
- **UNEXPLORED — the exact `POST /api/run` body shape** and how the server reconstructs `key=value`
  tokens from the inputs object (incl. JSON/typed values via `format_param_value`, which round-trips
  `infer_type`). Worth nailing in the design note.
- **The frontmatter deprecation follow-on has a real, sharp cost we didn't fully resolve:** MCP /
  `--no-trace` runs write the frontmatter store but write NO trace (`stream_to_disk=False`). So
  trace-based history would *lose MCP-run history* unless MCP starts writing traces (a deliberate change —
  MCP intentionally uses the in-memory collector). Plus moving/renaming a `.pflow.md` orphans its traces
  (frontmatter rides the file). These are why we decoupled it. Whoever does the deprecation must decide
  the MCP question explicitly — don't silently regress it.
- **CONSIDER — a first-class "open a past run" affordance for the agent.** Task 173 ships the URL-level
  primitive (`?workflow=X&run=<run_id>`, where `run_id` = the `execution_id` on the trace's meta line —
  replay read at mount); `pflow guide ui` now documents it, so the agent can hand-build that URL from a
  trace it already has. But there's NO CLI/Point affordance: `_viewer_url` / `pflow ui focus` only thread
  `&focus=`, and no Point verb switches an already-open Viewer to a run. A `pflow ui <wf> --run <id>`
  (open) + a "select-run" Point verb would let the agent open/replay a specific run for the user without
  URL-crafting — a natural fit for 175's run-inspection/re-run scope. (Surfaced in the Task 173 final-review
  guide-doc discussion, 2026-06-30.)

## What I'd Tell Myself

- Build `meta.inputs` first; everything hangs off it.
- Default to the *smallest faithful* thing. Every time I proposed something cleverer than "reuse what
  exists / match the CLI," the user pulled me back. Trust that instinct preemptively.
- For UI placement, **make a mockup** before debating in prose. The user is visual and will engage with a
  picture.
- The orphaned code (`rerun_display.py`, `ctx.obj["execution_params"]`) is dead — it is NOT "the existing
  rerun mechanism." Don't study it as prior art; it's deletable scaffolding.
- Don't conflate the THREE run-ish stores: (1) frontmatter execution stats, (2) trace files, (3) the
  dry-run last-run-stats in `plan.py` (reads trace/cache). They have different purposes. This task touches
  traces (+ adds meta.inputs); leave (3) alone.

## Open Threads

- **Decisions (a)–(d) are unconfirmed soft defaults** — confirm with the user, especially placement
  (separate ▶ vs fold into the clock panel). The user explicitly invited suggestions here.
- **Task 173 closure (pin D1, `task-review.md`) — sequence vs 175?** Unanswered. My read: they're
  independent; 173's closure can happen anytime and shouldn't block 175. But ask.
- **Secret-prefill protocol** needs concrete design (see above).
- The user last said the CLAUDE.md name should be short (done: "Run workflows from the UI"). No pending
  edits.

## Minor context that might confuse the next agent

- Early in the conversation the user said the work was "git staged"; it was actually already **committed**
  (commits `477c95a3` detail panel, `dd0203d5` catalog) — the working tree was clean. Their git mental
  model was slightly off. Irrelevant to 175, but don't be confused if they reference "staged changes."
- This branch is `feat/live-execution-overlay` (Task 173's branch). Task 175 is spun out as its own task
  but we have NOT discussed whether it gets its own branch. Likely yes when implementation starts.

## Relevant Files & References

Beyond what's in the task file's References section, the ones that most shaped my thinking:
- `src/pflow/runtime/workflow_trace.py` — `_meta_fields:945` (where `inputs` gets added), `_aggregates:957`
  (`json_output`), the lock/flock liveness.
- `src/pflow/ui/server.py:826-837` — the security tripwire comment; my proposed `_require_local_origin`
  guard *replaces* this implicit reasoning with an explicit check. `_json_body:418` is the verified
  JSON-enforcement seam.
- `src/pflow/core/workflow/graph/renderers/react_flow.py:233` — `RFRef.node_id = node.id.node_id` (the
  verified fact that makes `meta.inputs[ref.node_id]` work — already confirmed, don't re-verify).
- The three searcher transcripts are gone, but their findings are distilled in the task file's
  "Implementation Notes." If you need to re-derive: frontmatter anatomy = `runner.py:693-724` +
  `manager.py:397`; consumers = `history_formatter.py`; durability = there's literally no cleanup code.
- Task 173 progress log: `.taskmaster/tasks/task_173/implementation/progress-log.md` — the n8n-vs-pflow
  framing, ADR-0008, and the whole pipeline this builds on.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've
> read and understood by summarizing the key points, then state you're ready to proceed.
