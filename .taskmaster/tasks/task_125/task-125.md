# Task 125: Human-in-the-Loop Approval Gates

## Description

Add pause/resume capability to pflow workflows so execution halts at designated steps for human approval before continuing. Makes pflow trustworthy for workflows that take real-world actions (send messages, create PRs, deploy, delete).

## Status

not started

## Priority

high

## Problem

pflow workflows execute start-to-finish with no ability to pause. Any workflow that takes action on the user's behalf — posting to Slack, creating a GitHub issue, sending an email via MCP — runs without a checkpoint. Users can't review what's about to happen before it happens.

This is a trust barrier. Users won't put pflow in charge of real-world actions if they can't intervene. It also blocks adoption in contexts where agents operate with increasing autonomy (OpenClaw-style personal assistants, long-running agents) where a human approval step is the difference between useful and dangerous.

Lobster (OpenClaw's workflow engine, 25 days old) already has approval gates with durable resume tokens. This is table stakes for any workflow system that touches external services.

## Solution

A new `approval` parameter on any node that halts execution before the node runs, shows the user what's about to happen (resolved inputs), and waits for approval.

Two modes:
- **Interactive (TTY)**: Prompt directly in terminal, `[y/N]` style
- **Non-interactive (token-based)**: Emit a durable resume token, exit. User resumes later with `pflow resume <token> --approve yes|no`

Workflow state (completed node outputs, current position in execution) is serialized to disk at the pause point so resume doesn't re-execute completed nodes.

## Design Decisions

- **Parameter-level, not node-type-level**: `approval: required` is a parameter on any existing node type (`mcp`, `shell`, `http`, `llm`, etc.), not a separate `approval` node type. This keeps the node count unchanged and makes it composable — you add approval to an existing step, not insert a new step.
- **Preview resolved inputs**: At the pause point, show the user the actual resolved template values (e.g., "About to send Slack message to #releases: 'v0.9.0 released with 3 features'"), not the raw template (`${create-summary.result}`). The user needs to approve *what will happen*, not the abstract definition.
- **Resume tokens are self-contained**: Token encodes workflow identity, pause position, completed outputs, and a protocol version. A future session with no prior context can resume from the token alone.
- **State goes to `~/.pflow/resume/`**: Serialized shared store at pause point. Resume tokens reference this state. Cleanup after successful resume or configurable TTL.
- **Fits existing wrapper chain**: Approval check happens in a new wrapper (or in the existing `InstrumentedWrapper`) that intercepts *before* `prep()`. This keeps node implementations untouched.

## Dependencies

None. The shared store, wrapper chain, and template resolution system all exist. This is additive — no existing features need modification.

## Implementation Notes

### Wrapper integration

The approval check should slot into the existing wrapper chain:

```
InstrumentedWrapper (metrics, cache, trace)
    |
    v
ApprovalWrapper (NEW — check approval, serialize state, halt or continue)
    |
    v
BatchWrapper (if configured)
    |
    v
NamespacedWrapper (collision prevention)
    |
    v
TemplateAwareWrapper (${var} resolution)
    |
    v
ActualNode (prep -> exec -> post)
```

The `ApprovalWrapper` needs access to resolved template values to show the preview. This means it should sit *after* `TemplateAwareWrapper` resolves inputs, or it should trigger a preview-only template resolution pass. Consider which is cleaner — the wrapper ordering matters.

### State serialization

At pause:
1. Snapshot the shared store (all completed node outputs)
2. Record the current node index (which node we're paused before)
3. Record the workflow file path or saved name
4. Record the original input parameters
5. Write to `~/.pflow/resume/<execution-id>.json`
6. Generate a compact resume token that references this state

At resume:
1. Decode token, load state from `~/.pflow/resume/`
2. Reconstruct shared store from snapshot
3. Skip to the paused node
4. If approved: execute the paused node and continue
5. If denied: exit with a clear message ("Workflow cancelled at step 'notify-slack'")

### Batch interaction

If a batch node has `approval: required`:
- Approval applies to the **batch as a whole**, not per-item. Showing 70 individual approval prompts defeats the purpose.
- The preview should show: "About to process 70 items with node 'classify-commits' (type: llm). First 3 items: [preview]"

### Edge cases

- **Workflow changed between pause and resume**: Hash the workflow definition at pause time. On resume, compare hashes. If different, warn but allow with `--force`.
- **Multiple approval gates in one workflow**: Each gate pauses independently. After resuming gate 1, execution continues until gate 2 (or completion).
- **Timeout**: No auto-cancel by default. Resume tokens are valid until explicitly cleaned up or TTL expires. Consider a `pflow resume list` command to show pending approvals.

### CLI surface

```bash
# Workflow with approval gates runs and pauses
pflow my-workflow param=value
# Output: Paused at 'notify-slack'. Resume token: pflow-resume-abc123
# Run: pflow resume pflow-resume-abc123 --approve yes

# Resume
pflow resume pflow-resume-abc123 --approve yes
pflow resume pflow-resume-abc123 --approve no

# List pending
pflow resume list

# Auto-approve for CI/testing
pflow my-workflow param=value --auto-approve
```

### Markdown format

```markdown
### notify-slack

Post the release summary to Slack.

- type: mcp-composio-slack-SLACK_SEND_MESSAGE
- channel: ${slack_channel}
- markdown_text: ${create-summary.result}
- approval: required
```

## Verification

- **Basic gate**: Workflow with `approval: required` on a node halts before that node, displays preview, waits for input
- **Resume flow**: Paused workflow resumes correctly from token without re-executing completed nodes
- **Deny flow**: Denied approval exits cleanly with message, no side effects
- **Multiple gates**: Workflow with 2+ approval gates pauses at each in sequence
- **Batch + approval**: Batch node with approval shows batch preview, not per-item prompts
- **TTY mode**: Interactive prompt works in terminal
- **Non-TTY mode**: Token emitted to stdout, parseable by calling process
- **Stale resume**: Resuming after workflow definition changed shows warning
- **Shared store integrity**: Resumed workflow has access to all outputs from nodes that completed before the pause
- **Validation**: `pflow --validate-only` recognizes `approval` as a valid parameter (no unknown-param warning)
