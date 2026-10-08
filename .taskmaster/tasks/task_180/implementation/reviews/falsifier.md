# Falsification Review: Task 180, "resume refuses only when an edit touches a restored step"

Branch `feat/task-180-resume-step-identity` @ `b1eca16a`, diff `origin/main...HEAD` (merge-base `1d393487`). Code mode.
I executed every verdict below. Each scenario had its own isolated `HOME` under the scratchpad
`/private/tmp/claude-501/-Users-andfal-projects-pflow/c22e27cc-bfb0-4a16-8d61-2e5c3482f785/scratchpad/falsifier/`.
I made no paid LLM call. I edited no tracked file. `git status --porcelain` was empty before this report was written.

## Harness (re-runnable)

- `pf` = `cd <worktree>; HOME="$PFHOME" UV_CACHE_DIR=~/.cache/uv uv run pflow "$@"`. This is the real CLI entry through `uv run`.
- `lib.sh` provides these helpers:
  - `mk <name> [template]` makes a fresh dir with `home/.pflow/debug` and exports `PFHOME`.
  - `fail1` runs the workflow with `</dev/null` (non-TTY) and extracts the exec id from the "pflow resume <id>" hint.
  - `ed old new` edits `wf.pflow.md` once and asserts the old text was present.
  - `res` runs `pflow resume … </dev/null`. `rj` is the same with `--output-format json`.
  - `meta '<stmt>'` edits the trace's meta line.
- The base fixture is `base.pflow.md`, Task 118-compliant (values bind through `env:` / `inputs:`):
  - `produce` (shell; appends `produce` to `ledger.txt`, prints `$GREETING`)
  - → `shape` (code)
  - → `save` (write-file with `${shape.result.txt}` typo → fails before start).
  - `produce` and `shape` are restored; `save` is the resume point.
- Other fixtures:
  - `gate.pflow.md`: `g1` → `deploy`, which has `approval: required` and writes a ledger line.
  - `loop.pflow.md`: `seed` → `count`, a code loop that raises at iteration 3 → `report`.
  - `bhost.pflow.md` + `child.pflow.md`: `prep` → batched `type: workflow` host over `["a","b"]`. The child appends `fired $I` to the ledger; item b exits 3.
  - `backedge.pflow.md`: #719's router/save on-error back edge.
  - `carry.pflow.md`: a carry typo at iteration 2.
  - `bshell.pflow.md`: a batched shell where b fails.
  - `cache_shell` / `cache_llm.pflow.md`: row 10.
- `ptydrive.py` runs `pf` under a real `pty.fork()` PTY and answers the `[y/N]` prompt.

## Claim Ledger

