## Codex Agents running in Sandbox

Use `sandbox-testing` before running tests in either supported repository.

## Subagent routing

Poll running subagents at four-minute intervals by default; shorter intervals are fine when a
simple implementation or searcher task is expected to finish sooner.

`spawn_agent` accepts per-launch `model` and `reasoning_effort` fields even though they are omitted
from the currently displayed tool schema. Both overrides are recorded in the spawned thread's
persisted `turn_context`.

Always pass both fields explicitly:

- Every tier: `model: "gpt-6-astra"` — the one Codex runner model. Opus- and Fable-equivalent
  work both run on it; the Sonnet tier is retired (DECISIONS #24) — never launch it.
- Map `low`, `medium`, and `high` effort directly through `reasoning_effort`. Prefer `high` for anything other than mechanical tasks or search without judgement.

Full-history forks cannot override model or reasoning effort.
