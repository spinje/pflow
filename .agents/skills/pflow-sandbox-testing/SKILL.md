---
name: pflow-sandbox-testing
description: Run pflow's pytest suite efficiently from Codex sandbox mode. Use when validating this repository and running into problems with `uv run` or `make test` panics, tests try to write `~/.pflow`, or subprocess CLI tests fail because they invoke Homebrew `uv`.
---

# Pflow Sandbox Testing

## Commands

Use the existing virtualenv directly. In this sandbox, `uv run ...` can panic before Python starts:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest <paths-or-options>
```

Use `/private/tmp`, not `/tmp`, because macOS may report physical paths as `/private/tmp`; some shell cwd tests compare against `os.path.expanduser("~")`.

Focused example:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest tests/test_core/test_duration_format.py -q
```

Near-full sandbox baseline:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/python -m pytest -n 4 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py -k 'not test_dry_run_json_mode_emits_no_stderr and not test_litellm_not_imported_by_cli_main and not test_progress_streams_before_downstream_nodes_complete'
```

Known baseline at creation time: `5372 passed, 18 skipped` (might have changed since then).

## Known Failures

Do not trust `make test` or `uv run ...` inside this sandbox. `uv` may fail with:

```text
Attempted to create a NULL object.
Tokio executor failed
```

The three excluded tests spawn `/opt/homebrew/bin/uv` directly, so they fail for sandbox/tooling reasons:

- `tests/test_cli/test_dry_run_subprocess.py::test_dry_run_json_mode_emits_no_stderr`
- `tests/test_cli/test_lazy_imports.py::test_litellm_not_imported_by_cli_main`
- `tests/test_cli/test_progress_streaming_subprocess.py::TestRealSubprocessProgressRendering::test_progress_streams_before_downstream_nodes_complete`

If tests write to `/Users/<username>/.pflow`, set `HOME=/private/tmp/pflow-test-home`. `ExecutionCache` uses `Path.home() / ".pflow"` and otherwise hits sandbox permission errors.