| # | Claim (falsifiable) | Attacks executed | Observed | Verdict |
|---|---|---|---|---|
| R1 | Fixing the typo in the resume point resumes with no `--force` | text, `--dry-run`, `--output-format json --dry-run`, real JSON run | exit 0 "Resuming from 'save': 2 upstream steps restored"; `hello.txt`="# hello"; ledger `produce` ×1 | HELD |
| R2 | A prose-only edit on a restored step passes | prose + fix; prose only (no fix); trailing prose after the code block; multi-paragraph prose with markup | all pass the gate; prose-only re-runs `save` and fails on the typo; IR shows the prose folded into `purpose` | HELD |
| R3 | Editing restored `produce`'s command refuses and names only `produce` | text, `--dry-run`, JSON, JSON+dry-run, PTY answering "y" | "'produce' was edited. Resume re-runs nothing before 'save'…"; JSON `changed_steps:["produce"]`, `resume_point:"save"`, `node_id:"produce"`; PTY: no prompt, same refusal; ledger unchanged | HELD |
| R4 | An insertion before the resume point refuses; `--force` skips it | text, `--dry-run`, JSON, `--force` | "'shape' now continues to 'prepare', which never ran — resume would skip it." / "…not re-run ('prepare' is skipped)."; under `--force`, `prepare-ran` is absent | HELD |
| R5 | A new first step refuses | text + JSON | "The workflow now starts at 'banner', which never ran…"; `new_start:"banner"` | HELD |
| R6 | Rerouting upstream (`produce` `next: save`) refuses | text, `--force` | "'produce' now continues to 'save' instead of 'shape'."; `--force` exit 0 | HELD |
| R7 | A step appended after the resume point passes and runs | real run | exit 0, `notify-ran` present | HELD |
| R8 | A downstream edge change (`save` on-error/next) passes | real run (valid `next: end` fixtures) | exit 0 | HELD |
| R9 | An edited `## Inputs` default passes; the recorded value wins; `KEY=VALUE` overrides | default hello→hi; `greeting=cli` | `hello.txt` written, no `hi.txt`; with override, `cli.txt` | HELD |
| R10 | Editing a referenced `## Cache` chunk refuses with the chunk lead; an unreferenced chunk, `ttl`, and an unedited workflow pass; a selection change reads "was edited." | forged-meta CLI probe (below) + mocked-LLM pytest | as promised in all 5 variants; `tests/test_cli/test_resume_identity.py` 23 passed | HELD (meta forged; see note) |
| R11 | An edit to a loop step at its own resume point passes and resumes at iteration N; an upstream edit refuses with the iteration text | `--dry-run`, real run (non-TTY), `--force`; `seed` edit | "Resuming from 'count' (iteration 3)"; the gate passes, then the side-effect confirmation (count started); `--force` ledger `count 3`, `count 3`, `count 4`; `seed` edit → "'seed' was edited … 'count' (iteration 3) … Its iterations before 3 are restored too" + re-fire line | HELD |
| R12 | A removed or renamed resume point refuses without blaming its predecessor | rename `save`→`store`; between-nodes source with `produce` removed | "The resume point 'save' is no longer in the workflow." / 2. "Or restore the step 'save'…"; `resume_point_missing:true`, `changed_steps:[]` | HELD |
| R13 | A removed restored step is named as removed | remove `shape`, point `produce` at `save` | "'shape' is no longer in the workflow (resume would still restore its saved output). 'produce' now continues to 'save' instead of 'shape'." (extra lead logged by the implementer) | HELD |
| R14 | A paused approval step edited after approval refuses `--approve yes`; a denial passes | `--approve yes` text/dry-run/JSON; `--approve no`; prose-only edit + approve; UI | refusal "'deploy' was edited after it was approved…"; deny → exit 3 "Denied at gate 'deploy'", ledger has only `g1`; prose edit → approve runs `deploy v1` | HELD |
| R15 | Editing a sub-workflow's child file passes (blind spot unchanged) | non-batched host → failing `boom`; child edited | the gate passes (only the side-effect confirmation for `boom`); `--force` → `out.txt` still "ok" (child-v1) | HELD |
| R16 | An older trace refuses any edit with the older-version text and passes unedited | aged 2.8.0 + prose edit; aged unedited; aged + typo fix only | "This run was recorded by an older pflow version…" for both edits; unedited passes the gate | HELD |
| D7 | `--force` is one flag waiving both refusals | rows 4/6 force, back-edge refusal text | `--force` passes both; the stale text carries the "--force also re-runs 'save' (a shell step that already started…)" sentence when K started | HELD |
| D1b-a | A batched `workflow` host on a 2.9.0 trace is decided by the real `node.start` | child fired a, b failed; pipe (`echo y \|`), `</dev/null`, `--dry-run` | trace `node.start host 1` → `event host failed`; "Resume needs confirmation… 'host' (a workflow step)"; ledger stays `fired a`,`fired b` | HELD |
| D1b-b | On a hand-aged 2.8.0 trace the carve-out still asks | `step_identity` dropped, 2.8.0, host `node.start` dropped (true 2.8 shape); and kept | both ask | HELD |
| D1b-c | A non-batched host that never began skips the confirmation on 2.9.0 and asks on 2.8.0 | `inputs: item: ${prep.result.itm}` (runtime typo) | 2.9.0: no `node.start host`; resume re-runs host (no confirmation); aged 2.8.0: "Resume needs confirmation" | HELD |
| P1-a | Every step that begins writes a top-level `node.start`, batched hosts included; no other on-disk change | main vs branch event-shape diff over 7 workflows (base, batched host, nested batched host, loop, auto-approved gate, back edge, batched shell) | the only diffs are the meta `step_identity` key and `node.start host` (top level, and `parent=1` when nested); ids identical | HELD |
| P1-b | Killed mid-batch → resume entry = host, confirmation asked | SIGKILL by PID while item b's child slept | trace ends `node.start host 1` (dangling); resume: "Resuming re-runs step 'host'…"; `--dry-run` "Resuming from 'host'" | HELD |
| P1-c | `--no-trace` runs are unaffected | batched host success and failure with `--no-trace` | normal output and error text; 0 trace files | HELD |
| P1-d | Nested batched host inside a non-batched host | top → outer host → mid (batched host) → child | starts and events pair (`host 3 parent 1`); resume asks for `outer` | HELD |
| P1-e | Gate arm: a batched host stopped by a child gate pairs start/event and does not change resume | sequential and `parallel: true, max_concurrent: 1` | `node.start host` + `event host success`; resume "marked failed but has no failed step" — **identical to main** | HELD |
| #719-1 | Restored chain / resume-of-a-resume | unforced A2 then fix → by id and by path; A2 with an edit | pass / pass / refuses "'produce' was edited" | HELD |
| #719-2 | On-error back edge (started on visit 1, pre-start on visit 2) | pipe, `echo y` pipe, PTY n / PTY y, resume-point edit, restored `router` edit | confirmation asked (pipe); PTY n → "Resume cancelled", ledger unchanged; PTY y → one re-fire; `router` edit → refusal + re-fire sentence | HELD |
| #719-3 | Typo pipe/TTY (never started → no confirmation) | pipe and real PTY | no prompt on either; `save` re-runs | HELD |
| #719-4 | Loop carry error at iteration 2 skips the confirmation | carry typo | resume re-runs with no confirmation; ledger `count 1` only; carry fixed → completes `count 2`,`count 3` | HELD |
| #719-5 | Loop raise asks | row 11 | asks | HELD |
| #719-6 | Batched shell host asks; TTY y re-runs | pipe + PTY y | asks; PTY y re-fires a,b once | HELD |
| #719-7 | Auto-approved gate step that fired then failed asks; `--force` re-gates | `--auto-approve deploy`, deploy `exit 5` | asks (also after a resume-point edit); `--force` → "Paused at 'deploy'" (gate re-prompts, nothing fired) | HELD |
| #719-8 | Nested host with an on-error typo | host (child fired) → on-error handler with a runtime `${host.out}` typo | entry `host`, confirmation asked, ledger unchanged | HELD |
| #719-9 | 2.7.0 and pre-173 traces | 2.7.0 loop (iteration keys dropped); 2.5.0 with no hash/starts, unedited and edited | 2.7.0 asks / edit → older-version refusal; pre-173 → "Cannot verify… predates workflow-hash tracking" | HELD |
| #719-10 | `--only` gains no check (D8); an `--only` id | edited `produce`, `--only save`; resume an `--only` id | `--only` exit 0 with no stale check; resume an `--only` id → "No run to resume" (same on main) | HELD |
| E1 | Reordered params, flow-style env, explicit `next:` = document order, shifted source lines | all four in one edit, with the typo fixed | passes | HELD |
| E2 | A failed-and-recovered start step, no edit, resume of a resume | pytest `test_resume_of_a_resume_with_a_failed_recovered_start_step_passes` (CLI-level) | passed | HELD (pytest only) |
| E3 | A forced resume, then resume the attempt | edit `produce` → `--force` A2 → fix typo → resume A2; then revert `produce` → resume A2 | passes (D5 accepted precision); the revert refuses "'produce' was edited" (fail-safe over-refusal) | HELD-as-ruled (D5) |
| E4 | `on-error:` added to a restored step refuses | `shape` `on-error: save`; `produce` `on-error: alert` (new) | refuses both; see S1 for the second's text | HELD (text: S1) |
| E5 | Between-nodes source: an insertion after `last_completed` refuses and `--force` runs it; downstream insertion and an edit to the successor pass the gate | trace cut after `produce` (simulated kill) | "'produce' now continues to 'mid' instead of 'shape'. Resume would continue at 'mid'…"; `--force` runs `mid` (`mid-ran` present); the others reach only the (pre-existing) side-effect confirmation | HELD |
| E6 | Renamed start step | `produce`→`make` | refuses: removed `produce`, edited `shape`, new start `make` (skipped) | HELD |
| E7 | `loop:` added to a killed run's last-completed restored step (sneaks it into "resume point") | killed after `produce`; `loop:` added | refused loudly ("recorded no loop position"), text + dry-run | HELD |
| E8 | A saved workflow (library) run by name | save → run by name → fix + re-save `--force` → `resume idemo`; edit `produce` + re-save → resume by id | pass; refuse | HELD |
| E9 | A new required input added before resume is loud | `### suffix` required, used by `save` | "Workflow requires input 'suffix'"; `suffix=X` → `# helloX` | HELD |
| F1–F10 | Fail-closed on a malformed `step_identity` | string; missing `steps`; `steps` as list; `start` int; `start` absent; restored step absent; entry a string; `hash` int; `next` a string; `steps` `{}`. Each with an edited `produce`, and unedited (typo fixed) | **every one refuses**; none passed silently. Envelope errors fall back to the whole-hash path ("older pflow version"); per-step errors read "was edited" / "now continues to"; `start` absent → "now starts at 'produce' instead of 'None'" | HELD |
| UI-1 | `POST /api/resume` refusing row (3) | curl | HTTP 409, `refusal:"stale_workflow"`, `hash_known:true`, `errors[0].context.changed_steps:["produce"]`, `resume_point`, `resume_point_missing` | HELD |
| UI-2 | Passing row (1) spawns and the run succeeds | curl | 200 `spawned`; new trace `resumed_from=51003d06`, `final=success`; `hello.txt` written | HELD |
| UI-3 | D11: a validator-only error after the resume point → 400, no spawn | curl `/api/resume` and `/api/run` | 400 with both errors ("references non-existent node 'nosuch'", template error); trace count unchanged | HELD |
| UI-4 | Row 14 approve → 409; deny → 200; `force:true` on row 3 → 200; batched host → 409 `side_effect_confirmation` | curl | as stated; deny ran nothing (ledger `g1` only); force run `final=success` | HELD |

