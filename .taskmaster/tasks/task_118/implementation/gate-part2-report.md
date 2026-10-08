# Merged Review Report

Eight distinct lenses produced 12 reviews, all through **codex**. After deduplicating the escaped-reference preview defect: **1 Critical, 11 Warnings, 1 Suggestion, and 1 Minor finding**. Findings retain their originating severity; cross-lens handoffs and same-area convergence are identified below.

## Convergent findings

### Escaped batch references are expanded in dictionary previews — **Warning**
**Lenses:** `review-silent-failures` (web), `review-feature-interactions`
**Convergence:** Same defect independently identified by two lenses.

**Locations:** [batchItems.ts:69](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/web/src/utils/batchItems.ts:69), [batchItems.ts:130](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/web/src/utils/batchItems.ts:130). Runtime comparison: [templates.py:357](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/templates.py:357).

The new dictionary traversal applies `substitute()` to string leaves using a regex that matches `${item.name}` inside `$${item.name}`. With item `{name: "ada"}`:

```yaml
env:
  ACTUAL: ${item.name}
  LITERAL: $${item.name}
```

The expanded preview displays `LITERAL: "$ada"`, while runtime supplies the literal `${item.name}`. The regex predates the change, but dictionary expansion makes the defect newly reachable for `env:` maps. Existing dictionary tests cover ordinary references, keys, and nested lists, but omit escaped references.

**Requested correction:** Respect template escape boundaries during discovery and substitution; add a mixed escaped/unescaped dictionary case. The checkpoint’s body-only escape prohibition does not apply to `env:`.

### Expanded env previews use incorrect value conversion — **Warning**
**Lens:** `review-silent-failures` (web)
**Convergence:** Same dictionary-expansion code area as the two-lens escaped-reference finding; this is a distinct defect reported by one lens.

**Location:** [batchItems.ts:130](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/web/src/utils/batchItems.ts:130).

Dictionary/list substitution uses `fullValue()` rather than runtime conversion. For `env: {VALUE: "flag=${item.flag}"}` with `flag: true`, the preview shows `"flag=true"` while runtime supplies `"flag=True"`. Interpolated null displays `"null"` instead of empty text. Pure references also lose their native types before the enclosing JSON is rendered.

**Requested correction:** Preserve pure-reference types, use runtime stringification for interpolated text, and then format the resulting structure. ADR-0016 and checkpoint §4a require `True` and empty text for these cases.

### Python field-reference repairs discard the field path — **Warning**
**Lenses:** `review-agent-ux`; `review-spec-conformance` through an explicit cross-lens handoff
**Convergence:** The UX finding and spec-conformance handoff identify the same defect.

**Locations:** [data_flow.py:1267](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1267), [data_flow.py:1268](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1268).

With `inputs: {user: {name: ada}}`, `user: dict`, and:

```python
result: str = "${user.name}".upper()
```

The diagnostic advises using variable `user` instead of string `"${user.name}"`. Following it produces `user.upper()`, which fails because `user` is a dictionary. The shortcut recognizes input ownership but discards the reference path.

The spec-conformance handoff independently cites `${config.name}` with `inputs: {config: {name: bob}}`, connecting the issue to the promised “one-step fix.” Its requirement inventory marks existing-binding repair coverage **Partial**.

**Requested correction:** Preserve field/index access, such as replacing `"${user.name}"` with `user["name"]`. Apply the bare-variable shortcut only to bare references.

### Binding-advice convergence: replacement risk and duplicated formatting

**Lenses:** `review-agent-ux`, `review-simplicity`
**Convergence:** Both identify the same binding-advice code area. Their findings are distinct and retain separate severities.

#### Existing whole-map env bindings can be overwritten — **Warning**
**Lens:** `review-agent-ux`

**Locations:** [data_flow.py:1106](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1106), [validator.py:498](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/runtime/template_validation/validator.py:498).

A step already using `- env: ${cfg.env}` and containing leftover `${url}` is told to add `- env: {URL: ${url}}`. The existing-binding branch recognizes only nonempty dictionaries. Appending the suggested bullet replaces the original mapping because the Markdown parser stores the last parameter value, dropping existing authentication or configuration bindings.

**Requested correction:** Distinguish an absent binding from a whole-map template. For a whole-map template, instruct the agent to merge the entry into the upstream map while preserving existing entries and retaining one `env:` parameter. Apply the distinction to unread-input/carry warnings too.

#### The “add a binding” rule has two implementations — **Minor — take or leave**
**Lens:** `review-simplicity`

**Locations:** [data_flow.py:1106](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1106), [validator.py:497](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/runtime/template_validation/validator.py:497).

`_binding_phrase` chooses existing-map versus new-bullet advice, while `_unread_step_input_warning` reconstructs the same inspection, conditional, and formatting.

**Suggested improvement:** Share this small formatting rule while keeping diagnostic sentences with their respective producers. The lens explicitly characterizes this as optional consolidation, without changing checkpoint wording.

### Consumer-test convergence: two missing scenarios and dispatch scaffolding

**Lenses:** `review-test-fidelity`, `review-spec-conformance`, `review-simplicity`
**Convergence:** Three lenses identify the same consumer-test area. These are three distinct findings, not duplicate defects.

#### File-backed batch items lack the promised regression coverage — **Warning**
**Lens:** `review-test-fidelity`

**Locations:** [test_code_body_consumers.py:205](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_consumers.py:205), [dependency_discovery.py:182](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/dependency_discovery.py:182). Requirement: [progress-log.md:719](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/.taskmaster/tasks/task_118/implementation/progress-log.md:719).

The consumer test checks unchanged variable-bearing commands and resolved ordinary script paths using only inline batch items. Dependency discovery has a separate file-backed call. Losing node type there would make `command: ./scripts/$NAME.sh` in external batch YAML raise `FileNotFoundError` while this test still passes. Existing external-batch tests use LLM prompts and cannot detect the regression.

**Requested correction:** Add external batch YAML containing both a variable-bearing command and a real script path; assert preservation and dependency discovery respectively. The accepted amendment explicitly requires “tests inline and file-loaded batch items.”

#### The planned workflow-save regression test is missing — **Warning**
**Lens:** `review-spec-conformance`

**Locations:** [implementation-plan.md:810](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/.taskmaster/tasks/task_118/implementation/implementation-plan.md:810), [test_code_body_consumers.py:217](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_consumers.py:217).

