# Bugfix Log Writer Guide (for AI Coding Agents)

This guide defines how to write high‑signal bugfix entries to `.taskmaster/bugfix/bugfix-log.md` so future agents can quickly understand, reproduce, and verify fixes. Keep it concise, grep‑able, and consistent.

## Goals
- **Consistency**: Same headings and markers every time for easy parsing.
- **Reproducibility**: Always include copy/paste repro and verification commands.
- **Signal over noise**: One entry per fix, short sentences, precise causes.

## Where to write
- **File**: `.taskmaster/bugfix/bugfix-log.md`
- **Order**: Append at the top (reverse chronological).
- **Markers**: Wrap each entry with the exact HTML comments:
  - `<!-- ===== BUGFIX ENTRY START ===== -->`
  - `<!-- ===== BUGFIX ENTRY END ===== -->`

## Golden rules
- Include the current date in the title as `YYYY-MM-DD`.
- One bugfix per entry; include all relevant commits in that entry.
- Link to concrete files/tests when possible (use backticks for paths).
- Prefer absolute commands that work on fresh checkouts.
- Use short, technically specific “Root cause” lines (no guesswork).

## Meta field conventions
- **id**: `BF-YYYYMMDD-slug` (short, lowercase, dash-separated)
- **area**: `cli|runtime|planning|nodes|registry|tests|docs|infra`
- **severity**: `hang|crash|incorrect-output|data-loss|perf|ux|other`
- **status**: usually `fixed` (use `mitigated` if partial)
- **versions**: commit SHA(s), tag, or range
- **affects**: flags/modes/platforms that matter (e.g., `pipelines, --output-format json, macOS`)
- **owner**: human/agent responsible
- **links**: PR/commit/issue URLs or local paths

## Copy-paste template (use today’s date)
Use this exact shape. Replace braces with real values. Keep headings/markers as-is.

```markdown
<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] {short_title} — {YYYY-MM-DD}

Meta:
- id: BF-{YYYYMMDD}-{slug}
- area: {cli|runtime|planning|nodes|registry|tests|docs|infra}
- severity: {hang|crash|incorrect-output|data-loss|perf|ux|other}
- status: fixed
- versions: {commit|tag|range}
- affects: {flags, modes, platforms}
- owner: {name/agent}
- links: {PR|commit|issue URLs or paths}

Summary:
- Problem: {one-line symptom}
- Root cause: {one-line cause}
- Fix: {one-line fix}

Repro:
- Steps:
  1) {step}
  2) {step}
- Commands:
  ```bash
  {exact command users/devs can run}
  ```
- Expected vs actual:
  - Expected: {…}
  - Actual: {…}

Implementation:
- Changed files: `path/to/file.py` (brief what/why)
- Key edits: {one-liners about conditions, wrappers, flags, etc.}
- Tests: {tests added/updated}

Verification:
- Manual:
  ```bash
  {post-fix command}
  ```
  Output: {short expected result}
- CI: {which suites / notable assertions}

Risks & rollbacks:
- Risk flags: {e.g., TTY, SIGPIPE, namespacing, flow.run wrapper}
- Rollback plan: {how to revert safely}

Lessons & heuristics:
- Lessons learned: {1–3 bullets}
- Heuristics to detect recurrence: {grep/log cues}
- Related pitfalls: {links to `.taskmaster/knowledge/pitfalls.md` anchors}

Follow-ups:
- TODOs: {brief, if any}

<!-- ===== BUGFIX ENTRY END ===== -->
```

## Field guidance
- **Title**: Start with a verb or outcome (e.g., “Prevent CLI hangs when piped”).
- **Repro/Verification**: Exact commands in fenced blocks; don’t omit flags.
- **Changed files**: Use backticks for paths; add a 1‑line “what/why”.
- **Lessons & heuristics**: Capture reusable patterns and cues to spot regressions.

## Quality checklist (before committing)
- Date present and in `YYYY-MM-DD`.
- Meta values match defined enums/format.
- At least one repro and one verification command included.
- “Root cause” is precise and technically correct.
- Risks/rollbacks cover cross-cutting concerns (TTY, SIGPIPE, namespacing, template resolution, `flow.run` wrapping, registry imports).
- Link to relevant pitfalls when applicable.

## Common mistakes
- Vague causes (“buffering issue”) instead of specifics (“prompt gating used stdin TTY only; stdout piped”).
- Omitting runnable commands.
- Deviating from the template headings or removing markers.
- Non-deterministic verification (avoid credentials unless required; note when needed).

## Example (illustrative)

```markdown
<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Prevent CLI hangs when piped; resolve declared outputs on print — 2025-09-01

Meta:
- id: BF-20250901-tty-pipes-outputs
- area: cli
- severity: hang
- status: fixed
- versions: {commit SHA}
- affects: pipelines, planner success path, namespaced outputs
- owner: agent
- links: {PR/commit}

Summary:
- Problem: `pflow ... | jq ...` could hang; declared outputs sometimes empty.
- Root cause: Prompt gating only checked stdin TTY (stdout piped still prompted); outputs needed a mapping pass when not pre-populated.
- Fix: Prompt only when stdin AND stdout are TTYs; call `populate_declared_outputs(...)` in CLI fallback before printing.

Repro:
- Commands:
  ```bash
  uv run pflow --output-format json "say hello" 2>/dev/null | jq -r '.total_cost_usd'
  ```
- Expected vs actual:
  - Expected: JSON then jq value
  - Actual: hangs (prompt waiting on non-interactive pipeline)

Implementation:
- Changed files: `src/pflow/cli/main.py`
  - Prompt gating: `if sys.stdin.isatty() and sys.stdout.isatty():`
  - Output handling: fallback call to `populate_declared_outputs(...)` before printing
- Tests: manual verification; consider subprocess/pty e2e

Verification:
- Manual:
  ```bash
  uv run pflow --output-format json --file /tmp/echo.json 2>/dev/null | jq -r '.result'
  ```
  Output: `hello`
- CI: suites green

Risks & rollbacks:
- Risk flags: TTY detection, SIGPIPE, namespacing
- Rollback plan: revert CLI changes; disable gating change first if needed

Lessons & heuristics:
- Lessons learned:
  - “Interactive” means stdin AND stdout TTY.
  - Declared outputs require explicit `source` with namespacing.
- Heuristics:
  - Search for single‑ended `isatty()` checks in CLI.
  - If `.result` is empty, check `outputs[*].source`.
- Related pitfalls: `.taskmaster/knowledge/pitfalls.md#interactive-prompts-in-pipelines-cause-hangs`

Follow-ups:
- Add subprocess/pty e2e for pipe behavior

<!-- ===== BUGFIX ENTRY END ===== -->
```

## Workflow for agents
1) Confirm the fix, then draft the entry using the template above (newest on top).
2) Validate the commands locally. Prefer absolute paths where helpful.
3) Cross-link any new or updated items in `pitfalls.md`.
4) Commit both the code and the new log entry together when possible.

That’s it. Keep entries short, structured, and battle-tested.

