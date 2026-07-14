# Task 177 Implementation Progress

## 2026-07-13 — Phase 1 started

- Read `task-177.md`, all of `starting-context/`, and `implementation-plan.md` in full before editing code.
- Scope is Phase 1 only: extract the backend seam, preserve Claude behavior, migrate the Claude tests, and perform the gate-blocking example/guide type-string migration. Phases 2–5 remain out of scope.
- Verified the live implementation is 1,674 lines (the plan says 1,675). The cited lifecycle boundaries remain accurate: the current `exec()` wraps the entire schema-retry loop in one `asyncio.run`, missing-session continuation breaks and preserves the prior result, and `_claude_progress` / `_claude_tools` each have one writer.
- Verified `src/pflow/nodes/claude/__init__.py` is lazy but importing `claude_code.py` eagerly imports and version-checks `claude_agent_sdk`; the extraction must move that eager dependency entirely into `ClaudeBackend`.
- Resolved an internal wording conflict in the plan by following its authoritative “Resolved decisions”: `resume` is shared and validated by `AgentNode`; `max_turns`, tool lists, thinking tokens, Claude sandbox, and `use_api_key` are Claude-only and validated by `ClaudeBackend`. This differs from the later seam inventory sentence that calls some of those validators shared.
- Phase 1 must update the validator's import of `schema_validation.py` so deleting `nodes/claude/` does not break module import, but the validator's `claude-code` dispatch and behavior remain for Phase 2 as explicitly scoped.
- Baseline test attempt followed `pflow-sandbox-testing`: `HOME=/private/tmp/pflow-test-home PYTHONWARNDEFAULTENCODING=1 .venv/bin/python -m pytest ...`. It did not start because this worktree has no `.venv`; system Python 3.14.3 also has no pytest. No code had been changed. Later discovery: `/Users/andfal/projects/pflow/.venv/bin/python` is a healthy symlinked Python 3.13 environment; the initial `find -type f` check missed the symlink. Subsequent tests use that interpreter directly from this worktree.
- Verified only 9 current `examples/**/*.pflow.md` files contain `type: claude-code`; the plan's count of 14 is stale. All discovered workflow files remain in Phase 1 scope.
- Verified batch retry is exception-driven: `Node._exec()` calls `exec_fallback()` after node retries, and `batch_executor` re-attempts raised exceptions unless `retriable=False`. `AgentNode.exec_fallback()` therefore continues to raise the backend-translated exception.
- Implemented the backend-neutral boundary with `AgentResult.metadata` already normalized by `ClaudeBackend`. This is the plan's intended producer-boundary contract and removes Claude SDK usage parsing from `AgentNode`; retry records and final `llm_usage` now read the same normalized fields.
- Kept PocketFlow's node-level `exec_res` as a dict while the backend seam uses `AgentResult`. This is a deliberate compatibility choice: `AgentBackend.run()` has the planned typed result, while `AgentNode.exec()` preserves the existing PocketFlow lifecycle/test boundary instead of introducing an unrelated engine-facing result type.
- Moved the validator's schema-predicate import to `pflow.nodes.agent.schema_validation` so Phase 1 can delete `nodes/claude/`. The validator dispatch/helper rename and backend-aware static checks remain untouched for Phase 2, as scoped.
- Syntax compilation of the extracted modules passes. A direct package import check reaches the project's existing `pflow.core` import before failing on missing environment dependency `jsonschema`; it does not load `claude_agent_sdk`. Added an isolated test that pins SDK-free package/node import behavior under the real test environment.
- Focused Ruff format/check passes for the new node package, migrated node tests, SDK stub, and the validator import change.
- Attempted a bounded offline environment bootstrap before discovering the main checkout's symlinked venv: `HOME=/private/tmp/pflow-test-home uv sync --offline --frozen`. It hit the sandbox skill's known macOS signature (`Attempted to create a NULL object`; `Tokio executor failed`) before installing dependencies. The incomplete generated `.venv` was removed. This is retained as environment evidence but no longer blocks pytest.
- Corrected test execution to use the healthy symlinked main-checkout venv with `PYTHONPATH=src:.`, ensuring imports come from this worktree rather than the venv's editable main-checkout install.
- Migrated agent-node suite: 154 tests pass. Initial run found six migration regressions: Claude-specific warning wording had been over-generalized, and three direct `exec_fallback` tests omitted the new prepared backend handle. Restored exact Claude phrasing via backend warning-context fields and updated the direct tests to provide `ClaudeBackend`; the suite is now green.
- The three Phase 1 auto-discovery gates pass: example validation, guide example validation, and plan-to-code harness (19 tests total).
- Direct `make test` equivalent completed with 8,796 passing and 9 failing. Three failures are sandbox-only loopback socket bind denials in `tests/test_cli/test_ui.py`.
- The other six failures expose a binding phase-plan contradiction: Phase 1 explicitly renames the guide/examples and deregisters `claude-code`, but Phase 2 owns the guide map, reserved-name allowlist, validator dispatch/diagnostics/tests, and Phase 4 owns the regenerated React Flow contract fixture. Failures are exactly in those deferred surfaces (`test_guide`, `test_validate_only`, diagnostic `see_also`, and `run-cycle.json`). Implementing them now would start later phases, violating the user's Phase 1-only scope and the skill's “do not start the next phase” instruction. Phase 1-specific node and auto-discovery suites remain green; full-suite green is not achievable at this planned intermediate boundary without crossing scope.
- Repository-wide direct quality checks pass: Claude/Codex asset sync, Ruff lint, Ruff formatting, mypy (252 source files), and deptry (253 files).
- `pre-commit run -a` passed case-conflict, merge-conflict, TOML, YAML, JSON, JSON formatting, trailing-whitespace, MDX fence/template, and Taskmaster-status hooks. It cannot be fully green in this sandbox: EOF fixer opens unchanged read-only `.codex/agents/*.toml` in `rb+` and gets `PermissionError`, while the Ruff hooks invoke uv and reproduce the known Tokio panic. Direct repository-wide Ruff checks passed; the hook-created incomplete `.venv` was removed.
- Re-ran pre-commit against every changed/new file with only the uv-backed Ruff hooks skipped; all applicable hooks passed, including EOF and trailing-whitespace. Ruff lint/format remain covered by the direct repository-wide invocations above.

## 2026-07-13 — Phase 1 handoff

- Built `pflow.nodes.agent`: SDK-free `AgentNode`, `AgentBackend` protocol, normalized `AgentResult`, `ClaudeBackend`, shared schema/parameter constants, and lazy package export. The old `pflow.nodes.claude` package is removed; `agent` is registry-discovered and `claude-code` is not.
- Claude behavior remains pinned by the migrated suite: structured-output success/soft-fail, scalar coercion, multi-attempt resume retry, inclusive cache-token accounting, retry aggregation, tool/progress trace fields, subscription-vs-API-key handling, timeouts, SDK/process/auth translation, and lazy SDK import.
- Migrated the nine current example workflow files and shipped guide examples to `type: agent` + `backend: claude`; renamed `examples/nodes/claude-code/` and the guide topic file to `agent/` / `agent.md`. Preserved the authentication guide by moving it into the new package rather than deleting its user-critical billing guidance before Phase 5 folds it into the authored guide.
- Final Phase 1 regression batch: 173 passed (`tests/test_nodes/test_agent` plus example validation, guide-example validation, and plan-to-code harness). Registry/import reality check passed. Repository-wide Ruff, formatting, mypy, asset sync, and deptry passed.
- Deliberate internal compatibility choice: backend calls use `AgentResult`, while `AgentNode.exec()` still returns PocketFlow's established dict-shaped `exec_res`. This keeps the new seam typed without expanding the refactor into the engine lifecycle.
- No Phase 2/4 work was started. Consequently the full non-e2e suite remains 8,796 passed / 9 failed: three sandbox socket-bind denials and six phase-boundary failures caused by Phase 1's required clean-slate content rename landing before Phase 2 wiring/tests and Phase 4 fixture regeneration. Advancing those files solely to make the intermediate branch green would violate the requested Phase 1-only scope.
- Manual review focus: confirm the backend seam ownership and normalized metadata boundary; confirm the explicit Phase 1 `backend: codex` unavailable error is acceptable until Phase 3; and review the recorded phase-boundary gate contradiction before beginning Phase 2.

