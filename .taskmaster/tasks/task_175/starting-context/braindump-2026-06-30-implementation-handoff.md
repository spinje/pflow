# Braindump: Task 175 implementation handoff (the tacit half)

> Read alongside, not instead of: `task-175.md` (the what/why), `implementation/implementation-plan.md`
> (the approved plan — every file:line seam, every deep-review fix, the build order). This file captures
> ONLY what those don't: the journey of *this* planning session, the corrections we made, the traps the
> next agent will be tempted by, and the soft spots to verify first. Nothing here repeats the plan.

## Where this is

Planning is DONE and the plan is **user-approved**. No production code written yet. This session took the
2026-06-29 design braindump + the spec, **re-verified every load-bearing fact against the current
post-Task-173 code** (the spec's line numbers had drifted / some claims were wrong), corrected the spec,
wrote the plan, then ran a 4-agent `/deep-review` and folded all confirmed findings back in. The plan you
inherit is the *post-review* version — its decisions already survived an adversarial pass. Start at Phase 1.

## The user's mental model (use their words)

- **Simplicity is the governing constraint, and it's a *specific* one.** Their framing, verbatim:
  *"prioritize simplicity of the FINAL code… what would the top 10% of similar codebases do… This isnt
  about over-engineering (needs to be avoided), this is about more simple code that is optimized for AI
  agents to understand and add features to."* They will reject cleverness AND gold-plating. When in doubt,
  reuse what exists and match the CLI.
- **"build for the future with thoughtful seams where it makes sense."** They want extension points — but
  tied to *real* next features (HITL gates 125, resume 164/171, file-upload, voice 174), not speculation.
  The plan's "Forward-looking seams" section is the answer to this; the deep-review then *pruned* two of my
  seams (`buildRunArgv` inlined, `RunForm` re-justified) because they leaned on speculative futures. That
  pruning is exactly the balance they want — don't re-inflate it.
- **They check your rigor.** Mid-session: *"did you read the task review of task 173 and gather as much
  information as possible related to this from the progress log using subagent?"* — I hadn't yet; they were
  right to push. Lesson for you: when the plan cites a Task-173 behavior, trust it (it came from reading the
  173 review/progress-log via subagent), but if you touch overlay/tailer code, re-read the relevant 173
  review section yourself.
- **They are visual and design-engaged.** They picked the side-panel form via an ASCII mockup. If a UI
  detail is genuinely open during build, screenshot it (use `screenshot-pflow-web-ui`) rather than deciding
  silently.

## The corrections that reshaped this — don't relitigate, don't regress

1. **Secrets do NOT flow through the form. This was the user's catch, and it's load-bearing.** I initially
   carried the spec's "server-side reuse" secret-prefill protocol AND a wrong premise (`api_key: ${ENV}`
   defaults). The user stopped me: *"shouldnt secrets be taken from settings file?"* They were right.
   Verified model: pflow resolves inputs by a **5-tier precedence matching by input NAME** against
   `os.environ`/`settings.env` — there is **no `${VAR}`-in-default expansion** (zero such cases in the repo).
   Consequence that the plan encodes but you must internalize: **the form never collects a secret.** A
   sensitive-named field left blank is omitted from argv and the spawned `pflow run` resolves it from
   settings/env by name — identical to a terminal run. The whole "server-side reuse / sentinel protocol"
   idea is **dead**; do not resurrect it. Re-run prefill just *omits* sensitive keys server-side.
2. **The agent affordance (`--run` flag + `select-run` verb) is IN scope — but only after a wrong turn.**
   The 2026-06-29 braindump floated it as a "CONSIDER." I first deferred it; the user thought it belonged to
   Task 174, I verified 174 is *voice narration only* (no run-selection), the user then **reset my spec edits**
   and said *"I think I made a mistake pointing you at 174, those changes was supposed to be included in this
   task or?"* → we folded both pieces in. So: it's deliberately in-scope, it is NOT 174's, and the user
   actively wanted it. Phase 6.