PB-1 requires `./scripts/$NAME.sh` to remain command text through four callers: `resolve_file_references`, `has_file_references`, `discover_dependencies`, and `pflow workflow save`. The consumer test calls only the first three. Searches of save and bundling tests found no equivalent dollar-containing command case, and no recorded deviation removes the obligation.

**Requested correction:** Add a save-entry-point case proving that the command is preserved without attempting to read or bundle it as a file.

#### Remove the consumer-test dispatch layer — **Suggestion**
**Lens:** `review-simplicity`

**Location:** [test_code_body_consumers.py:247](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_consumers.py:247).

Twelve independent checks must accept `(Registry, Path)`, register in `CONSUMERS`, and execute through a forwarding test. Several do not meaningfully use either argument.

**Suggested improvement:** Convert them to ordinary `test_*` functions requesting only their actual fixtures, removing the callable interface, registration table, forwarding function, and unused parameters.

## Critical

### Nested misspelled references bypass the ruling-2 warning
**Lens:** `review-silent-failures` (core)
**Stated severity:** Critical — silent wrong results

**Location:** [data_flow.py:1327](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1327). Requirement: [diagnostics-checkpoint.md:27](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/.taskmaster/tasks/task_118/implementation/diagnostics-checkpoint.md:27).

With an upstream step named `fetch-data`, this shell body passes body checks without diagnostics:

```sh
unset PFLOW_T118_UNSET fecth
printf '%s' "${PFLOW_T118_UNSET:-${fecth-data.stdout}}"
```

The parser consumes the outer expansion as one `Issue`. `_foreign_shape_warning()` examines only `parse(text).expressions`, missing `${fecth-data.stdout}` inside that issue. The recursive leftover detector finds it but correctly rejects neither unknown root.

Shell consequently prints `data.stdout` and exits successfully: `${fecth-data.stdout}` means `$fecth` with default `data.stdout`.

**Requested correction:** Emit the ruling-2 warning for the nested misspelled reference, including the `fetch-data` suggestion. Use the recursive traversal already used by the leftover check, preserving source offsets.

**Evidence limitation:** Static code tracing; this scenario was not executed.

## Warnings

### Valid env names beginning with `__` disappear from reports
**Lens:** `review-silent-failures` (failure display/reports)

**Locations:** [trace_report.py:1361](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/trace_report.py:1361), [workflow_trace.py:1370](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/runtime/workflow_trace.py:1370).

A shell step with `env: {__VALUE: hello}` and command `printf '%s' "$__VALUE"` binds and reads `hello`. Reports reconstruct env from `node_params` or `template_resolutions`, both processed by a sanitizer that recursively removes `__`-prefixed keys. The empty map suppresses `## Env` entirely. Batch-item pages have the same problem.

The sanitizer predates the change, but the new report path depends on preservation of bound values. Checkpoint §7 promises that bound values receive their own section.

**Requested correction:** Preserve valid author-supplied env names through trace capture so reports show what the command received.

### Comments between adjacent Python literals are scanned as string content
**Lens:** `review-validation-consistency`

**Location:** [data_flow.py:1015](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1015).

With `inputs: {name: Ada}`, this code should validate and return `"hello world"`:

```python
name: str
result: str = (
    "hello "  # ${name} is available as a Python variable
    "world"
)
```

Python combines the adjacent literals into one `ast.Constant`. Its source span includes the intervening comment, so `ast.get_source_segment()` returns `${name}` as part of the extracted text. Validation and compilation then report a blocking leftover-reference error even though runtime ignores the comment.

**Requested correction:** Preserve individual literal source boundaries and exclude intervening comments, consistent with checkpoint ruling 1’s restriction to string-literal text. Add the case beside the adjacent-literal repair regression.

**Evidence limitation:** Code-path inspection; the lens left reproduction to the caller.

### Operator-preserving shell repairs can reproduce the validation error
**Lens:** `review-agent-ux`

**Location:** [data_flow.py:1131](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1131).

For batch alias `LIMIT` and command `head -n ${LIMIT:-10} file`, the generated repair says to add `- env: {LIMIT: ${LIMIT}}` and replace `${LIMIT:-10}` with `"${LIMIT:-10}"`.

The replacement remains a leftover because `LIMIT` is still the in-scope batch alias. The alternative concerning a variable assigned by the command does not apply. The allocator avoids only collisions among newly suggested names.

**Requested correction:** Preserve the shell operator while choosing a binding outside the step’s reference scope, such as `LIMIT_VALUE`, producing `"${LIMIT_VALUE:-10}"`.

### Python in-scope escape repairs omit the required annotation
**Lens:** `review-agent-ux`

**Location:** [data_flow.py:1306](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1306).

For a string workflow input `name` and `result: str = "$${name}"`, the repair says to add `- inputs: {name: ${name}}` and write `f"${name}"`. Applying it triggers the next validator error: `Input 'name' is missing a type annotation in the code block.`

**Requested correction:** Include the annotation step, as the ordinary leftover repair does: add the binding, declare `name: str`, and use `f"${name}"`.

### Failed probes discard the new display-safe env output
**Lens:** `review-impact-completeness`

**Locations:** [_probe_impl.py:211](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/cli/commands/_probe_impl.py:211), [node_output_formatter.py:115](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/execution/formatters/node_output_formatter.py:115).

Probe output excludes every key present in `execution_params`. Consequently:

```sh
pflow probe shell 'command=exit 3' 'env={"ENDPOINT":"users"}' --output-format json
```

drops `env` from `outputs`, although `ShellNode.post()` has replaced it with the masked/capped failure copy. The normal text path also discards these details by forwarding only the error message.

**Requested correction:** Preserve the node-written safe copy in JSON and pass it through the text failure formatter. Add failed-probe regression coverage for both formats.

**Evidence:** Static tracing identified a missed reader of the new shell output.

## Suggestions

The standalone **Suggestion** about consumer-test dispatch scaffolding and the **Minor — take or leave** binding-formatting consolidation are retained under their convergent code areas above. No additional suggestions were reported.

## Verified clean

These are the lenses’ reported clean assertions, condensed without reconciling them against findings from other lenses. All reviews were read-only; none independently executed tests or workflows.

### `review-silent-failures` — core

