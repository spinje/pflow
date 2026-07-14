# Task 177 Review: Unified `agent` Node (claude | codex)

## Metadata
- **Implemented:** 2026-07-13 → 2026-07-14, branch `feat/unified-agent-node-claude-codex`.
- **Commits:** `267c8e28` (P1 seam+ClaudeBackend) · `b0e03a55` (P2 wiring) · `ef8f6414` (P3 CodexBackend) · `a20b27a1` (P4 web UI) · `fe08e426` (P5 docs) · `c7579eed` (P6 auth guard) · `361d1de4` (live-verify + Codex pricing) · `d524c53d` (deep-review 1–8) · `1bbcdbd8` (live-verify round 2: strict schema + de-opaque failures + validate==run).
- **Status:** implemented, live-verified against real Claude (subscription) + Codex (ChatGPT) CLIs, `make check` green outside the macOS sandbox. Not yet merged. No external users (per root CLAUDE.md) — clean-slate rename shipped, no `claude-code` alias.
- **Journey lives in** `implementation/progress-log.md` (503 lines, chronological). This review is the distilled forward-reference.

## Read First — the load-bearing block

**What exists now:** one registered node `agent` (`src/pflow/nodes/agent/`) that picks a backend via the **required** `backend: claude|codex` param. `claude-code` no longer resolves. Claude = `claude-agent-sdk`; Codex = `codex exec` CLI subprocess. Everything shared (lifecycle, validation, schema coerce/retry, soft-fail, `llm_usage`) lives in `AgentNode`; backend-specific transport lives behind the `AgentBackend` protocol.

**Read these first (path → symbol):**
- `src/pflow/nodes/agent/backend.py` → `AgentBackend` protocol + `AgentResult` dataclass. **This is the whole contract.** `AgentResult.metadata` is the normalization boundary.
- `src/pflow/nodes/agent/agent_node.py` → `AgentNode.prep/exec/post`, `_coerce_structured_output` (JSON-Schema oracle), `_store_results`/`_store_schema_result` (soft-fail).
- `src/pflow/nodes/agent/schema_validation.py` → `SHARED_PARAMS`/`CLAUDE_PARAMS`/`CODEX_PARAMS` frozensets + all pure `validate_*` shape predicates. **Single source of truth** shared by static validator AND runtime.
- `src/pflow/nodes/agent/codex_backend.py` → `CodexBackend`, `_strictify_schema`, `_classify_login_status`/`_require_account_auth`, `_build_argv`, `_parse_events`, process-tree kill helpers.
- `src/pflow/nodes/agent/claude_backend.py` → `ClaudeBackend` (moved-verbatim claude-code logic + the SDK import/version guard).

**Invariants that must NOT break:**
1. **Backends normalize; `AgentNode` never parses backend token shapes.** Each backend returns `AgentResult.metadata` with the inclusive `llm_usage` fields already computed. Break this → token accounting / cost / cache math corrupts silently.
2. **Always emit `num_turns` + `session_id` (+ `retries` when they happen) in `llm_usage`.** Trace/report identify agentic calls by *field presence*, not node-type string (`workflow_trace.py:351`, `trace_report.py`). `num_turns` is NEVER `None` (Codex counts `turn.completed`, defaults to 1). Break this → agent calls silently vanish from agentic accounting.
3. **validate == run.** Every agent param-shape rule lives as a pure function in `schema_validation.py` and is called by BOTH `WorkflowValidator._validate_agent_param_shapes` and the runtime (`AgentNode.prep` / `backend.validate_params`). Adding a runtime check without routing it through the shared module reintroduces `--validate-only` false-greens.
4. **Codex safe mode (`use_api_key: false`) is a fail-closed spend boundary.** Before *every* possible model call (incl. schema-correction retries): copy `os.environ` (NEVER mutate it), scrub `OPENAI_API_KEY`/`CODEX_API_KEY`, run `codex login status` with that same child env, accept only ChatGPT/access-token account auth, reject everything else non-retriably. Raw status text / masked keys must never reach logs or exceptions. Break this → billing surprise or credential leak.
5. **`use_api_key` is a shared strict bool, default `false`.** Accepted forms are exact (see `validate_use_api_key`); no Python truthiness. Claude false-mode blanks `ANTHROPIC_API_KEY` in child-only SDK options.

