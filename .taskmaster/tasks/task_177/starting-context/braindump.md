# Braindump — Task 177 (unified `agent` node) implementation notes

> Complementary to `task-177.md` (what/why) and `implementation-plan.md` (how). This file is ONLY
> the tacit stuff not written down elsewhere — read it before you start, especially §1 (it corrects
> an error in the plan's appendix).

## 1. CRITICAL CORRECTION — the real `codex exec --json` event schema

**The plan's Appendix ("Event shape (observed)") is WRONG for the CLI.** It describes the MCP
server's `codex/event` / `task_complete` / `last_agent_message` notification stream — that's what
`mcp-codex-codex` (the MCP node) emits, a totally different transport. **`codex exec --json` emits a
clean typed event stream instead.** I captured it empirically just now (codex-cli 0.144.1). Do NOT
build the parser from the MCP probe output or the SDK's `TurnResult` shape — use THIS:

```
{"type":"thread.started","thread_id":"019f5bba-9c03-7220-88ac-4c8cc0e63e1d"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hi"}}
{"type":"turn.completed","usage":{"input_tokens":14653,"cached_input_tokens":9984,"output_tokens":5,"reasoning_output_tokens":0}}
```

Parser rules that follow from this:
- **`session_id`/thread id** ← `thread.started.thread_id` (NOT `_meta.threadId`, that's the MCP path).
- **Final text** ← use the **`-o/--output-last-message` file**, not the JSONL. It's the robust
  source. Reason: a run that uses tools emits MULTIPLE `item.completed` events (command executions,
  reasoning, etc.) and you'd have to find the last `item.type == "agent_message"`. The `-o` file
  gives you exactly the final message. Use JSONL only for usage + thread id + (optionally) tool
  events.
- **Structured output**: with `--output-schema`, the final message IS the JSON string. Verified:
  `agent_message.text` = `"{\"word\":\"banana\",\"count\":3}"` and the `-o` file = `{"word":"banana","count":3}`.
  So: when `output_schema` set, read the `-o` file and `json.loads` it. Then the existing
  `_coerce_structured_output` + soft-fail path in `AgentNode` takes over unchanged.
- **`num_turns`** ← count `turn.completed` events (one per turn; a single `codex exec` = 1, a resume
  adds turns). Default to `1`. It is NEVER in a single field — you compute it. (This is why the plan
  insists num_turns must never be None.)
- **Tool/command items** (captured in prework round 2): a command run emits `item.started` then
  `{"type":"item.completed","item":{"type":"command_execution","command":"/bin/zsh -lc 'echo hello'","aggregated_output":"hello\n","exit_code":0,"status":"completed"}}`.
  For `_agent_tools` parity: name ← `command`, summary ← `aggregated_output` (truncate ≤500 like
  claude). Filter these OUT when finding the final message (that's why `-o` is the robust final-text
  source — a tool run has agent_message AND command_execution items).
- **`--output-schema` requires top-level `type: object`** — non-object roots fail the turn with a 400
  `invalid_json_schema` (a `turn.failed` + `error` event, empty `-o` file). Same constraint as claude,
  so the shared validation rule is right. Your parser must handle `turn.failed`/`error` events (map to
  a raised error → `translate_error`).

## 2. Token mapping — worked example (the CLI usage differs from the SDK)

`turn.completed.usage` = `{input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens}`.
**There is NO `total_tokens` and NO cost in the CLI stream** (the SDK's `TokenUsageBreakdown` had
`total_tokens`; the CLI omits it). From the real numbers above:

- `input_tokens: 14653` is **inclusive** of cache (matches pflow's `input_tokens` contract directly).
- `cached_input_tokens: 9984` → pflow `cache_read_input_tokens`.
- `uncached_input_tokens` = 14653 − 9984 = **4669** (compute it).
- `output_tokens: 5` → `output_tokens`.
- `total_tokens` = input + output = **14658** (compute it; codex won't give it).
- `cache_creation_input_tokens` → `0` / omit (codex has no prompt-cache-write concept exposed here).
- `cost_usd` → **None** (codex exposes no per-run USD).
- `reasoning_output_tokens: 0` → codex-specific. **UNCLEAR where this belongs** in pflow's
  `llm_usage`; the plan says "carry through." Simplest: add it as an extra `reasoning_output_tokens`
  key and DON'T fold it into `output_tokens` (keep `output_tokens` = the visible completion tokens so
  cost math elsewhere isn't distorted). Confirm no `llm_usage` consumer chokes on an unknown extra key
  (it shouldn't — `_store_results` just dumps the dict).
- On **resume/retry** there are multiple `turn.completed` events → aggregate usage across them (sum),
  the same way claude's retry loop aggregates via `aggregate_llm_usage_with_retries`.

## 3. Dev-environment realities (this machine, right now)

- **codex is installed (`/opt/homebrew/bin/codex`, v0.144.1) and logged in via ChatGPT subscription**
  (`~/.codex/auth.json`, no API key). So you can run **real** `agent`+`codex` e2e immediately — no
  setup. Phase 3's "verify on the real surface" is genuinely doable here.
- **Cost/latency awareness**: every codex turn burns ~15k input tokens (mostly cached) even for
  "say hi" — it loads its own system context. Keep test prompts tiny. And **`--output-schema` runs
  are SLOW** — one took >90s wall-clock; a naive 30s test timeout WILL flake. Set generous timeouts in
  e2e (150s+) and make the node's default `timeout` comfortable.
- **codex is non-interactive by default**: `codex exec -s read-only "..."` ran to completion with no
  approval prompt and no `approval_policy` flag. Confirms the plan's "autonomous by default" — you do
  NOT need to pass anything for it not to hang. Only pass `-c approval_policy=...` if the user sets it.
- Ephemeral spike artifacts (will vanish — I baked their content into §1/§2 above): the captured JSONL
  and a working `codex-resume-test.pflow.md` were in the session scratchpad. There's also a throwaway
  venv with `openai-codex==0.1.0b2` — ignore it, we're not using the SDK.

## 4. Landmines (things that will bite you)

- **The MCP node (`mcp-codex-codex`) is a RED HERRING.** Earlier in this project's history we tried
  codex via MCP; it's still installable. Its resume is in-memory/process-local (fails across runs) and
  its event stream is `codex/event` notifications that spam pydantic validation errors. NONE of that is
  relevant to `codex exec`. If you find yourself reading MCP `codex/event` output, stop — wrong path.
- **Do NOT use the `openai-codex` SDK** (the user and I settled this hard). Concretely: it bundles a
  stale `codex 0.132.0` that (a) can't parse a current `config.toml` and (b) 401s on subscription
  turns. It only works if you override `codex_bin` to the system 0.144.1 — an unsupported
  client/engine version mismatch. The whole point of the `AgentBackend` seam is that we can swap to a
  `CodexSdkBackend` LATER without touching `type: agent`. Don't jump the gun.
- **`sys.modules` stub timing (pitfall #17)**: the claude tests only work because
  `conftest.py::install()` puts the fake `claude_agent_sdk` into `sys.modules` BEFORE the node's
  module-level `from claude_agent_sdk import ...` runs. When you move that import into
  `claude_backend.py`, the stub must still land first — verify the conftest import order after the
  move, or the whole `test_agent/` suite explodes with import errors.
- **`sandbox` is BACKEND-SHAPED, do NOT unify it (caught late; spec+plan were wrong at first).** The
  current claude-code `sandbox` is a **dict** (`enabled`/`network`/`excludedCommands`/… — SDK
  `SandboxSettings`), verified at `claude_code.py:204-209` + `_validate_sandbox:540-577` and confirmed
  against the Claude Agent SDK docs (`ClaudeAgentOptions.sandbox: SandboxSettings | None`). It has NO
  `read-only`/`workspace-write` string modes — those are ONLY codex. So: `ClaudeBackend` keeps
  `sandbox` as a passthrough dict EXACTLY as today (changing it to a string breaks every existing
  claude workflow); `CodexBackend` takes `sandbox` as a string mode → `-s`. `sandbox` lives in both
  backends' param sets, validated per-backend. The spec's "identical sandbox vocabulary" line and the
  plan's "shared string enum" were both wrong and have been corrected — but if you see any stale
  "shared sandbox" phrasing, trust THIS.
- **`codex exec resume` ≠ `codex exec` flags (verified, would-be-bug).** Resume rejects `-s/--sandbox`
  (`unexpected argument '-s'`). It DOES take `--json`, `-o`, `--output-schema`, `-m`, `-c`,
  `--skip-git-repo-check`, `--last`. So build the resume argv separately; set sandbox on resume via
  `-c sandbox_mode="…"`. If you factor a single argv builder for both exec and resume, this will bite.
- **Broadened grep early, not just at completion**: run
  `grep -rnE "claude[-_]code|ClaudeCodeNode" src tests docs examples architecture .claude/agents src/pflow/guide CLAUDE.md`
  after Phase 1 already, and re-run per phase. The hyphen-only grep hides `claude_code.` diagnostic
  kinds and `ClaudeCodeNode` class refs — the deep-review found five test files that way.

## 5. User's mental model & priorities (how to work with them)

- **The user is evidence-first and will challenge you to verify, not assert.** They corrected me
  TWICE from a confident-but-wrong claim: "are you sure codex doesn't have an SDK?" (it does) and "are
  you sure there's no way to make the SDK use subscription?" (there is — via `codex_bin` override).
  Both times, running the actual thing beat my prior. **Lesson for you: when you hit a codex behavior
  question, run codex and observe — don't reason from memory or docs.** The docs for `openai-codex`
  were notably thin; the installed package/CLI was ground truth.
- Their phrasing: they wanted "an **Agent** node ... with an agent parameter ... that can be either
  claude or codex" and "clean slate, no alias." They said use the CLI "**if this is the facts**" —
  i.e. the decision is contingent on the verification holding, not a preference. If you discover
  something that breaks the CLI premise, that's an escalation, not a quiet pivot.
- They care about the reasoning being exposed and reversible (this is a CLAUDE.md manifesto shop). The
  `AgentBackend` seam existing at all is the user's kind of move: make the SDK-vs-CLI call reversible
  rather than permanent.

## 6. Unexplored / might-matter (we did NOT nail these down)

- **RESOLVED (was unexplored) — codex tool-item shape**: captured in prework round 2 — it's
  `item.completed` with `item.type == "command_execution"` (see §1). You can now populate `_agent_tools`
  or skip it (guarded by `if tool_uses:`); decide explicitly.
- **RESOLVED — object-schema constraint**: codex requires top-level `type: object` (400 otherwise).
  Shared validation rule confirmed correct.
- **MIGHT MATTER — Windows.** codex-backend is a subprocess; ADR-0013 governs shell semantics and the
  blocking `tests-windows` CI job. Is `codex` even available/tested on Windows runners? The e2e smoke is
  `shutil.which("codex")`-guarded (good), but check the subprocess argv/quoting is Windows-safe.
- **CONSIDER — codex model name in the pricing table** (dry-run cost). The default codex model
  (`gpt-5.x-codex`) almost certainly isn't in pflow's pricing map; the plan flags verifying the
  estimator degrades gracefully. Related: with `model` omitted we don't even KNOW the model name until
  runtime (codex picks its config default), so dry-run can't price it at all — make sure that's a
  graceful "unknown," not a crash.
- **CONSIDER — where `reasoning_output_tokens` lives** (see §2). Genuinely undecided.
- **CONSIDER — temp file lifecycle**: the `-o` last-message file and the `--output-schema` temp file
  need creating/cleaning per run (use `tempfile`, clean in `finally`). Concurrency (batch) means unique
  temp paths per invocation — don't reuse a fixed path.

## 7. What I'd tell myself starting Phase 1

- **Get claude parity to 100% green before you touch codex.** Phases 1+2 are a pure refactor with a
  hard oracle: every existing claude test must pass unchanged (modulo rename). If they're green, the
  seam is correct. Only then is codex (Phase 3) a clean "implement one Protocol" job.
- **The seam inventory is already done and accurate** — the plan's "Target architecture" came from a
  method-by-method read of `claude_code.py` with line ranges. Trust it as your map, but the deep-review
  verified the line refs so they're reliable.
- **`AgentResult.metadata` is the contract.** Everything downstream (`llm_usage`, trace markers,
  soft-fail) reads normalized fields from it. If claude parity breaks after the split, the bug is almost
  certainly in how `ClaudeBackend` populates `metadata` vs how `_store_results` used to read SDK objects
  directly. Diff those two carefully.

## Relevant files & references (not already linked in the plan)

- Empirically-captured schemas: in §1/§2 above (the scratchpad JSONL is ephemeral — the content here is
  the record).
- `~/.codex/sessions/**/rollout-*.jsonl` — codex's on-disk session store; `codex exec resume <id>`
  reads it. Proof that resume is cross-process (unlike the MCP path).
- `~/.codex/config.toml` — the user's codex config (has `approval_policy = "never"`, `sandbox_mode =
  "workspace-write"`, a `gpt-5.x` model). Relevant because codex inherits it when you omit `-m`/`-s`.
- The two earlier searcher outputs that fed the plan (seam inventory; test-infra map) — their findings
  are folded into the plan, but if you want the raw method-by-method breakdown of `claude_code.py`, it
  was thorough.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points (especially §1 — the corrected
> `codex exec --json` schema — and the claude-parity-first sequencing in §7), then state you're ready
> to proceed.