- ADR-0016 classification is consistently applied across scoped runtime, validation, graph, file-discovery, and MCP expansion consumers. Bodies become static before template detection; other parameters retain template processing.
- Checkpoint hard cases a–g and escapes were checked against implementation and tests. Earlier bytes-literal, colon-less-default, nested **in-scope** reference, and multi-root-accounting fixes remain present.
- Unread shell inputs warn, and leftovers suppress duplicate unused-input diagnostics.
- Pass 7 removal follows the settled contract while retaining type checks for other parameters.
- All named slice files were read. No additional warnings or suggestions were reported.

### `review-silent-failures` — failure display/reports

- All six scoped files were read in full against the diff; ADR-0016, checkpoint §§6–7, accepted report fallback, and D9 archival decisions were checked.
- Failure env copies use bound text, key-based masking, newline escaping, and explicit truncation. Direct errors and downstream-reference diagnostics retain the copy.
- Sub-workflow and batch child-failure bundles preserve the safe copy through text, JSON, and MCP.
- Ordinary report pages retain static commands; batch pages prefer each item’s resolved values.
- Failure archival removes the live namespace, supporting the accepted omission of a success-path pop.
- No critical silent-result issue, additional failure-record loss, or secret exposure introduced by the scoped changes was identified.

### `review-silent-failures` — web

- All five assigned files were read in full. `isCodeBody` matches Python classification; `env`, `stdin`, code `inputs`, and same-named MCP parameters remain scannable.
- Body parameters cannot trigger per-item expansion.
- Decoration’s instant, successful-highlight, null-result, and line-mismatch paths preserve content and follow the accepted grammar-based teal rule.
- Empty/dynamic batches retain authored values; missing item fields remain unresolved and visible.
- ADR-0016, the checkpoint, PE requirements, and accepted deviations were checked. No critical workflow-execution issue was reported within the slice.

### `review-validation-consistency`

- Python `param_mode` and TypeScript `isCodeBody` classify exactly `shell.command` and `code.code`.
- Validation and compilation share the body rule through `validate_data_flow`; `check_inputs=False` and permissive template mode do not disable it.
- Compilation passes node type to `split_params`; bodies become static while `env:` and `inputs:` retain resolution.
- Step-local scope, batch/loop names, accepted dash splitting, nested shell expansions, grouped leftovers, and unused-input accounting share the intended detector.
- File resolution and dependency discovery share `is_param_file_reference`; MCP expansion skips bodies. Graph construction, dynamic flags, and TypeScript read scanning exclude bodies while retaining binding references.
- CLI probe directly executes nodes by design; MCP `registry_run` uses the runner/compiler. The settled warning-output follow-up was not re-reported.
- No critical validation/runtime mismatch was reported.

### `review-agent-ux` — diagnostics and output

- Messages follow ADR-0016 and the ruled checkpoint, explaining plain bodies and directing agents to `env:`/`inputs:`.
- Ordinary `${limit:-10}` repairs preserve the operator; the command-assigned-variable alternative is correctly conditional. Ambient collision advice correctly uses `$HOME` without braces.
- Shell `\"value: \\$$X_COST\"` advice correctly expresses a literal dollar followed by the bound value. Python escape explanation and literal-string splitting are coherent.
- Per-escape errors, grouped leftovers, structured `body_references`, and accepted `At: nodes[id=x].params.command:16` rendering retain actionable context.
- Both failure blocks share masked, capped `Env:` rendering. Reports show full-length stringified values in JSON, preserve item-specific resolution precedence, and avoid duplicating shell env under resolved parameters.
- No critical diagnosis-blocking message was reported.

### `review-agent-ux` — documentation/examples

- The [shell guide:32](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/guide/nodes/shell.md:32) teaches `env:` → `"$NAME"`, conversion, masking, the distinction from shell `inputs:`, and ruled destructive-command guidance.
- The [code guide:59](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/guide/nodes/code.md:59) teaches enforced `inputs:` binding while preserving Python f-string interpolation.
- The [shell reference:91](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/docs/reference/nodes/shell.mdx:91) provides a migration diagnostic, location, binding, and quoting repair consistent with implementation and the accepted location-rendering deviation.
- Both MCP instruction copies and converted examples place pflow references outside shell bodies. Architecture and instruction-file changes remove the retired command-type restriction.
- ADR-0016, all nine checkpoint rulings, and accepted deviations were checked. No stale recommendation to interpolate pflow values or use `$${` inside bodies, and no actionable regression, was found in this slice.

### `review-test-fidelity` — backend/integration

- Tests meaningfully exercise scoped leftovers, ambient shell syntax, Python f-strings, escapes, and compiler rejection under ADR-0016 and the checkpoint.
- Consumer tests have positive controls; Pass 6 includes another template to prevent an early-return false pass.
- Failure-display tests assert visible values alongside masking/truncation across text, JSON, reports, and MCP.
- Batch-report tests distinguish two items’ values. Recovery coverage respects namespace archival.
- Tightened error assertions distinguish intended validation failures from body-leftover errors.
- No critical issue or material test bloat was reported in the reviewed PB/PD additions.

### `review-test-fidelity` — web

- Scanner parity rows use an eligible producer shape and preserve positive reads through `env`, `stdin`, `inputs`, and another node type’s `command`.
- Decoration tests pair absent shell-body highlights with present prompt/null-grammar highlights, exercising successful highlighting, null results, line-count mismatch, and body preservation.
- Batch-expansion tests pair body exclusions with a working `stdin` expander and assert exact dict-env values for two distinguishable items plus JSON highlighting.
- Nested-value tests cover substituted leaves, untouched keys, preserved non-alias references, and discriminating labels.
- Migrated `command` → `stdin` fixtures preserve matching edge descriptors and focus, layout, navigation, and chip scenarios.
- Synthetic body references intentionally test frontend classification independently of validation. Null-grammar and dict-env behavior follow recorded rulings.
- Across seven reviewed files, no findings, newly vacuous parity rows, unsupported skip assertions, migration-induced scenario loss, or material test bloat were reported.

### `review-impact-completeness`

- Body classification reaches runtime splitting, validation surfaces, independent type validation, graph construction, React Flow dynamic flags, and MCP single-node expansion.
- File-reference resolution, discovery, and collection—including batch-item paths—use the body-aware predicate.
- TypeScript scanning and batch previews exclude bodies; dictionary env previews expand per item.
- Searches found no remaining references to deleted Pass 7 helpers, `_build_quoted_templates`, or `_validate_loop_carry_prompt_usage` across source, tests, architecture, and canonical agent instructions.
- Safe environment copies reach workflow error enrichment and referenced-failure rendering; reports use the ruled per-item fallback.
- Accepted inline-source decoration and null-grammar exceptions were excluded from findings. No critical missed-consumer defect was confirmed.

