# Braindump: Should Agent Instructions Teach Nested Workflows?

## Where I Am

This conversation was the tail end of Task 107 (markdown format migration). All Task 107 work is complete — 3608 passed, 516 skipped, `make check` clean. The user asked a specific question: "I want to talk about if we should add instructions for nested workflows in `src/pflow/cli/resources/cli-agent-instructions.md`... we made that work in this branch."

I recommended against it. The user didn't push back or agree — they immediately triggered a braindump because the context window was ending. So the conversation was unfinished. The decision is **not made**.

## User's Mental Model

The user said "we made that work in this branch" — referring to the Entry 14 fixes in the Task 107 progress log where `type: workflow` nodes were made to pass both validation and template validation. They're thinking of this as a capability that's now ready to teach.

Key context from the broader Task 107 conversation (documented in progress log entries 14-15):
- The user pushed for nested workflow verification as part of Task 107
- When issues were found, their approach was "fix the most obvious and easy to fix issues and then lets stop and pass the remaining hard work and audit to task 59"
- They care about agent experience — their original question was about how good the error messages are

The user considers nested workflows part of pflow's value proposition. They want agents to be able to compose workflows. The question isn't "should this feature exist" — it's "should we teach agents about it now."

## My Recommendation and Reasoning

I recommended **no, not now** for these reasons:

1. **Known UX gaps** (Entry 14 deferred to Task 59): tracebacks shown to agents, wrong `param_mapping` doesn't suggest available child inputs, relative path resolution broken for top-level `workflow_ref`, error stacking in deep nesting
2. **Examples use `type: test` nodes** — `examples/nested/process-text.pflow.md` uses `type: test`, which is an internal test node, not a realistic example
3. **Teaching cost is high** — `param_mapping`, `output_mapping`, `storage_mode`, relative paths, how child outputs become parent refs
4. **Risk of teaching something that breaks** — agents hitting the relative path bug or traceback issues will spiral

ASSUMPTION: My recommendation was sound, but the user may disagree. They've shown a pattern of wanting features documented close to when they're implemented, not waiting for perfection. They might want a minimal section with caveats.

## Assumptions & Uncertainties

UNCLEAR: How the user weighs "teach it now with caveats" vs "teach it when polished." The conversation ended before this was resolved.

UNCLEAR: Whether the user considers the Entry 14 fixes + existing examples sufficient for a minimal "Nested Workflows" section, or whether they agree the Task 59 gaps are blockers.

ASSUMPTION: The current agent instructions file (`cli-agent-instructions.md`) has zero mention of nested workflows — no `type: workflow`, no `workflow_ref`, no `param_mapping`, no `output_mapping`. This was confirmed by grep.

NEEDS VERIFICATION: Do the existing `examples/nested/` workflows actually execute end-to-end? They use `type: test` nodes which may require the test registry. An agent trying to run them outside of tests would likely fail.

## Unexplored Territory

UNEXPLORED: The middle ground — a brief mention in the "Node Selection" section that `type: workflow` exists for composing workflows, with a note that it's advanced and error messages are still being improved. Not a full teaching section, just awareness.

UNEXPLORED: Whether the agent instructions should address the "One Workflow or Multiple?" section (line 217-245) differently now that nested workflows work. Currently it recommends multiple independent workflows for complex cases. With nested workflows, "multiple workflows composed together" is now a third option.

CONSIDER: The "What Workflows CANNOT Do" section (line 184-215) doesn't mention nested workflows as an escape hatch for complexity. Should it?

MIGHT MATTER: The instructions currently say "30+ nodes → Too complex → Break into multiple workflows" in the Workflow Smells section. Nested workflows change this calculus — a 30-node workflow might be better expressed as 3 nested 10-node workflows.

CONSIDER: If instructions ARE added, they should show `workflow_ref` (file-based) not `workflow_name` (library-based), since the relative path resolution bug only affects the CLI path, not the case where both parent and child are in the same directory (the common case during development).

## What I'd Tell Myself

- Read the existing braindump at `.taskmaster/tasks/task_59/starting-context/braindump-nested-workflow-gaps.md` — it has the full technical gap analysis
- The user's question was strategic, not technical. Don't get pulled into implementation details. The question is about when to teach, not how to implement.
- Check if the `examples/nested/` workflows run outside of tests before recommending anything
- The user's "we made that work in this branch" suggests they view the feature as more ready than I do. Respect that signal — they may have a use case in mind that makes the current limitations acceptable.

## Relevant Files & References

- `src/pflow/cli/resources/cli-agent-instructions.md` — current agent instructions (no nested workflow content)
- `examples/nested/main-workflow.pflow.md` — parent workflow example (uses `type: test` child)
- `examples/nested/process-text.pflow.md` — child workflow (uses `type: test` node)
- `examples/nested/isolated-processing.pflow.md` — inline workflow_ir example
- `src/pflow/runtime/workflow_executor.py` — the executor implementation (~330 lines)
- `.taskmaster/tasks/task_59/starting-context/braindump-nested-workflow-gaps.md` — technical gap braindump from Entry 14
- `.taskmaster/tasks/task_107/implementation/progress-log.md` Entry 14 — the nested workflow fixes made during Task 107

## For the Next Agent

This is a **strategic conversation with the user**, not an implementation task. The user wants to discuss whether to add nested workflow instructions now. My recommendation was against it (see reasoning above), but the user hadn't responded before the context ended.

Start by:
1. Reading this braindump and the existing technical braindump linked above
2. Checking whether `examples/nested/` workflows actually run outside test context
3. Presenting the user with the open question: do they want minimal awareness (a brief mention), a full teaching section, or to defer until Task 59 fixes the UX gaps?

The user cares most about agent experience. Frame the discussion around: "Will an agent successfully use nested workflows with the current error messages, or will they get stuck?"

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
