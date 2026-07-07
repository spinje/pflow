# Task 116 Review: Windows Compatibility

## Metadata

- Implemented 2026-07-06 -> 2026-07-07 on `agent/windows-compatibility`.
- Commit anchor: `ef25113e Add Windows compatibility support`.
- PR: https://github.com/spinje/pflow/pull/564, draft at review creation.
- Status at review creation: implemented and locally verified; **not complete until `tests-windows`
  is green, `continue-on-error` is removed, and the Windows job is wired into the aggregate gate**.
- Local gates before PR: `make check` green; `make test` 8709 passed; `make test-e2e` 44 passed,
  1 skipped. Expected warning residue: test/third-party `EncodingWarning`s that are deliberately
  non-fatal.
- The chronological journey lives in `implementation/progress-log.md`. This review is the durable
  forward-reference: contracts, seams, and the CI handoff.

## Read First - the load-bearing block

**What exists now:** pflow has a `windows-latest` CI instrument, Windows production fixes for the
shell node, stdin detection, UTF-8 console/file I/O, detached UI-spawned runs, settings permission
warnings, and subprocess-test home isolation. The key product decision is ADR-0013: a shell step
means **POSIX sh everywhere**. On Windows, Git Bash supplies that shell; pflow does not silently
switch to `cmd.exe` or PowerShell.

**Read these first (path - symbol):**

- `context/adr/0013-116-shell-node-posix-sh-everywhere.md` - the dialect contract and WSL trap.
- `.github/workflows/main.yml` - `tests-windows`, debug bash-resolution step, Windows mypy, MCP
  `npx` smoke, current `continue-on-error` state.
- `src/pflow/nodes/shell/shell.py` - `_resolve_windows_bash`, `_windows_bash_or_raise`,
  `ShellNode.prep`, `ShellNode.exec`, `exec_fallback`.
- `src/pflow/core/shell_integration.py` - `stdin_has_data`, `_stdin_is_pipe_windows`,
  `read_stdin`.
- `src/pflow/cli/main.py` - `_reconfigure_windows_stdio`, `cli_main`.
- `src/pflow/core/settings.py` - `_validate_permissions`.
- `src/pflow/ui/server.py` - detached `subprocess.Popen` kwargs for ADR-0008 run survival.
- `tests/conftest.py` - `set_isolated_home`.
- `pyproject.toml` - `PLW1514`, preview-rule settings, scoped `EncodingWarning` filter, shell
  per-file ignores.
- High-signal tests: `tests/test_nodes/test_shell/test_windows_bash.py`,
  `tests/test_core/test_stdin_windows.py`, `tests/test_cli/test_dual_mode_stdin.py` Windows pipe
  e2e, `tests/test_cli/test_main.py`, `tests/test_core/test_settings.py`,
  `tests/test_encoding_warning_net.py`.

**Invariants that must NOT break:**

1. **Shell node contract is POSIX sh everywhere.** Never add a default `cmd.exe`/PowerShell fallback.
   Native shells may only be additive opt-in per-step behavior, not a default switch.
2. **Missing Git Bash must raise from `prep()`, not `exec()`.** `exec_fallback` catches every
   `exec()` exception and can turn missing bash into a green run under `ignore_errors: true`.
   The engine-level test pins this; do not "simplify" it back to `exec`.
3. **Windows bash resolution is deliberate, uncached, and rejects System32.** `PFLOW_BASH` wins and
   is trusted when non-empty; `C:\Windows\System32\bash.exe` is the WSL trap and must not be used;
   no `lru_cache` because a long-lived MCP server can outlive a Git install and tests can
   cross-contaminate mocked `shutil.which`.
4. **Win32-only imports stay lazy.** `msvcrt` and `ctypes.windll` must be referenced inside
   `_stdin_is_pipe_windows`; importing either at module load breaks Linux collection.
5. **Win32 stdin text read uses a `TextIOWrapper`, not raw bytes decode.** This preserves universal
   newline behavior (`\r\n` -> `\n`) and avoids starving the enhanced/binary fallback by consuming
   the whole stream before a decode failure.