### `review-feature-interactions`

- Execution paths consistently separate static bodies from templated bindings; failure env copies cross batch and child-workflow boundaries.
- `TestBatchErrorRecordsCarryOnlyTheSafeCopy` covers masked/capped values through CLI text, JSON child-failure bundles, and MCP.
- `test_a_batch_item_page_shows_the_command_and_its_own_values` distinguishes item-specific bindings beside the host’s static body.
- `test_shell_carry_threads_into_env_across_rounds` covers accumulation. Carry updates `inputs:` before env resolution; loop/batch exclusion remains enforced by validation and compilation.
- Dedicated tests cover nested provenance and script-relative diagnostic lines. File consumers share the `$`-aware body predicate.
- `test_template_input_change_invalidation` covers changed bindings against a warm memo cache.
- Branching, approval, and resume tests retain coalesced env references, resolved approval bindings beside static commands, and restored batch/subworkflow outputs.
- MCP single-node execution skips body expansion while retaining binding expansion.
- Accepted report fallbacks, archival, inline-decoration exception, and pre-existing MCP success-warning gap were not findings. No critical unhandled combination or execution-path regression was confirmed.

### `review-simplicity`

- ADR-0016 and checkpoint rulings justify the distinct diagnostic branches.
- The roughly 540-line body section in `data_flow.py` largely represents required detection, location reporting, grouping, and repairs. No concrete substantial simplification preserving the rulings was found; relocation alone would not simplify it.
- Shared Python classification and the explicit TypeScript mirror avoid scattered exemption rules.
- The source safe-env copy, shared terminal formatter, and resolved-or-static report helper each serve a purpose.
- Removing Pass 7 and quote-handling machinery deletes obsolete concepts.
- No warning-level simplicity issue was found in the inspected core implementation.

### `review-spec-conformance`

**The lens’s verdicts concern implementation/test presence, not runtime correctness. Execution evidence was taken from the progress log and was not reproduced.**

- **Contract/exemption — Met:** Exact two-body classification without registry metadata; node-type propagation; exclusion from template enumeration and validation passes; verbatim parameter splitting; preserved non-body type checks; graph/env-key-label and dynamic-flag parity; MCP exemption; node-owned direct/probe env preparation; body/env parity tests; preservation of deferred MCP policy, `${x|json}`, and linting scope.
- **Detection/diagnostics — Met in the inventory:** Step-local ownership; batch/run/compile rejection; hyphenated/dotted, single-quoted, index/iteration, own-input, carry, forward, and in-scope shell-expansion cases; nested in-scope references; ambient and bare-step-ID acceptance; local aliases; ambient-name collision explanations; unknown-bare-name exclusion; unknown-root warning behavior; embedded-language and array-index scope behavior; whole-body `env:`/`eval` repair; escape rejection with `$$${…}` exemption; dollar-plus-value repair; Python string/bytes handling and f-strings; split-literal repair; parser ownership of syntax errors; grouped structured diagnostics; workflow/script locations; suppression of duplicate unused-input errors across coalesce/index roots; parent provenance; reusable public helpers for Task 181.
- **Recorded detector departures:** Colon-less defaults parsed as Issues, helper placement in `data_flow.py`, `(param, language, text)` classification output, naming changes, and bytes/source-reading fixes were treated as recorded decisions. Existing-binding repair completeness was **Partial**, with the path-loss handoff retained above.
- **Binding boundary/re-homed checks — Met:** `to_string` conversion; compact JSON and hostile-text preservation; accepted `inputs:`/Carry parsing boundary and direct-binding guidance; invalid-name/NUL/encoding/oversize failures without `ignore_errors` swallowing them; case collisions and shell-owned-name warnings; env-sensitive memoization and approval masking; Pass 7 retirement; unread shell-input accounting through env/stdin/cwd, paths, and coalesces; retained LLM carry warnings; loop state through env; dangerous/warning/strict/audit body checks and documented value-blindness; body-aware file walks; executable file-loaded native shell syntax. The unchanged LLM-only prediction walk was a recorded deviation. Workflow-save regression coverage was **Partial**.
- **Failure display/reports — Met:** One source-created failure-only safe copy; primary text/JSON and downstream-reference display; masking, 200-character cap behavior, retained 150-character values, length suffixes, and newline escaping; bound-text rendering; safe child/batch bundles; clean success outputs; recovery archival; static command and full-length masked env sections; shell-only report gating; unchanged code pages; reuse of existing trace fields without a format change. Item-specific fallback and omitted success pop were recorded decisions.
- **Corpus/phase evidence — Met as recorded:** Corpus conversion before the exemption flip; every-node comparisons for seven runnable examples; Task-159 actual-output comparison and drift disposition; benign/hostile non-runnable equivalence with recorded exceptions; heredoc-layer removal and stubbed `osascript` launch exercise; three dollar-cost examples; instrumented suite and hook removal; bounded ten-node golden regeneration and zero PB drift; real CLI/report exercises; PB review dispositions before PE. T1–T4 migration coverage was **Met by recorded audit, with partial independent review**.
- **Web — Met for implementation/test presence:** TypeScript parity and binding partners; body expansion suppression with authorized dict/list expansion; instant/full/fallback decoration and recorded null-grammar behavior; five acceptance observations with a recorded DOM-sampling deviation and env-expanded screenshot evidence.
- **Documentation/instructions — Met where inspected or recorded:** Both MCP copies; shell authoring, quoting, conversion, limits, masking, shell inputs, direct-binding bytes, and dangerous-command limits; non-shell escape example; instruction/searcher-map updates and recorded mirror sync; guide-test inputs derived from template surfaces with a negative drift case; CONTEXT proposals without editing the shared file; historical/saved-workflow exclusions. Broad documentation/corpus completeness remained **Partial independent coverage**.
- **No unrequested behavior established:** Shell-only reporting, dict/list previews, null-grammar decoration, diagnostic text changes, and Task-159 guide regeneration had recorded authorization. The exhaustive inverse pass remained limited by incomplete reading coverage.

## Coverage