## 2026-07-13 — Phase 1 test-reflection follow-up

- After the user challenged whether the suite was testing the right behavior, applied the repository's `test-reflect` process instead of adding coverage-oriented tests. Identified three contract-level gaps worth pinning: SDK-free import in a genuinely fresh interpreter, PocketFlow retry/fallback behavior through the complete `Node.run()` lifecycle, and schema-retry behavior when the backend supplies no resumable session.
- The fresh-interpreter and lifecycle tests strengthen previously shallow or indirect assertions without changing production behavior.
- The missing-session test exposed a real Shape B bug: `exec()` correctly made zero corrective calls, but `post()` stored the nonconforming parsed object because its degradation branch only ran when `retry_attempts > 0`. This contradicted the plan's “break and keep prior result / soft-fail DEGRADED” contract. Updated result storage to distinguish “schema validation was enabled” from “a corrective retry occurred”; a nonconforming object with no session now stores raw text and emits `agent.schema_not_satisfied`, while `schema_retries: 0` retains its intentional no-validation behavior.
- Post-fix verification: the focused node-lifecycle file passes 121 tests; the full Phase 1 regression set passes 175 tests; repository-wide Ruff lint/format and mypy pass. The complete non-e2e suite is now 8,798 passed / 9 failed in the Codex sandbox: the same six deferred Phase 2/4 failures reported by the user plus the same three sandbox-only loopback-bind failures. The two additional passing tests are the new lifecycle and missing-session contract guards.

## 2026-07-13 — Phase 2 started

- Resolved the request's stale "Task 176" identifier in favor of Task 177: the assigned branch is `feat/unified-agent-node-claude-codex`, its head is the committed `phase 1 completed` handoff, and Task 177 is the only local plan for the unified `agent` node. Task 176 is an unrelated, already-completed Web UI approval bridge.
- Read every Task 177 file in full before editing and re-verified the Phase 2 seams against the committed Phase 1 code. The cited behavior remains current: validator dispatch and diagnostics still use `claude-code`; React Flow still keys structured `result` output on `claude-code`; plan/display classification still names `ClaudeCodeNode`; catalog, reserved-name, and guide maps still expose the old type.
- Phase 1 already established the intended single source of truth in `nodes/agent/schema_validation.py`: `SHARED_PARAMS`, `CLAUDE_PARAMS`, and `CODEX_PARAMS`, with `sandbox` intentionally present in both backend sets. Phase 2 will import these sets into static validation rather than duplicate them.
- The plan's named Phase 1 boundary contradiction is still visible in live code: `guide/nodes/agent.md` and migrated examples exist, while `guide/__init__.py`, the registry workflow template, and the validator still use `claude-code`. These are Phase 2-owned fixes, not new scope.
- Static-validation detail made explicit: a literal missing/invalid backend is rejected before the schema early-return; a templated backend value must defer enum and cross-backend checks until runtime resolution, while shared schema checks can still run. This follows the validator's existing defer-on-template policy and avoids a false preflight rejection for composed workflows.
- The plan's completion grep spans later-phase authored docs and MCP instructions, so Phase 2 will apply the clean-slate rename only to its enumerated Python wiring, comments, and affected tests. Phase 5 remains the owner of guide prose, architecture/docs, and MCP instruction authoring; Phase 4 remains the owner of web fixtures/bundle regeneration.
- Full-suite verification exposed a plan omission in the claimed shared-parameter inventory: migrated agent-orchestration workflows pass node-level `inputs` to file-backed prompt templates, but `inputs` was absent from every backend allowlist. Static Phase 2 validation therefore produced 29 false cross-backend errors, and runtime `prep()` would reject the same valid workflows. Added `inputs` to `SHARED_PARAMS` and the `AgentNode` interface, with static coverage for both backends and a runtime Claude pin; this restores the pre-rename behavior instead of editing valid workflows around the validator.

## 2026-07-13 — Phase 2 completed

- Rekeyed backend-agnostic wiring from `claude-code` / `ClaudeCodeNode` to `agent` / `AgentNode`: static validator dispatch and diagnostics, React Flow structured-result projection, dry-run cost/duration classification, display tags, rich workflow templates, reserved guide/save names, guide topic injection, cache/resume documentation comments, and affected test fixtures.
- Static validation now requires a literal `backend`, accepts only `claude` / `codex`, rejects flat parameters outside `SHARED_PARAMS ∪ <backend>_PARAMS` before the schema early-return, defers templated backend values to runtime, preserves the shared top-level-object schema rule, and applies `max_turns >= 2` only to the Claude backend. Diagnostics consistently use `agent`, `Agent Parameter Validation Error`, and `see_also=["agent"]`.
- Deviation from the plan: added node-level `inputs` to `SHARED_PARAMS` after real example validation proved the plan's supposedly exhaustive parameter inventory incomplete. This is required compatibility for file-backed prompt templates and is valid for both current/future backends; changing the migrated workflows would have hidden a runtime regression.
- Manual surface checks pass using the existing virtualenv: `pflow --validate-only examples/nodes/agent/claude-code-basic.pflow.md`, `pflow --dry-run ...` (renders `generate [agent]` with the LLM-family no-history cost hint), and `pflow guide agent` (resolves the renamed topic and injects the agent interface).
- Verification: 914 focused Phase 2/regression tests pass; repository-wide Ruff lint and format pass; mypy passes for 252 source files; Claude/Codex asset sync and deptry pass; applicable pre-commit hooks pass on every changed file (uv-backed Ruff hooks skipped because direct repository-wide Ruff already passed). The complete non-e2e suite is 8,814 passed / 4 failed in the Codex sandbox. Three failures are the unchanged loopback-bind permission denials in `tests/test_cli/test_ui.py`; the fourth is `run-cycle.json`, whose committed web contract still contains `claude-code` and is explicitly owned by Phase 4. Excluding only that Phase 4 fixture file and the sandbox-blocked UI file yields 8,757 passed.
- `make check` was attempted with writable HOME/cache and the existing project virtualenv, but `uv lock --locked` cannot start in this macOS sandbox (`system-configuration` NULL-object panic followed by `Tokio executor failed`). Direct equivalents for asset sync, Ruff, formatting, pre-commit, mypy, and deptry are green; no dependency or lock files changed.
- Key learning: the flat per-backend allowlist is now genuinely load-bearing for ordinary data wiring, not only backend knobs. Future shared agent parameters must be added to `SHARED_PARAMS` first so runtime and static validation move together.
- No Phase 3 Codex backend or Phase 4 web fixture/bundle work was started. Manual review should focus on validator error wording/order, the `inputs` compatibility correction, and the deliberate Phase 4 fixture boundary.

## 2026-07-13 — Phase 2 → Phase 3 handoff