6. **Windows stdout/stderr UTF-8 reconfigure preserves the existing error handler.** `stderr`
   normally uses `backslashreplace`; `reconfigure(encoding="utf-8")` alone resets it to `strict`,
   which can crash while reporting an error. Keep `errors=stream.errors`.
7. **The `EncodingWarning` net is scoped to `pflow.*`.** A blanket
   `error::EncodingWarning` detonates on test fixtures and third-party libraries; the goal is to
   catch pflow source regressions, especially `os.fdopen`, which `PLW1514` misses.
8. **`PLW1514` only works because ruff preview mode is explicit.** Keep
   `preview = true` and `explicit-preview-rules = true`; otherwise the selected rule has no effect.
9. **Do not certify skill symlinks on Windows.** The service is scheduled for rebuild without
   symlinks; skip-mark real symlink tests on win32 rather than adding copy fallback or relying on
   GitHub runners' admin symlink privilege.
10. **Do not mark Task 116 done while `tests-windows` is non-blocking.** Green local Linux and green
    ubuntu CI are not enough; the claim is "CI-verified Windows support."

## What Was Built

### CI and declaration

- Added `tests-windows` on `windows-latest`, Python 3.13, Git Bash shell, pytest, mypy, and MCP
  smoke coverage. It currently stays `continue-on-error: true` so the first Windows iteration does
  not block the existing gate.
- Kept Windows mypy load-bearing: Linux mypy treats normal `if sys.platform == "win32"` bodies as
  unreachable, so the Windows run is the only static check for the ctypes and creationflags arms.
- Added a `Debug: bash resolution` step. Read it first in CI triage; if it does not resolve Git
  Bash, the shell-node premise is wrong.
- Added a Windows-only MCP smoke step using `npx @modelcontextprotocol/server-everything` through
  `pflow mcp add` + `pflow mcp sync everything`. This closes the SDK `.cmd` shim assumption without
  forcing node/network into local `make test-e2e`.
- Added Windows classifier and docs/README install notes. The task status and CLAUDE.md completion
  flip are intentionally deferred until the Windows job is blocking and green.

### Shell node

- Added `_resolve_windows_bash()` with this order: `PFLOW_BASH`; PATH `bash` unless under
  System32; Git-derived install probes; default Git for Windows paths.
- Added `_windows_bash_or_raise()` and called it from `ShellNode.prep`, storing `bash_path` in the
  prep result for the win32 `exec()` branch.
- On Windows, `exec()` now calls `[bash_path, "-c", command]` with the same cwd/env/stdin/capture
  semantics as before. POSIX stays on the prior `shell=True` path.
- The missing-bash error is `UserFriendlyError` with authoring-surface guidance: install Git for
  Windows or set `PFLOW_BASH`. It does not mention node lifecycle internals.

### Stdin and console encoding

- `stdin_has_data()` now detects real Windows pipes with
  `GetFileType(msvcrt.get_osfhandle(fd)) == FILE_TYPE_PIPE`. Console, disk/file redirect, unknown,
  or exceptions return false, matching the defensive Unix behavior.
- `read_stdin()` on win32 wraps `sys.stdin.buffer` with `io.TextIOWrapper(..., encoding="utf-8",
  newline=None)` and detaches it afterward. This pins UTF-8 while preserving newline translation
  and fallback behavior.
- `cli_main()` reconfigures real Windows stdout/stderr `TextIOWrapper`s to UTF-8, preserving each
  stream's `errors` policy. It skips `StringIO`/Click test captures and leaves stdin to
  `shell_integration`.

### Encoding and filesystem portability

- Added explicit `encoding="utf-8"` to the verified pflow source sites plus the `os.devnull` opens.
- Enabled `PLW1514` and fixed the broader preview-discovered test source sites in scope for the
  branch.
- Added `PYTHONWARNDEFAULTENCODING=1` to test targets and CI so `EncodingWarning` can actually fire.
- Scoped pytest's warning promotion to `pflow.*` after proving the blanket filter was the wrong
  surface for third-party and pytest fixture code.
- `settings._validate_permissions` returns early on Windows so users do not get a false "run chmod
  600" warning on normal Windows `st_mode` bits.
