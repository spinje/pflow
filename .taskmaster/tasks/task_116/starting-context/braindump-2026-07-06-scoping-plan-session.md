# Braindump: Task 116 Scoping + Planning Session (2026-07-06)

For the implementing agents. This is the tacit layer — what the spec (`task-116.md`), plan (`implementation/implementation-plan.md`), ADR-0013, and breakdown (`implementation/plan-breakdown.md`) deliberately don't carry: session dynamics, evidence trails, rejected paths, gut feelings, and environment traps. Read the plan first; read this second; don't re-derive what's below.

## Where I Am

Spec rewritten (verified inventory, corrected stale claims), ADR-0013 written, plan approved by the user and then amended with 6 confirmed deep-review findings + 3 suggestions, breakdown written. **Zero code written.** Chunk A (phases 1–3) is next. The deep-review battery was: `review-plan`, `review-silent-failures`, `review-impact-completeness` — their findings are folded into the plan with `(deep-review)` markers; the full agent transcripts are gone with my context, but nothing load-bearing was left out.

## The Environment Will Lie to You

- **This sandbox cannot execute anything.** No `uv`, no `pip`, no network to PyPI (`curl` → 000), bare system Python 3.11, no `.venv`. `make test` / `make check` are impossible here. The kernel says WSL2 but there's no `/mnt/c`, no interop, no `python.exe` — you cannot touch Windows either. **Check `command -v uv` before assuming your session is different; don't burn time trying to bootstrap.** The loop is: write code → ask the user to run `make check && make test` locally (or push) → read results. Budget for that latency; batch your asks.
- Everything "verifiable locally" in the plan means *the user's machine or CI*, not your sandbox. What you CAN do here: read code, grep, reason, write.

## User's Mental Model (calibrate to this)

- **Precision of language matters to her.** When I said "we use bash for pflow right now," she probed until the truth surfaced: the contract is **POSIX sh** (what `/bin/sh` provides — dash on Debian, bash-in-sh-mode on macOS), not bash. ADR-0013 is written in those terms. Don't say "bash semantics" in code comments or errors; say POSIX shell.
- **She decides reversibility questions; bring her the tradeoff, not the decision.** The bash-on-windows call went through an explicit "why is this hard to reverse, what would we switch to" discussion before she accepted. The resolution was: the *default* dialect is forever; native dialects may only ever arrive as additive opt-in per-step params. If Phase 6 pressure tempts you to soften the missing-bash error into a cmd.exe fallback — **that is a decision she owns, stop and ask.**
- **Never run `git`/`gh`.** Not commit, not push, not even status-adjacent conveniences — she handles all of it and prefers not to be asked (CLAUDE.local.md). Hand her a "ready to push" note instead.
- **"Show Before You Code" applies to the Phase 5 error message.** The missing-bash `PflowError` text is user-visible output — per CLAUDE.md, show her the exact wording (title/explanation/suggestions) before implementing. Same for any new warning text Phase 6 introduces.
- She invoked the smart/dumb agent split deliberately — she's cost-aware about which model does what. The breakdown's outsourcing map is the contract; don't hand Phase 5's prep-raise to a subagent because it "looks small."

## Evidence Trails (so you don't re-verify — or know exactly what's still soft)

- **"141 test files use shell commands"** comes from a grep survey (3,451 occurrences; top offenders `test_markdown_parser.py` 162, `test_cache_analysis_renderers.py` 124). The claim "they mostly pass under Git Bash" is a *hypothesis* — GNU coreutils ship with Git Bash, but nobody has run it. CI run #2 is the experiment.
- **MCP `.cmd`-shim resolution** is inferred, not read: `uv.lock` pins `mcp` 1.26.0 which declares `pywin32; sys_platform == 'win32'` — proof the SDK ships a Windows path, not proof `npx` spawning works. The SDK source wasn't installed anywhere I could read. Hence the Phase 6 smoke test.
- **"Git Bash is on PATH on windows-latest runners"** is from training knowledge, not verified this session. Cheap insurance: make CI run #1's windows job print `which bash && bash --version` as a debug step — if that's WSL bash or nothing, Phase 5's premise needs rework *before* Chunk B.
- **GitHub Windows runners run as admin** → symlinks work in CI. That's why the skill-symlink skips are a *product* decision (service being rebuilt — see memory `skill-service-deprecation`), not a CI necessity. Don't let a green symlink test in CI convince you to unskip.
- The Jan-2026 research file (`research/stdin-fifo-detection.md`) was **deleted 2026-07-06** after its load-bearing content was absorbed into the plan (GetFileType approach + constants) and this braindump (rejections). One refinement over it survives: the plan uses `msvcrt.get_osfhandle(fd)` rather than the research's `GetStdHandle(-10)`, to honor the fd the function was given.

## Deliberate Non-Choices (don't "improve" these back in)

