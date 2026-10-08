# Merged Review Report

Scope: Task 118 PB, `c3189b41..76a1aed5`. Findings below consolidate the supplied reviews without verification or adjudication. Severity remains as stated by each lens.

## Convergent findings

### 1. Python bytes literals bypass the migration guard

**Convergence: 2 lenses — `review-validation-consistency`, `review-silent-failures`.**
**Severity: Critical — both lenses.**

**Location:** [data_flow.py:990](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:990)

`_readable_texts()` accepts only `ast.Constant` values of type `str`, excluding bytes literals from leftover detection.

`review-validation-consistency` supplied a step with `inputs: {name: bob}`:

```python
name: str
result: str = b"${name}".decode()
```

The body passes the guard and annotation checks. Previously, template resolution produced `"bob"`; PB passes the body unchanged through `split_params`, returning `"${name}"`. Workflow validation and direct compilation both miss it.

`review-silent-failures` supplied a batched code step with `items: [ada]`, `inputs: {}`, and:

```python
result: str = b"${item}".decode()
```

Previously this returned `"ada"`; PB successfully returns `"${item}"`. That lens also identified bytes literals containing `$${…}` as bypassing escape detection for the same reason.

**Requested correction:** Include bytes literals in the migration guard, preserving the f-string exemption and unchanged execution of bodies. The lenses identify this as a violation of the requirement that code relying on interpolation fail validation instead of silently returning literal text.

### 2. Dash splitting misses shell defaults parsed as Issues

**Convergence: 2 lenses — `review-validation-consistency`, `review-silent-failures`.**
**Severity: Critical — both lenses.**

**Location:** [data_flow.py:951](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:951)

The accepted dash-splitting rule applies to `Expression`, but not `Issue`. `_issue_reference()` consequently retains a dashed name that has no owner and misses the in-scope leading shell name.

`review-validation-consistency` supplied a shell step with `inputs: {limit: 5}`:

```sh
unset limit
printf '%s' "${limit-default:value}"
```

The colon classifies the expression as an Issue. `_issue_reference()` extracts `limit-default`, misses `limit`, and validation emits only the unread-input warning. Compilation succeeds and the shell prints `default:value`.

`review-silent-failures` supplied a shell step with `batch: {items: [ada]}`:

```sh
unset item
printf '%s' "${item-fallback value}"
```

The space classifies this as an Issue. `_issue_reference()` returns `item-fallback`; the step succeeds with `fallback value`. Before PB, malformed-template validation rejected it.

**Requested correction:** Apply the ruled leading-shell-name fallback to Issues too, retaining full pflow-name matching first. Checkpoint §1 requires a leftover ERROR when the leading name is in scope.

### 3. Python literal concatenation invalidates the prescribed escape repair; its test checks only the suggestion text

**Convergence: 3 lenses — `review-validation-consistency`, `review-feature-interactions`, `review-test-fidelity`.**
The runtime defect and the distinct test-coverage defect are retained separately below.

#### Runtime defect

**Severity: Warning — `review-validation-consistency`, `review-feature-interactions`.**

**Locations:** [data_flow.py:987](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:987), [data_flow.py:984](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:984)

`_readable_texts()` scans decoded AST constants, which combine adjacent Python string literals. This valid body is rejected:

```python
result: str = "$$" "{PRICE}" + "${HOME}"
```

The unrelated `${HOME}` activates the body scan. The AST combines the adjacent literals into `$${PRICE}`, triggering the escape ERROR. Without another `${…}`, the outer guard skips scanning and the prescribed repair passes.

`review-feature-interactions` identified the same behavior when the strings are in separate assignments:

```python
literal = "$$" "{PRICE}"
result: str = "${HOME}" + literal
```

Checkpoint §3 explicitly recommends splitting the string as `"$$" "{PRICE}"`.

**Requested correction:** Preserve source literal boundaries so the prescribed workaround remains valid alongside other allowed literals, and add regression coverage combining both.

#### Test-coverage defect

**Severity: Critical — `review-test-fidelity`.**

**Locations:** [test_code_body_leftovers.py:510](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_leftovers.py:510); supporting implementation references [data_flow.py:976](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:976) and [data_flow.py:1008](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:1008).

The test asserts the suggested text `"$$" "{PRICE}"`, but never validates and executes the repair alongside another legitimate `${…}` string.

For the mixed body above, the expected result is successful validation and execution returning exactly:

```text
$${PRICE}${HOME}
```

The traced implementation instead rejects the repair again. Testing the repair alone would miss the defect because the early guard skips scanning without another `${`.

