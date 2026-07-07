# Plan Breakdown — Task 116 Windows Compatibility (2026-07-06)

Analyzes `.taskmaster/tasks/task_116/implementation/implementation-plan.md` (post-deep-review version) for agent handoff points and per-phase outsourcing to `code-implementer` / `test-writer-fixer` subagents.

**Structural constraint this breakdown leans on:** the user pushes all branches manually and CI is the only ground truth, so the plan's two push-points (A→B, B→C) are *forced* session boundaries anyway — handoffs are cheapest exactly there. Wall-clock CI gaps make same-agent continuity across them worth little.

## Phase sizes

| Phase | Prod LOC | Tests | Cognitive | Risk |
|---|---|---|---|---|
| 1. Windows CI job (non-blocking) | ~25 (yaml) | none | LOW | MED (wrong = no signal, but visible) |
| 2. Encoding sweep + PLW1514 + EncodingWarning filter | ~25 edits / 10 files | existing suite | LOW | LOW |
| 3. USERPROFILE helper (7 sites) + server detach flags | ~50 | existing suite | LOW-MED | MED (test-isolation leaks are quiet) |
| 4. Win32 stdin detection + UTF-8 decode | ~50 | ~100 (mocked unit + 1 win32 e2e) | MED | HIGH (silent stdin-drop / mojibake class) |
| 5. Shell node bash-on-windows (prep-raise) | ~60 | ~120 (resolver, argv, ignore_errors regression) | MED-HIGH | **HIGH (silent-success class — the deep-review Critical)** |
| 6. CI green-up iteration | unbounded (~100–300 est.) | skip-marks + targeted fixes | HIGH (diagnosis) | MED-HIGH |
| 7. Declare support | ~10 | none | LOW | LOW |

## Tacit-dependency map

```
P1 ══║══ P2 ══║══ P3   ──[PUSH: CI run #1, no triage]──   P4 ──○── P5   ──[PUSH: CI run #2]──   P6 ══║══ P7
      each locked by                                        shared win32-idiom,                    green CI
      its own artifact                                      different files                        is the gate
```

- **P1→P2→P3: ║ FIREBREAKS.** Independent files; each phase is locked by its own artifact — the CI job by the yaml itself, the sweep by ruff `PLW1514` + the `EncodingWarning` filter (regression-proof by construction), the env helper by all callers being enumerated in the plan.
- **P3→P4 (the A→B push): ║ FIREBREAK.** Nothing in Chunk A informs Chunk B; the plan even forbids triaging CI run #1.
- **P4→P5: ○ LOOSE.** Different files (`shell_integration.py` vs `shell.py`), but they share the win32-branch + Linux-mock testing idiom and the same review conventions. Docs sufficient; mild benefit to one head.
- **P5→P6 (the B→C push): weak ║, honest caveat.** The firebreak is structural — ADR-0013 + the plan's Phase 5/6 sections document resolver order, MSYS-mangling expectations, and the triage rule ("product first, test second") — but Phase 6 diagnoses failures *of* Phase 4/5 code, and the implementer's instinct for "that's the resolver picking the wrong bash" vs "that's a test fixture problem" is real. Mitigation below (per-round progress log) is what makes this handoff safe.
- **P6→P7: ║ FIREBREAK.** Green CI is the gate; declaration is mechanical.

## High-risk phase

**Phase 5.** Its whole design exists to defeat a silent-failure trap (`exec_fallback` swallowing the missing-bash raise → green run under `ignore_errors`). The prep-raise placement, the error-class/message choice, and the `ignore_errors` regression test are one coherent thought — split across agents, the receiving agent's natural instinct ("raise in exec, that's where execution errors go") re-introduces the exact bug the review caught. **One agent owns Phase 5 design + its tests end-to-end.** Within it, only the resolver function body is safely outsourceable (pure function, fully spec'd).

## Split options

### Option A: N=3 agents (recommended)

| Agent | Phases | ~LOC | ~Tests | Tacit ownership |
|---|---|---|---|---|
| 1 — cheap/dumb OK | 1+2+3 (Chunk A) | ~100 edits | existing suite green | none — plan text is the full spec |
| 2 — smart | 4+5 (Chunk B) | ~110 | ~220 | win32 idiom, prep-raise rationale, error UX |
| 3 — smart | 6+7 (Chunk C) | ~100–300 | skip-marks + fixes | CI triage judgment |

