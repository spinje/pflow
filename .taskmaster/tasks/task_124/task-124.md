# Task 124: Code Node Dependency Management

## Description

Add a proper way to install and manage third-party Python packages for code nodes, without requiring users to understand `uv tool` vs `pipx` internals or risk losing existing extras.

## Status

not started

## Priority

low

## Problem

Code nodes can import any installed package, but installing packages into pflow's isolated environment is awkward:

- **pipx**: `pipx inject pflow-cli pandas` works and is additive — but only if you installed with pipx.
- **uv tool**: `uv tool install --with pandas pflow-cli` **replaces** the entire environment. If you forget to re-specify existing `--with` flags (like `--with llm-openrouter`), you lose them. You must run `uv tool list --show-with` first and include everything.
- **The error message** currently suggests both approaches with a warning, but agents and users still need to understand the difference.
- **The `requires` field** on code nodes is documentation-only — it doesn't install or validate anything.

This is the kind of thing where users (and their agents) will get burned once and lose trust.

## Desired outcome

A single pflow command that handles package installation correctly regardless of how pflow was installed:

```bash
pflow deps add pandas
pflow deps list
pflow deps remove pandas
```

Or alternatively, make `requires` on code nodes actually enforce/install dependencies before execution.

## Options to explore

1. **`pflow deps` CLI** — Detect the install method (uv tool, pipx, pip) and run the right command. `pflow deps add pandas` would call `pipx inject` or `uv tool install --with` (preserving existing extras) under the hood.

2. **Auto-install from `requires`** — When a code node has `requires: ["pandas"]` and the import fails, offer to install it automatically (with user confirmation).

3. **Virtual environment approach** — Maintain a separate venv for code node dependencies, independent of pflow's tool environment. More complex but avoids the uv/pipx problem entirely.

4. **Do nothing, improve docs** — Keep the current approach but make the error messages and docs clear enough that it's manageable. (Current state after today's fixes.)

## Current workarounds

- Error message in `python_code.py` suggests `pipx inject` (safe) and `uv tool list --show-with` before `uv tool install` (safe if followed).
- Docs accordion in `docs/reference/nodes/code.mdx` explains the caveats.
- LLM plugins have the same problem and are documented the same way in `docs/reference/nodes/llm.mdx`.

## Related

- Task 104: Python Code Node (original implementation)
- `src/pflow/nodes/python/python_code.py` lines 401-412 (ImportError handling)
- `docs/reference/nodes/code.mdx` (imports accordion)
- `docs/reference/nodes/llm.mdx` (same pattern for llm plugins)
