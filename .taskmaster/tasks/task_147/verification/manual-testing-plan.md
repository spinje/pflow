# Task 147 Manual Testing Plan

> Reusable verification plan for the validator-produces-Diagnostics-natively change.
> Designed to BREAK things, not confirm they work. Use as a regression checklist.

## Mindset

Test suite results (4653 tests pass) are **context, not evidence**. The implementer is also an LLM — its tests may be heavy on substring matching against rendered output, mocks, or happy-path coverage. The plan below probes the parts a test suite is least likely to catch.

## Setup

```bash
mkdir -p /tmp/task147-verify
```

All workflow files below go in `/tmp/task147-verify/`.

---

## Probe 1: Test-helper smell inspection (no execution)

**Why**: The implementer added 19 copies of `_split_validator_diagnostics` / `_split_template_diagnostics` helpers across test files. They preserve the OLD `(errors_str, warnings_diag)` tuple ergonomics by re-splitting the new single list. This is a smell — if the helper is wrong, all 19 callers test nothing meaningful.

**How**:
```bash
grep -A 8 "def _split_validator_diagnostics" tests/test_core/test_workflow_validator.py
```

**Expected**: helper that converts each error Diagnostic to its `format_diagnostic()` STRING and returns `(list[str], list[Diagnostic])`.

**Failure modes to look for**:
1. Filter uses `severity.value == "error"` (string comparison) — fragile
2. INFO severity is dropped silently (not in either list)
3. `errors` is the FORMATTED rendered output, not raw messages → substring matching becomes overly permissive
4. Tests assert on `errors[0]` substring, never on `diagnostic.context["path"]` or `diagnostic.suggestions` — structural fields are NEVER verified by 99% of tests

---

## Probe 2: Bypass paths (consumer surface)

**Why**: `--validate-only` is the easy path. Verify the rich format reaches every OTHER consumer too.

### 2a. Normal `pflow run` (text mode)

```bash
cat > /tmp/task147-verify/broken-run.pflow.md << 'EOF'
# Broken Workflow

## Steps

### writer
- type: write-file
- file_pat: output.txt
- content: hello
EOF

uv run pflow /tmp/task147-verify/broken-run.pflow.md
```

**Expect**: `Error: Validation Error / message / At: / Did you mean / Available fields / →` — full rich format.

### 2b. Normal `pflow run` (JSON mode)

```bash
uv run pflow /tmp/task147-verify/broken-run.pflow.md --output-format json
```

**Expect**: `errors[0].context.path`, `.context.available_fields`, `.context.similar_names`, `.context.node_type` populated. Same fields ALSO at top level (legacy compat).

### 2c. CLI save

```bash
uv run pflow workflow save /tmp/task147-verify/broken-run.pflow.md --name test-broken
```

**KNOWN PRE-EXISTING BUG (not Task 147)**: CLI save bypasses `WorkflowValidator.validate()` entirely. It only does schema validation via `validate_ir()`. So save succeeds for workflows with unknown parameters / unresolved templates / non-existent node refs. The new `Severity.ERROR` filter at `save_service.py:139` is **only reachable from the MCP `execution_service.py` path**, never from CLI save.

### 2d. MCP server validation (untested in this verification round)

Would need an MCP integration test or live MCP server invocation. The MCP path goes through `execution_service.py` which calls `load_and_validate_workflow()` which calls `_validate_and_normalize_ir()` which calls the new error filter. **This is the only production path that exercises `save_service.py:139`.**

---

## Probe 3: Sub-workflow provenance (single level)

```bash
cat > /tmp/task147-verify/child-broken.pflow.md << 'EOF'
# Broken Child

## Steps

### child-writer
- type: write-file
- file_pat: child-output.txt
- content: from child
EOF

cat > /tmp/task147-verify/parent-with-child.pflow.md << 'EOF'
# Parent

## Steps

### invoke-child
- type: workflow
- workflow: ./child-broken.pflow.md
EOF

uv run pflow /tmp/task147-verify/parent-with-child.pflow.md --validate-only
```

