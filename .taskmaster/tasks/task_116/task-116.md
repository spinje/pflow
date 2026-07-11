# Task 116: Windows Compatibility

## Status
done

## Priority: Committed (was: Low)

## Summary

Make pflow work on Windows, verified by CI: add a `windows-latest` job to GitHub Actions and make the full test suite pass there. Previously a placeholder tracking task; scoped and committed on 2026-07-06 after a full codebase audit.

**Why now:** pflow is Unix-first by design, but Windows is the largest desktop platform for the AI agents that drive pflow. "Works on Windows" is only a real claim if CI proves it — manual spot-checks rot silently.

**Why this is smaller than it looks:** the audit found production code is already mostly Windows-safe by design (guarded `fcntl`, no fork/pty/termios, MCP delegated to a Windows-supporting SDK, TTS is pure API + browser playback). The dominant cost is the *test suite*, and one design decision (shell node → bash on Windows) collapses most of it.

---

## Verified issue inventory (audited 2026-07-06)

All claims below were verified against the current codebase by file-grounded search unless marked otherwise. Line numbers are a snapshot; file + symbol are the load-bearing identifiers.

### Blockers

#### 1. Shell node assumes a POSIX shell — the linchpin

`src/pflow/nodes/shell/shell.py:539` — `subprocess.run(command, shell=True, ...)` with no platform branch. On Windows `shell=True` means `cmd.exe`: POSIX syntax (pipes, `&&`, quoting, `$VAR`, `2>&1`) and Unix commands (`cat`, `grep`, `sed`, …) fail or behave differently.

**Reach:** not just the node. 141 test files (37% of 379; roughly 800–1,500 test functions) use Unix shell commands as the generic "any command" placeholder in workflow fixtures suite-wide — worst offenders are core tests, not shell tests (`test_markdown_parser.py` 162 occurrences, `test_cache_analysis_renderers.py` 124, `test_plan_drift.py` 81). Whatever the shell node does on Windows determines whether these tests pass, get skipped, or get rewritten.

**Decision (2026-07-06): bash-on-windows.** On win32, execute via `["bash", "-c", command]` when bash is on PATH (Git Bash — preinstalled on GitHub `windows-latest` runners, ships with Git for Windows); raise a structured `PflowError` with install guidance when absent. Rationale: one shell dialect everywhere — workflows stay portable and the 141 test files pass unmodified. Rejected: cmd.exe semantics (forces skipping 37% of the suite or rewriting ~1,000 tests, hollowing out "CI-verified"); PowerShell (third dialect, same test cost as cmd). Tradeoff accepted: soft dependency on Git Bash for Windows end users. → ADR-0013 (`context/adr/0013-116-shell-node-posix-sh-everywhere.md`), which also sharpens the contract: POSIX *sh* semantics everywhere (not bash specifically), deliberate Git-Bash resolution (never naive `which("bash")` — WSL trap), native dialects only ever additive per-step, never a default switch.

#### 2. Stdin pipe detection never fires on Windows