3. **`meta.inputs` is stored RAW on disk, redacted on READ.** There was a live tension: the Task-173
   reviewer's note suggested redacting at write. We chose raw-at-write for *consistency with node_params*
   (secrets already land raw there) and a single redaction model. If a future reviewer flags "secrets in the
   trace," that's the pre-existing, accepted exposure class — not a Task-175 regression.

## Deep-review: the two criticals were MINE, and one is a trap you'll hit too

The 4-agent review (plan-structure+simplicity, feature-interactions, concurrency, impact-completeness) was
high-signal — every finding verified against code, none disputed. Two criticals, both self-inflicted:

- **THE TRAP: `subprocess.Popen`, NOT `asyncio.create_subprocess_exec`.** The spec said Popen. I "improved"
  it to asyncio (it's an async server — *of course* use async subprocess, right?). **Wrong.** Verified
  against the 3.14 stdlib: asyncio's `BaseSubprocessTransport.close()/__del__` calls `_proc.kill()` on a
  live child, so closing `pflow ui` can SIGKILL an in-flight detached run — the *exact* thing ADR-0008
  exists to prevent, and intermittent (finalization timing). The plan now mandates plain `Popen(...,
  start_new_session=True)` with no `create_task`. **You will feel the same pull I did. Resist it.** Popen's
  `__del__` only warns + defers reaping; init reaps the orphan; `subprocess._cleanup()` handles finished
  prior children. This is correct precisely *because* it looks "less async."
- **The IO-projection `ancestor_path` guard.** My prose claimed sub-workflow IO nodes degrade gracefully,
  but the cited `meta.inputs[ref.node_id]` lookup (bare-name keyed, top-level only) would render a
  *top-level* value for a sub-workflow node sharing a name (both `url`). The plan now mandates
  `if ref.ancestor_path: return None` FIRST. Tiny fix, real bug.

The reviewers also caught: the pre-flight had to become a **full compile** (not just `prepare_inputs`) and
go **fully off-loop in one `to_thread`**; the `sensitive` flag must live in the renderer for input nodes
only (NOT the pure `IOPort` dataclass — it'd leak onto outputs via `asdict`) and **requires regenerating the
contract fixtures**; and the IO projection must return an **`isRunNodeDetail`-valid shape**. All folded in.

## The META_KEYS saga (three sources disagreed — here's the truth)

Three different agents gave three answers on whether `meta.inputs` must be added to `META_KEYS`
(`trace_io.py:30`): "required allowlist" / "doc-only, not functional" / "required for test fixtures."
**Resolved truth:** production `reconstruct_trace_from_lines` round-trips meta keys *generically* (so it's
NOT a production allowlist), BUT the **test-fixture builder `tests/shared/trace_jsonl.py:98` iterates
`META_KEYS`** to decide meta-line vs. trailer placement. So you MUST add `inputs` to `META_KEYS`, and the
reason is *test fidelity*, not production reconstruct. If you skip it, Phase-4/5 fixtures silently put
`inputs` in the trailer and an implementer "fixes" it by reading the wrong line → divergence from
production. This is the most insidious item; the plan says it, but now you know *why* the sources conflicted.

## Soft spots — verify these DURING implementation (the plan flags them; here's the nuance)

- **NEEDS VERIFICATION — the pre-flight `compile_workflow` registry handle.** The plan calls
  `compile_workflow(resolved.ir, registry, initial_params=typed_params)` off-thread but doesn't name how
  the server gets `registry`. The `command()` handler's `resolve_validate_build` path obtains it internally
  — trace that to find the clean handle. **Fallback explicitly allowed by the plan:**
  `resolve_validate_build(workflow)` + `prepare_inputs(resolved.ir, typed_params, settings_env)` in the same
  `to_thread`. If you take the fallback, use **`prepare_inputs` directly** for the missing-required check —
  do NOT rely on `WorkflowRunner.validate()`, because a searcher flagged (unverified) that `validate()` may
  mask missing top-level inputs via `_fill_declared_defaults`. `prepare_inputs` is unambiguous.
- **NEEDS VERIFICATION — `RunNodeDetail.duration_ms` relaxation.** Phase 4 wants IO cards with no
  duration/tokens. The TS type declares `duration_ms: number` non-null. The plan says relax to
  `number | null` and "verify `ThisRunSection` renders an IO card without tokens/duration." Actually open
  `ThisRunSection.tsx`/`RunDetailBody` and confirm it tolerates absent metrics before you change the type —
  it may already guard, or may need a branch.
- **The pre-flight double-compiles** (pre-flight + the spawn's own compile). We accepted this: it's the same
  work, off-loop, and `command()` already compiles per-Point. Don't "optimize" it away by skipping
  pre-flight — its whole job is converting silent pre-trace failures into a 400.
- **`hasRunContext = runId !== null || runStatus.size > 0`** — I named this exact state, but I did not
  open GraphView to confirm `runStatus` is the right map in scope at the gate site (`:934`). Confirm the
  variable name before wiring.

## What I'd tell myself starting Phase 1

- Build `meta.inputs` first and **prove it on disk** before anything else — `uv run pflow run <wf> name=World`,
  then look at the newest `~/.pflow/debug/*.json` first line and confirm `inputs` is there, raw. Everything
  in Phases 4/5 hangs off this; a wrong shape here is expensive later.
- The IR-driven snapshot (`{n: shared_store[n] for n in resolved.ir.get("inputs", {})}`) was chosen over
  `{**params, **resolved_defaults}` deliberately — the latter carries `_`/`__` internal keys and the
  params-vs-defaults split is subtle. Don't "simplify" back to the merge.
- After the `sensitive`-flag renderer change, **immediately** run
  `uv run python -m tests.fixtures.react_flow_contracts._generate` and commit the fixture diff, or
  `make test` will fail confusingly on a contract drift that's actually expected.
- Capture the `make test` baseline (pass/fail by name) BEFORE touching anything — the project's CLAUDE.md is
  emphatic that "no regressions" is meaningless without a captured baseline.

## Unexplored / might matter

- **MIGHT MATTER — overlapping launches cost real money.** The submit-disable only covers POST latency, not
  run duration; a user can fire N detached LLM runs. We accepted it for v1 (noted in the plan's "Accepted
  limitations"), but if you have spare effort, a "run in flight" affordance keyed to overlay status is the
  cheap insurance the feature-interactions reviewer suggested.
- **MIGHT MATTER — trace accumulation.** The ▶ button multiplies `~/.pflow/debug` traces and there's no
  retention/cleanup anywhere (GH #542). Out of scope, but it's the most likely "why is my disk full" /
  "why is the run picker slow" follow-on once this ships.
- **CONSIDER — the faithfulness claim is "without `--no-cache`."** UI launches always read/write cache. A
  user who ran from the terminal with `--no-cache` will see UI re-runs light "cached." Documented, not a bug.
- **UNEXPLORED — Windows.** `_require_local_origin`, `start_new_session`, flock — all assume POSIX. The
  whole UI/overlay stack is POSIX-shaped already (Task 116 is the Windows task), so don't special-case here.

## For the next agent (direct)

- **Start with Phase 1, prove `meta.inputs` on disk, then go in plan order.** Phases are independently
  testable; 1 unblocks 4 & 5; 2 unblocks 3.
- **Do NOT switch the spawn to asyncio.** (Re-read the trap above. This is the #1 way this implementation
  goes wrong.)
- **Do NOT add `sensitive` to the Python `IOPort` dataclass.** Renderer, input-nodes-only, + TS type. Then
  regenerate fixtures.
- **Use `pflow-codebase-searcher` for verification, never `Explore`/`general-purpose`** (project rule).
- **Browser verification is mandatory and unit tests won't catch overlay failures** — use the Task-173
  launch→poll-trace→read-DOM loop, and `make ui-build` + restart `pflow ui` before every browser check.
- The user said `/deep-review` in plan mode was the gate; after you implement, a code-mode `/deep-review`
  (which CAN use `review-simplicity`, unlike plan mode) is the natural pre-PR gate.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've
> read and understood by summarizing the key points, then state you're ready to proceed.
