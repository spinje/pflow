# Task 180 — show before code: which edits refuse, which pass (USER CHECKPOINT)

> **RULED 2026-10-07** — user: *"yes go with your recommendations"* on the main orchestrator's plain-language relay.
> Every AFTER row stands as proposed (incl. row 14 refuses, row 9 passes, policy-only settings count as edits);
> `--force` = **(a)**, one flag. This file is the ruled text; the spec's ledger points here.

Every BEFORE below was **executed on today's code** (main `2a3f73ef`, isolated HOME, workflow
`produce` (shell) → `shape` (code) → `save` (write-file, template typo `${shape.result.txt}`); the
run fails at `save`, so `produce` and `shape` are the restored steps and `save` is the resume
point). AFTER is what the plan builds. One rule produces every AFTER row:

> **Resume refuses when a step whose saved output it restores was edited, removed, or now leads
> somewhere else; when the workflow now starts at a different step; or when the resume point
> itself is gone.** A step's "definition" is everything about it except its prose description
> (type, params and code blocks, batch, loop, retry, cache flags, approval, the `## Cache` chunks it
> references). Its "next" steps are recorded separately so the refusal can say where it leads
> now. Everything at or after the resume point is free to change.

| # | Edit | BEFORE (executed) | AFTER (proposed) | Why |
|---|---|---|---|---|
| 1 | Fix the typo in `save` (the resume point) | refuses, `--force` needed | **passes** | The headline (#690). Nothing restored changed. |
| 2 | Prose-only edit on restored `shape` ("Shape it." → "Shape the text.") | refuses | **passes** | Prose cannot change an output. |
| 3 | Edit restored `produce`'s command | refuses (names both restored steps) | **refuses**: "'produce' was edited" | Its saved output is stale. |
| 4 | Insert a step `prepare` between `shape` and `save` | refuses; with `--force` the new step is **silently skipped** (executed: its marker file was never written) | **refuses**: "'shape' now continues to 'prepare', which never ran — resume would skip it" | `shape`'s recorded next step changed. Silent skipping is the hazard; `--force` keeps today's behaviour for a user who wants it (the refusal says the step is skipped). |
| 5 | Insert a step `banner` before `produce` (new first step) | refuses; `--force` skips it | **refuses**: "the workflow now starts at 'banner', which never ran — resume would skip it" | The recorded start step differs. |
| 6 | Reroute upstream: `produce` gets `next: save` (skips `shape`) | refuses; `--force` resumes and `save` still reads `shape`'s restored output | **refuses**: "'produce' now continues to 'save' instead of 'shape'" | Its recorded next step changed; the restored set no longer matches the current path. |
| 7 | Append a step `notify` after `save` | refuses; `--force` runs it | **passes**, `notify` runs | Downstream of the resume point. |
| 8 | Edge change downstream (`save` → `on-error: notify`) | refuses | **passes** | Same. |
| 9 | Edit the `## Inputs` default (`hello` → `hi`) | refuses; with `--force` the tail still sees `hello` (executed: the recorded input wins; `greeting=cli` on the command line overrides) | **passes** (unchanged semantics: recorded inputs win, `KEY=VALUE` overrides) | The edit genuinely has no effect on this resume, but the right remedy is `KEY=VALUE`, not "re-run from the start" — so a refusal would send the agent the wrong way. The guide gains one sentence saying so (P4). Option (c), an INFO advisory listing the reused input values on every resume, is a follow-up if you want it. |
| 10 | Edit a `## Cache` chunk referenced by a restored `llm` step | refuses | **refuses**: "'summarize' was edited (a `## Cache` chunk it uses changed)" | The chunk is rendered into that step's prompt. |
| 11 | Edit the loop step that is the resume point (resumed at iteration N) | refuses | **passes**; iterations < N stay restored, the edit applies from N on (the guide says so) | The resume point is never checked. Same as #1 for loops. |
| 12 | Rename/remove the resume point `save` | refuses | **refuses**: "the resume point 'save' is no longer in the workflow" | Checked before anything else; the predecessor's changed next step is not blamed. |
| 13 | Remove restored `shape` (and point `produce` at `save`) | refuses | **refuses**: "'shape' is no longer in the workflow (resume would still restore its saved output)" | Named as removed, not "changed", so the agent knows where to look. |
| 14 | Paused **approval** on `deploy`, human approved the preview, then `deploy`'s command is edited and `pflow resume <id> --approve yes` | refuses (whole-workflow hash) | **refuses**: "'deploy' was edited after it was approved — the approval covered the earlier version" | The paused approval step is the one step at the resume point that IS checked: the recorded answer is consent for what the human saw. (Verified: `--approve yes` is matched by step name only; nothing compares the new preview to the approved one.) |
| 15 | Edit the child file of a `type: workflow` step | **passes today too** (the child's content is never in the hash — verified: only the `workflow:` path string is hashed) | passes (unchanged) | Pre-existing blind spot; flagged for a follow-up issue, not widened by this task. |
| 16 | Old trace (before this task) + any edit | refuses, names restored steps | **refuses** (whole-workflow compare kept): "this run was recorded by an older pflow version that did not record each step's definition, so resume cannot tell which step changed" | Old traces keep today's behaviour, including for prose-only edits. |

Two accepted limits of the rule (rare, both documented in the guide): a step that **failed and
recovered** through `on-error` is not restored, so an edit to it — or a step inserted right after
it — passes silently (it is never re-run either way; a reference to the inserted step fails loudly
as unresolved); and from the second attempt of a resume chain on, that step has no event at all.

## What the refusal says (AFTER)

```
Error: Workflow changed since the original run
'produce' was edited. Resume re-runs nothing before 'save' — it restores the saved outputs of the
steps that ran — so that edit would not take effect.
To fix this:
  1. Re-run the workflow from the start so the edit takes effect.
  2. Pass --force to resume anyway: steps before 'save' keep their saved outputs and are not
     re-run (an inserted step is skipped). [when 'save' already started: --force also re-runs
     'save' (a shell step that already started in the original run), so its side effects may
     fire again — if you are an AI agent, confirm that with your human first.]
```

Lead sentences by row: 4 "'shape' now continues to 'prepare', which never ran — resume would skip
it."; 5 "The workflow now starts at 'banner', which never ran — resume would skip it."; 6
"'produce' now continues to 'save' instead of 'shape'."; 12 "The resume point 'save' is no longer
in the workflow."; 13 "'shape' is no longer in the workflow."; 14 "'deploy' was edited after it was
approved — the approval covered the earlier version."; between-nodes sources say "nothing up to and
including 'esc'". Several leads combine in that order. The JSON form carries `changed_steps`,
`new_start` and `resume_point` as structured fields (agents and the web panel need not parse prose).

## Does `--force` split?

Options:
- **(a) Keep one `--force`** that waives both the stale refusal and the side-effect confirmation
  (today). After narrowing, the common path (fix the failed step, resume) needs no flag at all, so
  the "reflex `--force`" hazard the issue named is gone; the stale refusal still says when `--force`
  would also re-fire a started step (#719's line, kept). One flag, one sentence in the docs.
- **(b) Split**: `--force` keeps only the side-effect meaning; a new `--allow-edited` (name open)
  waives the stale refusal. Two flags to learn and document; the web bridge gains a second knob;
  `--force` alone would then refuse an edited-upstream resume that also needs the re-fire ack, so
  agents learn to pass both.
- **Recommendation: (a).** Importance 3 (user-visible CLI contract) — your call. **Reversal price,
  stated honestly:** narrowing `--force` later (option b as written) changes the meaning of a
  documented flag agents script; the cheap later move is ADDITIVE (new narrower flags, `--force`
  staying the superset waiver). If you pick (a), the plan records that constraint in the guide.

## Calls folded into the plan (reversible; say so if you disagree)

- **Rows 4–6, 12, 13 refuse.** The alternative — pass and let the resumed tail do whatever the
  current graph does — is exactly today's `--force` (the inserted step is skipped silently).
- **Row 9 passes** with a guide sentence; no advisory now (follow-up if you want (c)).
- **Row 14 refuses** — the approval is consent for the version the human saw.
- **Policy-only settings on a restored step (`retry`, `cache`, `prewarm`, `batch.parallel`) count as
  edits** even though they cannot change its saved output: one rule ("definition minus prose"),
  fail-closed; a denylist is a later refinement if over-refusal is ever observed.

## Files

- Scenario harness (gitignored scratch): the planner's scratchpad `scenarios.sh`, `scenarios2.sh`,
  `scenarios3.sh` — the BEFORE column is their output.