- `ui.server` uses `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` on Windows and
  `start_new_session=True` elsewhere, preserving ADR-0008's "run survives server exit" requirement.
- `tests.conftest.set_isolated_home()` sets both `HOME` and `USERPROFILE`; every subprocess env
  builder that overrides home routes through it.

### Test-suite shaping

- Added Windows-mocked unit coverage for pipe detection, stdin decoding, bash resolution, missing
  bash diagnostics, real-bash execution of the win32 branch, console reconfiguration, and settings
  permissions.
- Added one Windows-only real pipe e2e in `test_dual_mode_stdin.py` that sends non-ASCII UTF-8
  through the CLI and asserts byte-exact routing.
- Skip-marked real symlink and chmod-permission tests that do not represent portable Windows
  product behavior. Mock-only CLI skill tests remain live.

## What Was Deliberately Not Built

- No cmd.exe or PowerShell fallback.
- No `pywin32` dependency; ctypes + stdlib `msvcrt` are enough for pipe detection.
- No `PeekNamedPipe`; Unix can also block on an open-but-empty pipe, and symmetry beats extra
  complexity here.
- No copy fallback for skill symlinks.
- No job-wide `PYTHONUTF8=1`; it would mask the product-level stdout/stderr reconfigure path.
- No `MSYS_NO_PATHCONV` default yet. It is the systemic lever if Git Bash path mangling is broad,
  but it changes user-visible semantics and should be a user decision based on CI evidence.
- No completion flip in `task-116.md` or CLAUDE.md until the Windows job is green and blocking.

## Patterns & Anti-Patterns

**Patterns to propagate:**

- **Win32 branches as small seams with Linux-mock tests.** Keep platform-specific calls behind tiny
  helpers, then test those helpers by patching `sys.platform` and fake modules/objects.
- **Raise outside swallowing layers.** The shell-node missing dependency is a prep-time authoring
  error because the exec layer intentionally converts execution failures into node outputs.
- **Product fix over test-only env var.** The console glyph crash class affects real users piping
  pflow, so fixing `cli_main()` is better than hiding it with per-test `PYTHONIOENCODING`.
- **One home for test home isolation.** Use `set_isolated_home` whenever subprocess tests need a
  fake home; setting only `HOME` is wrong on Windows.
- **CI smoke for Windows-only external assumptions.** The MCP npx check belongs in
  `tests-windows`, not local e2e.

**Anti-patterns (do not resurrect):**

- Raising missing bash from `exec()`.
- Naive `shutil.which("bash")` with no System32 rejection.
- Caching bash resolution.
- Module-scope `msvcrt`/`ctypes.windll`.
- Raw `sys.stdin.buffer.read().decode("utf-8")` for win32 stdin.
- Blanket `error::EncodingWarning`.
- Skipping portable mock-only tests just because their domain also has a Windows skip class.

## Gotchas & Non-Obvious Coupling

- **`sys.platform` monkeypatch infects stdlib behavior.** In tests, patching platform to win32 makes
  `shutil.which` PATHEXT-probe `bash.exe` and can trigger Windows-only imports in unrelated code.
  Resolve real bash paths before faking win32, or mock the resolver.
- **Mypy unreachable behavior is statement-sensitive.** Ubuntu mypy skips normal
  `if sys.platform == "win32"` statement bodies, but a ternary expression still exposed
  Windows-only `subprocess.DETACHED_PROCESS` to Linux typeshed. Use real `if` statements for these
  branches.
- **`ctypes.windll` and `msvcrt.get_osfhandle` type ignores need `unused-ignore`.** On Linux the
  ignore suppresses attr-defined; on Windows the same ignore may be unused under
  `warn_unused_ignores`.
- **Windows file-delete/rename with open handles may still appear in CI.** Expect cache DB or
  temporary-file cleanup failures under xdist; fix product/test ownership from the specific log,
  not preemptively.
- **Git Bash path mangling is possible.** Absolute POSIX-looking args can be rewritten by MSYS.
  If failures are broad, consider `MSYS_NO_PATHCONV`, but only after surfacing the behavior change.
