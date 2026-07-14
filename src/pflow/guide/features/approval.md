# Approval gates

**Use when**: a step takes a real-world action a human should review first — "ask before sending", "confirm before deploying", "let me approve the message" — or an agent step may hit a decision it should not make alone.

Two gate kinds, one primitive (the run pauses, a human decides, the run continues):

| | Approval | Escalation |
|---|---|---|
| Declared by | the workflow author (`approval: required`) | raised by an agent step at runtime |
| Human sees | the step's **resolved** params — what is about to happen | a question + options + the agent's recommendation |
| Human answers | yes / no | picks an option or types an answer |
| On "no" | run stops cleanly (exit 3) — not a failure | n/a — an escalation is a choice, not a veto |

## Declaring an approval gate

Add `approval: required` to any step (top-level field, like `cache:`):

```markdown
### notify-slack

Post the release summary to Slack.

- type: mcp-composio-slack-SLACK_SEND_MESSAGE
- channel: ${slack_channel}
- markdown_text: ${create-summary.result}
- approval: required
```

At a terminal the run pauses before the step and shows the resolved values (the actual message text, not `${...}`), then asks `Run this step? [y/N]`. Deny → the run stops **cleanly before the step runs**: exit code **3** (not 1 — nothing failed), trace trailer `final_status: "denied"`.

Rules:

- **Not on batch steps** — rejected at validation (the preview could not show resolved `${item}` values). Gate the step before or after the batch instead.
- **Loop steps prompt every iteration** — each iteration is a new action.
- **Cached steps never prompt** — a cache hit performs no action, so there is nothing to approve.
- Works on `workflow` steps (gates the whole sub-workflow; the preview is its inputs) and on steps **inside** sub-workflows.

## If you are an AI agent operating a gated workflow

You cannot answer an interactive prompt (your runs have no terminal). The playbook:

1. **Discover gates before running**: `pflow <workflow> --dry-run` marks gated steps `[<type>, approval]` and lists them in a `⏸` footer (JSON: `"approval": true` per entry). A pause is cheap to answer later (resume restores the upstream work — nothing re-runs), but discovering gates up front lets you collect your human's approvals in one conversation instead of one pause at a time.
2. **Show your human the action** — the resolved preview, not just the step name. Approving blind defeats the gate.
3. **With their OK**, pre-approve exactly the gates they approved: `--auto-approve=<step-name>` (repeatable, one per gate — there is deliberately no approve-all flag), or `auto_approve=["<step-name>"]` on the MCP `workflow_execute` tool. **Never pass these without asking your human first.**

If a gate is reached without pre-approval in a non-interactive run, the run **pauses durably** instead of failing: the trace is finalized `paused`, stdout prints a resume token, and the run exits **4**:

```
Paused at 'notify-slack'. Resume token: 7a9e4afb-2095-447e-8043-0660438104f9 (exit 4)
```

The gate content follows on stderr (the resolved preview — enough to decide from the output alone). Show it to your human; they answer hours or days later with `pflow resume <token> --approve yes|no`, or **in the browser**: `pflow ui <workflow> --run <token>` opens the paused run with an answer panel at the ⏸ step, so they click Approve/Deny (or pick an escalation option) with the resolved preview in front of them — see the `resume` topic for the full flow (`pflow resume list`, escalation answers, token consumption). A warning still fires at run start when top-level gates are unapproved. Limits to know: the run-start warning sees **top-level steps only**, `--auto-approve` names are **flat across the workflow tree** (a child step with the same name as a flagged one is also approved), and gates that cannot pause keep the old hard error (exit 1): `--no-trace` runs, gates inside a parallel `batch:` item or a sub-workflow child, and inline/piped workflows (no file to resume — save the workflow first).

A prompt needs stdin AND stderr at a terminal — stdout piping (`pflow wf | jq`) does not disable gates.

## Escalation — an agent raises a decision mid-run

