<!-- ===== BUGFIX ENTRY START ===== -->

## [BUGFIX] Prevent CLI hangs when piped; resolve declared outputs on print — 2025-09-01

Meta:
- id: BF-20250901-tty-pipes-outputs
- area: cli
- severity: hang
- status: fixed
- versions: uncommitted (working tree)
- affects: pipelines, stdout-piped, --output-format json, planner success path, namespaced outputs
- owner: ai-agent
- links:

Summary:
- Problem: `pflow ... | jq ...` could hang; declared outputs sometimes appeared missing.
- Root cause: Prompt gating only checked stdin TTY (stdout piped still prompted); outputs needed a mapping pass when not pre-populated.
- Fix: Prompt only when stdin AND stdout are TTYs; call `populate_declared_outputs(...)` as a fallback in CLI before printing.

Repro:
- Steps:
  1) Run with stdout piped
- Commands:
  ```bash
  uv run pflow --output-format json "say hello" 2>/dev/null | jq -r '.total_cost_usd'
  ```
- Expected vs actual:
  - Expected: JSON printed, jq extracts a number (or null)
  - Actual (pre-fix): hang (prompt waiting on a non-interactive pipeline)

Implementation:
- Changed files: `src/pflow/cli/main.py`
  - Prompt gating: show save prompt only when `sys.stdin.isatty() and sys.stdout.isatty()`
  - Output handling: in `_try_declared_outputs`, if root keys not present, call `pflow.runtime.output_resolver.populate_declared_outputs(shared, workflow_ir)` then re-check
- Tests: manual verification; consider subprocess/pty e2e for pipe behavior

Verification:
- Manual:
  ```bash
  # File-based, no LLM required
  cat > /tmp/echo.json <<'EOF'
  {
    "ir_version": "0.1.0",
    "nodes": [{"id": "echo1", "type": "echo", "params": {"message": "hello"}}],
    "edges": [],
    "outputs": {"result": {"source": "${echo1.echo}"}}
  }
  EOF

  uv run pflow --output-format json --file /tmp/echo.json 2>/dev/null | jq -r '.result'
  ```
  Output: `hello`
- CI: existing suites remain green

Risks & rollbacks:
- Risk flags: TTY detection; SIGPIPE/EPIPE behavior; namespacing vs root output expectations
- Rollback plan: revert the two hunks in `src/pflow/cli/main.py` (prompt gating and declared output fallback)

Lessons & heuristics:
- Lessons learned:
  - “Interactive” means stdin AND stdout are TTYs; gate prompts on both.
  - With namespacing enabled, declared outputs should include `source` and may require population.
- Heuristics to detect recurrence:
  - Grep for single-ended `isatty()` checks in CLI code paths that might prompt.
  - If `.result` is unexpectedly empty in JSON mode, check `outputs[*].source` and ensure population occurs.
- Related pitfalls: `.taskmaster/knowledge/pitfalls.md#interactive-prompts-in-pipelines-cause-hangs`, `.taskmaster/knowledge/pitfalls.md#declared-outputs-require-explicit-source-when-namespacing-is-on`

Follow-ups:
- Add subprocess/pty e2e tests to simulate real TTY/pipe behavior

<!-- ===== BUGFIX ENTRY END ===== -->