**Row 10 note.** `prompt_cache` is valid only on `llm` nodes (`cache.invalid-on-non-llm`). A restored `llm` step therefore needs a real LLM call. Instead I ran the run with a shell `summarize`, then replaced the meta `step_identity` / `content_hash` with `step_identity(resolve_workflow(llm-version).ir)` (`forge_identity.py`, which uses the library function itself), and resumed with `--dry-run` through the CLI.

The paid-LLM path itself (a real `llm` step's restored output under a chunk edit) is **UNTESTABLE HERE**. It is covered by the mocked-LLM CLI tests (`test_row10_…`, `test_changing_which_cache_chunks_…`, both passing).

### Not attacked (and why)

- **Escalation-paused sources** (an answered escalation, between nodes). Producing one needs an `agent` step (paid LLM) or the test-only `escalating-node` registry. I relied on `tests/test_cli/test_paused_cli.py` (the escalation trio passed) and attacked the between-nodes logic through a simulated kill (E5) instead. **UNTESTABLE HERE via CLI.**
- **The web UI rendering of the refusals.** P4 drove rows 3 and 14 in the browser. I attacked the HTTP contract (UI-1..4) but did not re-drive the canvas. Coverage gap by choice: there is no `web/` change in this diff.
- **Windows path and encoding behaviour** (`tests-windows` CI only).
- **The `resume_point_missing` + UI "Resume anyway"** case (completion-gate W3, handed back and ruled a follow-up). Not re-litigated.
- **Concurrency of two UI resumes** (TOCTOU, tolerated by the documented design).

## Critical: falsified central promise

None.

## Warnings

None.

## Suggestions

**S1. The "which never ran" reroute lead drops the route's action, so an added `on-error:` reads as a main-flow change.**
`src/pflow/core/exceptions.py:1697-1704` (`_rerouted_lead`) names `never_ran` by target only. The `instead of` form one branch below keeps the action through `_routes_text` (the agent-ux W3 fix).

Repro:
```
mk onerr2; fail1
printf '\n### alert\n\nAlert.\n\n- type: shell\n- next: end\n\n```shell command\necho alert\n```\n' >> $W
ed '- type: shell
' '- type: shell
- on-error: alert
'
ed '- content: ${shape.result.txt}' '- content: ${shape.result.md}
- next: end'
pflow resume $E </dev/null
```

Observed:
> 'produce' now continues to 'alert', which never ran — resume would skip it.

Compare the twin, where `shape` gains `on-error: save` (an existing target):
> 'shape' now continues to 'save', 'save' on error instead of 'save'.

An agent reading the first line will think `produce`'s main path now goes to `alert`. "Resume would skip it" is also misleading here: `alert` is an error route of a step that succeeded, so it would not have run in an uninterrupted run either.

The refuse/pass outcome is as ruled (a restored step's `next` changed, so it refuses). Only the text is imprecise. Expected: "'produce' now continues to 'alert' on error…", or no "skip" claim for a non-default route.

This is review-agent-ux territory. Severity is Suggestion: the refusal is correct and `changed_steps:["produce"]` is accurate.

### Observations (no finding)

- **D5 precision (ruled).** After a `--force`d resume, the attempt's map describes the edited workflow. Resuming that attempt passes even though `produce`'s restored output predates the edit, and reverting the edit then refuses. This is identical to the pre-180 `content_hash` precision, so it is not a regression. The guide does not mention it.
- **Pre-existing, also on main `1d393487`:**
  - A failed `--only` run prints "pflow resume <id>", and resuming that id says "No run with execution id … was found". I reproduced this with main's own `.venv/bin/pflow`. It is out of scope; it may be worth an issue.
  - A batched host stopped by a child gate resumes as "marked failed but has no failed step". The defensive comment at `runtime/resume_source.py:513-515` ("not producible today") is false for that shape. Same outcome on main.
  - A between-nodes source asks for side-effect confirmation for a never-started successor (#719 by design).
- **`--approve no` on an edited approval step passes** (W5, accepted). I confirmed it runs nothing.

## Promises That Held

- **The 16 ruled rows, all HELD through `pflow resume`.** Every row was attacked on its own surface:
  - rows 1/3/4/14 with `--dry-run` twins;
  - rows 3/4/5/12/13/14/16 with JSON twins;
  - row 3 under a real PTY;
  - rows 1/3/14 through `POST /api/resume`.
- **D1b: both halves HELD.** The 2.9.0 batched host is decided by the real `node.start` (a mid-batch kill included). The aged 2.8.0 trace still asks, with and without the host start. The never-began proof works for a non-batched host on 2.9.0 and is refused on 2.8.0.
- **All of PR #719's falsifier attack list re-executed and HELD.** That covers the restored chain, back edge, typo pipe/TTY, loop carry, loop raise, shell pipe/TTY, batched workflow host (2.9.0 and 2.8.0), batched shell host, auto-approved gate, nested host with an on-error typo, 2.7.0, pre-173, and `--only`.
- **Identity edges HELD.** Resume-of-a-resume (unforced and forced), reorder/flow-style/explicit-next/line shift, cache chunk referenced vs unreferenced vs `ttl` vs selection, `on-error` added, a between-nodes insertion after `last_completed` (refuses, and `--force` runs the step), a removed resume point, a renamed start step, `loop:` added to a restored killed step, a saved library workflow, and a new required input.
- **Fail-closed HELD for 10 malformed `step_identity` shapes.** Every one refused; none passed silently.
- **Engine P1 HELD.** On-disk shape is unchanged except the host `node.start` and the meta key (main vs branch diff), `--no-trace` is unaffected, and nested batched hosts pair correctly.
- **UI HELD.** 409 stale with structured context, 200 spawn that completes, D11 400 with no spawn (on `/api/resume` and `/api/run`), deny 200, force 200, batched host 409 `side_effect_confirmation`.
- **Test context, not evidence.** 417 passed across the eight nearest test files (`test_paused_cli`, `test_resume_cli`, `test_resume_identity`, `test_ui_interaction_server`, `test_resume_preflight`, `test_emit_time_trace`, `test_resume_source`, `test_workflow_id`).

## Self-audit

- Every HELD verdict above cites an executed command. Two rows lean partly on tests, and I labelled them:
  - E2: pytest only.
  - R10: a forged-meta CLI probe plus mocked tests.
- The expensive attacks were run:
  - a SIGKILL mid-batch, with the sleeper PID killed by PID;
  - a real PTY driver;
  - a live `pflow ui` on free port 59273, PID 35911, killed by PID, port confirmed free;
  - aged and forged traces;
  - a main-vs-branch trace diff;
  - library save/run-by-name.
- No processes are left (`ps` grep on the scratch path is empty).

## Summary

The change's promises survive a careless, impatient workflow author. I executed about 60 attacks across the 16 ruled rows, the D1b carve-out, the P1 engine change, PR #719's three falsifier rounds, the identity edges, malformed traces and the UI endpoint, and none broke a refuse/pass outcome or let an edited restored step through silently.

The headline loop works through the real CLI, piped or TTY, with no `--force`: fix the failed step, then resume. Every edit to a step whose output is restored refuses and names the step. Malformed identity maps fail closed in every shape I tried. The batched sub-workflow host's side effect never silently re-fires, on either the new 2.9.0 trace or a hand-aged 2.8.0 one.

The one finding is text: when a restored step gains an `on-error` route to a new step, the refusal's "now continues to 'alert', which never ran — resume would skip it" drops "on error" (Suggestion). The coverage gaps I chose to leave:
- the paid-LLM restored-`llm` path, argued from mocked tests and a forged-meta probe;
- escalation-paused sources (test registry only);
- browser rendering (not re-driven);
- Windows.
