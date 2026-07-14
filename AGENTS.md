## Codex Agents running in Sandbox

Use `sandbox-testing` before running tests in either supported repository.

## Subagent routing

`spawn_agent` accepts per-launch `model` and `reasoning_effort` fields even though they are omitted
from the currently displayed tool schema. Both overrides are recorded in the spawned thread's
persisted `turn_context`.

Always pass both fields explicitly:

- Sonnet-equivalent work: `model: "gpt-5.6-terra"`
- Opus/Fable-equivalent work: `model: "gpt-5.6-sol"`
- Map `low`, `medium`, and `high` effort directly through `reasoning_effort`. Prefer `high` for anything other than mechanical tasks or search without judgement.

Full-history forks cannot override model or reasoning effort.