**Expect**:
- Message prefixed: `In step 'invoke-child' sub-workflow: ...`
- Context has `sub_workflow_step: "invoke-child"`, `sub_workflow_path: "./child-broken.pflow.md"`
- Child's `node_id` preserved (e.g., `child-writer`), NOT overwritten by parent step_id
- Child's `path` is relative to child IR (`nodes[id=child-writer].params.file_pat`)
- Renderer shows `Sub-workflow: ./child-broken.pflow.md`

---

## Probe 4: Sub-workflow provenance (3 levels deep)

**Why**: Recursion-unwinding bugs hide here. The single-level case can pass while 3-level is broken.

```bash
cat > /tmp/task147-verify/grandchild-broken.pflow.md << 'EOF'
# Grandchild

## Steps

### grandchild-writer
- type: write-file
- file_pat: gc.txt
- content: from grandchild
EOF

cat > /tmp/task147-verify/middle.pflow.md << 'EOF'
# Middle

## Steps

### invoke-grandchild
- type: workflow
- workflow: ./grandchild-broken.pflow.md
EOF

cat > /tmp/task147-verify/parent-deep.pflow.md << 'EOF'
# Deep Parent

## Steps

### invoke-middle
- type: workflow
- workflow: ./middle.pflow.md
EOF

uv run pflow /tmp/task147-verify/parent-deep.pflow.md --validate-only --output-format json
```

**Expect**:
- Message text chains correctly: `In step 'invoke-middle' sub-workflow: In step 'invoke-grandchild' sub-workflow: ...`
- `node_id = "grandchild-writer"` (deepest)
- `path = "nodes[id=grandchild-writer].params.file_pat"` (deepest)
- `sub_workflow_step = ?`
- `sub_workflow_path = ?`

**FOUND BUG (Task 147)**: `_add_child_provenance` at `validator.py:37-39` overwrites `sub_workflow_step` and `sub_workflow_path` on each recursion unwind. The OUTERMOST hop wins:
- `sub_workflow_step = "invoke-middle"` (outermost)
- `sub_workflow_path = "./middle.pflow.md"` (outermost — but the typo is in grandchild!)

A downstream JSON consumer using `sub_workflow_path` to locate the source file lands on `./middle.pflow.md`, but the actual error is in `./grandchild-broken.pflow.md`. Inconsistency between `path`/`node_id` (deepest) and `sub_workflow_path` (outermost).

---

## Probe 5: Sibling sub-workflows (dedup behavior)

**Why**: The Task 147 plan-review correction at `workflow_executor.py:337` changed `node_id=step_id` to `node_id=d.node_id or step_id`. Verify siblings with different node_ids don't get deduped.

```bash
cat > /tmp/task147-verify/sibling-a.pflow.md << 'EOF'
# Sibling A

## Steps

### writer-a
- type: write-file
- file_pat: a.txt
- content: a
EOF

cat > /tmp/task147-verify/sibling-b.pflow.md << 'EOF'
# Sibling B

## Steps

### writer-b
- type: write-file
- file_pat: b.txt
- content: b
EOF

cat > /tmp/task147-verify/parent-siblings.pflow.md << 'EOF'
# Parent

## Steps

### invoke-a
- type: workflow
- workflow: ./sibling-a.pflow.md

### invoke-b
- type: workflow
- workflow: ./sibling-b.pflow.md
EOF

uv run pflow /tmp/task147-verify/parent-siblings.pflow.md --validate-only
```

**Expect**: 2 errors shown, one per sibling, with distinct `In step 'invoke-a'` / `In step 'invoke-b'` prefixes. NOT deduped.

---

## Probe 6: Multi-error workflow (rendering + truncation)

```bash
cat > /tmp/task147-verify/multi-error.pflow.md << 'EOF'
# Many Errors

## Steps

### error-1
- type: shell
- comand: echo hi

### error-2
- type: write-file
- file_pat: x.txt
- content: x

### error-3
- type: shell
- command: echo ${ghost.stdout}

### error-4
- type: write-file
- conent: y
- file_path: y.txt

### error-5
- type: shell
- command: echo ${phantom.stdout}
EOF

uv run pflow /tmp/task147-verify/multi-error.pflow.md --validate-only
uv run pflow /tmp/task147-verify/multi-error.pflow.md --validate-only --output-format json | python3 -c "import json, sys; d = json.load(sys.stdin); print(len(d['errors']), 'errors;', len(d['warnings']), 'warnings')"
```

