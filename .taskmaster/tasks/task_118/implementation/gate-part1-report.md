# Merged Review Report

## Convergent findings

### 1. The shell guide omits the direct-binding qualification

**Lenses and stated severities:** `review-impact-completeness` — **Warning W1**; `review-agent-ux` — **Warning 2**; `review-feature-interactions` — **Suggestion**, explicitly handed off to `review-agent-ux`.

**Convergence:** Three lenses identify the same documentation defect at [shell.md:64](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/src/pflow/guide/nodes/shell.md:64).

The guide promises: “A string arrives unchanged, JSON-looking or not.” It omits “when bound directly,” the qualification in [diagnostics-checkpoint.md:275, §4a](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/.taskmaster/tasks/task_118/implementation/diagnostics-checkpoint.md:275).

With `inputs: {raw: ${up.stdout}}` followed by `env: {RAW: ${raw}}`, upstream `{"a":1}` becomes `{"a": 1}` because `inputs:` still auto-parses. Routing through loop carry can likewise parse and reserialize JSON-looking text. The implementation deliberately retains this behavior, and `TestJsonLookingTextStaysText` pins it. Authors relying on the unqualified promise for byte-sensitive processing can receive altered bytes without a warning.

**Requested correction:** State that strings arrive unchanged **when bound directly in `env:`**. Explain that `inputs:` and Carry retain existing parsing. This is a documentation correction that preserves the settled runtime ruling.

### 2. Encoding validation and recovery advice have distinct defects in the same binding area

**Convergence:** `review-validation-consistency` and `review-agent-ux` independently identify defects involving unencodable values in `env_binding.py`. These are separate findings, retained separately below.

#### 2a. Literal containers pass static checks but fail runtime encoding

**Lens:** `review-validation-consistency`
**Stated severity:** **Critical — validation/runtime mismatch**

[env_binding.py:114](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/src/pflow/nodes/shell/env_binding.py:114) checks encoding only for string values. A literal environment equivalent to Python `{"DATA": {"text": "\ud800"}}` therefore passes both validation and compilation.

At runtime, `bind_env()` serializes the dictionary through `to_string()` using `json.dumps(..., ensure_ascii=False)`, then rejects the retained surrogate at [env_binding.py:132](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/src/pflow/nodes/shell/env_binding.py:132). Earlier workflow steps may already have executed despite the value being fully static.

**Requested correction:** Apply the same conversion and encoding predicate to serialized literal containers during static validation, retain runtime checks for resolved values, and add parity coverage for nested dictionaries and lists.

**Evidence qualification:** Code-traced finding; no tests or workflow executions were run.

#### 2b. The encoding-error remedy leads to another failure

**Lens:** `review-agent-ux`
**Stated severity:** **Warning 1**

[env_binding.py:190](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/src/pflow/nodes/shell/env_binding.py:190) advises “Pass that value through stdin instead” for an unencodable character.

For the covered lone-surrogate value `"cut \ud800"`, that remedy also fails: [shell.py:885](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/src/pflow/nodes/shell/shell.py:885) encodes stdin with strict UTF-8, so the command never starts.

The message follows checkpoint §4f’s draft shape, but its repair is ineffective.

**Requested correction:** Retain stdin advice for NUL bytes. For encoding failures, use: “Repair the invalid Unicode in the upstream value before binding DATA. Passing the same text through stdin will also fail.”

## Critical

### C1. The carried-loop test cannot detect broken carry parsing

**Lens:** `review-test-fidelity`
**Stated severity:** **Critical — false confidence**

At [test_shell_env_binding.py:181](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/tests/test_integration/test_shell_env_binding.py:181), `test_a_carried_loop_value_is_parsed_like_inputs` asserts final stdout equals `{"a": 1}` and that two iterations occurred.

Round one already parses the compact upstream string through `inputs:` and prints the spaced representation. Round two therefore carries text whose spelling is identical whether parsing occurs or not. The test also passes if carry overrides are ignored entirely: both iterations can resolve the original upstream input and print the same result.

PA test 2 explicitly requires a sibling row covering “the same value routed through `inputs:` (and a carried loop round).”

**Requested correction:** Make the carried value compact and distinguishable from the initial seed, then observe its parsed representation in round two. The test should fail both when carry is bypassed and when carried JSON text stops being parsed.

## Warnings

No additional warning findings beyond those retained under **Convergent findings**.

## Suggestions

### Preserve the source reference in whole-map failures

**Lens:** `review-agent-ux`
**Stated severity:** **Suggestion**