## What Was Built (actual vs. planned)

Followed the 6-phase plan faithfully; the durable divergences are the ones found by **live** verification that the mocked suite could not catch:

- **`_strictify_schema()` (commit `1bbcdbd8`, NOT in the plan).** OpenAI strict `response_format` — which Codex enforces server-side — rejects any object schema missing `additionalProperties: false` or whose `required` omits a property. A schema that worked on Claude 400'd on Codex, breaking the *shared* `output_schema` contract (and the shipped guide example). Fix normalizes a **deep copy** at the `--output-schema` write boundary, recursing through `properties`/`items`/`$defs`/combinators. Uses **non-nullable** `required` so the parsed result still validates against the caller's *original* schema in `AgentNode.post()`. **The caller's dict is never mutated.**
- **`inputs` added to `SHARED_PARAMS` (Phase 2, plan omission).** The plan's "exhaustive" param inventory missed it; agent-orchestration workflows pass node-level `inputs` for file-backed prompt templates. Absent from the allowlist it produced 29 false cross-backend validation errors. It is load-bearing data-wiring metadata that Codex accepts-but-ignores at argv build.
- **Phase 6 was added after Phase 5** as a security follow-up: the shared `use_api_key` + Codex fail-closed account-auth guard. Superseded the original "`use_api_key` is Claude-only / Codex has no key param" contract everywhere in specs + docs.
- **Param-shape validators relocated (commit `1bbcdbd8`).** Originally the plan left sandbox/`schema_retries` shape checks in the backends; live testing showed `--validate-only` false-greened runtime-failing configs. They moved into `schema_validation.py`; the thin `_validate_*` wrapper methods were **deleted** (not kept as indirection).
- **Process-tree lifecycle (deep-review 5–6).** `subprocess.run(timeout=)` only kills the direct CLI; replaced with an owned process group + POSIX group-kill / Windows kill-on-close Job Object, plus batch-scoped cancellation via a shared event threaded through nested workflows into Codex.
- **Cost provenance split (deep-review).** Canonical `cost_usd` stays `None`/unavailable for agents; the LiteLLM comparison estimate is a separate `api_equivalent_cost_usd`. Codex is priced only when the workflow explicitly declares `model` (CLI-default model is unknown until runtime → graceful "unknown", never a crash).
- **`_readable_failure_detail()` (commit `1bbcdbd8`).** Codex failures were opaque ("N failure event(s)"). Now surfaces `code: message` from **structured** provider-error payloads only; free text / stdout / stderr / tool `aggregated_output` are never surfaced (keeps the secret-safe guard).

## Patterns & Anti-Patterns

- **Pattern — "two adapters = one real seam."** The `AgentBackend` protocol is deep: a small interface (`run`/`continuation_options`/`validate_params`/`translate_error`/`build_warning_context`) hides two very different transports (SDK message loop vs CLI subprocess+JSONL). Reuse this shape for a future `CodexSdkBackend` — no `type: agent` change needed.
- **Pattern — treat a CLI as a protocol adapter, not a text subprocess.** Codex channels are kept separate: typed JSONL = events/usage/thread-id; `--output-last-message` file = the *only* final-answer source; schema JSON = input artifact; stderr+exit+failure-events = diagnostics. Do not derive the final answer from the last `agent_message` JSONL event — tool runs emit multiple items.
- **Pattern — single source of truth for param sets.** `SHARED ∪ backend_PARAMS` computed from frozensets; reject iff outside the union. Never hand-maintain a duplicate list. `sandbox ∈ CLAUDE_PARAMS ∩ CODEX_PARAMS` (valid for both, different shapes, never cross-rejected).
- **Anti-pattern — a single argv builder for exec + resume.** `codex exec resume` has a *narrower* flag set (rejects `-s/--sandbox`; set sandbox via `-c sandbox_mode=`). `--profile` is a parent `exec` option (`codex exec --profile NAME resume …`, NOT `resume --profile`). Build resume argv separately.
- **Anti-pattern — Python `str()` as a TOML serializer.** `-c key=value` values are TOML. Use `_toml_value` (strings/bools/finite-numbers/arrays/inline-tables; rejects unsupported like `None`).
- **Anti-pattern — the `openai-codex` SDK.** Bundles a stale binary that 401s on subscription turns and can't parse a current `config.toml`. CLI is the verified v1 path; the SDK is a *later* swap behind the seam.