- **Repository state:** Phase 1 is committed at `267c8e28`; all Phase 2 production, test, and progress-log changes are intentionally uncommitted in this worktree, per `implement-plan`. Preserve the dirty tree and do not discard or commit it unless the user explicitly asks.
- **Read order for the next implementer:** all files under `.taskmaster/tasks/task_177/`, including the original `starting-context/braindump.md`, then `starting-context/braindump-phase-2-to-3.md`; inspect the current diff before writing. Use `pflow-sandbox-testing` before any tests.
- **Phase 2 proof:** 914 focused tests pass. The direct full non-e2e run reports 8,814 passed / 4 failed: the one Phase 4-owned `web/src/test/fixtures/contracts/run-cycle.json` mismatch and the three unchanged sandbox socket-bind denials. Excluding only `tests/test_core/test_react_flow_contract_fixtures.py` and `tests/test_cli/test_ui.py` yields 8,757 passed. Direct Ruff, format, mypy, asset sync, deptry, and applicable pre-commit hooks pass.
- **Do not absorb later phases:** Phase 3 owns only `CodexBackend` plus its tests and real-surface verification. Phase 4 owns web literals, the generated run-cycle contract fixture, bundle rebuild, and screenshot verification. Phase 5 owns remaining authored guide/docs/architecture/MCP prose and example filename cleanup.
- **Phase 3 starting seam:** valid `backend: codex` currently reaches `_UnavailableCodexBackend` in `agent_node.py` and fails with the intentional Phase 1 message. Replace that placeholder with a lazy `CodexBackend` import while preserving SDK-free package import, cross-backend validation before subprocess launch, and the existing `AgentResult` normalized boundary.
- **Known environment:** this worktree has no local `.venv`; use `/Users/andfal/projects/pflow/.venv/bin/python` with `PYTHONPATH=src:.`, writable `HOME=/private/tmp/pflow-test-home`, and `PYTHONWARNDEFAULTENCODING=1`. `uv`/`make check` panic before Python in this sandbox; direct tool invocations are the reliable path.
- **Stop point:** the next agent should implement Phase 3 only, append its dated completion entry, and stop before Phase 4. No commit has been created for Phase 2.

## 2026-07-13 — Phase 3 started

- Read the implementation skill, `pflow-sandbox-testing`, and every file under `.taskmaster/tasks/task_177/` in full before editing. Scope is Phase 3 only: the real `CodexBackend`, its contract tests, and real-surface verification; Phase 4 UI work and Phase 5 authoring remain out of scope.
- Re-verified the branch state and corrected a stale Phase 2 handoff statement: Phase 2 is committed cleanly at `b0e03a55` (after Phase 1 at `267c8e28`), not dirty/uncommitted. No user changes were present at Phase 3 start.
- Studied the complete Phase 2 commit and current backend seam together. `inputs` is now intentionally shared data-wiring metadata and must be accepted but never emitted as a Codex CLI option. `AgentNode` still owns schema coercion/retry/soft-fail storage, while each backend must return normalized `AgentResult.metadata`.
- The installed CLI is now `codex-cli 0.144.3` rather than the plan's observed 0.144.1. `codex exec` and typed JSONL contracts remain compatible. One real argv delta matters: `codex exec resume --profile NAME ...` is rejected, while the parent-option form `codex exec --profile NAME resume ...` parses successfully. Phase 3 will build and test this ordering.
- The current official Codex config reference documents `developer_instructions` as additional developer instructions injected into a session. This resolves the handoff's `system_prompt` gap: Codex will receive the shared parameter through `-c developer_instructions=<TOML string>` on both initial and resumed runs, with no prompt concatenation or silent drop.
- The CLI help confirms each `-c key=value` value is parsed as TOML (falling back to a raw string). Phase 3 will use a deliberate serializer for strings, booleans, numbers, arrays, and inline tables, rejecting unsupported values such as `None` instead of relying on Python `str()` or shell quoting.
- `reasoning_output_tokens` has no strict-dict consumer, but the retry aggregator currently sums only input/output/cache fields. Carrying Codex reasoning usage through correctly therefore requires storing it in `llm_usage` and summing it across schema retries; it must remain separate from visible `output_tokens`.
- The first real-CLI smoke reached the installed/logged-in Codex binary but failed on the Codex sandbox's DNS/network denial (`failed to lookup ... api.openai.com`), before any model response. It also exposed a real integration bug: without an explicit stdin, `codex exec` announced `Reading additional input from stdin...` and could append pflow's own input pipe as a `<stdin>` block. The backend now uses `stdin=subprocess.DEVNULL`; unit tests pin that boundary. Real paid text/schema/resume verification remains pending an unrestricted network surface.

## 2026-07-13 — Phase 3 completed