[env_binding.py:91](/Users/andfal/projects/pflow-worktrees/feat-task-118-shell-env-binding/src/pflow/nodes/shell/env_binding.py:91) emits `env must be a map of NAME: value — got a str.` when `${cfg.env}` resolves to ordinary text. Checkpoint §4e explicitly specifies `${cfg.env} resolved to a str.`

**Requested improvement:** Restore the source reference so an agent can locate the upstream value and distinguish a resolution failure from a literal authoring error.

## Verified clean

The following preserve each lens’s own assertions; they are not adjudications of other lenses’ findings.

### `review-impact-completeness`

- No missed production consumer of the changed binding or resolution rules was found; the lens reported high confidence in the production impact map.
- The compiler supplies `TemplateConfig.node_type`; ordinary execution, batch resolution, execution planning, and memo-key calculation use the updated resolver. Carry preserves the field through `dataclasses.replace`.
- `ShellNode.prep()` covers compiled workflows, nested execution, and direct CLI probes. MCP single-node execution routes through the runner.
- Validator and direct compiler checks share `env_problems`; runtime binding reuses it. Compilation forwards structured diagnostics and filters warnings appropriately.
- `EnvBindingError` uses the existing `NodeError` contract. Retries and batch handling recognize its non-retriable, nonfatal-per-item classification; shell fallback preserves it.
- The Interface retains `env: dict`; registry source-change detection covers refreshed metadata. No stale `_reject_non_string_code` references were found.
- ADR-0016’s `to_string` conversion, checkpoint §4’s warning/error distinctions, and the logged §4e message deviation are respected. Shell/code bodies remain Templates for Part 1.
- Both tooling workflows bind `CWD_OVERRIDE` through `env:` and use quoted shell expansion.

### `review-feature-interactions`

- No concrete runtime interaction defect was found. `ShellNode.prep()` provides the explicit text conversion, name/encoding validation, and spawn-size failure boundary without a new shared-store propagation key.
- Settled rules are respected: `to_string` conversion, direct JSON-string byte preservation, `True`/`False` boolean spelling, shell-owned-name warnings, case-duplicate errors, and binding errors bypassing `ignore_errors`. The whole-map wording deviation is accounted for.
- Batch resolution preserves `node_type`; binding and merging create fresh dictionaries. Tests cover sequential/parallel indices and unchanged process/config environments.
- `retriable=False, batch_fatal=False` matches item-failure handling. `test_a_continue_batch_fails_the_item_once_and_finishes` checks retained successes, original error index, and no retry. All-failed `continue` batches remain rejected.
- Carry preserves metadata through `dataclasses.replace`; the lens describes the carried-loop test as explicitly preserving accepted `inputs:` parsing. Batch/loop exclusion remains enforced by validation and compilation.
- Non-batch memo keys include resolved `env:` values. `test_a_changed_env_value_changes_the_memo_key` checks a hit and a changed-value miss; the acknowledged batch-cache limitation remains outside scope.
- Nested compilation reaches the same static checks; runtime binding failures use existing child-failure propagation. Existing tests cover partial, parallel, and all-failed nested batches.
- CLI probes reach the bare node lifecycle; MCP registry execution reaches the runner/compiler lifecycle. Both bind through `prep()`.
- Disabling leaf JSON parsing for `shell.env` preserves reference resolution, coalescing, and strict unresolved-reference checks.
- Shell/code bodies remain Templates; both tooling workflows use quoted `$CWD_OVERRIDE`.

### `review-simplicity`

- No worthwhile simplification, minor finding, emergent duplication, unused scaffolding, or unnecessary abstraction was identified. Small helpers have concrete responsibilities.
- `env_binding.py` owns name checks, conversion, environment merging, and size-refusal messages; `ShellNode.prep()` adds no execution state.
- Validator/compiler reuse `shell_env_diagnostics`; runtime reuses `env_problems`. `EnvProblem` carries messages and fixes into two diagnostic presentations.
- ADR-0016 is respected through existing `to_string` conversion and direct-leaf parsing control, with no second serialization table or binding channel. Shell/code bodies remain Templates.
- Checkpoint §4 checks use focused logic. The logged non-map wording deviation avoids threading original template text through the engine solely for one message.
- Integration adds one consumer-specific parsing decision, extends the existing Windows environment seam and parity harness, and uses the same straightforward tooling-workflow binding pattern.

### `review-silent-failures`

- No new silent-failure defect was found in the assigned seam.
- `bind_env()` preserves zero, false, null, empty strings, and empty containers through specified `to_string()` semantics; binding and merging create fresh dictionaries.
- Invalid names, case collisions, NUL bytes, and POSIX encoding failures raise before spawning and cannot become successful commands through `ignore_errors`.
- `E2BIG` becomes non-retriable `EnvBindingError`; fallback re-raises it, and engine/batch recording retains the failure signal.
- Direct `shell.env` leaves bypass JSON parsing; whole-map resolution retains existing behavior, and unresolved references still reach diagnostics.
- Compiler-supplied `node_type` survives loop copies. Static shell-binding errors and existing code-parameter errors remain loud.
- Configuration reuse and cache planning use the same resolution rule; resolved environment values participate in memo keys.