For agent steps (`agent`, or a `code` guard) that may discover a lasting-impact fork the plan did not settle: the step returns an `escalation` object inside its `result`, the run pauses, the human chooses, and the choice is written back into the result for the workflow to act on.

The contract — `result.escalation`, with this shape:

```json
{"escalation": {
  "question": "The plan assumes one config file, but the code has per-env configs. Which way?",
  "options": [
    {"label": "merge", "description": "one file", "tradeoffs": "breaks env overrides"},
    {"label": "per-env", "description": "template per env", "tradeoffs": "more files"}
  ],
  "recommendation": "per-env"
}}
```

- **On an `agent` step, declare `output_schema` and put `escalation` in it** (nullable). Without a schema, an agentic session that ends on prose loses the marker — pflow then emits a degrading warning ("an escalation attempt may have been swallowed") instead of pausing. A plain string `escalation` value also works (it becomes the question).
- After the human answers, the marker gains `decision`: `result.escalation.decision = {"chosen": ..., "notes": ...}`. A marker that already carries `decision` never re-prompts.
- The escalating step must end on a **clean success** (`default` action). A `code` step that routes via `next:` cannot escalate from the same execution — escalate from the agent step, route on the decision downstream.
- Escalations **cannot be pre-approved** (`--auto-approve` does not apply — the question is unknown in advance). A non-interactive run **pauses durably at the escalation** — after the step has already run — and prints a resume token; answer with `pflow resume <token> --choose "<answer or option number>"`. The answer is folded into the completed step's result and the run continues at the next step: **the agent step's work is never re-paid**. (The escalating result is deliberately never cached — a cached escalation would replay on a later run as resolved-without-a-decision.) Escalations on a loop step, a `code` router, or a workflow's **final** step cannot pause and stay hard errors — put escalating agent steps mid-graph with a single next step.
- Not supported from inside a `batch:` step — the run fails with a clear error; restructure so the escalating step runs outside the batch.

### Continuing from the decision — the re-fork recipe

The engine only records the choice; **the workflow decides what happens next**. The standard shape is a `loop:` that re-runs the agent with the decision carried in:

```markdown
### implement

Implement the plan; escalate genuine lasting-impact forks.

- type: agent
- backend: claude
- prompt: |
    Implement the plan at ${plan_path}.
    ${implement.result.escalation.decision ?? ""}
    If you hit a decision with lasting impact the plan does not settle, return it
    in `escalation` (question, options, recommendation) and stop. Decide routine
    choices yourself and log them.
- output_schema: {"type": "object", "properties": {..., "escalation": {...}}}
- loop:
    while: ${implement.result.escalation}
    max_iterations: 3
```

Round 1 escalates → the human answers → round 2 re-runs the same step with `decision` resolved into the prompt. (`while:` reads the marker; a decided marker still loops one more round to fold the answer in — have the agent clear `escalation` (null) once the decision is applied, which ends the loop.)

**Calibration is the contract**: instruct the agent to escalate ONLY genuine lasting-impact forks it cannot resolve from the plan — never routine choices (too eager defeats autonomy; too reluctant silently bakes in bad decisions).

## Observability

- Every gate emits `gate` trace events (pause with the full payload; resolution with `approved`/`denied`/`auto`/`choice` and `resolved_via: prompt|flag` — the audit trail for which gates a human answered vs. a flag). One exception: a gate answered inside a `batch:` item's sub-workflow is honored but its gate events do not reach the trace (batch-item events are rollup-only today) — if you need the audit record, gate outside the batch.
- Denied runs: exit 3, `final_status: "denied"`, amber in `pflow ui`. A denied trace is not used as an `--only` snapshot source.
- Paused runs: exit 4, `final_status: "paused"` (the trailer also carries `paused_node_id` + the full gate payload), amber ⏸ in `pflow ui`; `pflow resume list` shows pending unanswered pauses. Answering consumes the token — the resumed attempt is a new run linked by `resumed_from`, and a second answer refuses with the newer attempt's id.
- Ctrl-C at a prompt aborts the run like any interrupt (exit 130).
