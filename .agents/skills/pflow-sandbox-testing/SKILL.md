---
name: pflow-sandbox-testing
description: Run focused pflow tests and CLI checks safely inside Codex sandbox mode on Windows, macOS, or Linux. Use when `make test`, `make check`, or `uv run` fails because of sandboxed caches or home-directory writes; Windows Git Bash or subprocess tests fail; or validation must be split between local focused checks and GitHub Actions.
---

# Pflow Sandbox Testing

## Operating Rules

1. Detect the host platform and invoke the existing virtualenv directly. Do not use `uv run` merely to launch Python or pytest inside the sandbox.
2. Run the smallest test path that proves the change. Expand scope only when the preceding layer passes.
3. On Windows, bound every unfamiliar batch to 30 seconds. If it reaches the limit, terminate it and its exact child process tree; do not retry a broader command.
4. Do not run pflow's full Windows suite in the Codex sandbox. Use GitHub Actions for authoritative Windows shell, subprocess, e2e, and full-suite validation.
5. Treat sandbox-specific failures as environment evidence, not product regressions, until a focused reproduction succeeds outside the restricted boundary or fails in CI.

## Direct Virtualenv Commands

Set `PYTHONWARNDEFAULTENCODING=1` in the environment so pytest-xdist workers inherit the encoding-warning guard. Do not replace it with `python -X warn_default_encoding` in parallel runs; interpreter flags do not propagate to xdist worker interpreters.

### Windows PowerShell

```powershell
$env:PYTHONWARNDEFAULTENCODING = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_core\test_duration_format.py -q
```

If tests use `Path.home()` or write pflow state, redirect both Windows home variables to writable temp space:

```powershell
$testHome = Join-Path $env:TEMP "pflow-test-home"
New-Item -ItemType Directory -Force $testHome | Out-Null
$env:HOME = $testHome
$env:USERPROFILE = $testHome
```

### macOS

```bash
HOME=/private/tmp/pflow-test-home \
PYTHONWARNDEFAULTENCODING=1 \
.venv/bin/python -m pytest tests/test_core/test_duration_format.py -q
```

Use `/private/tmp` because physical-path comparisons may resolve `/tmp` to `/private/tmp`.

### Linux

```bash
HOME="${TMPDIR:-/tmp}/pflow-test-home" \
PYTHONWARNDEFAULTENCODING=1 \
.venv/bin/python -m pytest tests/test_core/test_duration_format.py -q
```

## Validation Ladder

Use these layers in order:

1. **Collection diagnosis:** `python -m pytest --collect-only -qq <scope>`
2. **Focused behavior:** one test, class, or file
3. **Related regression surface:** a small explicit list of files
4. **Directory batch:** only when its expected runtime is known and bounded
5. **Broader POSIX run:** only when proportional to the task
6. **Full Windows or broad e2e run:** GitHub Actions

Example broader non-e2e macOS run:

```bash
HOME=/private/tmp/pflow-test-home \
PYTHONWARNDEFAULTENCODING=1 \
.venv/bin/python -m pytest -n 4 --dist=worksteal --doctest-modules \
  --ignore=tests/test_nodes/test_llm/test_llm_integration.py -m "not e2e"
```

Do not hard-code historical pass counts in validation reports. Report the command, platform, exit status, and current result.

## Windows Sandbox Failure Signatures

### uv cache access

`uv`, `make test`, or `make check` may try to access `%LOCALAPPDATA%\uv\cache` and fail with `Access is denied`. Use `.venv\Scripts\python.exe` or the relevant `.venv\Scripts\*.exe` tool directly. Do not relocate or rebuild the environment as a workaround.

### Git Bash process creation

Shell-dependent tests may fail with:

```text
bash.exe: *** fatal error - couldn't create signal pipe, Win32 error 5
```

This is a sandbox process-permission failure. Stop the affected batch; repeated shell launches create a large failure storm and can make pytest spend excessive time formatting and transporting failures. Validate non-shell behavior locally and defer Git Bash behavior to Windows CI.

### Buffered or silent long runs

No output does not prove a run is healthy. If a bounded command yields a running process, enforce the original deadline. Terminating the parent tool call may leave `make`, `python`, or `bash` children alive on Windows, so record the run's start time or PIDs and verify that only processes created by that run are stopped. Never kill unrelated user processes by name alone.

## Other Sandbox Failure Signatures

- `Attempted to create a NULL object` or `Tokio executor failed` before Python starts: bypass `uv` and use the virtualenv executable directly.
- Writes under `~/.pflow` or the real user home fail: redirect home to a writable temp root.
- Network, remote MCP, LiteLLM, or external API checks fail: treat restricted network or credentials as the leading cause; do not weaken tests to make them pass.
- A required validation genuinely needs downloads, credentials, network, or writes outside workspace/temp: request the appropriate permission instead of constructing a brittle workaround.

## Quality Checks Without `make check`

Run only the tools relevant to the change through `.venv` when `uv lock` or tool caches are blocked. Examples on Windows:

```powershell
.\.venv\Scripts\ruff.exe check <paths>
.\.venv\Scripts\ruff.exe format --check <paths>
.\.venv\Scripts\python.exe -m mypy <paths>
```

Do not claim that `make check` passed when only selected tools ran. Lock consistency, pre-commit, and the complete quality gate remain separate checks for an unrestricted environment or CI.

## Manual pflow Checks

Prefer the virtualenv CLI directly:

```powershell
.\.venv\Scripts\pflow.exe --help
.\.venv\Scripts\pflow.exe guide core
```

On macOS:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow --help
HOME=/private/tmp/pflow-test-home .venv/bin/pflow guide core
```

On Linux:

```bash
HOME="${TMPDIR:-/tmp}/pflow-test-home" .venv/bin/pflow --help
HOME="${TMPDIR:-/tmp}/pflow-test-home" .venv/bin/pflow guide core
```

Good sandbox checks include `--validate-only`, `--dry-run`, `--print`, JSON output, and code or local-file workflows confined to workspace/temp. On Windows, do not use shell-node workflows to certify behavior after the Git Bash signal-pipe failure appears.

## CI Handoff

Use the latest Windows GitHub Actions job to distinguish a sandbox limitation from a repository regression. CI is authoritative for:

- the full Windows suite;
- Git Bash and real subprocess behavior;
- e2e tests and subprocess CLI entry points;
- global `uv`/Make integration outside sandbox filesystem restrictions.

When handing off, state which focused checks passed, which checks were skipped because of sandbox boundaries, and which CI job must provide the remaining proof.
