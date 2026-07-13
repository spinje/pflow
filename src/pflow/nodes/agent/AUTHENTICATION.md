# Agent Node: Claude Backend Authentication Guide

## Overview

The `agent` node with `backend: claude` spawns the Claude CLI through the Claude Agent SDK. The CLI
supports two authentication methods with different billing implications:

1. **Subscription (default)** — uses your Claude Pro/Max entitlements. No per-token charges.
2. **API key (opt in)** — bills your Anthropic Console account per token.

**By default the node uses your subscription.** It does this by blanking
`ANTHROPIC_API_KEY` for the Claude subprocess (`options.env = {"ANTHROPIC_API_KEY": ""}`
in `_build_claude_options`). Set `- use_api_key: true` on the node to bill to your
Console instead.

## Why the node blanks `ANTHROPIC_API_KEY` by default

The Claude CLI prefers an `ANTHROPIC_API_KEY` over a logged-in subscription: if the
key is present, it bills your Anthropic Console **even when you are logged into a
Pro/Max subscription**. This is a silent cost footgun, because the key is easy to
have in the environment without realising it:

- you `export ANTHROPIC_API_KEY=...` in your shell, **or**
- you ran `pflow settings set-env ANTHROPIC_API_KEY ...` for the `llm` node — pflow
  injects stored settings keys into `os.environ` at startup
  (`inject_settings_env_vars`, `src/pflow/core/llm_config.py`) so LiteLLM can find
  them. The Claude SDK subprocess then inherits that key too.

To protect subscription users, the node overrides the key with an empty string for
**its subprocess only**. `os.environ` is left untouched, so a sibling `llm` node in
the same workflow still reads the real key for LiteLLM.

### Mechanism note (why empty string, not "omit the key")

The SDK builds the subprocess environment as
`{**os.environ, ..., **options.env, ...}` (`claude_agent_sdk` subprocess transport).
`os.environ` is the **base** of that merge, so it always carries an ambient
`ANTHROPIC_API_KEY`. A dict merge can only add or overwrite keys — it cannot delete
an inherited key by leaving it out of `options.env`. The node therefore sets
`ANTHROPIC_API_KEY` to an empty string, which **overrides** the inherited value. The
CLI treats an empty key as "no key" and falls back to subscription auth (verified
with `claude auth status`: an empty `ANTHROPIC_API_KEY` reports
`subscriptionType: "max"` with no `apiKeySource`).

## Using your subscription (default)

Install and authenticate the CLI once:

```bash
npm install -g @anthropic-ai/claude-code
claude auth login          # interactive OAuth
# or, for non-interactive / CI:
claude setup-token         # long-lived token (requires a subscription)
```

Check your current auth without making a billed call:

```bash
claude auth status
```

No node configuration is required — subscription is the default.

## Using an API key (opt in)

Set `use_api_key: true` on the node and make `ANTHROPIC_API_KEY` available:

```markdown
### agent
- type: agent
- backend: claude
- prompt: Refactor this module
- use_api_key: true
```

```bash
# either of these provides the key:
export ANTHROPIC_API_KEY=sk-ant-...
pflow settings set-env ANTHROPIC_API_KEY "sk-ant-..."
```

With `use_api_key: true` the node does not blank the key, so the CLI uses it and
bills your Anthropic Console per token. This is the right choice for CI/CD, servers,
or when you have no subscription.

`use_api_key` accepts a real boolean (`true`/`false`) or the canonical string
literals (`"true"`/`"false"`/`"1"`/`"0"`/`"yes"`/`"no"`). Any other value raises a
`TypeError` — the node fails closed rather than guess and risk silent per-token
billing (e.g. the string `"false"` would otherwise be truthy).

## Billing comparison

| Mode | `use_api_key` | Billing | Best for |
|------|---------------|---------|----------|
| Subscription (default) | `false` | Claude Pro/Max — no per-token charge | Personal use, development |
| API key | `true` | Anthropic Console — pay per token | CI/CD, servers, no subscription |

## Troubleshooting

### "Claude Code could not authenticate" (default mode)
You are not logged into a subscription and the key is intentionally not used.
- Recommended: `claude auth login` (or `claude setup-token` for non-interactive/CI),
  then `claude auth status` to confirm.
- Or set `- use_api_key: true` to bill `ANTHROPIC_API_KEY` to your Anthropic Console.

### Authentication failed while `use_api_key: true`
The key may be invalid or out of credit.
- Check/replace `ANTHROPIC_API_KEY` in your Anthropic Console, or
- Remove `- use_api_key: true` to use your subscription instead.

### "Claude Code CLI not installed"
Install it: `npm install -g @anthropic-ai/claude-code`.

### `CLAUDE_CODE_PATH`
Set a custom path to the Claude CLI executable if it is not on `PATH`.

## Security best practices

1. Never commit API keys to version control.
2. Store keys via `pflow settings set-env` or your secret manager, not in workflow files.
3. Rotate keys regularly and use separate keys for development and production.