| Lens | Provider | Reviews produced | Declared coverage |
|---|---|---:|---|
| `review-silent-failures` | codex | 3 | Core: all named slice files read. Failure/report: six scoped files read in full. Web: five assigned files read in full. |
| `review-validation-consistency` | codex | 1 | Read-only validation/runtime seam review; Python extraction finding not executed. |
| `review-agent-ux` | codex | 2 | Diagnostics/output slice and documentation/example slice. Runtime diagnostic completeness beyond the documentation slice was explicitly outside that review. |
| `review-test-fidelity` | codex | 2 | Backend review partial; web review covered seven files and was not a verdict on other branch surfaces. |
| `review-impact-completeness` | codex | 1 | Full-scope searches and affected-path inspection; incomplete full-file reading of migrated tests/corpus. |
| `review-feature-interactions` | codex | 1 | Implementation/test-assertion inspection; incomplete full-file reading across the 192-file diff. |
| `review-simplicity` | codex | 1 | Inspected core implementation; incomplete full-file reading of bulk-converted tests, documentation, and examples. |
| `review-spec-conformance` | codex | 1 | Requirement inventory with partial independent corpus/test/documentation coverage and log-derived execution evidence. |

**Failed or missing lens reviews:** None. The supplied coverage-gaps input is empty.

**Explicit limitations and outstanding gate evidence:**

- None of the reviews ran tests, workflows, probes, or mutation checks, and none wrote files.
- Backend test fidelity did not complete full-file reads of every PC2-converted file or every large existing test module.
- Impact completeness, feature interactions, simplicity, and spec conformance explicitly declined an exhaustive completion-gate clearance because their required full-file reading was incomplete.
- Spec conformance reported truncated large diff outputs and reliance on logged inventories, instrumented runs, and the T2 audit for some mechanical conversions. Generated artifacts were excluded as requested.
- Spec conformance marked **Part 2 Windows CI, final-branch searcher/fan-out, falsifier, and PZ checks as pending gate evidence**. The log contained Part 1 Windows outcomes and phase-local evidence, with control handed to PZ; this was not presented as missing PD–PF implementation.
- The missing external-batch and workflow-save regression scenarios remain distinct warning findings above.


---

# Appendix A — review-spec-conformance, raw lens output (Requirement Inventory for review-falsifier)

Appended by the gate runner (G1) verbatim from the run's collect output (trace ~/.pflow/debug/workflow-trace-7e357182-run-review-lenses-20261008-014828-858277.json); the merge above condenses it.

## Spec Conformance Review

### Requirement Inventory

**Verdicts concern implementation/test presence, not runtime correctness.** No tests were run. Recorded execution evidence below comes from the progress log.

Sources:

- **S** — `.taskmaster/tasks/task_118/task-118.md`
- **P** — `.taskmaster/tasks/task_118/implementation/implementation-plan.md`
- **CP** — `.taskmaster/tasks/task_118/implementation/diagnostics-checkpoint.md`
- **ADR** — `context/adr/0016-118-code-bodies-untemplated-env-binding.md`
- **L** — `.taskmaster/tasks/task_118/implementation/progress-log.md`

Repeated evidence paths:

- **DF** — `src/pflow/core/workflow/data_flow.py`
- **TC** — `tests/test_integration/test_code_body_consumers.py`
- **TB** — `tests/test_integration/test_code_body_leftovers.py`
- **TD** — `tests/test_integration/test_shell_failure_display.py`

#### Contract and exemption

| Checkable requirement | Source quote | Verdict | Evidence |
|---|---|---|---|
| Classify only `shell.command` and `code.code` as bodies, using node type and param. | ADR: “One classification, consulted by all.” | **Met** | `src/pflow/core/workflow/template_surfaces.py:29`, `:34` |
| Keep classification callable without registry metadata; callers pass node type. | P D1: “a function absorbs that without reshaping callers.” | **Met** | `template_surfaces.py:34`; `src/pflow/runtime/compilation/compiler.py:332` |
| Exclude bodies from template-surface enumeration. | S: “never scanned, validated or resolved as Templates” | **Met** | `template_surfaces.py:123`; TC:57 |
| Preserve `${…}`, `$$`, and `$${…}` verbatim during parameter splitting. | P PB-2: “reach `split_params`' static side unchanged” | **Met** | `src/pflow/runtime/engine/template_resolution.py:127`; TC:179 |
| Exempt bodies from path, batch-field, malformed-template, and source-file-hint passes. | P PB-1: “each calling **that consumer's own entry point**” | **Met** | TC:66, :74, :116, :140 |
| Exempt bodies from Pass 6 while retaining type checks on other params. | P PB-12: “Pass 6 still works” | **Met** | `src/pflow/runtime/template_validation/type_validation.py:39`; TC:154 |
| Produce no graph dependency from a body; retain the env leaf dependency and its key label. | P PB-1: “the env leaf draws one labelled by its **key**” | **Met** | `src/pflow/core/workflow/graph/build.py:587`; TC:187 |
| Mark bodies nondynamic while retaining dynamic env params. | P PB-1: “`False` for the body, `True` for `env`” | **Met** | `src/pflow/core/workflow/graph/renderers/react_flow.py:312`; TC:197 |
| Skip MCP single-node environment expansion for bodies, retaining expansion elsewhere. | S: “a body is exempt there too.” | **Met** | `src/pflow/mcp_server/services/execution_service.py:738`; TC:235; TB:628 |
| Preserve probe/direct-node env binding through node-owned preparation. | S: “it must get the same `env:` binding.” | **Met**, Part 1 regression boundary | `src/pflow/nodes/shell/shell.py:777`; `tests/test_nodes/test_shell/test_env_binding.py:218` |
| Keep body and env parity rows. | P PB-13: “`shell_body` and `code_body` surface entries” | **Met** | `tests/test_integration/test_template_parity.py:611`, `:616`, `:1615` |
| Leave MCP code-param policy, `${x\|json}`, and linting to their deferred tasks. | S: “MCP code params are unchanged by this task” | **Met** in inspected changes | Two-entry body classification; `web/src/graph/scan.test.ts:253` retains an MCP `command` presence partner |

#### Leftover detection and ruled diagnostics