`src/pflow/core/shell_integration.py:143` — `stdin_has_data()` is FIFO-only (`stat.S_ISFIFO`). Windows pipes are not POSIX FIFOs, so `echo x | pflow …` is silently undetected (guarded — degrades, doesn't crash). Unchanged since Task 115.

**Fix direction:** win32 branch using `GetFileType(GetStdHandle(-10)) == FILE_TYPE_PIPE` → True, everything else False. This mirrors Unix semantics exactly (pipes detected; file redirects and consoles not). No `PeekNamedPipe` — the empty-pipe edge case doesn't justify the complexity. Logic unit-testable on Linux with mocked kernel32.

#### 3. Encoding-less text IO — 17 sites (cp1252 crashes on non-ASCII)

Python defers to the locale encoding (`cp1252` on typical Windows), so any non-ASCII content (em-dashes, glyphs, names) raises `UnicodeEncodeError`/`UnicodeDecodeError`. Verified sites missing `encoding="utf-8"`:

- `src/pflow/core/trace_report.py` — 7 sites (`_render_report_snapshot`, `_write_node_files`, marker read)
- `src/pflow/registry/registry.py` — 3 sites (2 reads + fdopen write)
- `src/pflow/cli/commands/report.py` + `run.py` — 1 each (`summary.md` read_text)
- `src/pflow/core/prompt_utils.py:28` — prompt-file read (high non-ASCII risk)
- `src/pflow/core/settings.py:157` — settings read (write side at `:260` already correct — asymmetric)
- `src/pflow/mcp/manager.py:86,121` — config read + fdopen write
- `src/pflow/nodes/mcp/node.py:485` — config read

**Enforcement:** ruff `PLW1514` (`unspecified-encoding`) is not in the current `select` list (`pyproject.toml`); adding it catches all 17 and prevents regressions permanently. `-X warn_default_encoding` (Python 3.10+ `EncodingWarning`) validates at test time on any platform.

**Stale spec claim corrected:** the old spec listed `workflow_trace.py save_to_file` as a write site. No longer true — `save_to_file` is now a thin alias to `finalize()`; the single trace writer (`workflow_trace.py:932`, post-#531 consolidation) already has `encoding="utf-8"`.

#### 4. Bare `os.rename` over possibly-existing targets

`src/pflow/core/workflow/manager.py:108` and `src/pflow/core/trace_report.py:216` rename with `os.rename`/`Path.rename`; on Windows that raises `FileExistsError` if the target exists (POSIX overwrites). ⚠️ Both rename *directories* — and Windows cannot atomically replace an existing directory even with `os.replace`. Whether the target can actually pre-exist at each site must be determined during implementation; a blind `os.replace` swap is not sufficient.

#### 5. UI detached run spawn doesn't detach on Windows

`src/pflow/ui/server.py:1096` — `start_new_session=True` (POSIX `setsid`) is silently ignored on Windows, so the ADR-0008 detachment requirement (run survives server exit) is not met. Needs `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` on win32.

#### 6. Test-suite portability gaps beyond the shell commands

- **conftest HOME leak:** `tests/conftest.py` `prepared_subprocess_env` sets `HOME` but not `USERPROFILE`; on Windows child processes resolve `Path.home()` via `USERPROFILE`, so config isolation leaks for the 35 subprocess-invoking test files. In-process tests are fine (`Path.home` is monkeypatched).
- **chmod-mode assertions:** ~15 tests assert POSIX mode bits (0o600 etc.) — meaningless on Windows, need skip or relax.
- **Symlink tests:** ~40 test functions exercise `create_skill_symlink` (`skill_service.py:214`). **Decision (2026-07-06): skip-mark on win32, no copy-fallback** — the skill service will be deprecated and rebuilt without symlinks, so investing here is waste. (Note: GitHub Windows runners run as admin so symlinks *work in CI*; the skip is about not certifying a feature end users without Dev Mode can't use and that is scheduled for removal.)
- ~20 `skipif(win32)` guards already exist (SIGPIPE, flock-liveness, Unix-pipe tests) — the pattern is established; CI iteration will reveal where more are needed.

### Verified already-safe (no work needed)

- **No** `os.fork`, `pty`, `termios`, `tty`, `grp`, `pwd`, `resource` anywhere in `src/pflow`.
- All three `fcntl` advisory-lock sites (`workflow_trace.py`, `resume_source.py`, `ui/run_tailer.py`) guard with `try/except ImportError` and degrade to heuristics. Accepted degradation on Windows: crashed-vs-running run detection loses precision (live overlay / resume liveness probes).
- `SIGPIPE` registration wrapped in `suppress(AttributeError)` (`cli/main.py`); remaining signals (SIGINT/SIGTERM) exist on Windows.
- `os.statvfs` disk checks guarded with explicit Windows comments (`write_file.py`, `copy_file.py`).
- `os.devnull` used correctly (no `/dev/null` strings); no hardcoded `/tmp`, `/bin/sh`.
- Atomic writes elsewhere already use `os.replace` (cross-platform).
- **MCP client:** zero subprocess/signal/pipe code of pflow's own — all spawning/teardown delegated to the `mcp` SDK (locked at 1.26.0, which declares a win32-only `pywin32` dependency, i.e. ships a Windows path). *Assumed correct, not source-verified:* SDK-side `.cmd`-shim resolution for `npx`/`uvx` (SDK not installed in the audit sandbox). Confirm with a Windows CI smoke test spawning an `npx`-based stdio server.
- **Voice narration (Task 174):** pure Gemini API + stdlib `wave` + browser playback — no `say`/`afplay`/platform binaries.
- **Gates/TTY (Tasks 125/171):** all interaction via Click and `isatty()` on the three std streams — portable. (These postdate the original spec; audited clean.)
- **Trace filenames:** timestamp format has no colons; names sanitized to `[a-zA-Z0-9_-]` — Windows-legal.
- **Permission hardening no-ops:** `os.chmod(0o600)` on settings is inert on Windows (won't raise). Accepted degradation, documented here.
  **Correction (2026-07-07, Chunk C):** the second half of the original claim — "the world-readable-settings warning is inert on Windows" — was wrong. `_validate_permissions` had no win32 guard, and Windows `st_mode` always reports group/other-read on regular files, so every Windows user with secrets would have gotten a spurious "insecure permissions … run chmod 600" warning on every load. Fixed: win32 early-return in `settings.py::_validate_permissions`, pinned by `test_validate_permissions_noop_on_windows`.

---

## Decisions locked (2026-07-06)

| Decision | Choice | Alternatives rejected |
|---|---|---|
| Scope | Full CI-verified support (`windows-latest`, suite must pass) | Encoding-only sweep; runtime-only without CI |
| Shell node on win32 | `["bash", "-c", cmd]` via Git Bash on PATH; clear error if absent | cmd.exe (test-suite cost), PowerShell (third dialect) |
| CI matrix | One `windows-latest` job, Python 3.13; ubuntu keeps 3.10–3.14 | Full 5-version Windows matrix (2× slower runners, version bugs rarely Windows-specific) |
| Skill symlinks | Skip-mark tests on win32 | Copy-fallback (skill service being rebuilt without symlinks — don't invest) |

## Validation constraints

- The dev sandbox is Linux (WSL2 kernel, no interop, no network) — **no Windows execution and no test execution locally**. Real `windows-latest` CI is the only ground truth; the user pushes branches herself (never commit/push from the agent).
- Consequence: the CI job must land *first* (non-blocking) so every subsequent fix gets real Windows feedback.
- Locally verifiable regardless of platform: ruff `PLW1514`, `EncodingWarning` via `-X warn_default_encoding`, unit tests mocking `sys.platform`/kernel32.

## Files affected (verified locations)

- `src/pflow/nodes/shell/shell.py` — bash-on-windows execution
- `src/pflow/core/shell_integration.py` — win32 stdin pipe detection
- 7 files with encoding-less IO (see inventory #3) + `pyproject.toml` (ruff `PLW1514`)
- `src/pflow/core/workflow/manager.py`, `src/pflow/core/trace_report.py` — directory-rename semantics
- `src/pflow/ui/server.py` — detached spawn creationflags
- `tests/conftest.py` — `USERPROFILE`; assorted tests — skip marks
- `.github/workflows/main.yml` — windows job
- `pyproject.toml` classifiers + `README.md` — declare support (final step)

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-22 | Create placeholder task | Document findings from Task 115 |
| 2026-01-22 | Defer implementation | Unix-first tool, current fallbacks are acceptable |
| 2026-01-22 | Simplified to FIFO-only | Removed unreliable `select()` fallback; Windows stdin not supported |
| 2026-07-06 | Commit to full CI-verified Windows support | User decision; "works on Windows" must be a tested claim |
| 2026-07-06 | Shell node: bash-on-windows | One dialect everywhere; saves 141 test files; Git Bash ubiquitous |
| 2026-07-06 | CI: windows-latest × Python 3.13 only | Cost control; version bugs rarely Windows-specific |
| 2026-07-06 | Skill symlinks: skip on win32 | Skill service scheduled for symlink-free rebuild |
| 2026-07-06 | Re-audited entire codebase | Jan spec predated Tasks 125–175; found 17 encoding sites (not 5), one stale claim, 3 new issue classes |
| 2026-07-06 | Deep-review (3 agents) on implementation-plan.md; 6 confirmed findings folded in | Biggest: bash resolution moved to `prep()` (exec_fallback swallows exec() raises → silent success under ignore_errors); USERPROFILE fix widened to all ~6 env builders; Windows mypy step load-bearing; win32 stdin decode + ground-truth pipe test added; EncodingWarning filter committed (PLW1514 misses os.fdopen); lru_cache dropped from bash resolver |
| 2026-07-07 | Console-encoding product fix landed pre-CI: win32 `reconfigure(encoding="utf-8")` on stdout/stderr in `cli_main()` | Failure is deterministic (cp1252-strict piped streams × `✓` glyphs), predicted broad by Chunk B handoff; each CI round costs a manual push — product fix over per-test env vars per braindump preference |
| 2026-07-07 | Fixed spurious settings-permission warning on Windows (win32 early-return in `_validate_permissions`) | Spec's "verified already-safe" claim was wrong — st_mode always shows group/other-read on Windows, so the warning would fire for every Windows user with secrets, advising a no-op `chmod 600` |
| 2026-07-07 | MCP npx smoke = CI step in `tests-windows` (add + sync `server-everything`), not an e2e pytest test | Keeps node/npx + network out of local `make test-e2e` forever; the assumption to close (SDK `.cmd`-shim spawn) is Windows-only |
| 2026-07-07 | Declaration edits (classifier/README/docs) staged with the proving push; task Status + CLAUDE.md flip only when `tests-windows` is green and gate-wired | Declaring "done" while green-up iteration may still be in flight would be false; the flip is bundled with the `continue-on-error` removal |

## Related

- Task 115: Automatic Stdin Routing for Unix-First Piping (origin of FIFO-only detection)
- Task 125 / 171: Gates + non-TTY handling (audited clean for Windows)
- Task 174: Voice narration (audited clean — no platform binaries)
- Task 175 / ADR-0008: UI detached run spawn (issue #5)
- ~~`research/stdin-fifo-detection.md`~~ — Jan 2026 Win32 API research, deleted 2026-07-06; content absorbed into `implementation/implementation-plan.md` (Phase 4) and `starting-context/braindump-2026-07-06-scoping-plan-session.md` (rejected options)
