# claude-code defaults to subscription billing by blanking ANTHROPIC_API_KEY

Status: accepted

The Claude CLI prefers an ambient `ANTHROPIC_API_KEY` over a logged-in Pro/Max
subscription, silently billing the Anthropic Console per token (issue #455). pflow
makes this worse: it injects settings-stored keys into `os.environ` at startup
(`inject_settings_env_vars`, for the `llm` node's LiteLLM path), and the claude-code
SDK subprocess inherits that key. We decided the claude-code node should **default to
subscription billing** and only use the key when the author opts in with
`use_api_key: true` (default `false`). It enforces this by setting
`options.env = {"ANTHROPIC_API_KEY": ""}` for its subprocess only — `os.environ` is
untouched, so a sibling `llm` node still reads the real key.

## Considered options

1. **Omit the key from a rebuilt env dict** (the issue's proposed fix). Does not
   work: the SDK merges `{**os.environ, ..., **options.env}`, so `os.environ` is the
   base and a dict merge cannot delete an inherited key by leaving it out. The
   subprocess would still receive the key — and the proposed unit test (asserting on
   `options.env`) would pass while the bug survived. Rejected.
2. **Pop `ANTHROPIC_API_KEY` from `os.environ` around the query.** Process-global and
   not thread-safe: it would race with parallel batch items and starve a concurrent
   `llm` node of the key it needs for LiteLLM. Rejected.
3. **Override the key with an empty string in `options.env`** (chosen). The only
   in-process, subprocess-scoped, thread-safe mechanism. The CLI treats an empty key
   as "no key" and falls back to subscription — verified against `claude` v2.1.159
   with `claude auth status` (empty `ANTHROPIC_API_KEY` → `subscriptionType: "max"`,
   no `apiKeySource`; a present key → `apiKeySource: "ANTHROPIC_API_KEY"`).

## Consequences

- **Billing-affecting default change.** Anyone who relied on an ambient key + the
  claude-code node now gets subscription billing unless they set `use_api_key: true`.
  A user with *only* a key and *no* subscription login will see an auth failure until
  they opt in; `exec_fallback` detects auth-marker error text and emits guidance
  (subscription setup first, `use_api_key: true` second). Acceptable: pflow has no
  users yet, and the alternative is silent overcharging.
- **`use_api_key` fails closed.** Node params are not coerced to bool at runtime, and
  a templated string `"false"` is truthy in Python — so the validator accepts only
  real bools / canonical string literals and raises on anything else, rather than
  risk silently re-enabling per-token billing.
- **Scope is `ANTHROPIC_API_KEY` only.** `CLAUDE_CODE_OAUTH_TOKEN` (the subscription
  path) is deliberately left intact; Bedrock/Vertex vars are not referenced by pflow
  or the SDK and are out of scope.
- **Auth detection is heuristic string-matching.** The common auth failure arrives as
  a bare `Exception` carrying the CLI's error text (the SDK rewrites the result-level
  error before re-raising) and `ProcessError.stderr` is a useless placeholder, so a
  multi-marker OR on the message is the most robust signal available; the exact
  markers may need tuning as CLI wording drifts.
