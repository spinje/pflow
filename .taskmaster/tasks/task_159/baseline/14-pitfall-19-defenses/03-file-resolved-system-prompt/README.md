# 03 — File-resolved prompt (Path 1 boundary contract)

**Surface**: 14-pitfall-19-defenses

**Triggers**: Workflow's `prompt:` references an external file
(`./long-system-prompt.md`, ~30k chars committed alongside the workflow).
Path 1 boundary contract requires `resolve_workflow` to file-resolve
before returning to consumers.

**Why this is the Path 1 regression vector** — per task-review.md
"Stage 1 verification on lyrics-generator":

> Surfaced the architectural smell that the analyzer wasn't actually
> file-resolving prompts — `tokens=7` on a 3,752-token prompt (was
> tokenizing the literal `"./prompt.md"` filename string). Path 1 fix
> made `resolve_workflow` and `resolve_sub_workflow` both file-resolve at
> the boundary.

**Expected**: `summarize` per_call shows `input_tokens_estimated` reflecting
the FILE CONTENTS (~7000+ tokens for our ~30k-char file), NOT 1-2 tokens
from the filename string.

**Mutation contract**: revert `resolve_workflow` / `resolve_sub_workflow`
to NOT file-resolve, AND `input_tokens_estimated` collapses to single
digits. The contract test
`test_workflow_resolver_contract::test_resolve_workflow_returns_fully_file_resolved_ir`
catches this structurally; this case catches it at the analyzer surface.