| Checkable requirement | Source quote | Verdict | Evidence |
|---|---|---|---|
| Determine leftover ownership from workflow inputs, own inputs, local batch/loop names, and step IDs with paths. | CP §1: “the **step's own scope**” | **Met** | DF:856, :874 |
| Reject batch `${item}` before execution through validate-only, normal run, and direct compilation. | P PB-3: “at the run, **and** through `compile_workflow`” | **Met** | TB `SHAPES`; TB:207, :216, :239 |
| Reject hyphenated `${fetch-data.stdout}` and dotted `${a.b}` references. | S: “`${fetch-data.stdout}`”; “`${a.b}`” | **Met** | TB `SHAPES`; DF:954 |
| Reject a declared input reference even inside shell single quotes. | S: “`'${overwrite}'` in single quotes stays literal” | **Met** | TB `single_quoted_input` row |
| Reject local `${__index__}` and `${__iteration__}` leftovers. | S: “`${__index__}` / `${__iteration__}`” | **Met** | DF:888; TB `batch_index` and `loop_iteration` rows |
| Reject own-input, carry-key, and forward-reference leftovers. | P PB-3: “an `inputs:` key, a carry key, a forward reference” | **Met** | TB `SHAPES` |
| Reject shell expansion forms rooted in an in-scope name, including `${limit:-10}` and `${#item}`. | CP §1: “a shell expansion form whose leading name is in scope” | **Met** | DF:976; TB `SHAPES` |
| Handle colon-less defaults, including defaults parsed as Issues. | L: “The split now applies to an Issue's leading name too” | **Deviated with record** | DF:969; TB:290, :677 |
| Detect an in-scope reference nested inside a shell expansion. | L: “`${UNSET:-${item}}`” | **Met** | DF:931; TB:685 |
| Accept ambient variables and shell forms when their roots are outside scope. | CP §1: “**shell — never flagged**” | **Met** | TB:371 |
| Accept bare `${count}` when `count` is only a step ID. | CP §1: “a bare step id was never a valid reference” | **Met** | DF:864; TB:380 |
| Keep batch aliases local: a same-named shell loop on another step remains valid. | CP hard case (b): “On any other step the same text is plain sh” | **Met** | TB:380, :418 |
| Reject ambient-name collisions such as own input `HOME` or batch alias `PATH`, explaining ownership. | CP hard case (a): “**ERROR** naming *why*” | **Met** | TB:398 |
| Leave unknown bare `${ENDPONT}`/`$ENDPONT` unchecked. | P D6: “Not built: did-you-mean for a bare `$ENDPONT` or a plain `${endpont}`” | **Met** | DF:954, :1329 |
| Warn, rather than reject, unknown-root dotted/coalesce shell shapes. | CP ruling 2: “**W … warning**” | **Met** | DF:1329; TB:430, :452, :461 |
| Preserve another language’s syntax when outside scope; report the collision when in scope. | CP hard case (d): “passes … unless `user` is in scope” | **Met** | TB:430 |
| Accept `${arr[0]}` outside scope and reject it when `arr` is in scope. | CP hard case (e): “passes unless `arr` is in scope” | **Met** | TB:473 |
| For a whole-body reference, offer `env:` plus `eval "$CMD"`. | CP hard case (g): “the fix says bind it and run it” | **Met** | DF:1204; TB `whole_body_reference` row |
| Reject `$${…}` in shell and Python bodies; exempt `$$${…}`. | CP §3: “an error in both bodies” | **Met** | DF:1023, :1278; TB:491, :510, :523 |
| Offer the dollar-sign-plus-bound-value repair for an escaped in-scope reference. | CP §3: “write `\$$COST` inside double quotes” | **Met**, naming delta recorded | DF:1297; TB:502 |
| Read Python string/bytes literals while accepting genuine Python f-string interpolation. | CP §1: “only the text of its string literals is looked at” | **Met**, bytes/source-reading fixes recorded | DF:997; TB:479, :530, :651 |
| Preserve the checkpoint’s split-literal escape repair beside another `${…}` occurrence. | CP §3: “split the string: `"$$" "{PRICE}"`” | **Met** | TB:696 |
| Leave Python syntax errors to the existing parser; run ordinary code unchanged. | P PB-7: “the parser's error and no leftover error” | **Met** | DF:1008; TB:565, :572, :581 |
| Group leftovers per body, identifying reference, owner, line, and suggested binding structurally. | P D5: “**one** ERROR”; “`context["body_references"]`” | **Met** | DF:1143; TB:252 |
| Cite workflow lines or the loaded script’s own path and line. | P D5: “cite `<script path>:<line in the script>` instead” | **Met** | DF:1059; TB:328, :557 |
| Offer fixes that account for existing bindings, quoting, ambient names, and embedded-language collisions. | P D5: “one paste-able fix” | **Partial** | DF:1102, :1204, :1250; existing-input **path** repair needs UX review, noted below |
| Avoid an additional unused-input error for a leftover, including all coalesce/index roots. | CP §2: “one mistake, one diagnostic” | **Met** | DF:944; `src/pflow/runtime/template_validation/validator.py:113`; TB:598, :712, :718 |
| Carry parent provenance for child-workflow leftovers. | P PB-3: “the error carries the parent provenance” | **Met** | TB:312 |
| Expose reusable scope/detector/accounting helpers for Task 181. | L: “ONE named public helper 181 can call alone” | **Met** | DF:874, :910, :944 |
| Place `body_references` in data flow and yield body language from classification. | L: “`body_references` lives in `data_flow.py`”; “`(param, language, text)`” | **Deviated with record** | DF:910; `template_surfaces.py:50` |

#### Binding regression boundary and re-homed checks

