# Task 116: Windows Compatibility — Implementation Plan

## Context

pflow is Unix-first and README-declared "Windows untested". Task 116 (scoped 2026-07-06, see `.taskmaster/tasks/task_116/task-116.md` and ADR-0013) commits to **full CI-verified Windows support**: a `windows-latest` job in GitHub Actions with the full test suite passing.

A five-sweep audit found production code is mostly Windows-safe by design (guarded `fcntl`, no fork/pty, MCP delegated to the Windows-supporting SDK, TTS is API+browser). The real work: the shell node's POSIX assumption (locked decision: **bash-on-windows**, ADR-0013), Win32 stdin pipe detection, a 17-site encoding sweep, and CI green-up.

**Locked decisions:** shell node runs `["bash", "-c", cmd]` via Git Bash on win32 (deliberate resolution, never naive `which("bash")` — WSL trap); CI = one `windows-latest` job on Python 3.13; skill-symlink tests get `skipif(win32)` (skill service will be rebuilt without symlinks — do not invest).

**Validation constraint (shapes the phase order):** the dev sandbox cannot execute anything (no uv/pip/network) and cannot run Windows. Real `windows-latest` CI is the only ground truth. The user pushes all branches herself (agent NEVER runs git). Therefore the CI job lands FIRST (non-blocking), and every later phase iterates against real Windows runs.

**Verified-safe on direct read (no change; watch in CI):** `trace_report._replace_report_dir` and `manager._atomic_rename` both guarantee the rename target doesn't exist at rename time (backup-shuffle / pre-check + rmtree), so `os.rename` is Windows-OK there. All `fcntl`/SIGPIPE/statvfs sites already guarded.

---

## Phases

Phases are grouped into natural handoff chunks. **[DUMB]** = mechanical, fully specified below, a cheap agent can execute verbatim. **[SMART]** = requires judgment, error-UX conventions, or diagnosing unforeseen failures.

### ═══ Chunk A — mechanical groundwork [DUMB agent] ═══
Everything below is precisely specified; no design judgment needed. One PR-sized unit.

**Phase 1: Windows CI job (the instrument), non-blocking**
File: `.github/workflows/main.yml`
- Add job `tests-windows` (mirror `tests-and-type-check`, lines 53–76): `runs-on: windows-latest`, single `python-version: "3.13"` (no matrix), `defaults.run.shell: bash`, same pytest invocation (`uv run python -m pytest -n 2 --doctest-modules --ignore=tests/test_nodes/test_llm/test_llm_integration.py`), **`continue-on-error: true`** for now.
- **The job's `uv run mypy` step is LOAD-BEARING, not incidental** (deep-review): ubuntu mypy treats `sys.platform == "win32"` branch bodies as statically unreachable and never type-checks them — the Windows mypy run is the ONLY static check the win32-only code in this task (Phase 3 creationflags, Phase 4 ctypes) ever gets. Keep it in the job explicitly.
- Do NOT add it to the `tests-and-type-check-done` branch-protection gate yet (flipped in Phase 6).
- ✅ Verified: `.github/actions/setup-python-env/action.yml` is already Windows-compatible — `actions/setup-python@v5` + `astral-sh/setup-uv@v2` (both support Windows) and its single `run: uv sync --frozen` step declares `shell: bash` (Git Bash on windows runners). No change needed.