- **No `pywin32` dependency.** ctypes + msvcrt (stdlib) are deliberate — pflow gains zero Windows-only deps from this task. An agent reaching for `import win32file` is regressing a choice.
- **No `PeekNamedPipe`.** The empty-pipe edge (pipe open, no data yet → we'd block on read) was judged not worth the complexity; Unix has the same blocking behavior on an empty-but-open FIFO. Symmetry beats cleverness.
- **No `msvcrt.kbhit()`.** Explored in the Jan-2026 research (file since deleted): it only detects console *keyboard* input, never pipe data — useless for this problem. Don't re-explore it. (Other GetFileType returns, for reference: 1=DISK, 2=CHAR, 3=PIPE; anything ≠3 → False.)
- **No cmd.exe/PowerShell fallback, no copy-fallback for symlinks, no lru_cache on the resolver** — all rejected with reasons recorded (ADR-0013, spec decision table, plan Phase 5).
- **`git --exec-path` for bash discovery was considered and dropped** — it returns `libexec/git-core`, a different relative hop from bash; the sibling-path probes from `which("git")` are simpler and cover the same installs.
- **`detect_stdin()`** (`shell_integration.py:64`, plain `not isatty`) is production-unused — export + tests only. Don't route the win32 fix through it, and don't unify it with `stdin_has_data()` "while you're there."

## Gotchas Discovered Too Late for the Plan's First Draft (now patched in, but know the why)

- **`EncodingWarning` is opt-in at the interpreter level.** `filterwarnings = ["error::EncodingWarning"]` does nothing without `PYTHONWARNDEFAULTENCODING=1` (or `-X warn_default_encoding`) on the process. Set the env var in Makefile test targets AND the CI jobs. Sanity-check it fires: temporarily revert one encoding fix, confirm the suite goes red on the user's machine.
- **The `✓ ✗ ⚠️ ↻` glyph crash class** (plan watch-list): Windows piped stdout is cp1252-strict; the first glyph write in a subprocess e2e test raises `UnicodeEncodeError`. CliRunner tests are immune (StringIO). If Phase 6 shows this broadly, prefer the product fix (win32 `reconfigure(encoding="utf-8")` at CLI entry) over per-test env vars — real Windows users piping pflow hit the same crash. That's a "show the user first" moment.
- **MSYS path mangling has an escape hatch** the docs don't mention: `MSYS_NO_PATHCONV=1` / `MSYS2_ARG_CONV_EXCL` env vars disable Git Bash's `/foo` → `C:\...\Git\foo` rewriting. If Phase 6 finds the mangling class is *wide*, setting that env in the shell node's win32 invocation is a one-line systemic fix — but it changes semantics for users who *want* conversion, so it's a user decision, not a silent fix.

## Assumptions & Uncertainties (ranked by blast radius)

1. ASSUMPTION: Git Bash on runner PATH (see debug-step insurance above). Wrong → Chunk B premise breaks.
2. ASSUMPTION: the 141 shell-fixture files pass under Git Bash. Wrong-in-part → Phase 6 grows; wrong-broadly → escalate, don't grind.
3. ASSUMPTION: windows job wall-clock is tolerable (~8k tests, ~2× slower runners, `-n 2`). If >30 min, bump to `-n 4` (4-core runners) before touching scope.
4. ASSUMPTION: mcp SDK resolves `.cmd` shims (lockfile evidence only). Phase 6 smoke test closes it.
5. UNCLEAR: whether GH Windows runners have long paths enabled — `tmp_path_factory` nesting + report dirs could brush MAX_PATH (260). If you see `FileNotFoundError` on paths that plainly exist, check length before anything else.
6. UNCLEAR: reserved device names (`con`, `nul`, `aux`) as step IDs would produce unwritable report filenames — `safe_id` sanitizes charset, not reserved names. Almost certainly nobody names a step `con`; note it, don't fix it preemptively.

## Unexplored Territory

- **`~/.pflow` tree on real Windows** (registry.json, workflows/, debug/ traces, cache.db) — everything goes through `Path.home()`/`tempfile` so it *should* just work; nobody has looked. The open-handle class (plan watch-list) most likely bites in `cache.db` under xdist.
- **pflow-as-MCP-server on Windows** — stdio transport via the SDK, assumed symmetric with the client story. Zero verification. Out of scope unless a test drags it in.
- **The `--say`/TTS and web-UI paths on Windows** — audited clean (API + browser), but no Windows CI exercises `pflow ui` beyond unit level. The `web` CI job stays ubuntu-only on purpose.
- **`PFLOW_BASH` override semantics** — the plan names the env var but doesn't say whether it should be validated (exists? executable?) or trusted. My inclination: trust it and let the subprocess error speak (simpler, and the user set it deliberately). Owning agent's call; document either way.

## Handoff Protocol Between Chunks

Chunk A's agent ends by telling the user "push when ready; CI run #1 is expected red in the shell-dialect way — no triage." Chunk B's agent ends with a progress-log entry (`implementation/progress-log.md` — create it) predicting what CI run #2 should still fail on (MSYS mangling, open-handle, chmod asserts, glyph encoding), because Chunk C's agent triages *against that prediction* — a failure class Chunk B didn't predict is a signal to look for a design problem, not a test problem. Chunk C keeps one progress-log section per CI round: failure → classification → fix/skip + reason. That log is what makes Chunk C's agent swappable mid-stream.