## Gotchas & Non-Obvious Coupling

- **`AgentNode` docstring `- Params:` MUST list the union of all params incl. `backend`.** The static unknown-param check (`validator.py` step 8) is **backend-blind** — it derives its allowlist solely from the docstring via `metadata_extractor`; backends aren't `Node` subclasses so their params are invisible. Drop a param from the docstring → every `agent` workflow (or any codex-only-param workflow) is falsely rejected.
- **DEVNULL stdin is functional, not hygiene.** Without it the real `codex exec` announces "Reading additional input from stdin…" and can consume pflow's own input pipe as a `<stdin>` prompt block.
- **`system_prompt` maps to Codex `-c developer_instructions=…`** (documented config key), on both initial and resume — not prompt concatenation, not a silent drop.
- **`reasoning_output_tokens` is Codex-only and must stay absent for Claude.** The retry aggregator sums it *only when present*; unconditionally seeding `0` leaks a Codex field into Claude usage (a real bug caught in Phase 3 test-reflection).
- **`exec_fallback` must RAISE** (batch retry is exception-driven via `raise` vs `return`, `batch_executor.py`). But deterministic Codex failures (binary-not-found, auth) raise `PflowError(retriable=False)` — else a batch re-spawns `codex exec` `max_retries`× on "codex not found".
- **`translate_error` returns an existing `CodexNonRetriableError` unchanged, first** — preflight errors must reach `Node._exec()` as non-retriable and produce zero model subprocesses.
- **Continuation-on-`None`:** when `continuation_options` returns `None` (no session/thread id), the retry loop **breaks and keeps the prior result** → soft-fail DEGRADED. It does NOT do a fresh-prompt retry. Codex returns `None` when its first run produced no thread id.
- **Package imports SDK-free.** `import pflow.nodes.agent` pulls neither `claude_agent_sdk` nor the codex CLI — the SDK import lives inside `ClaudeBackend`, codex import is lazy in `AgentNode._load_backend`. The claude test suite still relies on `conftest.install()` seeding the fake `claude_agent_sdk` into `sys.modules` before `ClaudeBackend`'s module-level import (tests/CLAUDE.md pitfall #17).
- **Compiler flattens fenced-prompt line metadata to `_prompt_source_line`** — a sidecar key the allowlist would reject. Guarded by `is_compiler_source_line_sidecar` in both backends (found by live parser→compiler→prep testing, invisible to mocked backend tests).

## Integration Points

**Rekeyed `claude-code`/`ClaudeCodeNode` → `agent`/`AgentNode` (blast radius):**
- `core/workflow/validator.py:816` — dispatch to `_validate_agent_params`; `:935` `_validate_agent_param_shapes` (runs shared predicates before the `output_schema is None` early-return; defers templated values).
- `core/workflow/graph/renderers/react_flow.py:282` — `kind == "agent"` → structured output maps to the `result` port.
- `execution/plan.py:71` `_LLM_NODE_CLASSES = {"LLMNode","AgentNode"}` · `execution/formatters/plan_formatter.py:374` · `core/node_type_display.py:10,41` — dry-run/plan cost+duration classification.
- `guide/__init__.py:40` topic map · `core/workflow/save_service.py:51` reserved name.
- Web UI: `web/src/utils/icons.ts` (`iconFor` reads the `backend` param → claude/codex/neutral icons), `format.ts` (prompt/system_prompt highlighting + accent). Bundle rebuilt via `make ui-build`; contract fixture `web/src/test/fixtures/contracts/run-cycle.json` regenerated via `tests.fixtures.react_flow_contracts._generate` (never hand-edit).