**Requested correction:** Extend the test to assert successful validation and exact runtime output for the mixed body, preserving checkpoint §3’s repair and ADR-0016’s plain-Python contract.

### 4. Compound leftovers lose dependency roots in accounting; tests do not cover multiple known roots

**Convergence: 4 lenses — `review-validation-consistency`, `review-impact-completeness`, `review-feature-interactions`, `review-test-fidelity`.**
The accounting defect and the distinct regression-coverage defect are retained separately below.

#### Accounting defect

**Severity: Warning — `review-validation-consistency`, `review-impact-completeness`, `review-feature-interactions`.**

**Locations:** [data_flow.py:943](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:943), [data_flow.py:941](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:941), and accounting consumer [validator.py:478](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/runtime/template_validation/validator.py:478).

`_leftover()` returns after the first in-scope reference, so `body_reference_roots()` loses subsequent operands and dynamic-index roots.

Evidence supplied across the lenses:

- With workflow inputs `a` and `b` used only by `command: echo '${a ?? b}'`, only `a` is retained. Full validation reports the intended leftover error plus an incorrect unused-input error for `b`, suggesting removal of its declaration. Direct compilation reports only the leftover.
- With an existing `branch` step and workflow input `fallback` used only by `echo "${branch.stdout ?? fallback}"`, validation additionally reports **“Declared input(s) never used as template variable: fallback”**.
- `${values[${index}]}` similarly loses `index` when both roots are declared.
- The truncated collection also reaches `validator.py:478`: two step-input keys in one leftover can generate an extra unread-input warning for the second key, including a later carry/input operand.

Checkpoint §2 requires that an input referenced through a leftover **“does not also get”** the unused-input error: “one mistake, one diagnostic.”

**Requested correction:** Collect every in-scope dependency root for both accounting consumers while retaining one grouped body error. Cover coalesces and dynamic indices with multiple known roots.

#### Test-coverage defect

**Severity: Warning — `review-test-fidelity`.**

**Locations:** [test_code_body_leftovers.py:598](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_leftovers.py:598), expression coverage at [test_code_body_leftovers.py:278](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/tests/test_integration/test_code_body_leftovers.py:278), and implementation reference [data_flow.py:927](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:927).

The unused-input test checks one declared input referenced by one leftover. The expression test likewise includes only one in-scope root per expression. Neither catches:

```text
workflow inputs: primary, fallback
shell command: echo "${primary ?? fallback}"
```

Both inputs appear only in this leftover. The expected diagnostic set contains the leftover error without an unused-input error for either name; the implementation reports `fallback` as unused.

**Requested correction:** Strengthen the existing test with two declared roots in one expression and check the complete error set through `WorkflowValidator`. M19’s “first operand only” mutation does not cover this accounting loss. `review-feature-interactions` likewise notes that detecting a later operand does not test accounting for multiple known operands.

## Critical

### An outer shell expansion hides an in-scope nested reference

**Lens:** `review-silent-failures`
**Location:** [data_flow.py:918](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/core/workflow/data_flow.py:918)

With `batch: {items: [ada]}`, this body succeeds with empty output:

```sh
unset PFLOW_T118_UNSET item
printf '%s' "${PFLOW_T118_UNSET:-${item}}"
```

The parser consumes the outer expansion through the first closing brace as one Issue. The guard checks only its leading name, `PFLOW_T118_UNSET`; nested `${item}` receives no scope check. No workflow input exists to trigger the unused-input diagnostic. Previously, the outer malformed template failed loudly.

**Requested correction:** Detect the nested in-scope `${item}` and reject the body before execution.

## Warnings

### Successful MCP single-node responses discard body warnings

**Lens:** `review-silent-failures`
**Location:** [execution_service.py:803](/Users/andfal/projects/pflow-worktrees/feat-task-118-part-2-bodies-untemplated/src/pflow/mcp_server/services/execution_service.py:803)

```python
run_registry_node("shell", {"command": "printf '%s' '${fecth.stdout}'"})
```

This now reaches execution and generates the ruled unknown-root warning. The success branch returns only `format_node_output(...)`, without forwarding `result.diagnostics`. The caller consequently receives success without the warning intended to flag unresolved text. Tracing is disabled on this path too.

**Requested correction:** Surface body warnings alongside successful MCP output, preserving ruling 2’s warning-only behavior.

## Suggestions

No standalone suggestions were reported. `review-test-fidelity` requested strengthening existing tests as recorded above.

## Verified clean

These are the lenses’ supplied assertions, condensed without additional verification.

### `review-validation-consistency`

