# Braindump: the 2026-06-12 split session (short, tailored)

Spec is current as of 2026-06-12 (blocking-only scope, dry-run parity section, parallel-batch
escalation hard problem). This captures only what's NOT in it.

## Why the spec looks the way it does

- The user killed the old build-order sandwich (125-blocking → 164 → 125-durable) with one
  line: *"im not sure I follow the order here... that doesnt make sense?"* The decider was
  their convention: **"tasks are not implemented as separate prs though, its all one BIG pr."**
  Durable went to Task 171. If you find yourself adding token/serialization code here, you're
  re-merging the split — stop.
- The "non-TTY + gate fails loudly" requirement only exists because of the split (the token
  fallback used to absorb that case). It was never discussed beyond that — the error message
  design is yours.

## Standards the user will hold you to (their words, this session)

- *"The bar isn't 'passing', it's 'passing the right thing'"* — they asked me to audit my own
  tests for shallowness and will ask you. Mutation-verify the dry-run parity pin (recipe in
  `task_164/starting-context/braindump-planner-mirror-session.md`).
- *"Simplicity of the FINAL code... what would the top 10% of similar codebases implement"* —
  with the explicit guard against overengineering.
- Show expected output BEFORE implementing (the gate prompt UX is user-visible — mock it first).

## Sequencing trap

Branch AFTER PR #505 merges (planner-mirror refactor). Your `_classify` gate case lands in
code #505 rewrote (it now dispatches on the shared `route_action`); pre-merge work = conflicts.

## Not in the spec, might matter

- CONSIDER: **MCP server is the non-TTY case in production.** `execution_service.execute_workflow`
  on a gated workflow must hit the loud-error path; add it to the CLI/MCP parity tests
  (`test_cli_mcp_parity.py`), not just a CLI test.
- CONSIDER: **`--auto-approve` is a footgun on an agent-first CLI** — an agent that reflexively
  passes it defeats the gate's entire purpose. Maybe it shouldn't exist, or should be
  `--auto-approve=<node-id>` scoped. Never discussed; surface it to the user.
- The plan-review pairing that paid off in this session's refactor: `review-silent-failures` +
  `review-impact-completeness` on the implementation plan (caught a divergence five other
  passes missed). Worth repeating.

> **Note to next agent**: Read this fully, then task-125.md fully (especially "Dry-run parity
> & engine placement" and Known Hard Problems). Confirm by summarizing key points before
> proceeding.