| Checkable requirement | Source quote | Verdict | Evidence |
|---|---|---|---|
| Preserve number/boolean/null/object/array text conversion through `to_string`. | ADR: “one function, `core/templates.to_string`” | **Met**, retained Part 1 implementation | `src/pflow/nodes/shell/env_binding.py:116`; `tests/test_integration/test_shell_env_binding.py:100` |
| Preserve directly bound compact JSON and hostile text without shell reinterpretation. | S: “a string is itself, never re-parsed and re-serialized” | **Met**, retained regression coverage | `src/pflow/runtime/engine/template_resolution.py:90`; `test_shell_env_binding.py:151`, `:198` |
| Keep the accepted parsing boundary through `inputs:`/Carry; document direct binding when bytes matter. | P D2: “that is #686, Task 120's” | **Met** | `src/pflow/guide/nodes/shell.md:56`; existing Part 1 tests |
| Preserve invalid-name, NUL, encoding, and oversized-value failures without `ignore_errors` swallowing them. | S: “A binding failure never surfaces as a command exit code” | **Met**, retained implementation/test presence | `env_binding.py:56`, `:85`, `:163`; `test_shell_env_binding.py:210`, `:339` |
| Preserve case-collision errors and shell-owned-name warnings. | S: “compared case-insensitively” | **Met** | `env_binding.py:25`, `:85`; `test_shell_env_binding.py:411`, `:438` |
| Preserve resolved-env memo-key sensitivity and approval masking. | S: “changing an `env:` value changes the memo-cache key” | **Met**, retained regression coverage | `test_shell_env_binding.py:494`; converted approval-preview assertions |
| Retire Pass 7, quoted-template helpers, and obsolete tests without moving the block onto env. | P D7: “**deleted**” | **Met** | `src/pflow/runtime/template_validation/type_validation.py`; validator no longer dispatches Pass 7 |
| Warn for every unread shell `inputs:` key; count env/stdin/cwd references, nested paths, and coalesces. | CP §5: “every `inputs:` key of a shell step” | **Met** | `src/pflow/runtime/template_validation/validator.py:449`; `tests/test_core/test_loop_validation.py:412`, `:443`, `:458` |
| Preserve the LLM carry-warning obligation. | CP §5: “llm steps keep their carry warning” | **Met** | `validator.py:491`; `test_loop_validation.py:484` |
| Carry shell state through env across rounds. | S Verification: “reads its carried value through `env:`” | **Met** | `tests/test_integration/test_loop_config.py:1115` |
| Keep dangerous/warning/strict/audit checks on body text and document their value-blindness. | CP §9: “The dangerous-command check reads the command text only.” | **Met** | `src/pflow/nodes/shell/shell.py:751`, `:756`, `:802`; guide shell:64 |
| Treat a dollar-containing one-word body as code at every file-reference walk, including batch-item walks. | P D7: “one node-aware predicate” | **Met** | `src/pflow/core/file_resolver.py:96`, `:206`, `:270`; `dependency_discovery.py:140`, `:209` |
| Exercise that rule through file resolution, file detection, discovery, **and workflow save**. | P PB-1: “and `pflow workflow save`” | **Partial** | TC:205 covers the first three; save entry-point case is missing — W1 |
| Load and run `./cmd.sh` containing native `${HOME}`/default expansion. | P PB-10: “A file-loaded `./cmd.sh` … runs” | **Met** | TB:614 |
| Leave the prediction walk unchanged because it receives only LLM nodes. | L: “D7's `predict.py` row is not built.” | **Deviated with record** | L:721; no branch edit to that walk |

#### Failure display and reports

| Checkable requirement | Source quote | Verdict | Evidence |
|---|---|---|---|
| Record one masked, display-safe env copy only on shell failure. | CP §6: “made once at the source” | **Met** | `src/pflow/nodes/shell/shell.py:946`; `env_binding.py:144`; TD:343 |
| Show body and bound values in the primary text error and JSON `shell_env`. | P PD goal: “the failure block, the JSON error” | **Met** | `src/pflow/execution/executor_service.py:362`; `diagnostic_render.py:829`; TD:99 |
| Show the same env lines for a later reference to the failed step. | P PD-6: “the same `Env:` lines” | **Met** | `src/pflow/runtime/engine/template_errors.py:299`; `diagnostic_render.py:617`; TD:404 |
| Mask secrets, retain 150 characters, cap 5,000 characters at 200 with length suffix, and escape newlines. | CP §6: “each value capped at **200 characters**” | **Met** | `env_binding.py:157`; TD:176 |
| Render the text actually bound, e.g. `True`, in failure blocks and reports. | P D11: “One text for a bound value on every reader” | **Met** | `env_binding.py:116`; `src/pflow/core/trace_report.py:1363`; TD:231 |
| Keep failed child/batch error records masked and capped across text, JSON, and MCP. | P PD-8: “the child-failure bundle carries D9's safe copy” | **Met** | TD:496 |
| Keep successful node/batch results free of the failure-only env output. | P PD-5: “have no `env` key” | **Met** | TD:343 |
| Ensure recovery does not retain a stale failure copy. | P PD-9: “has no `env` in its namespace afterwards” | **Met**; success-pop omission recorded | TD:575; L:586 |
| Show `## Command` for static shell steps and `## Env` once, with full-length masked values. | CP §7: “every shell step's page” | **Met** | `trace_report.py:1324`, `:1353`; TD:305 |
| Show each batch item’s resolved values, falling back to host params for static values. | L: “ITEM's own … when present, else the host's” | **Deviated with record** | `trace_report.py:1368`, `:1568`; TD:319; legacy/static tests in `test_trace_report.py` |
| Preserve code report pages; gate shell sections by node type. | P PD-7: “A code step's report page is unchanged” | **Met**; shell gating recorded | `trace_report.py:1324`; TD:423 |
| Reuse existing trace fields without a format change. | P D12: “No trace-format change” | **Met** | Report reads existing `node_params`/`template_resolutions`; no trace-writer/schema change in the branch |

#### Corpus, web, documentation, and phase evidence