- **The Windows settings-permission bug was real product behavior, not test noise.** Windows
  regular files report group/other-readable mode bits; without the guard every user with secrets
  would get a false chmod warning.
- **Ruff `PLW1514` is incomplete around unannotated pytest fixtures.** Runtime
  `EncodingWarning` remains useful because static analysis misses many `tmp_path`-derived paths and
  all `os.fdopen` sites.
- **`tests-windows` mypy and MCP smoke use `if: ${{ !cancelled() }}` intentionally.** During
  red-green iteration, a failing pytest step should not hide the Windows type/smoke signals.

## Integration Points

- **CI gate:** `.github/workflows/main.yml` gains `tests-windows`. Final merge readiness requires
  removing `continue-on-error` and adding `tests-windows` to `tests-and-type-check-done`'s `needs`
  and result expression.
- **Shell-node contract:** ADR-0013 is now the durable user-facing rationale. Any future per-step
  native shell mode must be additive and explicit.
- **CLI entry path:** `cli_main()` is now the only real-process stdio reconfigure seam. Tests that
  call Click commands directly bypass it by design.
- **Stdin routing:** Task 115's Unix FIFO logic is extended, not replaced. File redirects still do
  not count as "stdin has data"; pipes do.
- **Settings security UX:** chmod hardening remains meaningful on POSIX and becomes a no-op warning
  path on Windows.
- **UI run spawning:** Task 175 / ADR-0008 detached-run guarantees now have a Windows creationflags
  arm.
- **Test isolation:** subprocess tests must set both `HOME` and `USERPROFILE`; in-process tests can
  still rely on the existing `Path.home` monkeypatch.
- **Docs/declarations:** README, quickstart, and classifier now state Windows support and the Git
  for Windows requirement for shell steps. Do not treat that declaration as final until the CI gate
  is blocking.

## Tests That Matter

- `tests/test_nodes/test_shell/test_windows_bash.py` - resolver order, System32 rejection,
  prep-time missing-bash failure, `ignore_errors` regression through the real runner, argv shape,
  real bash execution of the win32 branch.
- `tests/test_core/test_stdin_windows.py` - GetFileType behavior table, lazy import seam,
  routing, UTF-8 decode, CRLF normalization, invalid UTF-8 fallback behavior, empty pipe contract.
- `tests/test_cli/test_dual_mode_stdin.py::test_windows_pipe_utf8_round_trip` - Windows-only real
  pipe ground truth for detector + decode + CLI routing.
- `tests/test_cli/test_main.py::TestWindowsStdioReconfigure` - UTF-8 stdout/stderr repin, POSIX
  untouched, StringIO untouched, error handler preserved, `cli_main()` wiring.
- `tests/test_core/test_settings.py::test_validate_permissions_noop_on_windows` - mutation-proven
  guard against false Windows chmod warnings.
- `tests/test_encoding_warning_net.py` - warning filter is live for pflow source and scoped away
  from non-pflow modules.
- `tests/conftest.py` helper consumers - any new subprocess env builder should route through
  `set_isolated_home`.

## CI Handoff Protocol

The first real Windows run is the ground truth. Triage in this order:

1. Read `Debug: bash resolution`. If it resolves System32/WSL bash or nothing, stop and fix bash
   discovery before interpreting pytest failures.
2. Read Windows pytest failures. Treat each as a product finding first, a test portability issue
   second.
3. Read Windows mypy even if pytest failed; it is the only static check for win32-only code.
4. Read the MCP npx smoke. Failure likely means the SDK `.cmd` shim assumption is false or pflow is
   passing command metadata in the wrong shape.
5. Known likely classes: test-side `subprocess.run(text=True)` cp1252 decode, residual
   chmod/symlink inventory misses, MSYS path mangling, open-handle cleanup, MAX_PATH.
6. If green: remove `continue-on-error`, wire `tests-windows` into the done gate, set Task 116
   status to `done`, and update CLAUDE.md's task status if still expected.

---
*Distilled from the implementation context of Task 116. The chronological record and per-round
decisions live in `implementation/progress-log.md`; this review is the durable forward-reference
for future Windows work and CI triage.*
