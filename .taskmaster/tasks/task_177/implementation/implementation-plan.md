# Implementation Plan — Task 177: Unified `agent` Node (claude | codex)

> **Read alongside** `.taskmaster/tasks/task_177/task-177.md` (the what & why — not restated here).
> **On approval, save this file to** `.taskmaster/tasks/task_177/implementation/implementation-plan.md`.
> Per-phase scope/tier/agent/checkpoint notes are **recommendations** per ORCHESTRATION.md
> (§ Model routing, § Agent economics, § Checkpoints); whoever runs the plan may adjust on live
> judgment. The *what* (decisions, edge cases, behavior) is binding.

## Context

pflow has one agentic node, `claude-code` (`src/pflow/nodes/claude/claude_code.py`, 1675 lines),
tightly wrapping `claude-agent-sdk`. We're replacing it clean-slate with a single `agent` node
that selects a backend (`claude` | `codex`) so a second agent (OpenAI Codex, via the `codex exec`
CLI) can be added behind one interface without duplicating the ~1600 lines of lifecycle /
validation / schema-retry / token-normalization scaffolding. Verification in the originating
session established: codex's CLI runs on the user's ChatGPT subscription, has native
`--output-schema`, and disk-based `codex exec resume`; the `openai-codex` SDK is beta with a stale
bundled binary, so v1 uses the CLI. The `AgentBackend` seam keeps the future SDK swap invisible to
`type: agent`.

## Resolved decisions (no open forks — implement as stated)

- **Param shape: FLAT + per-backend validation.** All params are flat (no nested `claude:`/`codex:`
  maps). Backend-exclusive params are accepted only for the active backend; using one with the
  wrong backend is a **blocking validation error** naming the active backend and the offending key
  (e.g. `'approval_policy' is not valid for backend 'claude'`). Migration of existing claude-code
  examples is therefore near-pure: add `backend: claude`, keep params unchanged.
- **`backend` is REQUIRED** (no default). Missing `backend` is a blocking validation error listing
  the valid values. Explicit is safer than silently defaulting to claude for a codex user.
- **Shared vs backend-specific params** (VERIFIED against `claude_code.py:177-210` — param names,
  types, defaults, and the full `llm_usage` output contract at :182-193 all match):
  - *Shared (validated in `AgentNode`), valid for both backends, same shape*: `prompt`, `model`,
    `cwd`, `output_schema`, `resume`, `timeout`, `system_prompt`, `schema_retries`.
  - *claude-only (validated in `ClaudeBackend`)*: `allowed_tools`, `disallowed_tools`, `max_turns`,
    `max_thinking_tokens`, `use_api_key`.
  - *codex-only (validated in `CodexBackend`)*: `approval_policy`, `add_dir`, `profile`, `config`.
  - ***`sandbox`* is valid for BOTH backends but is BACKEND-SHAPED** — see next bullet. It is NOT a
    shared param; each backend validates its own shape.
- **`sandbox` is backend-shaped, NOT a shared string enum** (CORRECTION — an earlier draft wrongly
  called it shared; the deep-review missed it; verified against the live node):
  - **claude**: `sandbox` is a **dict** (SDK `SandboxSettings`) — keys `enabled`,
    `autoAllowBashIfSandboxed`, `excludedCommands`, `allowUnsandboxedCommands`, `network`,
    `enableWeakerNestedSandbox`, `ignoreViolations` (`claude_code.py:204-209`, `_validate_sandbox`
    :540-577). **Keep this EXACTLY as-is** — making `sandbox` a string would break every existing
    claude workflow. claude has NO `read-only`/`workspace-write` modes.
  - **codex**: `sandbox` is a **string** mode `read-only` | `workspace-write` | `full-access`, mapped
    to CLI `-s` (`full-access` → `danger-full-access`); default `workspace-write` when unset.
  - Frozenset model: `sandbox` goes in BOTH `CLAUDE_PARAMS` and `CODEX_PARAMS` (never cross-rejected);
    the allowed set for backend B is `SHARED_PARAMS ∪ B_PARAMS`; each `validate_params` validates
    sandbox's shape for its backend. The docstring union lists `sandbox` once.
- **Structured output**: keep the top-level `type: object` schema constraint for **both** backends
  (shared validation). Keep the existing soft-fail contract: on non-conforming output, fall back to
  raw text in `result`, set `_schema_error`, emit `__warnings__[node_id]` → DEGRADED; never route
  `on-error`. Keep the scalar-coercion + resume-and-retry loop.