| Checkable requirement | Source quote | Verdict | Evidence |
|---|---|---|---|
| Convert corpus before the exemption flip, with no braced shell variables during PC. | P D13: “corpus first, flip second” | **Met**, recorded | L PC1/PC2 entries followed by PB |
| Compare every node’s outputs for the seven named runnable examples. | P PC: “The workflow result alone does not see converted steps” | **Met**, recorded | `implementation/baseline/node_outputs.py:28`, `:41`; L:650 |
| Compare Task-159 actual output against prior actual output; explain drift. | P PC: “compare each case's **actual** output” | **Met**, recorded | `implementation/baseline/task159_actual.sh`; L:654; PF drift disposition |
| Exercise non-runnable conversions with benign/hostile contexts and stubbed external commands. | P PC: “transcripts must be identical, twice” | **Met**, recorded exceptions | `implementation/equivalence.py:139`; L:666 |
| Remove worktree-creator’s old heredoc escaping layer and exercise `launch-cli` with stubbed osascript. | P PC1: “delete that layer with the conversion” | **Met**, recorded | `examples/real-workflows/git-worktree-task-creator/workflow.pflow.md:301`; L:676 |
| Rewrite the three agent dollar-cost examples by hand. | P §5.6: “bind the value … and write `\$$COST`” | **Met**, recorded conversion evidence | Three changed `examples/nodes/agent/claude-*.pflow.md` files; L:667 |
| Run an instrumented suite to find helper/f-string sites; remove the hook. | P PC: “Remove the hook.” | **Met**, recorded | L PC1/PC2 instrumented-run entries |
| Move T2 vehicles to still-templated params, preserve T1 outputs, update T4 display assertions, and retire T3 cases. | P §5.7: “keep the assertion's meaning” | **Met by recorded audit; partial independent review** | L:896 named T2 check-off; inspected CLI/MCP/display conversions |
| Bound golden-hash regeneration to converted nodes; require zero drift at PB. | P D14: “At PB the expected drift is **zero**” | **Met**, recorded | L:657 names ten nodes; L:876 records zero PB drift |
| Preserve shell/code no-read parity in TypeScript, with env/inputs presence partners. | P PE: “parity rows” | **Met** | `web/src/utils/format.ts:146`; `web/src/graph/scan.ts:139`; `scan.test.ts:232` |
| Suppress body per-item expansion while allowing dict/list env expansion. | P PE acceptance 5: “item expansion for `env` and not for `command`” | **Met**; widening explicitly ruled | `web/src/components/ReadPanel.tsx:76`; `web/src/utils/batchItems.ts:120`; L:1171 |
| Prevent code-fence teal in instant, full, and fallback tiers; preserve null-grammar behavior. | P PE: “the instant tier teals only where the full tier would” | **Met**, null-grammar deviation recorded | `web/src/graph/sourceDecorate.ts:64`, `:312`, `:325`; `sourceDecorate.test.ts:214` |
| Record all five web acceptance observations using the screenshot skill. | P PE: “every item screenshotted” | **Met**, recorded DOM-sampling deviation | L:1093; env-expanded screenshot recorded at L:1163 |
| Update shell/code guides, related feature guides, public docs, architecture, shell docstring, and registry snippet. | P PF: “no shipped text teaches the old form” | **Partial independent coverage** | Required files changed; shell guide/docs and named prose changes inspected; broad corpus completeness rests partly on L’s scan record |
| Update both hand-maintained MCP instruction copies. | S: “The MCP server's agent instructions” | **Met by diff/log evidence** | Both instruction resources changed; L PF records the corresponding rule edits |
| Teach names, quoting, text conversion, size limits, masking, shell inputs, direct-binding bytes, and dangerous-command limits. | P PF: “rewritten around one pattern” | **Met** | `src/pflow/guide/nodes/shell.md:16`, `:54`; `docs/reference/nodes/shell.mdx:35` |
| Keep the escape documentation using a non-shell example. | P PF: “keeps `$${` with a non-shell example” | **Met** | `docs/how-it-works/template-variables.mdx:319` |
| Update the named instruction files and searcher location map; synchronize mirrors. | P PF: “then `make sync-claude-assets`” | **Met**, sync recorded | Named CLAUDE files and `.claude/agents/pflow-codebase-searcher.md:154`; L PF |
| Derive guide-test dummy inputs from template surfaces; retain a meaningful drifted-reference negative case. | P PF: “collect names from the parsed IR's `template_params`” | **Met**, relocation to PB recorded | `tests/test_docs/test_guide_example_validation.py:174`, `:283` |
| Propose CONTEXT nouns without editing that shared file here. | P PF: “the main orchestrator writes it” | **Met** | P §11 contains proposals; no branch edit |
| Leave saved workflows and historical artifacts unconverted. | P §5.8: “anything under `~/.pflow/`” | **Met** in inspected scope | No such branch changes; history exclusions acknowledged |
| Exercise ruled diagnostics on real CLI/report surfaces. | P PD/PB handoffs: “through `uv run pflow`” | **Met**, recorded | L PD:586, PB:877, PF verification |
| Record the PB mid-task review and dispositions before PE. | P PB: “Fixes fold in before PE.” | **Met** | L:1014, :1065 |
| Clear Part 2 Windows CI and finish final-branch searcher/fan-out, falsifier, and PZ checks. | S: “`tests-windows` is a blocking gate”; P PZ: “on the final branch” | **Partial — pending gate evidence** | L records Part 1 Windows outcomes and phase-local evidence; latest entry hands control to PZ. This is not treated as a missing PD–PF implementation. |

**Unrequested behavior:** None established in the inspected changes. Shell-only report gating, dict/list batch previews, null-grammar decoration, diagnostic text deltas, and the Task-159 guide regeneration have explicit recorded authorization. The exhaustive inverse pass remains subject to the coverage limitation below.

### Critical — absent or contradicted requirements

None established.

### Warnings — incomplete obligations

**W1 — The planned workflow-save regression test is missing.**

[P PB-1](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/.taskmaster/tasks/task_118/implementation/implementation-plan.md:810) explicitly requires:

> “`./scripts/$NAME.sh` is a command through all four callers (`resolve_file_references`, `has_file_references`, `discover_dependencies`, and `pflow workflow save`)”

The [consumer test](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_consumers.py:217) calls the first three but never workflow save. Searches of the save and bundling tests found no equivalent dollar-containing command case. No recorded deviation removes this obligation.

Consequently, the named save-path requirement lacks its promised regression test. Add a save-entry-point case that preserves `./scripts/$NAME.sh` as command text without attempting to read or bundle it as a file.

**Other-lens handoff:** `review-agent-ux` — S Verification promises a “one-step fix,” but [DF:1268](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1268) tells an existing-input leftover such as `${config.name}` to use `config`, dropping `.name`; assess the repair for `inputs: {config: {name: bob}}` with `result: str = "${config.name}"`.

### Suggestions — improvements

None.

### Requirements Met

The inventory’s **Met** rows identify the implementation and test evidence for the core exemption, scoped leftover detector, ruled diagnostics, retained env channel, re-homed checks, failure display/reporting, and web behavior. The ADR and all nine checkpoint rulings were explicitly included; recorded departures were treated as decisions.

**Coverage limitation:** I did not complete the protocol’s required full-file reading of every changed corpus/test/documentation file. Some large diff outputs were truncated; mechanical conversion coverage is partly supported by the logged inventory, instrumented runs, and T2 audit. Therefore this report is **not an exhaustive clean completion-gate verdict**. Generated artifacts were excluded as requested, and no execution evidence was independently reproduced.

### Summary

The inspected implementation substantially matches Part 2’s contract and ruled plan. One explicit test obligation is missing, and one diagnostic repair needs the UX lens’s attention.

The full gate remains open: finish the exhaustive reading coverage and obtain the pending PZ/Part 2 CI evidence before concluding “no less and no more.”