**Phase 2: Encoding sweep + permanent enforcement**
- `pyproject.toml` → `[tool.ruff.lint] select`: add `"PLW1514"` (unspecified-encoding).
- Add `encoding="utf-8"` at the 17 verified sites (full list in task-116.md §3): `core/trace_report.py` (7: lines ~178, 207, 208, 669, 678, 682, 688), `registry/registry.py` (80, 153, and `os.fdopen(fd, "w")` at 219), `cli/commands/report.py:91`, `cli/commands/run.py:193`, `core/prompt_utils.py:28`, `core/settings.py:157`, `mcp/manager.py` (86, fdopen at 121), `nodes/mcp/node.py:485`.
- The three `open(os.devnull, "w")` sites (`mcp/discovery.py:51`, `mcp/pool.py:311`, `nodes/mcp/node.py:274`): add `encoding="utf-8"` (harmless, quieter than noqa).
- Ruff will flag any site the manual list missed — fix those too. Tests: existing suite covers these paths; run `make check` + `make test`.
- **COMMITTED, not optional** (deep-review, two agents converged): `filterwarnings = ["error::EncodingWarning"]` in `[tool.pytest.ini_options]` (with targeted `ignore::EncodingWarning:<module>` entries for any third-party noise). Reason: PLW1514 does NOT flag `os.fdopen` — the two fdopen sites are fixed manually here, but only the runtime EncodingWarning net guards that idiom against future regression. If third-party noise proves unmanageable, escalate to the user rather than silently dropping it.
- **Gotcha — the filter alone is INERT:** Python only emits `EncodingWarning` when the interpreter runs with `-X warn_default_encoding` or `PYTHONWARNDEFAULTENCODING=1`. Set the env var for the pytest runs (Makefile test targets + the CI jobs' `env:`), or the filterwarnings line silently guards nothing.

**Phase 3: Small portability fixes**
- **USERPROFILE — fix the whole consumer set, not just the shared fixture** (deep-review: the conftest fixture is one of ~6 subprocess-env builders; two are *same-named shadow fixtures* the conftest edit never reaches). Add a small helper in `tests/conftest.py`, e.g. `set_isolated_home(env, home)` setting BOTH `env["HOME"]` and `env["USERPROFILE"]` (comment the why: subprocess `Path.home()` reads USERPROFILE on Windows — mirror the existing HOME-vs-Path.home comment at ~404). Then route every builder through it:
  - `tests/conftest.py` `prepared_subprocess_env` (~line 508)
  - `tests/test_cli/test_workflow_save.py:14-21` — module-scoped **shadow fixture** named `prepared_subprocess_env` (verified HOME-only)
  - `tests/test_cli/test_dual_mode_stdin.py:36-43` — another shadow fixture
  - `tests/test_cli/test_dry_run_subprocess.py:31-43` — `subprocess_env` fixture
  - `tests/test_cli/test_progress_streaming_subprocess.py` (~74) and `tests/test_core/test_stdin_no_hang.py:188` — inline `env["HOME"]`
  - `tests/test_cli/test_cli_error_boundary.py:84-85, 109-110, 137-138` — **the quiet one**: overrides `HOME` after inheriting the fixture without re-pointing USERPROFILE; on Windows the child reads the stale USERPROFILE and the test mis-asserts instead of crashing. Route the overrides through the helper too.
  Prefer consolidating the shadow fixtures onto the conftest one where the module-scoping allows; otherwise just use the helper in place.
- `src/pflow/ui/server.py:1091` detached spawn: platform-conditional detachment —
  ```python
  detach: dict[str, Any] = (
      {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
      if sys.platform == "win32" else {"start_new_session": True}
  )
  subprocess.Popen([...], ..., **detach)
  ```
  Preserve the load-bearing comment block (ADR-0008); extend it with one line on the win32 flags.

**Natural breakpoint A→B:** user pushes; first real Windows CI run produces the raw failure inventory. Chunk A is verifiable red/green per-file even before push (ruff/mypy locally by user). **Do NOT triage individual failures from this first run** (deep-review): the inventory is dominated by cmd.exe shell-dialect noise that Phase 5 erases wholesale — real triage starts after Chunk B lands.

### ═══ Chunk B — platform features [SMART agent] ═══
Design judgment: error UX (agent-facing message conventions per `core/CLAUDE.md`), mock strategy, resolution edge cases.

**Phase 4: Win32 stdin pipe detection**
File: `src/pflow/core/shell_integration.py`, `stdin_has_data()` (lines 73–146).
- After the existing guard chain (closed / isatty / devnull / fileno), branch: on `sys.platform == "win32"`, return `_stdin_is_pipe_windows(fd)`; else the existing `S_ISFIFO` path.
- `_stdin_is_pipe_windows`: ctypes kernel32 `GetFileType(msvcrt.get_osfhandle(fd)) == FILE_TYPE_PIPE (3)` → True; console/disk/unknown → False. Mirrors Unix semantics exactly (pipes yes, file redirects no). No PeekNamedPipe. Wrap in broad try/except → False (matching the function's existing defensive style).
- **Import seam (deep-review — gets this wrong and the whole Linux suite dies at collection):** `import msvcrt` raises `ModuleNotFoundError` on Linux and `ctypes.windll` doesn't exist there. Both MUST be imported/referenced *inside* `_stdin_is_pipe_windows`'s body (lazy), never at module top of `shell_integration.py`. Linux unit tests inject fakes via `sys.modules["msvcrt"]` / patch `ctypes.windll`.
- **Stdin DECODE fix (deep-review — detection alone leaves silent corruption):** `read_stdin()`'s text-mode `sys.stdin.read()` decodes a redirected pipe as cp1252 on Windows — which almost never raises, so UTF-8 input (`café`) becomes mojibake silently. On win32, read via `sys.stdin.buffer.read().decode("utf-8")` (mirroring `read_stdin_enhanced`'s existing UTF-8-safe path); Unix path unchanged.
- Update the big docstring's environment table with a Windows column/rows.
- Tests (new, in `tests/test_core/`): mock `sys.platform` + the ctypes calls; assert pipe→True, console→False, disk→False, exception→False. Existing `skipif(win32)` markers on `test_dual_mode_stdin.py` remain (they test real Unix FIFOs).
- **Ground-truth test on Windows (deep-review — without it the broad-except detector is unfalsifiable: a wrong GetFileType constant returns False forever and CI stays green):** one e2e test with the INVERSE skip (`skipif(sys.platform != "win32")`) piping real non-ASCII data (`café`) through the CLI to a `stdin: true` input, asserting it routes AND round-trips byte-exact. One test covers both the detector and the decode fix.

**Phase 5: Shell node bash-on-windows (ADR-0013)**
File: `src/pflow/nodes/shell/shell.py`.
- New module-level resolver, **NO `lru_cache`** (deep-review: caching `None` goes stale in the long-lived MCP server after the user installs Git, and the cache cross-contaminates tests that mock `shutil.which`; resolution is ~µs once per shell step — simplest is no cache):
  `_resolve_windows_bash() -> str | None` — order: (1) `PFLOW_BASH` env override; (2) `shutil.which("bash")` **rejected if the resolved path is under `System32`** (WSL trap — case-insensitive check); (3) derive from Git: `shutil.which("git")` → try sibling `../bin/bash.exe` and `../../usr/bin/bash.exe`; (4) `C:\Program Files\Git\bin\bash.exe` / `C:\Program Files (x86)\Git\bin\bash.exe` if they exist; else None.
- **Resolve + raise in `prep()`, NOT `exec()`** (deep-review CRITICAL, verified against code): `ShellNode.exec_fallback` (shell.py:720-738) converts every `exec()` exception into `{exit_code: -2}` — never re-raises — and `post()` (shell.py:654) then returns the SUCCESS action under `ignore_errors: true` (which the node's own docstring recommends). An `exec()`-raised missing-bash error therefore becomes a **silent green run with empty stdout**, and even without `ignore_errors` the structured diagnostic is flattened to raw stderr. `prep()` is called outside any try/except (`core/node.py:45`), so a raise there reaches the diagnostic pipeline intact and is immune to `ignore_errors`. Concretely: in `prep()` on win32, resolve bash and stash the path in the returned prep dict (e.g. `prep_res["bash_path"]`); raise there when None.
- The raise: a `PflowError` subclass with authoring-surface guidance — shell steps require a POSIX shell; on Windows install Git for Windows (https://gitforwindows.org) or set `PFLOW_BASH`. **Never mention shared store/params/lifecycle** (core/CLAUDE.md convention). `NonRetriableError` semantics moot in prep (no retry wraps it) — pick the class by diagnostic fit.
- In `exec()`: on win32, `subprocess.run([prep_res["bash_path"], "-c", command], ...)` (same capture/stdin/cwd/env/timeout kwargs, no `shell=True`); on POSIX unchanged.
- Lint: `pyproject.toml` per-file-ignores for shell.py has `S602`; the new list-form call may trigger `S603` — add it there with a comment.
- Update the node docstring (line ~18 "shell=True for maximum compatibility") to state the POSIX-sh-everywhere contract + Windows/Git-Bash behavior, referencing ADR-0013.
- Tests (`tests/test_nodes/test_shell/`): resolver unit tests (env override wins; System32 path rejected; git-derived found; none → None) with mocked `shutil.which`/filesystem; exec-path test mocking `sys.platform`+resolver asserting argv shape `[bash, "-c", cmd]`; missing-bash test asserting the error raises from `prep()` **and still surfaces when the step declares `ignore_errors: true`** (the regression the prep-raise design exists to prevent). All runnable on Linux via mocks.

**Natural breakpoint B→C:** user pushes; CI now exercises real bash-on-windows + stdin detection. Everything before this point is locally reviewable; after it, the work is CI-log-driven.

### ═══ Chunk C — CI green-up iteration [SMART agent, unavoidably] ═══

**Phase 6: iterate on real Windows failures until green, then declare**
Loop (per round: agent fixes → user pushes → read CI):
- Apply known skip-marks first: `@pytest.mark.skipif(sys.platform == "win32", reason="skill symlinks — service scheduled for symlink-free rebuild (Task 116 decision)")` on the symlink-exercising tests (`test_skill_service.py`, `test_skills.py`, `test_workflow_save_service.py` symlink cases); chmod-mode-bit assertions (~15 fns across 4 files) get skips or relaxed asserts; follow the existing ~20 `skipif(win32)` precedents.
- Diagnose the rest from CI logs. Expected classes: path-string assertions (`/` vs `\`), `\r\n` in subprocess output, cmd-vs-bash `echo` residue in tests that bypass the shell node, timing. Fix production code where the bug is real; skip-mark only what is genuinely POSIX-only. **Judgment rule: a test failing on Windows is a finding about the product first, the test second.**
- MCP smoke: one e2e-marked test (or CI step) spawning an `npx`-based stdio MCP server on Windows to close the SDK `.cmd`-shim assumption (task-116.md "Assumed correct" item). If runner npx setup is disproportionate, a CI-step-level `pflow mcp sync` against a trivial npx server suffices.
- When green: flip `continue-on-error` off; wire `tests-windows` into the `tests-and-type-check-done` gate (extend the `needs`/result check).

**Phase 7: declare support [DUMB agent]**
- `pyproject.toml` classifiers: add `"Operating System :: Microsoft :: Windows"`.
- `README.md:158`: replace "(Windows is untested)" with Windows supported, requires Git for Windows for shell steps (link ADR-0013 rationale in docs if a docs page exists — check `docs/` for an install/requirements page and update it).
- `CLAUDE.md` Project Status one-liner if appropriate; mark Task 116 done in the task file's Status + decision log.

---

## Files touched (summary)

| File | Phase | Change |
|---|---|---|
| `.github/workflows/main.yml` | 1, 6 | windows job; later gate wiring |
| `.github/actions/setup-python-env/action.yml` | 1 | verify/fix Windows compat |
| `pyproject.toml` | 2, 5, 7 | PLW1514; S603 ignore; classifier |
| 7 src files w/ encoding sites | 2 | `encoding="utf-8"` (list above) |
| `tests/conftest.py` + 6 test files w/ HOME-only env builders | 3 | shared `set_isolated_home` helper (HOME + USERPROFILE) |
| `src/pflow/ui/server.py` | 3 | win32 creationflags |
| `src/pflow/core/shell_integration.py` | 4 | win32 pipe detection + UTF-8 stdin read on win32 |
| `src/pflow/nodes/shell/shell.py` | 5 | bash resolver + exec branch |
| assorted `tests/**` | 4, 5, 6 | new unit tests; skipif marks |
| `README.md`, task-116.md | 7 | declare support |

## Verification

- **Chunk A:** `make check` (ruff PLW1514 proves the sweep complete) + `make test` — run by the user locally (sandbox can't execute). No behavior change expected on Linux; encoding args are no-ops there.
- **Chunk B:** new mocked unit tests run on Linux in `make test`; `make check` for typing. Note the asymmetry (deep-review): `sys.platform == "win32"` guards make ubuntu mypy *suppress* errors in win32 bodies, which also means it never *validates* them — the Windows job's mypy step (Phase 1) is what actually type-checks that code.
- **Chunk C:** the `windows-latest` CI run IS the verification. Green full suite on Windows + green existing ubuntu matrix (regression guard: the baseline is the current green main; any ubuntu delta is a regression this task introduced).
- **End-to-end proof at finish:** CI green on windows-latest including e2e subprocess tests (real PowerShell-spawned pflow runs happen inside those tests via `prepared_subprocess_env`), MCP npx smoke test green.

## Risks / watch-list

- Windows runner wall-clock: ~8k tests at 2× slowness; if the job exceeds ~30 min, consider `-n 4` (windows runners have 4 cores) before trimming scope.
- `os.rename` sites verified safe by inspection but exercised heavily in tests — if CI disagrees, the fix is target-absence handling, not blind `os.replace` (directories!).
- Git Bash `echo`/coreutils are GNU — the 141 fixture files should pass, but MSYS path mangling (`/foo` → `C:\...\Git\foo`) may surface in a handful of tests using absolute POSIX paths in commands; those become targeted fixes or skips in Phase 6.
- **Windows open-handle class** (deep-review): Windows refuses delete/rename of files with open handles — expect Phase 6 hits from SQLite `cache.db` under `-n 2` parallelism, tempfile cleanup, and any `NamedTemporaryFile(delete=False)` pattern (tests/CLAUDE.md already discourages it). Named here so it reads as expected, not surprising.
- **Console-encoding class**: pflow's progress output uses non-ASCII glyphs (`✓ ✗ ⚠️ ↻` in `output_controller.py`). A Windows subprocess with PIPED stdout/stderr gets cp1252 streams (strict errors) → `UnicodeEncodeError` the first time a glyph is written — this will hit the e2e subprocess tests even though CliRunner tests are immune (StringIO). Candidate fixes when it bites in Phase 6: `PYTHONIOENCODING=utf-8` in the subprocess-test env helper, or a win32 `sys.stdout/stderr.reconfigure(encoding="utf-8")` at CLI startup (a product fix benefiting real Windows users piping pflow — prefer this if the failure class is broad).