**Contracts:** `llm_usage` gains conditional `reasoning_output_tokens` + `api_equivalent_cost_usd` (agents only). Registry name `agent` auto-derived from the class name (no explicit `name` attr). Agent output is **not** memoized (`is_side_effecting("agent") == True` because `node_type != "llm"` — `compiler.py`), which also correctly governs resume re-run.

## Tests That Matter

Run `tests/test_nodes/test_agent/` when touching anything here. The ones that guard real regressions:
- `test_codex_backend.py::TestStrictifySchema` — Bug 1 regression (OpenAI strict schema). Mutation-verified: without `_strictify_schema` the live Codex call 400s.
- `test_codex_backend.py::TestReadableFailureDetail` — pins that structured provider errors ARE surfaced and free-text/tool output is NOT (secret-safe).
- `test_codex_backend.py::TestCodexAccountAuthGuard` — the Phase 6 fail-closed matrix (API-key/personal-token/Bedrock/logged-out/unknown/conflicting all → 0 exec calls, non-retriable, no masked-secret leak; opt-in → 1 exec, 0 status).
- `test_codex_backend.py::TestCodexProcessLifecycle` — parent-exits-first pipe-holder cleanup (POSIX + Windows), batch cancellation.
- `test_codex_backend.py::TestCodexArgvAndParsing` — argv shapes, **separate resume builder**, JSONL→`llm_usage`/`result`, tool capture. Key style: the fake subprocess writes the *real* `--output-last-message` temp file, so it crosses the filesystem/argv boundary parser-only tests miss.
- `test_cli/test_validate_only.py` — validate==run parity (claude string sandbox, codex dict sandbox, `schema_retries: 99` rejected with the exact runtime message).
- `test_agent_node.py` — Claude parity, schema coerce/soft-fail, shared `use_api_key` on both backends.
- `test_schema_validation.py` — strict-bool matrix (single owner) + top-level-object rule.
- `test_agent/test_compiled_workflow.py` — full parser→compiler→`prep()` path (the `_prompt_source_line` sidecar).

**Live smoke** (`@pytest.mark.paid`, `shutil.which("codex")`-guarded): excluded by every Makefile target's marker expr; requires explicit owner authorization (account credits/overage may apply). Mocked tests are transport-independent — they cannot catch OpenAI's real strict-schema rules or account-auth behavior. **Re-verify schema + cross-process resume on a live host after any Codex-backend change.**

## Breaking Changes & Extension Points

- **Breaking (intentional, no external users):** `type: claude-code` is gone — workflows must use `type: agent` + `backend: claude`. Existing Codex API-key workflows now fail before the model call unless they add `use_api_key: true` (Phase 6 compatibility change, documented in guide/reference/changelog).
- **Deferred:** Finding 4 — agent param validators raise vanilla `ValueError`/`TypeError` instead of `PflowError` subclasses (inherited verbatim from `claude-code`; the plan preserved Claude behavior identically). Tracked as **GitHub issue #592**, not fixed this session.
- **Extension points:** `CodexSdkBackend` slots behind `AgentBackend` when the SDK's bundled binary matures. `approval_policy` is a strict v1 string enum (`untrusted`/`on-request`/`never`) — Codex's granular table form is future API design. Re-scope Task 99 ("Expose pflow Tools to the Agent Node") to `agent`.

---
*Distilled from the implementation context of Task 177. The chronological journey — dead ends, live-CLI probes, per-phase test counts — lives in `implementation/progress-log.md`.*