### `review-validation-consistency`

- Validator step 9 and direct compilation share `shell_env_diagnostics`; compilation preserves error diagnostics and excludes warnings.
- Invalid names, non-string keys, case collisions, non-map literals, and direct string NUL/encoding failures use shared rules.
- Whole-template maps defer checks to `ShellNode.prep()`; probes reach those checks through `node.run()`.
- Binding failures escape `ignore_errors`; permissive template resolution cannot bypass `bind_env`.
- Literal-map leaves accept scalar and container values without inappropriate template type restrictions. Direct JSON-looking template values retain their text.

### `review-agent-ux`

- No critical diagnostic that leaves agents unable to debug was reported.
- Invalid-name errors give a valid replacement and quoted shell usage; case-collision errors identify both keys.
- Boolean warnings explain `true` → `True` and give a concrete quoting fix.
- PATH warnings explain consequences and provide an executable extension command.
- Validator diagnostics retain structured severity, node ID, parameter path, and suggestions; direct compilation preserves them.

### `review-concurrency-safety`

- No change-induced concurrency or resource-lifecycle defect was found.
- `env_binding.py:122` builds a fresh string-valued dictionary on every call, including empty inputs; compiled maps and whole-map template results remain unmodified.
- `env_binding.py:141` merges into a fresh dictionary; `shell.py:876` passes it to the subprocess without changing `os.environ`, isolating concurrent bindings.
- `shell.py:64` copies its input before changing PATH or `MSYS_NO_PATHCONV`, preventing repeated support-path accumulation in caller environments.
- `batch_executor.py:844` deep-copies worker nodes before parameter assignment/execution. No locks, handles, or other non-copyable instance state were introduced.
- Compiler-supplied `node_type` survives loop/planning copies. `parses_leaves()` is read-only; resolution uses local containers.
- Binding failures occur before spawning; `E2BIG` remains non-retriable through fallback, and batch errors remain item-local without retries.
- The interleaving inspection covered shared compiled maps, whole-map aliases, and repeated execution; fresh dictionaries and worker copies preserve isolation.

### `review-test-fidelity`

- No substantial test bloat was identified.
- Value tests verify exact text and variable presence, distinguishing empty bindings from dropped variables.
- Dynamic name/NUL/surrogate cases reach runtime, assert no execution, and inspect actual failure records. A command-failure control establishes exit-code recording.
- Compact-JSON tests cover upstream output, batch items, and parity; successful parity rows run through the real runner.
- Memoization tests establish a hit before changing the environment value and checking renewed execution.
- D8 tests use real child processes, distinct inherited/bound PATH markers, exact hostile-value output, and marker-file absence checks.
- Existing PATH-override and gate-preview masking tests retain PA regression coverage.

## Coverage

| Lens that produced a review | Provider |
|---|---|
| `review-impact-completeness` | codex |
| `review-feature-interactions` | codex |
| `review-simplicity` | codex |
| `review-silent-failures` | codex |
| `review-validation-consistency` | codex |
| `review-agent-ux` | codex |
| `review-concurrency-safety` | codex |
| `review-test-fidelity` | codex |

**Failed-lens gaps:** None supplied. All eight listed lenses produced reviews.

**Reported verification limits and scope gaps:**

- All reviews were read-only inspections. No lens executed tests, probes, or workflows.
- Windows D8/environment behavior and Linux size-limit or oversized-spawn outcomes remain caller/CI verification items. `review-test-fidelity` specifically retains the need to pin D8-4 after observing its Windows result.
- `review-impact-completeness` notes that type checking and documentation meta-tests cannot establish platform outcomes or catch the guide’s semantic overstatement.
- `review-feature-interactions` found no dedicated `env:` combinations with nested workflows or branch convergence; those conclusions rely on shared-infrastructure tracing. Part 2 and `uv.lock` were excluded; the batch-cache limitation remains outside scope.
- `review-simplicity` reviewed `origin/main...HEAD`; generated baseline captures and `uv.lock` were excluded from code critique.
- `review-silent-failures` covered the assigned P0 + PA seam in `origin/main...HEAD`; the documented `inputs:` JSON-parsing limitation remains outside this part’s scope.
- `review-validation-consistency` was limited to shell `env:` and its callers/counterparts.
- `review-agent-ux` did not exercise rendered CLI/JSON output.