Handoffs land exactly on the two forced push-points, where a session break happens regardless. Agent 2 keeps the loose P4–P5 pair in one head. Riskiest handoff is 2→3 (the weak firebreak); mitigated by Agent 2 ending with a progress-log entry (what was built, what to expect in CI run #2, known-suspect areas) and by the plan's documented triage rule.

### Option B: N=4 agents

| Agent | Phases | ~LOC | ~Tests | Tacit ownership |
|---|---|---|---|---|
| 1 — cheap | 1+2+3 | ~100 | existing | none |
| 2 — smart | 4 | ~50 | ~100 | ctypes/import-seam, decode fix |
| 3 — smart | 5 | ~60 | ~120 | prep-raise design |
| 4 — smart | 6+7 | ~100–300 | fixes | CI triage |

Only worth it if context budget forces it: the P4/P5 boundary is loose-but-real, and both segments are small — splitting buys blast-radius isolation at the cost of one extra handoff and re-explaining the shared win32-mock idiom.

### Option C: N=2 agents

| Agent | Phases | ~LOC | ~Tests | Tacit ownership |
|---|---|---|---|---|
| 1 — smart | 1–5 (Chunks A+B) | ~210 | ~220 | everything pre-CI |
| 2 — smart | 6+7 (Chunk C) | ~100–300 | fixes | CI triage |

Maximum coherence; viable because Chunk A is small. The single handoff sits on the B→C push, which has a real wall-clock gap anyway. Downside: Chunk A wastes a smart agent's session on mechanical work (unless it delegates — see below).

## Recommendation

**Option A (N=3), with Phase 5 never subdivided.** The two handoffs coincide with the pushes the user must make anyway, so they cost nothing extra; Chunk A can run on a cheap agent (or be fully delegated to `code-implementer` subagents by whoever orchestrates); the high-risk Phase 5 stays whole inside Agent 2. If the same session that produced this breakdown starts implementation, Option C's Agent-1 role collapses into "orchestrator delegating Chunk A to subagents, then doing Chunk B itself" — same shape, fewer sessions.

## Within-phase outsourcing map (code-implementer / test-writer-fixer)

| Phase | Outsourceable to `code-implementer` | Must stay with the owning (smart) agent |
|---|---|---|
| 1 | **All of it** — yaml block is fully spec'd (job shape, flags, continue-on-error, keep-mypy note) | verify the diff against plan intent (2-min review) |
| 2 | **All of it** — site list is exhaustive, rule name given; one task: "add PLW1514 + encoding= at these sites + filterwarnings line" | judgment call ONLY if the EncodingWarning filter surfaces third-party noise (plan says escalate, not drop) |
| 3 | **All of it** — helper signature + all 7 call sites + the server-detach dict are spelled out verbatim; instruct: preserve the ADR-0008 comment block | review that the error_boundary overrides route through the helper (the quiet case) |
| 4 | Resolver-style prod code (`_stdin_is_pipe_windows` + decode branch) IF given the plan text verbatim (constants, import seam warning); unit tests → `test-writer-fixer` (behavior table is in the plan) | docstring environment-table update; the win32 e2e test design (inverse skip, round-trip assertion); final review of the import seam |
| 5 | `_resolve_windows_bash()` body only (pure function, 4-step order spec'd); resolver unit tests → `test-writer-fixer` | **prep-raise wiring, error-class choice, message wording (agent-facing conventions), the `ignore_errors` regression test, exec argv change** — the silent-success trap lives exactly here |
| 6 | Per-round mechanical fixes once diagnosed: the known skip-mark list (symlink/chmod tests), path-sep assertion fixes, `\r\n` normalizations → `code-implementer`/`test-writer-fixer` with exact file+reason lists | **all diagnosis/triage** — reading CI logs, product-bug-vs-test-only calls, deciding fix vs skip |
| 7 | **All of it** — classifier, README line, task status | none |

Rule of thumb that falls out: **everything the deep-review had to correct is exactly what can't be outsourced** (prep-vs-exec placement, import seams, the quiet USERPROFILE override) — the plan now documents those, but the owning agent must verify the subagent didn't regress them, because they're the spots where the "natural" implementation is wrong.

## Irreducible tacit knowledge → mitigations

- **Why prep() and not exec()** (the silent-success trap) → already pinned: plan documents it with verified line refs + the mandated `ignore_errors` regression test makes it structurally locked. An agent who "simplifies" back to exec-raise turns the test red.
- **Why the resolver rejects System32 bash** (WSL trap, CI-can't-catch-it) → pinned in ADR-0013 consequences + a dedicated resolver unit test asserting the rejection.
- **Phase 6 triage state across rounds** (which CI failures are classified, which fixes are in flight) → NOT in any doc by default. Mitigation: Agent 3 maintains `.taskmaster/tasks/task_116/implementation/progress-log.md` with one section per CI round: failures seen → classification → fix/skip decision + reason. This is also what makes swapping Agent 3 mid-Chunk-C survivable.
- **What CI run #2 is *expected* to still fail on** (MSYS path mangling, open-handle class, chmod asserts) → pinned in the plan's watch-list; Agent 2's handoff note should say which of these it believes it triggered.
- **EncodingWarning filter noise decisions** (which third-party ignores were added and why) → record each `ignore::EncodingWarning:<module>` entry with an inline comment in pyproject.toml; silent drops forbidden by the plan.
