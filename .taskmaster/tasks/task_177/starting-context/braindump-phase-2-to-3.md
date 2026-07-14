# Braindump: Task 177 after Phase 3

_This intentionally replaces the old Phase 2 → 3 handoff. The filename is retained because the
user explicitly asked to overwrite it. The progress log contains the implementation inventory and
test counts; this note records the judgment and uncertainty that are easier to lose._

## What the user actually cares about

The user asked whether I was **"FULLY happy with the implementation"** and whether there were
**"Any loose ends?"** That is the quality bar to carry forward. A large hermetic suite is not enough
to call the Codex backend merge-ready: the user wants a candid distinction between confidence in
the design and proof against the real CLI.

My answer was deliberately qualified. I am happy with the architecture, normalization boundary,
and transport-independent tests. I am not fully happy with real-integration confidence until an
unrestricted host has exercised text output, structured output, and a separate-process resume.
Do not soften that caveat merely because the local suite is green.

## The mental model that made the implementation cohere

Treat the Codex CLI as a protocol adapter, not as a text-producing subprocess:

- typed JSONL is the event/control channel;
- `--output-last-message` is the only final-answer channel;
- the thread id is continuation state;
- schema JSON is an input artifact;
- stderr, exit status, and failure events together are diagnostic evidence.

Keeping those channels separate prevents a seductive but incorrect shortcut: deriving the final
answer from the last `agent_message` event. The recorded stream can contain useful agent messages,
but the CLI explicitly owns final-message materialization. Preserve that boundary.

Likewise, do not push Codex-specific parsing or accounting back into `AgentNode`. Phase 1's most
valuable architectural decision was that a backend returns a normalized `AgentResult`; Phase 3
works because Codex and Claude meet at that boundary while retaining different transports.

## Hard-won CLI knowledge

These facts were discovered by probing the installed `codex-cli 0.144.3`, not by guessing from
option names:

- A profile is a parent `exec` option. `codex exec resume --profile NAME ...` is rejected, while
  `codex exec --profile NAME resume ...` parses.
- Resume does not accept the initial command's `--sandbox` form. The compatible resume form is
  `-c sandbox_mode=...`.
- `-c key=value` values are TOML. Python `str()` is not a serializer: it mishandles strings,
  booleans, containers, escaping, and unsupported values.
- The current official config reference documents `developer_instructions`; that is why shared
  `system_prompt` maps there instead of being silently ignored or concatenated into the user
  prompt.
- Leaving subprocess stdin inherited caused the real CLI to announce that it was reading extra
  input and risked consuming pflow's own pipe as a `<stdin>` prompt block. `DEVNULL` is a functional
  isolation requirement, not cosmetic subprocess hygiene.

If a future CLI changes one of these rules, update the exact argv tests and record the observed
version. Do not make the builder "more flexible" by sending both old and new flag forms.

## Where confidence stops

**NEEDS VERIFICATION:** Run the installed-CLI smoke on a host that can resolve and reach
`api.openai.com`. This sandbox reached the CLI and began the request, then failed DNS resolution.
That proves command parsing only; it does not prove a successful response.

**NEEDS VERIFICATION:** Exercise all three real workflows independently:

1. plain text with an exact short response;
2. JSON Schema output read from the final-message file;
3. a first invocation followed by resume in a new subprocess, confirming the emitted thread id
   and retained session behavior.

The third is especially important. Hermetic tests prove our two argv shapes and parser behavior,
but not whether Codex persists working directory and additional-directory access in exactly the
way assumed when resume omits `--cd` and `--add-dir`.

**NEEDS VERIFICATION:** `subprocess.run(timeout=...)` terminates the direct CLI process, but there
is no explicit process-group/tree cleanup. That is acceptable for the scoped v1 and much safer
than improvising a cross-platform lifecycle abstraction, but it remains a genuine orphan-process
risk if the CLI leaves descendants behind on timeout.

**NEEDS VERIFICATION:** Missing-binary and authentication errors become `retriable=False` only
when `AgentNode.exec_fallback()` translates them. PocketFlow's internal node retry has already
happened by then. Avoid adding a backend retry loop. If fast-failing deterministic errors becomes
important, first study and test PocketFlow's node exception lifecycle; the metadata flag alone
does not bypass it.

## Test judgment, not just test count

The most valuable Phase 3 tests are the ones whose fake subprocess writes the actual temporary
final-message file while returning typed JSONL. They cross the backend's real filesystem/argv
boundary and would catch regressions that parser-only tests miss. Preserve that style.

The real smoke is intentionally guarded only by `shutil.which("codex")`, following the Phase 3
plan. This makes it honest but operationally fragile: a machine with Codex installed but logged
out or offline will run and fail it. Do not quietly change it to opt-in without deciding whether
CI/local reliability or automatic real-surface coverage is the stronger project policy.

The requested test reflection caught one real cross-backend leak: retry aggregation introduced a
zero-valued `reasoning_output_tokens` field for Claude-style retry usage even though `AgentNode`
deliberately preserves backend-specific usage shapes. The aggregator is now conditional: the key
stays absent unless the main call or a retry supplied it, and then all supplied reasoning tokens
are summed. Tests pin both sides of that contract.

Do not add more event-shape tests for coverage's sake. Add a test only when it protects a real
protocol boundary, an error translation decision, or lifecycle behavior that could plausibly
break unnoticed.

## Scope boundaries that still matter

Phase 4 owns the remaining `run-cycle.json` contract mismatch, web literals/bundle generation, and
UI verification. The one non-sandbox full-suite failure is expected until that phase lands. Do not
"fix" it by manually editing a generated fixture without following Phase 4's regeneration path.

Phase 5 owns the remaining authored docs, architecture/MCP prose, and cleanup. The strict v1
`approval_policy` string enum deliberately excludes Codex's granular table form; expanding that is
future API design, not a Phase 4 cleanup.

`inputs` is a load-bearing shared agent parameter even though Codex ignores it at argv construction.
It represents workflow data wiring for file-backed prompts. Removing it from `SHARED_PARAMS` would
recreate the false cross-backend validation failures found in Phase 2.

## What I would do next

Review the current diff, especially option precedence, stdin isolation, retry usage shape, and
error translation. On an unrestricted host, run the three real workflows above. If those pass,
proceed to Phase 4 without broadening the Codex backend API.

Do not commit unless the user asks. Phase 1 and Phase 2 are already separate commits; the current
Phase 3 changes are intentionally left for review.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