- `WorkflowValidator` and direct `compile_workflow` reach the same body guard through `validate_data_flow`; neither `check_inputs=False` nor permissive template mode disables it.
- Compiler-provided node type makes `split_params` classify bodies before template detection. Runtime resolution and loop carry preserve static classification.
- Template surface enumeration and Pass 6 exclude bodies; Pass 7 is removed. Python annotation validation remains active.
- Batch/loop scope is step-local; bare step IDs remain exempt. Ordinary Python f-string interpolation remains distinct from literal leftovers.
- Shell unread-input warnings inspect other template parameters, including `env`, `stdin`, and `cwd`.
- HEAD consumer searches found no additional body-template walk in this slice; `predict.py` remains LLM-only.

### `review-impact-completeness`

- Shared surface enumeration excludes bodies from ordinary reference, malformed-template, path, and batch-item checks; Pass 6 uses `template_params`.
- The compiler passes node type to `split_params`; runtime consumers receive static bodies.
- Graph edges, Python canvas `is_dynamic`, and MCP single-node environment expansion consult classification.
- All five file-reference sites, including batch-item loading and dependency discovery, use the node-aware predicate.
- No Python references remain to deleted Pass 7 helpers.
- HEAD searches found no additional body-reading template walk. Prediction is LLM-only, consistent with the amendment; child-call parameter resolution is workflow-node-only.
- No Critical findings or additional missed body-resolution consumers were found.

### `review-silent-failures`

- Classification precedes template detection in `split_params`; bodies remain static without collapsing escapes.
- Ordinary leftover diagnostics reach validation and compilation.
- All five file-reference sites use the node-aware predicate.
- Pass 6, graph edges, and canvas `is_dynamic` exclude bodies.
- Unread shell-input warnings run before the no-template early return.
- HEAD’s additional sub-workflow parameter walk is workflow-node-only. Prediction remains LLM-only, matching the amendment.

### `review-feature-interactions`

Static inspection supports:

- **Batch and classification:** Compiler splitting keeps bodies static; item resolution continues through template parameters.
- **Loop carry and shell binding:** Carry replacement preserves static bodies and resolves inputs before `env`. Existing `test_shell_carry_threads_into_env_across_rounds` asserts accumulated output.
- **Nested workflows and diagnostics:** Child validation retains parent provenance; `test_a_child_workflow_leftover_carries_the_parent_provenance` covers it.
- **Loop, nested workflows, and caching:** `__loop_active__` remains propagated; existing `test_cache_staleness_guard_drains_despite_inner_cache_true` covers suppression.
- **File references, MCP expansion, graph edges, and canvas flags:** Changed consumers consult classification; the consumer table exercises their entry points.
- **HEAD interactions:** No newly merged template-parameter walk over shell/code bodies was identified. The dropped prediction walk remains LLM-only.
- No Critical findings were demonstrated.

### `review-test-fidelity`

- The consumer table pairs body exclusion with positive controls, including a compatible neighboring template that ensures Pass 6 runs.
- `BODY_ROWS` checks compiler and validator rejection separately; accepted rows assert exact output through `WorkflowRunner`.
- The no-execution test proves its filesystem observation works by running the repaired workflow.
- Tightened assertions identify intended missing-field, missing-input, and forward-reference failures.
- Loop-warning tests cover self-named input bindings, nested references, and retained LLM behavior.
- The tests provide substantial behavioral confidence without material bloat.
- Limited HEAD interaction inspection found no additional body-reading parameter walk.

## Coverage

| Lens | Provider | Review received | Reported limitations |
|---|---|---|---|
| `review-validation-consistency` | codex | Yes | Code tracing only; no tests, workflow executions, or writes. |
| `review-impact-completeness` | codex | Yes | Read-only; no tests. Full-file reading was not completed for every large touched module and test file. Consumer-map confidence stated as moderate. |
| `review-silent-failures` | codex | Yes | Static traces only; no tests, workflows, or writes. Scoped diff and relevant callers inspected, but full-file reading was not completed for every large touched module and test file. |
| `review-feature-interactions` | codex | Yes | No tests or writes. Changed paths and relevant intersections inspected, but large unchanged sections were not read end to end. Golden-hash execution remains unverified. |
| `review-test-fidelity` | codex | Yes | Read-only; no tests or mutations executed. HEAD interaction inspection was limited and was not a review of the later merge. |

**Failed or missing lenses:** None listed in the supplied gaps input.

All five lenses reported considering ADR-0016, the ruled checkpoint, amendments, and accepted deviations. Their findings do not reopen those settled decisions.