- Replaced the Phase 1 placeholder with a lazily imported `CodexBackend` that runs `codex exec` through a shell-free argv list and unique temporary schema/final-message files. Initial and resume commands have separate scopes: initial runs use `--sandbox` / `--cd` / repeated `--add-dir`; resume uses `-c sandbox_mode=...`, omits unsupported flags, and places `--profile` before the `resume` subcommand.
- Added runtime validation for Codex sandbox, approval policy, add-dir, profile, and config shapes. Config values use a small TOML serializer (strings, booleans, finite numbers, arrays, inline tables); `system_prompt` maps to the documented `developer_instructions` override. The explicit node sandbox/approval/system parameters are appended after general `config` overrides so dedicated params win deterministically.
- Implemented the observed typed JSONL contract: thread id from `thread.started`; summed usage and turn count from every `turn.completed`; command tools from `item.completed.command_execution`; real failures from `turn.failed` / `error`; final text exclusively from `--output-last-message`. Malformed successful JSONL and missing final-message files raise; malformed structured final text remains a successful backend result and enters `AgentNode`'s existing retry/soft-fail path.
- Codex usage now writes inclusive input, uncached/cache-read breakdown, visible output, separate `reasoning_output_tokens`, computed total, measured duration, non-null `num_turns`, and session id. Reasoning tokens flow only for backends that provide them (preserving Claude's exact output shape) and are summed across schema retries by the trace aggregator.
- Deterministic missing-CLI and authentication errors translate to actionable `PflowError` subclasses with `retriable=False`; timeouts, invalid JSONL, and other process failures retain useful stderr/event detail and remain retryable under the established node/batch contract.
- Added a real-Codex e2e smoke (installed-CLI guarded) plus hermetic subprocess-boundary tests for argv/TOML/schema temp files, typed events, token mapping, default turn accounting, tool capture, resume flags, `AgentNode` text/structured/soft-fail lifecycles, no-session retry stop, fallback translation, and failure preservation. Added a Codex dry-run guard proving an unpriced model degrades to unknown cost without crashing.
- Verification: 38 focused non-e2e Codex tests pass; the complete agent suite passes 202 tests; the Phase 2/agent regression batch passes 954 tests; related trace aggregation/report tests pass 241 tests. The complete non-e2e suite reports 8,853 passed / 4 failed, exactly the Phase 2 boundary failures: one Phase 4-owned `run-cycle.json` fixture and three sandbox-denied loopback socket tests.
- `make check` was attempted and cannot start because `uv lock --locked` reproduces the documented macOS sandbox panic (`system-configuration` NULL object / Tokio executor). Direct equivalents are green: Claude/Codex asset sync, repository-wide Ruff lint and format (679 files), mypy (253 source files), deptry (254 files), and all applicable pre-commit hooks on the seven changed files (uv-backed Ruff hooks skipped because the direct repository-wide checks passed). No dependency or lock file changed.
- Deviation/environment handoff: the planned paid real text + structured-output + two-process resume verification could not complete because this Codex sandbox has no DNS/network access to `api.openai.com`; a separate resume-parser probe was also blocked by the host's in-process app-server permission denial. The installed 0.144.3 CLI parsed the initial argv far enough to begin the request, and all transport-independent behavior is pinned with recorded real JSONL fixtures. Re-run the e2e smoke and manual schema/resume workflows on an unrestricted host before merge.
- Phase 4 was not started. Manual review should focus on CLI option precedence, `DEVNULL` stdin isolation, error retriability, and whether the intentionally strict v1 `approval_policy` string enum should later expand to Codex's granular-table form.

## 2026-07-13 — Phase 3 test-reflection follow-up

- Applied the user-requested `test-reflect` standard: looked for tests that could catch plausible protocol or lifecycle defects rather than adding coverage-oriented cases.
- Found and fixed one real cross-backend shape leak. The generic retry aggregator unconditionally added `reasoning_output_tokens: 0` to Claude-style retry usage, despite `AgentNode` deliberately emitting that Codex-specific field only when a backend supplies it. Aggregation now preserves absence unless the main call or any retry contains the field, while still summing it across all attempts when present.
- Added two contract tests for that conditional behavior. Strengthened two existing Codex tests rather than adding shallow cases: config precedence now uses conflicting general/dedicated approval and developer-instruction values, and zero-exit CLI failure events must preserve their diagnostic text.
- Sandbox-safe verification used the existing virtualenv directly: the focused reflection batch passed 44 tests with the paid e2e deselected; the complete agent plus trace/report consumer batch passed 732 tests with the paid e2e deselected. Focused Ruff lint/format and `git diff --check` pass.

## 2026-07-13 — Phase 4 started

- Read the requested `implement-plan` skill, the required `pflow-sandbox-testing` and `screenshot-pflow-web-ui` skills, and every file under `.taskmaster/tasks/task_177/` in full before editing. Scope is Phase 4 only: frontend node-kind presentation, affected web tests/fixtures, bundle rebuild, and browser verification. Phase 5 documentation and prose migration remains out of scope.
- Re-verified the repository state against the handoff. The user's statement is current: Phases 1–3 are committed separately at `267c8e28`, `b0e03a55`, and `ef8f6414`, and the worktree was clean at Phase 4 start. The Phase 3 braindump's claim that Phase 3 was uncommitted is stale historical context.
- The Phase 4 source cites remain load-bearing in the live frontend: `icons.ts` still maps `claude-code`, `format.ts` still keys prompt highlighting and the violet identity color on `claude-code`, and `types.ts` still documents `result` using the old kind. The affected component/view tests also still construct `claude-code` nodes.
- The plan's fixture wording is incomplete: `web/src/test/fixtures/contracts/run-cycle.json` is generated live-renderer output, guarded by `tests/test_core/test_react_flow_contract_fixtures.py` and owned by `tests.fixtures.react_flow_contracts._generate`. It will be regenerated through that module, not manually rewritten. Because the generator refreshes all four committed contracts deterministically, any unrelated output change must be inspected before keeping it.
- UI identity decision: use the existing backend-neutral `ai-llm.svg` sparkle for `agent`, while retaining the established violet agentic-node accent. A static Claude logo would misrepresent `backend: codex`; backend-specific brand switching would add presentation behavior beyond Phase 4's requested kind rename and make otherwise identical agent cards visually depend on params.
- Updated the frontend kind seam and its affected tests from `claude-code` to `agent`: generic icon lookup, markdown prompt/system-prompt highlighting, identity color, output-shape comment, approval/run-detail fixtures, and edge-panel graph fixtures. A source grep now finds no old kind outside the generated contract.
- The first sandbox-safe contract regeneration wrote the first three fixtures, then failed on the unrelated prompt-caching fixture because the writable temporary HOME intentionally has no stored Anthropic key. Re-ran with a non-secret placeholder `ANTHROPIC_API_KEY`, which satisfies static model validation without making a network call; all four fixtures regenerated successfully and only `run-cycle.json` changed. Its diff contains the expected three kind renames, newly rendered `backend: claude` params, associated migrated source-line offsets, and the `kind_output_types.agent` key.
- Phase 4's build and focused gates are green: `make ui-build` installed the locked npm tree, passed strict TypeScript checking, and built the Vite production bundle; the Python contract drift guard passed 4 tests; the four affected Vitest files passed 132 tests; and the complete web suite passed 799 tests across 54 files.
- Browser verification is blocked by the same macOS sandbox loopback restriction recorded in prior phases. A dedicated `pflow ui --port 8794` launch cannot bind and is reported as “port already in use” despite no listener. The only existing server on 8765 belongs to a different worktree and the sandbox cannot connect to it (`Operation not permitted`), so using it would test a stale bundle. The temporary two-backend workflow validated successfully before removal; retry the screenshot on an unrestricted host rather than treating stale-bundle output as evidence.

## 2026-07-13 — Phase 4 completed

- Replaced every shipped frontend `claude-code` kind literal with `agent`: backend-neutral sparkle icon, preserved violet identity accent, `prompt`/`system_prompt` markdown-source highlighting, output-shape prose, and all named component/view fixtures. Added a focused icon contract proving Claude- and Codex-backed agent nodes share the neutral identity instead of leaking the old Claude brand.
- Regenerated the real React Flow fixtures through `tests.fixtures.react_flow_contracts._generate`; only `run-cycle.json` changed. The committed contract now carries three `kind: agent` nodes, their required `backend: claude` params, migrated source-line metadata, and `kind_output_types.agent`.
- Verification is green on every sandbox-capable gate: `make ui-build` succeeds (strict TypeScript + production Vite bundle); the complete web suite passes 800 tests across 55 files; the Python contract drift guard passes 4 tests; and the broader non-e2e Python suite passes 8,803 tests with only the known sandbox-denied `tests/test_cli/test_ui.py` file excluded. Direct asset sync, repository-wide Ruff lint/format, mypy (253 source files), deptry (254 files), applicable pre-commit hooks, and `git diff --check` pass.
- `make check` was attempted as required but cannot start past `uv lock --locked`; it reproduces the documented macOS sandbox `system-configuration` NULL-object/Tokio panic. The direct equivalents above are green, no dependency/lock file changed, and this is environment evidence rather than a product failure.
- Deviation/remaining manual proof: the mandated `screenshot-pflow-web-ui` check could not run because loopback bind/connect is forbidden in this sandbox. On an unrestricted host, rebuild, launch `pflow ui`, and inspect a two-node Claude/Codex agent graph for the violet accent, `AGENT` category, highlighted prompt/system-prompt source, and the backend-specific icons recorded in the follow-up below. No Phase 5 work was started and no commit was created.

## 2026-07-13 — Phase 4 backend-icon follow-up started

- The user requested backend-specific agent branding and supplied light/dark Codex SVGs in the repository-root `Codex_light_dark/` staging directory. The live graph contract already carries the resolved `backend` param in `RFNode.params`, so this is a frontend-only selection change at the existing `iconFor()` seam.
- UI theme reality: the canvas is dark-only, making the supplied white `Codex_dark.svg` the active mark. Both supplied variants will move into the owned icon asset directory and the root staging directory will be removed; Claude reuses the existing native-color `claude.svg`. Missing, dynamic, or unknown backend values retain the generic `ai-llm.svg` fallback.

## 2026-07-13 — Phase 4 backend-icon follow-up completed

- `iconFor()` now reads the agent node's `backend` param: `claude` renders the existing orange Claude mark, `codex` renders the supplied white Codex dark-theme mark, and unresolved/future values retain the neutral sparkle. Focused tests pin both product mappings and all fallback cases.
- Moved both supplied Codex theme SVGs into `web/src/assets/icons/` as `codex-dark.svg` and `codex-light.svg`, documented their trademark attribution, and removed the root `Codex_light_dark/` staging directory. The light variant is retained beside the active dark variant for a future light UI theme; the current dark-only bundle imports only `codex-dark.svg`.
- Verification: the focused icon suite passes 2 tests; `make ui-build` passes strict TypeScript and the production Vite build; the complete web suite passes 801 tests across 55 files. An accidental overlapped `npm test`/`npm ci` attempt was invalid because the installer replaced dependencies under the runner; it was terminated and the clean sequential full-suite rerun passed.
- The screenshot skill remains environment-blocked: a fresh port 8795 launch reproduces the sandbox's false “port already in use” bind failure, so no current-bundle browser screenshot can be captured here. No Phase 5 work was started and no commit was created.

## 2026-07-13 — Phase 5 started

- Read the requested `implement-plan` skill, the required `pflow-sandbox-testing` skill, the `claude-md-update` skill, and every file under `.taskmaster/tasks/task_177/` in full before editing. Scope is Phase 5 only: remaining examples, guide, user docs, architecture/MCP prose, agent-facing instruction cleanup, and the prescribed validation gates.
- Re-verified repository state against the user handoff: Phases 1–4 are committed separately at `267c8e28`, `b0e03a55`, `ef8f6414`, and `a20b27a1`; the worktree was clean at Phase 5 start.
- The plan's remaining migration surfaces are live. The shipped guide topic has already been renamed to `agent.md` and examples already use `type: agent` + `backend: claude`, but the guide is still Claude-only and the example filenames/README prose still use `claude-code`. Phase 5 will author the dual-backend contract and finish filename/prose cleanup rather than repeat the completed syntax migration.
- The broadened grep found additional stale agent-facing references in `tests/CLAUDE.md` and `src/pflow/core/CLAUDE.md` beyond the plan's abbreviated `CLAUDE.md` list. They describe load-bearing import/token boundaries, so they will be updated to the current `AgentNode` / `ClaudeBackend` architecture rather than deleted.
- Historical architecture documents under `architecture/historical/` remain intentionally unchanged, as the plan directs. The real npm package name `@anthropic-ai/claude-code` in Claude installation guidance and assertions also remains intentional. Any other residual `claude-code`, `claude_code`, or `ClaudeCodeNode` reference in shipped/current prose is in scope.
- Updating `.claude/agents/review-feature-interactions.md` makes its generated `.codex/agents/review-feature-interactions.toml` stale. The prescribed `scripts/sync_claude_assets.py --write` reached that target but the sandbox exposes `.codex/` read-only and rejected the write with `Operation not permitted`. The authoritative Claude source remains corrected; regeneration of the derived Codex asset is an environment handoff unless a writable surface becomes available.
- Direct repository-wide mypy exposed 10 errors in the committed Phase 1 Claude adapter despite prior progress entries claiming mypy was green: two async methods declare `dict` while returning `AgentResult`, and the optional old-SDK exception-import fallback assigns `None` to names inferred as class-only. Phase 5 will correct these annotations/import aliases without changing runtime behavior because this is Task 177's final cleanup phase and leaving a known task-local quality-gate failure would violate the plan's completion gate.

## 2026-07-13 — Phase 5 completed

- Finished the clean-slate public migration: authored a dual-backend `pflow guide agent` topic; renamed and rewrote the Mintlify node reference; updated current guide/MCP instructions, docs, architecture, root/example indexes, changelog examples, and agent-facing `CLAUDE.md` facts; renamed the four Claude example files; and replaced stale harness prose/diagrams. Folded the subscription-vs-API-key material from `nodes/agent/AUTHENTICATION.md` into the shipped guide before deleting the standalone internal file.
- The guide/reference now pin the actual flat contract: required `backend`, shared versus backend-only parameters, backend-shaped sandbox, Codex model/config inheritance, Claude/Codex authentication, native object-schema output, scalar coercion plus same-session retries, soft-failure routing, normalized usage differences, and cross-run resume IDs. Corrected two inherited prose errors while authoring: `input_tokens` is cache-inclusive, and top-level `llm_usage` describes the final schema attempt while `retries` stores superseded calls (reports/traces aggregate them).
- Cleanup deviation required by the final gate: corrected the pre-existing Claude adapter type defects found by mypy. Optional SDK exception classes now use explicit nullable aliases, and both async execution methods correctly declare `AgentResult`; runtime behavior is unchanged. The complete non-e2e agent suite passes after the change.
- Intentional residuals: historical architecture/release records remain unchanged; `/integrations/claude-code` remains the real Claude Code product integration route; `@anthropic-ai/claude-code` remains the real npm package. The scoped clean-slate search finds no current `type: claude-code`, `ClaudeCodeNode`, or `claude_code.*` identifier.
- Verification: focused docs/guide/MCP batch 111 passed; related agent/orchestration/graph/CLI batch 315 passed with the paid real-Codex e2e deselected; final agent batch 202 passed with that e2e deselected; final broad sandbox-capable non-e2e suite 8,803 passed. The excluded UI file separately reports 53 passed / 3 failed, all three failing before product code because this sandbox forbids loopback `socket.bind`. `pflow guide agent`, both named workflow validations, and a full 14-node/3-sub-workflow plan-to-code dry-run succeed.
- Quality: repository-wide Ruff lint and format, mypy (253 source files), deptry (254 files), applicable pre-commit hooks on all 50 changed/new files, MDX fences, links, JSON formatting, and `git diff --check` pass. `make check` itself cannot start because `uv lock --locked` reproduces the documented macOS NULL-object/Tokio sandbox panic. Its asset-sync equivalent additionally reports the one generated `.codex/agents/review-feature-interactions.toml` file that cannot be regenerated because `.codex/` is read-only here; run `make sync-claude-assets` on a writable checkout.
- Manual proof still outside this sandbox: execute a paid/live migrated agent example and the Phase 3 text/schema/separate-process Codex resume checks on a network-enabled host. Phase 5 did not make live backend calls or commit changes.

## 2026-07-13 — Phase 6 auth/billing guard planned

- The user identified a contract gap after Phase 5: `use_api_key` exists only for Claude, while
  Codex inherits its environment/configuration and can use API-key auth without a node-level opt-in.
  The requirement is now explicit: pflow must protect the known first-party API-key paths by
  default and require an affirmative node parameter before permitting them.
- Read every Task 177 file in full and re-verified the live seams before planning. Current code puts
  `use_api_key` in `CLAUDE_PARAMS`, normalizes it inside `ClaudeBackend`, and launches
  `codex exec` without an explicit `env`, so Codex inherits `OPENAI_API_KEY` / `CODEX_API_KEY` and
  arbitrary profile/config provider selection.
- Used three focused `pflow-codebase-searcher` reviews—not a generic explorer—to independently map
  auth enforcement, test/fixture impact, and the maintainable public API. Their findings were
  reconciled into a binding Phase 6 in `implementation-plan.md`; the task spec was updated so an
  isolated implementer no longer encounters the obsolete "Claude-only" / "Codex has no key
  parameter" contract.
- Resolved `use_api_key` as one shared strict permission flag rather than a new auth-mode enum.
  Omitted/false preserves Claude's existing child-only `ANTHROPIC_API_KEY` scrubbing and activates
  the Codex account-auth guard. True permits stored/environment API-key or configured-provider use
  but does not require a key, mutate credentials, or force a paid request. This preserves Claude
  compatibility and directly models the user's "do not permit API-key use without opt-in" intent.
- Codex safe-mode design is pinned at the spend boundary: copy (never mutate) `os.environ`; remove
  `OPENAI_API_KEY` and `CODEX_API_KEY`; run `codex login status` with a fixed short timeout; and pass
  that same environment object to `codex exec`. Repeat the preflight for every `CodexBackend.run`,
  including schema-correction/resume turns; do not cache it.
- Status parsing is exact, fail-closed, and secret-safe. Accept ChatGPT login and enterprise Codex
  access-token status; reject stored API-key, personal-token, Bedrock, logged-out/non-zero,
  conflicting, and unknown/future output before a model call. Parse both stdout and stderr, tolerate
  unrelated warning lines around one recognized status, and never put the raw status or masked key
  in logs/exceptions.
- Defense-in-depth decision: append `model_provider="openai"` after caller provider selectors in
  false mode, while retaining profile/config support. Do not use `forced_login_method` because
  Codex documents that a credential mismatch logs the user out; do not use `--ignore-user-config`
  because it would break Task 177's shipped configuration contract. In true mode, preserve the
  caller's environment/provider behavior and skip status because `CODEX_API_KEY` execution
  precedence can differ from stored-login status.
- Narrowed the guarantee after adversarial review. The guard controls named first-party key
  variables, recognized stored Codex API-key auth, and the ordinary provider selector; it cannot
  prove that custom profiles/providers/proxies/base URLs are unmetered. It also cannot prevent
  purchased ChatGPT/Claude credits, auto-reload, overage, or administrator policy. Shipped docs must
  state these concrete protections rather than promise zero incremental spend.
- The Phase 6 plan specifies exact production ownership, pure helpers, subprocess arguments,
  non-retriable error propagation, fixture dispatcher refactor, parameterized status matrix,
  AgentNode/static-validation coverage, docs to update, and sandbox-safe non-e2e commands. Paid
  API-key e2e, credential mutation, and unapproved real provider calls are explicitly excluded.
- Official Codex auth documentation confirmed subscription and usage-based API-key sign-in,
  `codex login status`, ChatGPT-managed enterprise access tokens, and the destructive mismatch
  behavior of `forced_login_method`. Current OpenAI credit documentation confirmed that ChatGPT
  plan usage can consume purchased credits/auto top-up after included allowance. The Codex-manual
  helper could not resolve `developers.openai.com` inside the sandbox, so the check used the same
  official pages through the available web surface; no local Codex auth state was changed.
- Final plan verification: the focused design reviewer found and then re-checked fixes for four
  ambiguities—absolute billing wording, AgentNode versus backend default ownership, resume config
  ordering, and mismatch-test naming—and declared Phase 6 isolation-ready with no remaining major
  ambiguity. `git diff --check` passes for the plan/spec changes. No production implementation or
  tests were run during this planning-only step.

## 2026-07-13 — Phase 6 implementation handoff

- **Next scope:** implement Phase 6 only from `implementation-plan.md` § Phase 6. Phases 1–4 are
  committed separately; Phase 5 and this planning update are present in the current dirty worktree.
  Preserve all existing changes and inspect the diff before editing.
- **Required read order:** all files under `.taskmaster/tasks/task_177/`, then the current agent
  production modules, focused tests, and auth documentation named by Phase 6. Append commands,
  results, and implementation discoveries below this handoff rather than duplicating the plan.
- **Testing rule:** read `.agents/skills/pflow-sandbox-testing/SKILL.md` before any test command.
  Use the plan's direct `.venv`/temporary-HOME non-e2e gates. Do not run a real model request,
  API-key login, logout, or credential-changing command without explicit owner authorization.
- **Checkpoint:** before committing, confirm the mocked sequence is `status → exec` for each safe
  run and `status → exec → status → resume exec` for schema correction; false-mode failures make
  one status call and zero model calls; true mode makes no status call; parent environment and raw
  status secrets never leak; docs retain the narrowed guarantee.

## 2026-07-13 — Phase 6 implementation started

- Read the requested `implement-plan` skill and every file under `.taskmaster/tasks/task_177/` in
  full before editing. Scope is Phase 6 only: centralize `use_api_key`, add the fail-closed Codex
  account-auth preflight/provider guard, update focused tests, and reconcile the named auth docs.
- Re-verified the repository state and corrected the handoff's stale dirty-tree statement: Phases
  1–5 are committed separately through `fe08e426` (`phase 5 completed`), and the worktree was clean
  at Phase 6 start. No user changes need to be preserved around the Phase 6 edits.
- The live seams match the Phase 6 plan: `use_api_key` is still in `CLAUDE_PARAMS`; strict coercion
  lives privately in `ClaudeBackend`; `AgentNode.prep()` does not prepare a shared value;
  `CodexBackend.run()` creates temp files and launches the model without an explicit child env or
  login-status preflight; `_append_config_options()` has no final provider guard; and
  `translate_error()` currently logs/rewraps every exception before classification.
- Static validation already imports `SHARED_PARAMS` from the shared module, so moving the parameter
  there is sufficient for literal Claude and Codex workflows. No validator implementation branch
  is needed. The registry allowlist is driven by `AgentNode`'s docstring, whose current wording is
  the only metadata change required.
- Test-fixture delta confirmed: the existing Codex fake assumes every subprocess is a model call
  with `--output-last-message`; Phase 6 must replace it with the planned status/exec dispatcher.
  Existing Claude coercion tests call the backend-private helper and must move to the shared pure
  helper rather than duplicate the matrix through runtime backends.
- Documentation still teaches the superseded contract (`use_api_key` as Claude-only and Codex as
  having no key parameter), including absolute “no API billing/per-token charges” language in the
  plan-to-code examples. The Phase 6 wording changes are therefore necessary, not mechanical churn.
- Implemented the production boundary as planned: strict coercion now lives in
  `schema_validation.validate_use_api_key`; `AgentNode.prep()` prepares it once for either backend;
  Claude consumes that shared value without changing its child override; and Codex builds one copied
  environment, checks account auth before temp-file/argv work, and reuses the environment for exec.
- Codex status classification is a closed enum and discards matched text. Only ChatGPT/access-token
  account classes pass. API-key, unsupported credential, logged-out/non-zero, conflicting, and
  unknown output raise secret-safe `CodexNonRetriableError` instances before a model call. Safe mode
  appends `model_provider="openai"` after caller config; opt-in mode omits both status and provider
  guard.
- Refactored the Codex fake subprocess boundary into a status/exec dispatcher and added contract
  coverage for environment identity/sanitization, status parsing and fail-closed cases, opt-in,
  provider precedence on initial/resume argv, preflight launch failures, idempotent non-retriable
  translation, and schema-retry call order. The strict bool matrix now has one owner at the shared
  helper boundary.
- Phase 6 focused checkpoint passed on Darwin using the worktree `.venv` and writable temporary
  HOME: collection found 104 non-e2e tests across the shared validation and Codex backend files;
  the focused run passed all 104 with the paid real-Codex smoke deselected. The assertions pin
  `status → exec`, `status → exec → status → resume exec`, one status/zero model calls on safe-mode
  rejection, no status call in opt-in mode, same-object sanitized env reuse, and provider-last
  precedence without exposing masked status text.

## 2026-07-13 — Phase 6 completed

- Shipped one shared strict `use_api_key` contract. `AgentNode` normalizes it once; Claude's false
  mode still blanks only `ANTHROPIC_API_KEY` in SDK options; Codex false mode copies and sanitizes
  the child environment, requires recognized account auth before every possible model call, and
  appends the final OpenAI provider override. True mode skips the Codex status guard and preserves
  explicit key/profile/provider configuration without requiring a key or mutating credentials.
- Codex authentication failures are fail-closed, secret-safe, and non-retriable. The classifier
  tolerates unrelated warnings around one recognized status but rejects API-key, personal-token,
  Bedrock, logged-out/non-zero, conflicting, and unknown/future output. Status launch absence and
  timeout are converted at the preflight boundary; `translate_error()` preserves those errors
  unchanged so PocketFlow performs one status call and zero model calls.
- Updated every Phase 6-named guide/reference/architecture/example/changelog surface. The public
  guarantee now names the controls precisely and records the Codex compatibility change; it does
  not claim that custom providers/proxies/base URLs, account credits, auto-reload, overage, or
  administrator policy cannot be metered. `pflow guide agent` rendered successfully and manual
  inspection confirmed the shared parameter table, both auth modes, remediation, and caveat.
- Verification: focused shared-validation/Codex tests passed 104 with one paid e2e deselected; the
  full affected surface passed 274 with one paid e2e deselected. Repository-wide Ruff lint/format,
  mypy (253 source files), deptry (254 files), applicable changed-file hooks, and `git diff --check`
  passed. The complete `make check` gate passed outside the macOS sandbox, including lock
  consistency, asset sync, all pre-commit hooks, Ruff, mypy, and deptry.
- Deviation required to make the mandated gate truthful: Phase 5 had committed its authoritative
  `.claude/agents/review-feature-interactions.md` rename but left the derived
  `.codex/agents/review-feature-interactions.toml` stale because that path was read-only in the
  sandbox. Regenerated exactly that one derived file with `make sync-claude-assets`; its two-line
  semantic diff replaces the old node/class names and `make check` now confirms synchronization.
- No real model turn, paid/API-key e2e, login/logout, credential mutation, or `codex login status`
  reality check was run. Those are intentionally unnecessary for this guard phase; the existing
  paid Codex smoke remains deselected pending explicit owner authorization. No commit was created.

## 2026-07-13 — Phase 6 deep-review fixes completed

- Ran a three-specialist code-mode deep review over the unstaged Phase 6 scope: silent failures /
  secret handling, validation and impact completeness, and test fidelity / feature interactions.
  The allowlists, metadata seam, provider precedence, environment isolation, retry sequencing, and
  named documentation surfaces reviewed cleanly. Reviewers found three concrete warnings and one
  redaction hardening opportunity; the user approved all four fixes.
- Removed retained timeout diagnostics completely. Because `TimeoutExpired` can carry partial
  stdout/stderr, the sanitized Codex preflight error is now raised after leaving the `except` block;
  its `__cause__` and `__context__` are both `None`. A regression test supplies secret-bearing
  partial output and asserts that neither text nor exception linkage survives.
- Corrected opt-in remediation to match the permission-only contract. Claude no longer claims that
  `use_api_key: true` proves `ANTHROPIC_API_KEY` was effective; it gives conditional key guidance and
  account-login verification. Codex post-exec auth failures now branch on the normalized flag so
  opt-in mode points to environment/profile/provider credentials before offering account-login mode.
- Invalid shared `use_api_key` values now report only their type, never the value. A secret-shaped
  rejected string test pins redaction. This preserves the exact accepted bool/int/string forms while
  removing an avoidable template/input secret exposure.
- Verification after fixes: 50 targeted auth/redaction tests passed; the full affected non-e2e
  surface passed 277 with one paid Codex e2e deselected; focused Ruff lint/format passed; and the
  complete `make check` gate passed outside the macOS sandbox (lock consistency, asset sync, Ruff,
  all pre-commit hooks, mypy, and deptry). No live provider call or commit was made.

## 2026-07-13 — Adversarial end-to-end verification and fixes

- Read the complete task folder, implementation, and focused test surface, then treated the existing
  suite as context rather than end-to-end proof. Real Claude and Codex text, structured-output, and
  cross-process resume workflows were exercised with `use_api_key: false` while all three known key
  variables contained deliberately invalid sentinel values.
- Both providers completed through account/subscription auth. Separate `pflow` processes resumed the
  original Claude session and Codex thread, returned the prior exact token, and preserved the exact
  same session/thread ID. Claude's reported `cost_usd` remains the existing pricing estimate derived
  from usage; it is not evidence of API-key auth or per-request billing.
- Found a real parser/compiler/runtime integration defect missed by the mocked backend suites: a
  documented fenced `prompt` passes validation, but compilation flattens its line metadata to
  `_prompt_source_line`, which backend allowlist validation rejected. Added one narrow shared
  predicate for compiler source-line sidecars, used it in both backends, and pinned the complete
  markdown parser → compiler → real `AgentNode.prep()` path for Claude and Codex. A real Codex fenced
  workflow then returned the requested exact token.
- Found that the Codex timeout used `subprocess.run`, which only kills the direct CLI process and can
  leave tool descendants alive or block while they retain stdout/stderr pipes. Replaced it with an
  owned process-group runner, POSIX group termination, Windows `taskkill /T /F`, bounded pipe drain,
  and interruption cleanup. The real regression launches a parent that exits immediately while its
  sleeping grandchild retains the pipes; cleanup now returns at the configured timeout.
- Corrected the remaining current architecture overview label from the removed `Claude-Code` node to
  `Agent`. Temporary manual-verification workflows and logs were deleted after the checks.
- Darwin verification results: 117 focused non-e2e tests passed with one paid smoke deselected; the
  affected parser/compiler/agent surface passed 489 with one paid smoke deselected; the broader
  non-e2e suite passed 8,868 tests with the loopback UI file isolated; that UI file passed all 56
  tests outside the restricted socket sandbox. `make check` passed in full, including lock and asset
  synchronization, Ruff, pre-commit, mypy (253 source files), and deptry (254 files).

## 2026-07-13 — Explicit Codex model pricing

- Added one shared LiteLLM pricing seam for completed calls made outside `litellm.completion` and
  routed Codex usage through it only when the workflow explicitly declares `model`. The estimator
  passes Codex's cache-inclusive input total and cached-input count to LiteLLM's cache-aware
  `cost_per_token` calculator. Omitted or unpriced models remain `cost_usd: null`; pflow does not
  inspect private Codex rollout/session files to infer the CLI-configured model.
- Kept the existing prompt-cache analysis import surface compatible while moving its pricing data
  lookup into the shared LiteLLM runtime seam. Added tests against the real bundled LiteLLM catalog,
  public AgentNode metadata propagation, cache discounts, no-model lazy behavior, unknown-model
  fallback, and structured-output retry aggregation so every completed Codex call is counted.
- A real subscription-backed Codex run used `model: gpt-5.5`, `use_api_key: false`, and deliberately
  invalid `OPENAI_API_KEY`/`CODEX_API_KEY` sentinels. It returned the requested marker with 16,109
  input tokens (1,920 cached), 23 output tokens, and `cost_usd: 0.072595`; the CLI report propagated
  the same total. This is an API-equivalent pricing estimate for comparison, not evidence that the
  ChatGPT subscription incurred a per-token charge. A separate `gpt-5.2-codex` live attempt was
  correctly rejected by the current ChatGPT account before execution, demonstrating that catalog
  pricing and account model availability are independent.
- Verification after the pricing change: 140 focused tests passed with two paid e2e cases
  deselected; the affected non-e2e surface passed 561 with three deselected; focused mypy passed;
  and the broad non-e2e suite passed 8,873 tests with the loopback UI file isolated. The final UI
  subprocess file passed all 56 tests outside the restricted socket sandbox. The complete
  `make check` gate also passed: lock and asset synchronization, all hooks, Ruff, mypy (253 source
  files), and deptry (254 files).

## 2026-07-13 — Deep-review items 1–4 implemented

- Replaced the structured-output scalar checker with JSON Schema validation as the conformance
  oracle. Valid values are preserved, coercion is attempted only for invalid direct scalar fields,
  candidates must satisfy their field schema, and the complete result must validate. Regression
  coverage now includes union ordering, object/array/null mismatches, enum equality, and nested
  constraints.
- Corrected AgentNode error signaling. A backend `is_error` result in free-form mode retains its
  text but emits an `agent.backend_error_free_form` warning and `_agent_error`, producing DEGRADED
  status. Corrective schema calls continue to degrade for retriable failures but now translate and
  propagate non-retriable failures such as authentication rejection.
- Hardened Codex's public diagnostic boundary. Model timeouts use a sanitized exception without a
  secret-bearing argv/cause, process failures no longer expose raw stdout/stderr or JSONL through
  messages/logs, and authentication detection uses narrow patterns over failure diagnostics rather
  than broad searches across model/tool output. Sentinel tests cover prompt/config timeout leakage,
  failed JSONL/tool output, and incidental auth words/token counts.
- Separated cost provenance for both agent backends. Canonical `cost_usd` remains unavailable,
  SDK/LiteLLM comparisons use `api_equivalent_cost_usd`, missing Codex usage is never priced, retry
  aggregation keeps the channels independent, and trace reports label the comparison estimate
  separately from paid cost. Public architecture, guide, reference, template-variable, and example
  documentation now describe the distinction.
- Verification: 26 schema tests, 134 AgentNode tests, 75 non-e2e Codex tests, 300 trace/report/usage
  tests, and the complete 284-test non-e2e agent package passed. The broad sandbox run passed 8,860
  effective tests after the two expected generated-guide/contract updates; the 3 socket-only cases and
  the separate 90-test interaction-server file passed outside the restricted loopback sandbox. Focused
  Ruff and mypy checks passed. The paid Codex smoke remained explicitly deselected; no provider call
  was made.

## 2026-07-14 — Deep-review items 5–8 implemented

- Added batch-scoped cancellation for external Agent work. Parallel fail-fast and `_execute_parallel`
  cleanup set a shared event that propagates through nested workflows into AgentNode options. Codex
  polls the event while communicating, terminates the process tree, and exits without consuming batch
  retries. Tests cover fail-fast cancellation and main-thread `KeyboardInterrupt` cleanup.
- Hardened Windows process ownership with a kill-on-close Job Object. If Job assignment is unavailable,
  the existing `taskkill /T /F` fallback now has a fixed timeout. The parent-exits-first pipe-holder test
  now runs on Windows as well as POSIX, and a Windows-only, non-network `.cmd` shim test pins exact argv
  handling for spaces and shell metacharacters.
- Registered a `paid` pytest marker and marked the live Codex smoke explicitly. `test`, `test-e2e`,
  `test-debug`, `test-all-local`, and `test-with-skipped` each exclude `paid` in their own marker
  expression; static Makefile contract tests prevent an environment variable or future target edit from
  silently collecting the smoke.
- Changed static Agent schema validation to defer recursively templated schemas until runtime resolution,
  while still enforcing Claude's statically knowable `max_turns >= 2` rule. Migrated the core guide, both
  MCP instruction resources, and the core implementation guidance away from stale Claude Code wording;
  a scoped regression test rejects its return.
- Decoupled planning history from memo-hit eligibility. Successful cache-disabled executions persist only
  `llm_usage` and duration under a deterministic reserved history key, never reusable node output. A
  default Agent run now seeds dry-run duration/API-equivalent cost history and still executes on every run.
- Promoted effective Agent prompts and bounded tool summaries into canonical single/batch trace fields and
  report sections. Isolated each batch item's warning channel, retained warnings in per-item traces, and
  deterministically aggregated indices and kinds into `batch.item-warnings` so parallel schema soft-fails
  cannot overwrite one another.
- Validation used the direct virtualenv with the sandbox-safe HOME. Focused Agent, batch, history, trace,
  report, guide, MCP, Ruff, format, mypy, and asset-sync checks passed. The broad non-e2e/non-paid suite
  passed, and the isolated loopback UI files passed outside the restricted socket sandbox. The non-paid
  E2E selection passed except for one unrelated `uv run pflow` test whose temporary working directory
  could not resolve this worktree's executable. No provider call was made; the paid smoke stayed deselected.

## 2026-07-14 — Adversarial pflow-user verification: two real Codex bugs found + fixed

- Verification specialist pass driving the node end-to-end through the real `pflow` CLI against **live**
  Claude (subscription) and Codex (ChatGPT) backends — the mocked suite was treated as context, not proof.
  Confirmed working live: Claude/Codex text, Claude structured output, cross-process Codex resume (recalled
  a secret across two separate `pflow` processes), `llm_usage` normalization (Codex `total_includes_cache`
  vs Claude `split_cache_fields`; `reasoning_output_tokens` present only for Codex; `session_id`/`num_turns`
  populated; `model→cost` gating), the Phase 6 safe-mode guard (poisoned `OPENAI_API_KEY`/`CODEX_API_KEY`
  scrubbed, run still succeeded via ChatGPT), batch+Codex parallel fan-out, and the static-validation battery
  (missing/invalid backend, cross-backend params, array-root schema, claude `max_turns>=2`, unknown-param).
- **Bug 1 (High) — Codex structured output was broken for ordinary schemas.** `codex_backend.py` wrote the
  user's `output_schema` verbatim to `--output-schema`; OpenAI's strict `response_format` (which Codex
  enforces) rejects any object schema lacking `additionalProperties: false` and any object whose `required`
  omits a property. The SAME schema succeeded on Claude and 400'd on Codex — breaking the unified node's
  shared-parameter contract, including the shipped guide's Codex `output_schema` example. The entire Codex
  test suite missed it because every test feeds canned JSONL and never exercises OpenAI's real strict rules.
  Fix: `_strictify_schema()` returns a deep copy with `additionalProperties: false` on every object and
  `required` filled with all property keys (recursively, through `properties`/`items`/`$defs`/combinators),
  applied at the `--output-schema` write. Non-nullable required (not nullable) so the result still validates
  against the caller's *original* schema in `AgentNode.post()`. The caller's dict is never mutated. Verified
  live: the previously-failing schema and a nested+optional schema both now return parsed objects.
- **Bug 2 (Medium) — Codex failures were undiagnosable.** `translate_error` reported only "N failure
  event(s). Run the same Codex command directly" and discarded the real reason even from the debug trace.
  Fix: `_readable_failure_detail()` surfaces `code: message` from **structured** provider-error payloads only
  (a JSON object carrying an `error` object), de-duplicated across the `error`/`turn.failed` events. Free
  text, raw stdout/stderr, and tool `aggregated_output` are never surfaced, so the Phase 6/deep-review
  secret-safe guard (`test_failed_jsonl_and_tool_output_never_reach_public_error_or_logs`) still passes
  unchanged. Verified live with an invalid model: now reports `invalid_request_error: The '<model>' model is
  not supported when using Codex with a ChatGPT account.`
- Tests: updated the schema-write assertion to expect the normalized form (and pinned that the caller's dict
  is untouched); added `TestStrictifySchema` (5) and `TestReadableFailureDetail` (5, incl. a free-text/tool
  secret NOT surfaced + a structured message IS surfaced). Focused Codex/schema suite 86 passed; full agent
  dir 298; broader sweep (agent + trace_report + unknown_param + guide_example) 519 passed. Ruff + mypy clean.
## 2026-07-14 — Finding 3: `--validate-only` now matches runtime for agent param shapes

- Owner principle: validate should catch whatever a run catches. The validator already committed to this
  (its docstring: predicates live in the SDK-free `schema_validation` "so runtime prep and this static
  preflight cannot drift"), but sandbox-shape and `schema_retries` validators still lived in the backends,
  so `--validate-only` false-greened configs that fail at runtime prep.
- Fix (single source of truth, no duplicated logic): moved the pure param-shape validators into
  `schema_validation.py` — `validate_schema_retries`, `validate_claude_sandbox`/`_max_turns`/
  `_max_thinking_tokens`/`_tool_list`, `validate_codex_sandbox`/`_approval_policy`/`_add_dirs`/`_profile`
  (plus shared `CODEX_SANDBOX_MODES`/`CODEX_APPROVAL_POLICIES` constants). The backends' `validate_params`
  and `AgentNode.prep` now call these directly (the thin `_validate_*` wrapper methods were deleted, not
  kept as indirection — simplest final code, per owner steer). `WorkflowValidator._validate_agent_param_shapes`
  runs the SAME validators, converting a raised `ValueError`/`TypeError` into a Diagnostic; it runs before
  the `output_schema is None` early-return and defers templated values. So validate == run by construction.
- Verified: `--validate-only` now rejects a claude string sandbox, a codex dict sandbox, and
  `schema_retries: 99` with the exact runtime messages; valid codex shapes still pass; a live codex run
  confirms the refactored runtime `validate_params` still executes (`MANGO`). Tests: added 5 validate-only
  parity tests; agent dir 298, validate_only + agent + unknown_param 343, broad sweep (agent + validate_only
  + trace_report + example/guide validation) 554 — all green. Ruff + mypy clean.
- One deliberate remaining gap (noted, not a false green risk): codex `config` shape validation stays in
  `CodexBackend._validate_config` because it is coupled to the codex TOML serializer (`_toml_value`); a
  malformed `config` still surfaces at runtime prep. Moving the TOML serializer into the shared module for
  this rare/advanced case would be disproportionate.

- Finding 4 (raw `ValueError`/`TypeError` from agent param validation instead of `PflowError` subclasses):
  pre-existing and pervasive (inherited verbatim from `claude-code`; the plan preserved Claude behavior
  identically). Deferred by owner decision to GitHub issue #592 rather than a scope-expanding sweep this session.
