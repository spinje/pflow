# Braindump: Task 177 Phase 2 → Phase 3

_Written at the Phase 2 stop point. This intentionally does not summarize the plan, code, or
progress log; it records only the remaining tacit judgment I would otherwise lose._

## User's quality signal in this handoff

When told only 14% of the context window remained, the user explicitly chose a complete handoff
over beginning Phase 3. Their follow-up was: "make the handoff in the progress log and then
$braindump skill for the last 20% of tacid knowledge that matters." Treat that as a strong signal:
they prefer a fresh agent doing the subprocess/parser phase coherently over visible progress made
with degraded context. Do not turn Phase 3 into a hurried partial implementation.

## The most important gap I noticed but did not investigate

**NEEDS VERIFICATION — `system_prompt` on Codex.** The public node contract calls
`system_prompt` shared, and `AgentNode.prep()` already puts it into backend options. The Phase 3
argv recipe never says how `CodexBackend` delivers it, and `codex exec --help` has no obvious
system-prompt flag in the recorded CLI reference. Silently ignoring it would violate the shared
contract while every ordinary prompt test still passed. Before coding the argv builder, determine
whether the installed CLI has a supported config key such as developer instructions; if not,
choose an explicit, test-pinned fallback or surface the mismatch to the user rather than quietly
dropping the value. Resume must preserve the same decision.

**NEEDS VERIFICATION — `config` serialization.** The plan says `config: dict` becomes repeated
`-c key=value` arguments but never defines how Python values become TOML literals. Strings need
quoting/escaping, booleans must be lowercase, and arrays/objects need a supported representation.
A naive `str(value)` produces invalid TOML for several types. Establish one small serializer from
observed CLI behavior and pin argv exactly; do not let shell quoting leak into this because argv is
passed directly, not through a shell.

**NEEDS VERIFICATION — backend parameter shapes.** `approval_policy`, `add_dir`, `profile`,
`config`, and Codex `sandbox` have names and high-level types in the plan, but not every runtime
shape/allowed value is test-pinned yet. Verify the installed CLI/config vocabulary before making
an enum stricter than Codex itself. Static validation only rejects cross-backend keys; Phase 3's
runtime backend owns these shape checks.

## Subprocess/error-flow instinct

The tempting design is one large `run()` that builds temp files, calls `subprocess.run`, parses
JSONL, and raises `RuntimeError` on any nonzero exit. That will work on happy-path tests but makes
actionable translation fragile because `AgentNode.exec_fallback()` calls
`backend.translate_error(exc, opts)` only after the node retry lifecycle. Preserve stdout,
stderr, exit code, and parsed failure events in a backend-owned exception so translation can tell
not-installed, auth/login, timeout, and turn failure apart without stringifying away evidence.

**MIGHT MATTER:** deterministic not-installed/auth failures will still pass through AgentNode's
ordinary node retry budget before `exec_fallback` translates them; `retriable=False` chiefly stops
the outer batch retry. Do not accidentally add another retry loop inside CodexBackend. If avoiding
the two node attempts matters, verify PocketFlow's exception contract first rather than assuming
`retriable=False` changes `Node._exec()`.

For v1, `subprocess.run(..., timeout=...)` is the simplest correct primitive if cleanup is handled
in `finally`; the plan's cancellation/orphan concern is real but belongs to deliberate lifecycle
work, not an improvised process-group abstraction. Keep argv as a list on all platforms. Never use
`shell=True`.

## Test construction I would use

Drive CodexBackend with a fake `subprocess.run` that:

- inspects argv;
- finds the unique `--output-last-message` path and writes the final text there;
- returns a `CompletedProcess` whose stdout is the recorded typed JSONL stream;
- varies stderr/return code for error translation tests.

This exercises the temp-file boundary instead of mocking the parser separately. Add narrow pure
parser tests only for malformed lines, `turn.failed`, multiple `turn.completed` usage records, and
command events. Keep the final message sourced from `-o`; do not reintroduce "last agent_message"
logic just because it is convenient in a canned stream.

One pytest trap burned a few minutes during Phase 2: `-k` filters explicitly named node IDs too.
I once passed explicit example/contract tests alongside `-k 'shared_inputs or static_validator'`
and misread the result as those explicit tests passing; they had been deselected. Run important
explicit nodes without `-k`, especially the real-Codex smoke and contract fixtures.

## Contract connections that are easy to miss

- `inputs` is now shared because file-backed agent prompts use it heavily, but it is data-wiring
  metadata, not a Codex CLI option. CodexBackend validation must accept it via `SHARED_PARAMS` and
  then ignore it when building argv.
- `default_model = None` is intentional for Codex: `AgentNode.prep()` will leave `model` as `None`,
  allowing omission of `-m`. Do not replace it with the model found in this machine's config.
- The Phase 1 `_UnavailableCodexBackend` rejects wrong-backend params before its availability
  error. When replacing it with a lazy import, preserve that user-visible order through the real
  backend's `validate_params()`; a missing `codex` binary is a run-time concern, not prep-time
  static availability probing.
- Structured JSON should become `AgentResult.structured_output`; malformed JSON with otherwise
  successful final text should flow into AgentNode's existing schema soft-fail machinery, not be
  converted into an execution exception. Conversely, CLI `turn.failed`/nonzero exit is a real
  backend failure and must raise.
- The current dirty tree is intentional and includes all Phase 2 work. Do not use checkout/reset
  while experimenting with parser mutations. If mutation-testing, copy the target file to a
  writable scratch location first and restore it explicitly with `apply_patch`.

## Assumptions and unexplored edges

**ASSUMPTION:** the installed/logged-in Codex CLI facts captured in the original braindump still
hold. The current Codex sandbox may deny network even if local auth is valid, so distinguish a
sandbox network failure from a product/auth failure before changing code.

**UNEXPLORED:** what a successful resume JSONL stream reports for `thread.started` on every CLI
version. The original capture says the same thread ID is emitted; pin the parser to observed facts
but fail loudly/actionably if no thread ID exists rather than inventing one.

**CONSIDER:** aggregate usage across every `turn.completed` event in one invocation, but do not
confuse Codex's cumulative session context with pflow's per-invocation accounting. The captured
resume event is for the resumed turn; summing events emitted by the current subprocess is safe.

**MIGHT MATTER:** `reasoning_output_tokens` should remain an additive metadata key and should not
be folded into visible `output_tokens`. Before finalizing, grep consumers for strict dict models;
my expectation is they are permissive, but I did not re-verify this during Phase 2.

## What I would do first

After reading the required files, inspect `AgentBackend`, `ClaudeBackend`, and AgentNode's exact
retry/post flow together. Then write the Codex argv/parser/error tests before replacing the
placeholder. The first behavioral checkpoint should be: a completely fake Codex subprocess
returns text plus normalized usage/session metadata through a real `AgentNode.run()` lifecycle.
Only after that is green should structured output, resume argv, errors, and the paid/real surface
be layered on.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm
> you've read and understood by summarizing the key points, then state you're ready to proceed.