**Expect**:
- Text mode: `format_validation_failure` truncates display to first 5 errors with `... and N more errors` footer (hardcoded `errors[:5]` at `validation_formatter.py:45`)
- JSON mode: ALL errors present (no truncation)
- 7 errors total (the 5 deliberate ones plus cascading template errors), 1 warning

---

## Probe 7: Negative tests (false positives)

```bash
cat > /tmp/task147-verify/clean.pflow.md << 'EOF'
# Clean

## Steps

### greet
- type: shell
- command: echo "hello"
EOF

uv run pflow /tmp/task147-verify/clean.pflow.md --validate-only
```

**Expect**: `✓ Workflow is valid` plus the cache lint warning (`⚠ [greet] Shell node has no template inputs ...`). Zero errors.

---

## Probe 8: Batch with unresolved template

```bash
cat > /tmp/task147-verify/batch-error.pflow.md << 'EOF'
# Batch Error

## Inputs

### items

Items.

- type: list
- default: [{"name": "a"}, {"name": "b"}]

## Steps

### process
- type: shell
- batch: ${items}
- command: echo ${itm.name}
EOF

uv run pflow /tmp/task147-verify/batch-error.pflow.md --validate-only
```

**FOUND BUG (Task 147 self-consistency violation)**: The defensive `except Exception` wrappers in `validator.py:_validate_data_flow` and `_validate_templates` set `context["exception_type"] = type(e).__name__`. The progress log explicitly forbids producers from setting `exception_type`:

> Keys validator producers MUST NEVER set: `exception_type` — Runtime wrapped-exception path. Renders "Type: X" — suggests unhandled exception.

When this wrapper fires (e.g., on the unresolved `batch: ${items}` template), the user sees `Type: AttributeError` which mimics a runtime crash. The user-facing diagnostic looks like:

```
Error 2: Validation Error
Data flow validation error: 'str' object has no attribute 'get'
  Type: AttributeError
```

Sites: `validator.py:172, 230, 259, 326`. All four were ADDED by Task 147 (`git show d8e7252c -- src/pflow/core/workflow/validator.py | grep exception_type`).

**Pre-existing context**: the wrappers themselves existed before Task 147 (the implementer's progress log says they were "kept"). The crash trigger (`'str' object has no attribute 'get'` from `data_flow.py` not handling unresolved batch templates) is also pre-existing. What's NEW is setting `exception_type` in the wrapper context.

**Also pre-existing (NOT task 147)**: the malformed path `nodes[0]batch` (missing dot) comes from `ir_schema.py:_format_path` at line 335. Logic is `if i > 0 and not formatted.endswith("]"): formatted += "."` — but for `[0, "batch"]`, after `[0]` it ends with `]`, so no dot is added before `batch`. Task 147 didn't touch ir_schema.py.

---

## Probe 9: Compile-time data-flow filter (source review only)

**Why**: The plan-review correction added `errors = [d for d in data_flow_diagnostics if d.severity == Severity.ERROR]` at `compile_validation.py:117`. Currently dormant (no warning producers in `data_flow.py`), but defends against future regressions.

**Verification (no runtime injection needed)**:

```bash
grep -n "Severity.ERROR" src/pflow/runtime/compilation/compile_validation.py
grep -n "Severity\." src/pflow/core/workflow/data_flow.py
```

**Expect**:
- `compile_validation.py:117` has the filter
- `data_flow.py` only emits `Severity.ERROR` (6 sites, no WARNING/INFO)

If `data_flow.py` ever gets a `Severity.WARNING` producer in the future, this test plan should add a runtime probe verifying compile still succeeds when `data_flow.py` returns only warnings.

---

## Cleanup

```bash
rm -rf /tmp/task147-verify
# pflow has no `workflow remove` CLI command, so saved test workflows must be deleted manually:
rm -rf ~/.pflow/workflows/test-broken
```