- **codex default model**: when `model` is unset, **omit `-m`** and let codex use its own configured
  default (don't hardcode a possibly-wrong model name). Pass `-m <model>` through when set.
- **Rename `_claude_progress`/`_claude_tools` → `_agent_progress`/`_agent_tools`** (2 writer lines,
  no named readers — safe; trace tooling filters `_`-prefixed keys generically).
- **Registry name `agent`** is auto-derived from `AgentNode` via `registry/scanner.py:53-65`
  (`camel_to_kebab`, no explicit `name` attr) — no manual registry edit.
- **`AgentNode` docstring `- Params:` must list the UNION** of shared + claude-only + codex-only
  params, **including the required `backend`**. Reason (deep-review, validation-consistency C1): the
  static unknown-param check (step 8, `validator.py:693-786`) is **backend-blind** — it derives its
  allowlist solely from `AgentNode`'s docstring via `metadata_extractor.py`, and backends are not
  `Node` subclasses so their params are invisible to the registry. If the docstring omits
  `backend` or any codex-only key, step 8 rejects valid workflows (every `agent` workflow, in the
  `backend` case). Listing the union makes step 8 accept all params; cross-backend rejection then
  lives solely in step 9 + runtime `validate_params`.
- **Single source of truth for per-backend param sets.** Define `SHARED_PARAMS`, `CLAUDE_PARAMS`,
  `CODEX_PARAMS` frozensets in the shared `schema_validation.py` (which already exists to prevent
  validator↔runtime drift). `sandbox ∈ CLAUDE_PARAMS ∩ CODEX_PARAMS` (valid for both, different
  shapes). Allowed-for-backend-B = `SHARED_PARAMS ∪ B_PARAMS`; reject a param iff it's outside that
  union. Both `_validate_agent_params` (static) and each backend's `validate_params` (runtime) import
  these sets — no hand-maintained duplicate lists. (deep-review validation-consistency C2 +
  review-plan W2.)
- **Cross-backend rejection + `backend`-required run FIRST in `_validate_agent_params`**, before the
  existing `output_schema is None` early-return (`validator.py:877-879`). Otherwise a schema-less
  `backend: claude` + `approval_policy: ...` passes static validation but the node rejects it at
  runtime (false green on `--validate-only`/`--dry-run`/save). (validation-consistency C2.)
- **`max_turns >= 2 when output_schema set` is claude-only** — gate it to `backend == "claude"` in
  `_validate_agent_params` (it currently reads `max_turns` unconditionally). (validation-consistency
  W2.)
- **Diagnostic `kind` strings rename `claude_code.*` → `agent.*`** (e.g.
  `agent.schema_not_satisfied`, `agent.sdk_error_no_structured_output`). Clean-slate consistency; the
  hyphen-only grep won't catch `claude_code.` residuals, so this must be explicit. Update every
  asserting test (migrated AND non-migrated — see Phase 2 test list). (impact-completeness C2.)
- **Continuation-on-`None` semantics (precise)**: when `backend.continuation_options(prev, opts)`
  returns `None`, the retry loop **breaks and keeps the prior result** (→ soft-fail DEGRADED) —
  exactly today's `claude_code.py:729-731` behavior. It does **NOT** do a fresh-prompt retry. codex
  must return `None` when its first run produced no thread/session id. (review-plan W3 +
  feature-interactions S4.)
- **Phase 1 step-3 decision (no fork)**: the `backend` enum accepts `{claude, codex}` from Phase 1;
  selecting `codex` before Phase 3 raises a clear runtime "codex backend not available yet" error.
  Static validation accepts `backend: codex`; only run-time errs in the Phase 2→3 window. Phases 1–3
  land together for completion. (review-plan S7 + validation-consistency W3.)
- **`@anthropic-ai/claude-code` (claude_code.py:1136) is the real npm package name — do NOT rename**
  during find-replace. (impact-completeness.) Likewise replace, don't duplicate, `ClaudeCodeNode`
  in `_LLM_NODE_CLASSES`/`plan_formatter` with `AgentNode`.

## Target architecture (from the seam inventory)

New package `src/pflow/nodes/agent/` (rename of `nodes/claude/`):
- **`agent_node.py` — `AgentNode(Node)`** (SDK-free): owns `prep` (shared `_validate_*` +
  `backend.validate_params()` for backend-exclusive params), `exec` (calls `backend.run(...)`),
  the schema coercion + retry **orchestration** (currently in `_exec_async` 702-798), `post`,
  generic `exec_fallback` (delegates error translation to the backend), `_coerce_structured_output`,
  `_store_results`, `_store_schema_result`, `_emit_soft_fail_signal`,
  `_emit_schema_resolved_null_warning`, `_usage_record_from` (fed normalized usage),
  `_log_session_results`, and the shared validators
  (prompt/schema-core/cwd/max_turns/timeout/schema_retries/tool-list-shape).
- **`backend.py` — `AgentBackend` Protocol + `AgentResult` dataclass**:
  ```
  AgentResult: result_text: str; tool_uses: list; metadata: dict; progress_events: list;
               structured_output: Any | None; is_error: bool; error_text: str | None
  # metadata is NORMALIZED: cost_usd, duration_ms, num_turns, session_id, and inclusive
  # token fields (input_tokens, uncached_input_tokens, cache_read_input_tokens,
  # cache_creation_input_tokens, output_tokens, total_tokens, input_token_accounting)
  AgentBackend: default_model: str
    run(prompt, opts) -> AgentResult
    continuation_options(prev: AgentResult, opts) -> opts | None   # resume seam for retries
    validate_params(params) -> dict                                # backend-exclusive params
    translate_error(exc, opts) -> Exception                        # exec_fallback seam
    build_warning_context(opts, result) -> dict                    # backend diagnostic keys
  ```
  `AgentNode` maps `AgentResult.metadata` token fields directly onto `shared["llm_usage"]` — it
  never calls a claude-specific token normalizer; each backend returns already-normalized fields.
- **`claude_backend.py` — `ClaudeBackend`**: owns the `claude_agent_sdk` import + version guard
  (today `claude_code.py:65-99` — **moved here so importing the node package no longer requires the
  SDK**), `_claude_token_fields`, `_build_claude_options`, `_execute_with_timeout`,
  `_run_claude_session`, `_process_assistant_message`, `_extract_metadata`,
  `_create_completion_event`, `_enrich_error_result_exception`, `_is_auth_error`,
  `_auth_failure_guidance`, `_AUTH_ERROR_MARKERS`, and the claude-only validators
  (`max_thinking_tokens`, `resume`, `use_api_key`, claude sandbox sub-keys) + the top-level-object
  error text. Behavior identical to today's node.
- **`codex_backend.py` — `CodexBackend`** (new, Phase 3): drives `codex exec` via subprocess.
- **`schema_validation.py`**: unchanged predicates; update docstring references.
- **`__init__.py`**: keep the lazy `__getattr__` pattern (today's `nodes/claude/__init__.py:18-23`)
  so importing the package pulls in **neither** SDK nor codex CLI until a backend is selected.
  Backends are imported lazily inside `AgentNode` keyed on `backend`.

---

## Phase 1 — Seam extraction + ClaudeBackend (claude behavior identical)

**Scope**: ~large (refactor within the 1675-line node; net new files, mostly moved code).
**Tier**: **Opus** — highest-risk phase (structured output, schema-retry, token accounting,
soft-fail contract). Keep it in ONE agent; do not split. **Triggers mid-task review** (targeted:
`review-test-fidelity` + `review-impact-completeness`) after handback.

Do:
1. Create `src/pflow/nodes/agent/` with `agent_node.py` (`AgentNode`), `backend.py`
   (`AgentBackend` + `AgentResult`), `claude_backend.py` (`ClaudeBackend`), moved
   `schema_validation.py`, and lazy `__init__.py`. Delete `src/pflow/nodes/claude/`.
2. Split methods per the target architecture above. The retry loop stays in `AgentNode` but calls
   `backend.run(...)` per attempt and `backend.continuation_options(prev, opts)` to build the
   corrective continuation (claude → resume via `session_id`; returns `None` ⇒ loop degrades to a
   fresh-prompt retry / bail exactly as today's "no session_id → break", `claude_code.py:729-731`).
3. `AgentNode.prep`: validate shared params; require `backend ∈ {claude, codex}`; call
   `backend.validate_params(self.params)` for backend-exclusive params; a param belonging to the
   *other* backend is a blocking error. (Phase 1 registers only `claude`; `codex` selects a
   not-yet-implemented backend that raises a clear "codex backend not available" until Phase 3 —
   OR gate `backend` enum to `{claude}` in Phase 1 and widen in Phase 3. Prefer the explicit
   "not available yet" error so the enum/validation is written once.)
4. Rename shared-store keys `_claude_progress`→`_agent_progress`, `_claude_tools`→`_agent_tools`
   (the 2 writer lines). Update `context["node_type"]` strings `"claude-code"`→`"agent"`
   (`claude_code.py:377,1665`) and the `input_token_accounting` tag if you want backend-neutral
   naming (keep the existing value if simpler — no consumer keys on it).
5. Move the SDK import + version guard into `ClaudeBackend`; verify `import pflow.nodes.agent`
   succeeds with `claude-agent-sdk` **absent** (import only fails when `backend=claude` is selected).
6. Migrate tests: `tests/test_nodes/test_claude/` → `tests/test_nodes/test_agent/`.
   - `test_schema_coercion.py`, `test_schema_validation.py`: pure static-method tests — import
     rename only.
   - `test_claude_code.py`: keep the `tests/shared/claude_sdk_stub.py` + `conftest.install()`
     mechanism and its `sys.modules` timing (tests/CLAUDE.md pitfall #17) — it carries over because
     `ClaudeBackend` still does `from claude_agent_sdk import ...` at its module top. Update the
     `patch("pflow.nodes.claude.claude_code.query")` target to the new `ClaudeBackend` module path;
     update `node_type == "claude-code"` literals (:306,:935,:1286-1333) to `"agent"`; instantiate
     `AgentNode()` with `backend="claude"`.

7. **Mechanical type-string migration of all auto-discovered content — MUST land in this same
   phase/commit** (deep-review review-plan C1 + impact-completeness C1/C3): de-registering
   `claude-code` breaks three non-e2e test suites that rglob real workflow files —
   `test_docs/test_example_validation.py`, `test_docs/test_guide_example_validation.py`,
   `test_integration/test_plan_to_code_harness.py`. So in Phase 1 also:
   - Rewrite every `type: claude-code` → `type: agent` + `backend: claude` across `examples/**`
     (14 files: `examples/nodes/claude-code/**`, `examples/agent-orchestration/**`) and rename the
     `examples/nodes/claude-code/` dir → `examples/nodes/agent/`.
   - Rewrite `type: claude-code` in `src/pflow/guide/**` and rename `guide/nodes/claude-code.md` →
     `agent.md` (content *enrichment* — documenting codex — is Phase 5; the file must at least be
     valid `agent`/`claude` examples now).
   - The richer authoring (docs/, architecture/, prose) stays Phase 5; only the gate-blocking
     *type-string* migration is pulled forward.
8. Update `claude_code.py:323` legacy-schema error text (moves into `ClaudeBackend`) — the doc path
   `docs/reference/nodes/claude-code.mdx` → `agent.mdx` (impact-completeness W9).

Edge cases / must-hold:
- `AgentNode.exec_fallback` must still **raise** (retriable) after retries — preserves http-like
  batch-retry (which is NOT type-keyed; driven by raise-vs-return in `exec_fallback` —
  `batch_executor.py:327-342,696`, `node.py:95-104`). Do not convert to a returned error dict.
- Keep emitting `num_turns` + `session_id` + `retries` in `llm_usage` — trace/report mark agentic
  calls by field presence, not type name (`workflow_trace.py:351`, `trace_report.py:345-925`).
- `use_api_key` subscription-vs-key semantics (ANTHROPIC_API_KEY blanking) preserved in
  `ClaudeBackend`.
- **Sync/async boundary shift (design note, review-plan W4)**: today the whole schema-retry loop
  runs inside ONE `asyncio.run` (`exec:675`→`_exec_async`). Moving the loop into a sync
  `AgentNode.exec` that calls `backend.run()` per attempt means `ClaudeBackend.run` wraps its own
  `asyncio.run` — N event loops per node execution instead of one. Expected benign (claude resume is
  server-side/session-id), but it is a real event-loop-lifecycle change, not pure code motion.
  Require a multi-attempt schema-retry test exercising ≥2 `backend.run` calls end-to-end.
- `test_claude_code.py:42` imports `_claude_token_fields` — that import path moves to `ClaudeBackend`;
  update it (not just the sibling static-method files).

Gate: `make test` + `make check` green; every migrated claude test passes with no behavior change.
Failure scenarios the tests must catch: structured-output success writes parsed `result` with no
warning; malformed output soft-fails to DEGRADED with `_schema_error`; token accounting sums
across retries via `aggregate_llm_usage_with_retries`; `CLINotFoundError`/timeout/rate-limit/auth
errors translate and raise; importing the package without `claude-agent-sdk` installed succeeds.
Handback true-state: `agent` node exists, `backend=claude` is fully at parity, package imports
SDK-free.

## Phase 2 — Backend-agnostic wiring migration (validator, renderer, catalog, plan)

**Scope**: ~small-medium, spread across ~8 files. **Tier**: **Opus**, **resume the Phase 1
implementer** (continuous, same tier; the validator preflight must mirror Phase 1's flat+validation
design — tightly coupled). Bundle-vs-resume litmus: Phase 1's gate outcome doesn't change these
instructions ⇒ resume, don't stop.

Do (rekey `"claude-code"`/`ClaudeCodeNode` → `"agent"`/`AgentNode`, preserving behavior):
- **Validator** (`core/workflow/validator.py:816`): rekey the dispatch to `node_type == "agent"`;
  rename `_validate_claude_code_params`→`_validate_agent_params` **and the sibling
  `_claude_code_param_error`→`_agent_param_error`** (:891-972); implement **flat + per-backend**
  preflight matching the node. Ordering (validation-consistency C2): check `backend` required +
  cross-backend param rejection **before** the `output_schema is None` early-return (:877-879). Draw
  the claude-only/codex-only sets from the shared `schema_validation.py` frozensets (no duplicate
  lists). Gate the `max_turns >= 2` rule to `backend == "claude"` (:955-966). Keep the top-level-object
  schema rule (shared). Update `see_also`, error `node_type`, docstring (:163,:865-991).
- **react_flow renderer** (`graph/renderers/react_flow.py:282`): `node.kind == "agent"` →
  `_llm_kind_shape(node, field="result")`. Update docstrings (:72,:113,:116,:280,:1235,:1285-1290).
- **Display/plan/classification**: `node_type_display.py:10` (`"AgentNode": "agent"`);
  `execution/plan.py:71` and `formatters/plan_formatter.py:374` (add `AgentNode` to the LLM-node
  set so cost/duration estimates still apply); `core/llm_usage.py:80` comment.
- **Catalog / allowlist / guide map**: `registry/context_builder.py:608` (emit `- type: agent`
  template incl. `backend:`); `core/workflow/save_service.py:51` (`"agent"` reserved name);
  `guide/__init__.py:40` (`"agent": ["agent"]`) and `:461`.
- **The real cache/resume gate (feature-interactions W1 — correction)**: agent output is NOT
  memoized because `is_side_effecting("agent")` is `True` (`compiler.py:643-668`,
  `_default_cache_for_node_type`) since `node_type != "llm"` — this SAME gate governs resume re-run
  (Task 164). The instrumentation `LLMNode`-only allowlist (`instrumentation.py:300-323`) only gates
  trace-2.1.0 `cache_key`/`cache_source` metadata *fields*, NOT memoization. Both outcomes are
  automatically correct for `agent ≠ llm`, but update these docstrings knowing `compiler.py` is the
  load-bearing gate, not a mere comment.
- **Comments only** (no behavior): `core/exceptions.py:1314`; the `claude-code`/`ClaudeCodeNode`
  prose in `execution/plan.py:985`, `trace_report.py:345-1212`, `workflow_trace.py:1135-1200`,
  `runtime/workflow_executor.py:78`, `core/llm_usage.py:80`.
- Update affected tests (the plan's original list PLUS the five the deep-review found —
  impact-completeness C1/C3/W4/W5): renderer (`test_graph_react_flow_renderer.py`), trace/report
  (`test_trace_report.py`), parser (`test_markdown_parser.py`), `test_unknown_param_validation.py`,
  `test_dry_run.py`, guide, resume-cli, approval-gate (`test_execution/test_gate_prompt.py:46`),
  plan-to-code harness (`test_integration/test_plan_to_code_harness.py`), **`test_cli/test_validate_only.py`**
  (validator error-text + the `make_claude_code_workflow` helper that `test_dry_run.py:11` imports —
  rename the helper), **`test_runtime/test_memoization_integration.py:241-269`** (asserts emitted
  `node_type`/`kind` + passes `node_type_name="ClaudeCodeNode"`), **`test_runtime/test_trace_format_2_1.py:94-236`**
  and **`test_runtime/test_cache_opt_out_compiler.py:73`** (update the dead `"ClaudeCodeNode"`/`"claude-code"`
  strings to `"AgentNode"`/`"agent"` so they exercise the real class, not pass on a dead string).

Gate: `make test` + `make check` green; a `type: agent` + `backend: claude` workflow **validates
and runs** (`uv run pflow ...`). Verify: no shipped code references `claude-code`;
`pflow guide agent` resolves.

## Phase 3 — CodexBackend via `codex exec`

**Scope**: ~medium (new file + tests). **Tier**: **Opus** (real judgment: subprocess orchestration,
JSONL parsing, resume, error mapping). Resume the same implementer (builds directly on the Phase 1
`AgentBackend` protocol) unless the window is degrading — then a fresh Opus launch with this plan +
Phase 1/2 handback.

Implement `CodexBackend(AgentBackend)`:
- **run(prompt, opts)**: build argv `codex exec <prompt> --skip-git-repo-check --json
  --output-last-message <tmpfile>` plus `-m <model>` (omit if unset), `-s <sandbox>` (map
  `full-access`→`danger-full-access`), `-C <cwd>`, `--add-dir` (repeatable), `--output-schema
  <tmp schema.json>` when `output_schema` set, `-c approval_policy="<...>"` for the codex
  `approval_policy` param (default: none passed — `codex exec` is non-interactive/auto by default),
  `--profile`/`-c` for `profile`/`config`. Run via `subprocess.run`/`Popen` (sync — no async
  ceremony). Read final text from the `--output-last-message` file; parse `--json` JSONL for token
  usage + tool/progress events + thread/session id.
- **Token normalization**: map codex `TokenUsageBreakdown`
  (`cached_input_tokens`/`input_tokens`/`output_tokens`/`reasoning_output_tokens`/`total_tokens`)
  onto the normalized `AgentResult.metadata` (cache_read ← cached_input_tokens; carry
  `reasoning_output_tokens` through without breaking the shared contract; `session_id` ← codex
  thread id; `num_turns` ← 1 or the observed turn count; `cost_usd` ← None if codex omits it;
  `input_token_accounting` ← a codex tag). **Pin the exact JSONL event schema by running
  `codex exec --json` once during implementation** (bounded detail, not a design fork).
- **continuation_options(prev, opts)**: return opts that run `codex exec resume <session_id>
  <corrective_prompt>` — codex resume is disk-based, so schema-retry parity with claude holds.
- **resume param**: `resume: <session_id>` → initial call becomes `codex exec resume <id> <prompt>`.
- **Build the resume argv SEPARATELY (verified gotcha)**: `codex exec resume` does NOT accept
  `-s/--sandbox` (it errors); it DOES accept `--json`, `-o`, `--output-schema`, `-m`, `-c`,
  `--skip-git-repo-check`. Pass sandbox on resume via `-c sandbox_mode="<mode>"`, not `-s`. Do not
  reuse the exec argv builder for resume.
- **validate_params**: codex-only params (`approval_policy`, `add_dir`, `profile`, `config`);
  reject claude-only params.
- **translate_error**: `FileNotFoundError` (codex not on PATH) → actionable "codex not found;
  install codex"; auth failure (401 / login error in output) → "run `codex login`"; non-zero exit →
  surface stderr. **Must raise** (batch-retry + exec_fallback contract). **Deterministic classes
  (not-found, auth) must raise a `retriable=False` PflowError** (`core/exceptions.py:48` default is
  `True`; exemplars at :801/:972/:1002/:1075) — otherwise a `backend: codex` batch re-spawns
  `codex exec` `max_retries`× on "codex not found" (feature-interactions W2).

Codex must-holds (feature-interactions S4/S5, review-plan W3):
- **`num_turns` is NEVER `None`** — default to `1` even when JSONL parsing yields nothing;
  `workflow_trace.py:351` counts agent calls purely by `num_turns is not None`, so a parse-miss would
  silently drop the call from agentic accounting.
- **`continuation_options` returns `None` when the first run produced no thread/session id** → the
  retry loop breaks and keeps the prior result (soft-fail DEGRADED), matching claude. Never emit a
  `codex exec resume` with an empty id.
- **Soft-fail returns the `default` action (raw text in `result` + `__warnings__`), never raises** —
  so a malformed-schema item counts as batch success, identical to claude.
- **Dry-run/plan estimator (feature-interactions W3)**: `AgentNode` joins `_LLM_NODE_CLASSES`
  (Phase 2), but codex `cost_usd = None` and the codex model is likely absent from pflow's pricing
  table. Verify the dry-run estimator produces a graceful "unknown"/`$0.00`, not a crash, for an
  unpriced agent node before relying on it.

Tests (follow the shell subprocess pattern, NOT the claude async pattern —
`tests/test_nodes/test_shell/test_posix_timeout.py`): `monkeypatch.setattr(<codex module>.subprocess,
"Popen"/"run", fake)` feeding canned JSONL + last-message file. Assert (a) argv construction
(model/sandbox/cwd/add-dir/schema/resume flags), (b) JSONL→`llm_usage`/`result` mapping,
(c) structured-output success + soft-fail, (d) resume-flag assembly, (e) error translation raises
with actionable text. Add one `@pytest.mark.e2e` real-codex smoke guarded by `shutil.which("codex")`.

Gate: `make test` + `make check` green. **Verify on the real surface** (codex is installed +
ChatGPT-logged-in on this machine): run a real `type: agent` + `backend: codex` workflow via
`uv run pflow ...` — confirm `result`, `llm_usage` (tokens + session_id), structured output, and a
two-run resume (`resume: ${prev.llm_usage.session_id}`) that recalls prior context.

## Phase 4 — Web UI rename (MANDATORY Fable, separate agent — DECISIONS #8)

**Scope**: ~small (4 source edits + fixtures + rebuild). **Tier**: **Fable**, always a separate
`task-phase-implementer`, built with design/UX care; green component tests alone never close it.

Do: the `kind` value changes to `"agent"` at the backend (Phase 2). Update the frontend literals to
match: `web/src/utils/icons.ts:41` (`KIND_ICON` — pick the icon for `agent`), `web/src/utils/
format.ts:137` (`paramLanguage` markdown for `prompt`/`system_prompt`), `format.ts:177`
(`KIND_COLORS` accent), `web/src/types.ts:201` (comment). Update web test fixtures/tests asserting
`"claude-code"` (`web/src/test/fixtures/contracts/run-cycle.json`, `format.test.ts`,
`GateCallout.test.tsx`, `EdgePanel.test.tsx`, `GraphView.test.tsx`). Rebuild the bundle with
**`make ui-build`** (never hand-edit `src/pflow/ui/static/assets/*`).

Gate: `make ui-build` succeeds; `cd web && npm test` green. **Verify via the
`screenshot-pflow-web-ui` skill** — render a graph containing an `agent` node and confirm the card
icon, accent color, category label, and prompt syntax-highlighting are correct for both backends.
Kill stale `pflow ui` servers first (recorded gotcha).

## Phase 5 — Examples, guide, docs migration

**Scope**: ~medium (many files, mostly mechanical + one authored guide page). **Tier**: **Opus**
(the `guide/nodes/agent.md` rewrite documents both backends — real authoring; mechanical
find-replace rides along). Could route pure example find-replace to Sonnet if split out, but bundle
for continuity.

Do:
- **Examples** → `type: claude-code` becomes `type: agent` + `backend: claude`; rename dirs/files
  `examples/nodes/claude-code/**` → `examples/nodes/agent/**`; migrate the Task 163 harness
  (`examples/agent-orchestration/**`), READMEs, `examples/CLAUDE.md`, `examples/README.md`.
- **Guide** (shipped via `pflow guide`): rename `src/pflow/guide/nodes/claude-code.md`→`agent.md`
  (filename drives the topic name) and **rewrite it to document the unified node + both backends +
  the flat backend-specific params + resume**; update `guide/entry.md:1,43`, `core.md:392`,
  `features/approval.md:58,73,88`, `features/batch.md:208`, `features/patterns.md:5`,
  `features/resume.md:3,72`.
- **MCP-server instructions**: `mcp_server/resources/instruction_resources.py:216` and the two
  `instructions/*.md` (:631,:633).
- **User docs (Mintlify)**: rename `docs/reference/nodes/claude-code.mdx`→`agent.mdx` (document
  both backends), update `docs/reference/nodes/index.mdx`, `docs/docs.json` nav, and the scattered
  refs (`cli/index.mdx`, `cli/skill.mdx`, `how-it-works/*.mdx`, `integrations/overview.mdx`,
  `guides/publishing-skills.mdx`, `roadmap.mdx`, `changelog.mdx`, `docs/CLAUDE.md`).
- **Root `CLAUDE.md`** node roster + the directory `CLAUDE.md` files that name the node/class
  (review-plan S5): `guide/CLAUDE.md`, `core/workflow/CLAUDE.md`, `ui/CLAUDE.md`, `runtime/CLAUDE.md`,
  `nodes/CLAUDE.md` (references `ClaudeCodeNode`).
- **`architecture/` docs (impact-completeness W8)** — not in the original plan: `architecture/CLAUDE.md`,
  `architecture/architecture.md`, `architecture/overview.md`, `architecture/features/simple-nodes.md`,
  `architecture/reference/template-variables.md`, and `architecture/core-node-packages/claude-nodes.md`
  (describes the package path `nodes/claude/`→`nodes/agent/`). Leave `architecture/historical/*` as-is.
- **`.claude/agents/review-feature-interactions.md` (impact-completeness W6)** — the backtick
  `` `ClaudeCodeNode` `` (:231) breaks `test_docs/test_agent_references.py` (its symbol check requires
  every CamelCase token to exist in `src/`/`tests/`; after clean-slate it exists nowhere). Update the
  reference (and the prose `claude-code` at :212). This file is outside the plan's original scope.
- **Fold `nodes/claude/AUTHENTICATION.md` content into `agent.md`** before deleting the package
  (review-plan S6) — the subscription-vs-`use_api_key` guidance must not be silently dropped.
- Leave `.taskmaster/tasks/**` historical files as-is (informational); optionally re-scope Task 99
  ("Expose pflow Tools to Claude Code Node") to `agent`.

Gate: `make test` + `make check` green — including `tests/test_docs/test_guide_example_validation.py`
(migrated examples must validate under the new syntax). Verify `pflow guide agent` renders the new
content; a migrated harness example runs.

---

## Completion (task-orchestrator, after all phases FULLY happy)

- **`make test-all-local`** green (adds e2e).
- **Code-mode `/deep-review`** on the full branch diff (this touches the node contract + structured
  output + token accounting — apply fixes, log every finding's disposition).
- End-to-end reality check both backends: `uv run pflow` an `agent`+`claude` workflow and an
  `agent`+`codex` workflow (incl. structured output + cross-run resume). Confirm clean slate with the
  **broadened grep** (impact-completeness W7 — the hyphen-only form missed `claude_code.` diagnostic
  kinds, the `_claude_code_param_error` helper, and `ClaudeCodeNode` in comments):
  `grep -rnE "claude[-_]code|ClaudeCodeNode" src tests docs examples architecture .claude/agents src/pflow/guide CLAUDE.md`
  — expect zero hits except the intentional `@anthropic-ai/claude-code` npm package name in
  `ClaudeBackend`.
- `/create-task-review`, then `/create-pr`.

## Notes / edge cases carried from investigation

- **No engine/trace-logic changes** — only comments and the node's own output contract; the trace
  format is untouched (agentic markers ride on `num_turns`/`session_id` field presence). So the
  plan-author's mandatory engine/trace deep-review trigger does **not** fire; Phase 1's targeted
  review is the author's judgment call (recommended — structured-output/token parity is subtle).
- **codex exec approval**: `codex exec` is non-interactive by default; only pass `-c
  approval_policy=...` when the user sets the `approval_policy` param. Confirm the exact override
  flag/config path when pinning the JSONL schema.
- **codex sandbox default**: if `sandbox` unset, default to `workspace-write` (matches agentic
  coding intent + claude's autonomous posture); document it.
- **Backend availability at parse time**: the static validator can't know if `codex` is installed;
  installation/auth errors surface at run time via `translate_error`. Validation only checks
  param/enum correctness.
- **Batch-parallel abort + codex subprocess (feature-interactions S6, low priority)**: on
  batch-parallel fail-fast, `future.cancel()` cannot interrupt an already-running `codex exec`
  subprocess — it runs to its own timeout, risking a briefly orphaned process. Ensure `CodexBackend`
  runs the subprocess with a timeout and, ideally, terminates the child on cancellation. A targeted
  `review-concurrency-safety` pass on the codex subprocess lifecycle is worthwhile after Phase 3.

---

## Appendix — Verified `codex` CLI reference (baked in from the investigation spike)

Empirically confirmed against `codex-cli 0.144.1` on this machine (do not re-derive):

**`codex exec` flags** (from `codex exec --help`):
- `[PROMPT]` positional (or stdin, or `-`)
- `-m, --model <MODEL>` — omit to inherit codex's configured default
- `-s, --sandbox <read-only|workspace-write|danger-full-access>` — agent `full-access` → CLI
  `danger-full-access`
- `-C, --cd <DIR>` — working root; `--add-dir <DIR>` — extra writable dirs (repeatable)
- `--output-schema <FILE>` — JSON Schema file for structured final response
- `-o, --output-last-message <FILE>` — write the final agent message to a file (robust capture)
- `--json` — emit events as JSONL on stdout
- `--skip-git-repo-check` — allow running outside a git repo
- `-c, --config <key=value>` — TOML config overrides (e.g. `-c approval_policy="never"`);
  `-p, --profile <NAME>` — layer a config profile
- **Resume**: `codex exec resume [SESSION_ID] [PROMPT]` (or `--last`) — **disk-based**, works across
  separate processes (reads `~/.codex/sessions/**/rollout-*.jsonl`).

**Auth (verified)**: `codex exec` runs on the user's **ChatGPT subscription** via existing
`codex login` — `~/.codex/auth.json` holds OAuth `tokens.access_token`, **no `OPENAI_API_KEY`
required**. Confirmed: `codex exec --sandbox read-only "Reply with ONLY the word BANANA."` → `BANANA`,
exit 0. If not logged in, `translate_error` should point at `codex login`.

**Token usage shape (verified via the SDK spike, same underlying binary)** —
`TokenUsageBreakdown(cached_input_tokens, input_tokens, output_tokens, reasoning_output_tokens,
total_tokens)`, reported as both `last` (this turn) and `total` (cumulative). Map: `cache_read` ←
`cached_input_tokens`; carry `reasoning_output_tokens` through; codex does not surface a per-run USD
cost → `cost_usd = None`.

**Event shape (VERIFIED — captured from `codex exec --json`, corrects an earlier draft that
described the MCP `codex/event` stream)**: the CLI emits a typed JSONL stream, NOT `codex/event`
notifications. Exact events:
```
{"type":"thread.started","thread_id":"<uuid>"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"<final text>"}}
{"type":"turn.completed","usage":{"input_tokens":N,"cached_input_tokens":N,"output_tokens":N,"reasoning_output_tokens":N}}
```
So: `session_id` ← `thread.started.thread_id`; final text ← the `-o/--output-last-message` file
(robust — tool runs emit multiple `item.completed`); usage ← `turn.completed.usage` (NOTE: **no
`total_tokens`, no cost** in the CLI stream — compute `total = input + output`); `num_turns` ← count
of `turn.completed` events (default 1). With `--output-schema`, `agent_message.text` and the `-o`
file are the JSON string → `json.loads` the `-o` file. Full worked token mapping + the tool-item
caveat are in `../starting-context/braindump.md` §1–§2.

**Why CLI not SDK (one-liner; full rationale in the spec)**: `openai-codex==0.1.0b2` bundles a stale
`codex 0.132.0` that 401s on subscription turns and can't parse a current `config.toml`; it only
works by overriding `codex_bin` to the system binary — an unsupported client/engine version combo.
The `AgentBackend` seam lets a `CodexSdkBackend` replace `CodexBackend` later with no `type: agent`
change once the SDK's bundled binary is current.

**Additional facts VERIFIED in prework round 2 (all confirmed by running codex):**
- **Tool/command events**: a run that executes a command emits `item.started` then
  `{"type":"item.completed","item":{"type":"command_execution","command":"/bin/zsh -lc '…'","aggregated_output":"…","exit_code":0,"status":"completed"}}`.
  Map these to `_agent_tools` (name ← `command`, summary ← `aggregated_output`) if you want parity;
  filter `item.type == "agent_message"` out. The final `agent_message` is still the last item — but
  use the `-o` file for final text (multiple items exist).
- **`--output-schema` REQUIRES a top-level `type: object`** — a non-object root fails the turn with
  HTTP 400 `invalid_json_schema` ("schema must be of type object, got array"). **This confirms the
  shared top-level-object validation rule is correct for BOTH backends** (resolves the spec's open
  item + validation-consistency W1 — no backend-scoping needed).
- **`codex exec resume` has a DIFFERENT, narrower flag set than `codex exec`** — it accepts
  `--json`, `-o/--output-last-message`, `--output-schema`, `-m`, `-c`, `--skip-git-repo-check`,
  `--last`, but **NOT `-s/--sandbox`** (passing `-s` errors `unexpected argument '-s'`). Set sandbox on
  resume via `-c sandbox_mode="…"` or rely on the persisted session. Build the resume argv
  separately — do NOT reuse the exec argv builder verbatim.
- **CLI resume verified end-to-end**: `codex exec resume <id>` echoes the SAME `thread_id`, recalls
  prior context (confirmed a secret word across two separate processes), and its `turn.completed.usage`
  is that resumed turn's usage (input grows as context accumulates — sum across turns for totals).
