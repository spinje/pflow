# Task 154 Progress Log

> **What this file is**: the epistemic trail for this task — decisions, rejected alternatives, reviewer findings that shifted the plan, and non-obvious traps. Complementary to (not redundant with) `task-154.md` (the what/why) and `implementation-plan.md` (the how).
>
> Read this before touching code. Append to it as you work.

---

## 1. Planning journey — what the design NEARLY was and why it isn't

### 1.1 First attempt: "one Python vocabulary everywhere"

Before reviewer input, the plan was going to unify S1 and S2 onto a single Python vocabulary. Rationale: *"Pydantic/FastAPI/Typer/Prefect/Dagster all use Python type hints as the single type language."*

**Why this was wrong**: those are all Python libraries whose contract IS Python. pflow is a workflow format that happens to run Python. Shell nodes, HTTP nodes, LLM nodes, Claude Code nodes don't use Python annotations at all — forcing S1 to speak Python alienates non-Python consumers (CLI users piping values, MCP clients, docs readers) without any corresponding payoff.

Two independent external reviewers caught this with a cleaner framing: *"S1 is a declarative contract; S2 is Python because runtime is Python."* They serve different purposes, so they use different dialects.

**Implication for the implementer**: if you're ever tempted to "simplify" by collapsing the two vocabularies, know this was deliberately rejected. The bridge is documented once; each surface stays in its native dialect.

### 1.2 Four-agent poll on authoring preference

Before external reviewers, I polled four `pflow-codebase-searcher` agents on what vocabulary they'd naturally want as authoring agents. Result: 3 of 4 voted for the unified Python vocabulary. One dissenter (Agent 4) argued exactly what the external reviewers later argued: two vocabularies with an explicit bridge.

**Lesson**: unanimous-ish preference among authoring agents is a weak signal when the alternative has architectural coherence on its side. Don't let "what feels natural" override "what's structurally right" — authoring agents optimize for their own cognitive load, not for system coherence.

### 1.3 Poll P1 — how `any` should work at Surface 2

Three agents polled with three designs:
- **Design A**: `x: any` (lowercase) rewritten to `Any` behind the scenes
- **Design B**: `x: Any` with auto-injection (selected)
- **Design C**: omit annotation for `any` inputs

Result: 3/3 chose B. Most important thing they agreed on: **Design A rejected forcefully** — *"Invisible source rewriting is never invisible when it breaks."* The plan calls for Design B; if a future PR proposes silently rewriting annotations, this decision's rationale explains why not.

Design C rejected because *"missing annotation reads as 'I forgot'; explicit `Any` documents deliberate intent."*

### 1.4 Poll P3 — breaking-change cost/value

Three agents polled on three paths:
- Path A: keep Python aliases silently, only fix `object`-as-wildcard
- Path B: hard errors, ship both breaks atomically (selected)
- Path C: deprecation warnings, two-release cutover

Result: 3/3 chose B, all recommending atomic shipping. Key quote: *"Deprecation warnings are the worst of both worlds — ambiguous, ignored until they become errors anyway."*

This matters because the plan's "hard errors with fix suggestions" posture is not merely stylistic — it's the polled judgment of three independent authoring-agent perspectives. Softening to warnings would walk back a validated decision.

### 1.5 The unresolved split — `number` vs `float`

Polls split 3/1 between:
- *Keep `number` as first-class type* (maps to int-or-float)
- *Use `float` since `int` satisfies `float` per Python convention*

**Resolution**: kept `number`. Reasons: JSON Schema semantics (number = numeric, integer = integer); `integer` distinction gives authors a way to require int-only; bridges cleanly to `int | float` in code.

**Implementer note**: the plan's bridge table shows `number → int | float (or float)` as the Python-side equivalent. Both work; `float` is simpler if the author doesn't care about int narrowing. This isn't a trap, just a documented flexibility.

### 1.6 `?` suffix syntax for optional was considered and rejected

One external reviewer proposed `- type: string?` as ergonomic shorthand for optional inputs. Rejected because it conflates two distinct axes:
- **Absence** (input key may be missing) — expressed by `required: false` + optional `default:`
- **Nullability** (value may be `None`) — expressed by `type: any` today, union syntax later

Collapsing both into `?` is the mistake Pydantic v1 made and v2 untangled. We're keeping them orthogonal from day one.

### 1.7 Strict runtime enforcement deferred to Task 120

This is the single most important scope boundary to preserve.

This PR ships the **vocabulary change**:
- Enum accepts only canonical names
- `object` is documented as dict-only
- `any` is the explicit wildcard
- Error messages teach the new rules

This PR does NOT tighten runtime coercion:
- `coerce_workflow_input` stays lenient
- Existing workflows with `type: object` that actually pass non-dict values will continue to work (leniently) until Task 120 lands

**Why this boundary**: the runtime-strictness change has its own test surface, its own migration complexity, and its own risk profile. Bundling them would make the PR harder to review and harder to revert. The polls specifically endorsed this split.

**Implementer trap**: if you find `coerce_workflow_input` "seems wrong" because it accepts non-dict for `type: object`, that's by design *for this PR*. Don't fix it here — Task 120 is the home for that change.

### 1.8 Three vocabularies intentionally coexist post-refactor

Not two. Three. This is the single most confusing thing about the post-refactor state:

| Surface | Vocabulary | Example | Why |
|---|---|---|---|
| **S1** — workflow IR `## Inputs`/`## Outputs` | 7 canonical JSON Schema names | `type: object` | External contract; readable by non-Python consumers |
| **S2** — Python code-block annotations | Python types (`Any` auto-injected) | `x: dict` | Runtime is Python |
| **S3** — node registry `Interface:` docstrings AND LLM `output_schema` / Claude Code `output_schema` | Python types (not changed) | `Writes: shared["x"]: dict` | Authored by Python library writers; feeds LLM prompt construction for Claude Code (`_build_schema_prompt` embeds names literally into prompts) |

The S1↔S2 bridge is the primary doc artifact. S3 is acknowledged as a deliberate third dialect.

**Implementer trap**: if a reviewer or later contributor says "why don't we unify S3 too?" — the answer is (a) LLM prompt construction embeds literal Python names, (b) node library authors write `Interface:` docstrings as Python annotations, (c) Registry Interface vocab has a different consumer population. The three-dialect coexistence is intentional, not technical debt.

### 1.9 `null` dropped from vocabulary (for now)

Considered adding `null` to the 7-name list. Dropped. Without union syntax (`string | null`, `int | null`), `type: null` on its own means "value must be None" — almost never useful. Value of `null` is in unions; add when unions land.

**Guidance today**: "use `type: any` if the value may be None." This phrasing is deliberately in the `null` rejection error message (plan §3 note 4) — lead with the fix, not the deferred feature.

### 1.10 Complex nested input schemas out of scope

User asked if we could support complex schemas (e.g., `type: object` with `properties:`) — deferred to a later task.

**Relevant context the implementer should know**: pflow already has `yaml output_schema` fenced blocks in Claude Code and LLM nodes for structured output. When complex input schemas are added, the natural implementation reuses that existing flat `{field: {type, description}}` YAML convention. Verified that both `llm` node and `claude-code` node accept the same outer YAML shape (they diverge on internal interpretation — see `src/pflow/nodes/llm/llm.py:285` vs `src/pflow/nodes/claude/claude_code.py:199-214`).

---

## 2. Reviewer findings that reshaped the plan

Five specialized reviewers ran against the draft plan. Findings that changed the plan follow. These are documented NOT in the plan itself (plan shows the corrected end-state) — they live here as the "why this file looks the way it does" record.

### 2.1 Critical — `_coerce_to_any` signature mismatch (`review-plan`)

**Draft plan had**: `def _coerce_to_any(value: Any) -> Any: return value`

**Verified against code**: `param_coercion.py:293` calls `coercer(value, log_context)`. Single-arg signature would `TypeError` on the first `type: any` workflow.

**Plan corrected**: §4.4 now specifies `(value, log_context)` with a code comment referencing this log.

**Trap for the implementer**: the `log_context` parameter is unused in the body but REQUIRED by the dispatcher convention. Don't "clean it up" by removing it.

### 2.2 Critical — diagnostic context pipeline bypass (`review-agent-ux`)

**Draft plan had**: error signal flattened into `SchemaValidationError.suggestion` as a prose string.

**Verified against code**: `src/pflow/core/CLAUDE.md` explicitly documents *"Error handling philosophy — producers are self-describing. Never flatten structured data (paths, fuzzy matches, available fields, suggestions) into string messages for downstream code to reverse-engineer."* The unified renderer in `diagnostic_render.py` already consumes `context["similar_names"]` → "Did you mean" block, `context["available_fields"]` → numbered-list block, `suggestions_list` → multi-suggestion rendering.

**Plan corrected**: extended `SchemaValidationError.__init__` with four structured kwargs (`similar_names`, `available_fields`, `available_fields_label`, `suggestions_list`); introduced `TypeVocabularyError` dataclass that carries both prose and structured fields; threaded them through `_suggest_for_invalid_type` → `_get_suggestion` → `validate_ir`.

**Why this matters**: agents consuming JSON output (`--output-format json`) get programmatic access to the canonical replacement via `context.suggestions_list[0]`. Without this, they'd have to regex-parse prose. Respect the pattern.

### 2.3 Critical — parameterized generic canonical mapping (`review-agent-ux`)

**Draft plan had**: for `list[str]`, error message would produce `"Use 'list'"` or `"Use 'the base type'"`. But `list` is a Python alias, so the fix suggestion was itself illegal — agent would need two round-trips.

**Plan corrected**: the rule is now "if the outer name is in `PYTHON_ALIASES_AT_S1`, suggest its canonical replacement." So `list[str]` → `"Use 'array'"`, `dict[str, int]` → `"Use 'object'"`. One-shot fix.

### 2.4 Critical — `dict` wildcard hint must be multi-suggestion, not prose (`review-agent-ux`)

**Draft plan had**: single prose string `"Use 'object' instead of 'dict' (for a wildcard that accepts any type, use 'any')"`.

**Problem**: ambiguous about WHEN to pick which. Agent has to infer semantics from parenthetical.

**Plan corrected**: populate `suggestions_list` as a two-entry list — renderer emits numbered list:
```
To fix this:
  1. Use 'object' if the value is a dict: - type: object
  2. Use 'any' if the value can be any type: - type: any
```

### 2.5 Rationale correction — `_TYPE_ALIASES` kept, but for the right reason

**Draft plan claim**: `_TYPE_ALIASES` stays because "`_normalize_type()` has downstream consumers (template validation, registry interop)."

**Verified against code**: `_normalize_type()` has exactly ONE caller: `coerce_workflow_input` itself. No downstream consumers.

**Plan corrected**: rationale rewritten to "defense-in-depth for IR paths that bypass schema validation (programmatically-constructed IR dicts, cached IRs, future MCP entry points)." The code stays; the reason is honest.

**Implementer guidance**: if you find this and think "this is dead code, let me remove it" — that's a legitimate follow-up cleanup, NOT this PR's scope. Flag as a follow-up issue.

### 2.6 Documentation inventory undercounted

**Draft plan listed**: ~3 files in `architecture/` and 2 sets of lines in MCP instruction files.

**Reviewer found**:
- `architecture/reference/ir-schema.md` has ~20 Python-alias examples, not 3
- `architecture/reference/template-variables.md` has lines 511-512, 678-683, 986-988 (was marked OPTIONAL; now REQUIRED)
- `mcp-agent-instructions.md:836` and `mcp-sandbox-agent-instructions.md:822` contain `"Use \`object\` as type when you don't know the type (skips validation)"` — directly teaches REMOVED semantics
- `docs/CLAUDE.md` uses the old advice as a voice-style exemplar

**Plan corrected**: §7.8–§7.13 now enumerate all of these explicitly, plus a final grep sweep across `docs/`, `architecture/`, `src/pflow/guide/`, `src/pflow/mcp_server/resources/instructions/`.

### 2.7 `NonRetriableError` not `ValueError` (`review-agent-ux`)

**Draft plan had**: `raise ValueError(...)` in `_check_annotation_vocabulary`.

**Per `src/pflow/nodes/CLAUDE.md`**: node validation errors must use `NonRetriableError`. Vanilla `ValueError` triggers retries (wasteful for deterministic validation failures).

**Plan corrected**: §4.3.2 now imports `NonRetriableError` and raises that subclass.

### 2.8 Disputed — "`integer` missing from compatibility matrix" (false claim)

One reviewer (review-validation-consistency) claimed `TYPE_COMPATIBILITY_MATRIX` lacks an `"integer"` key, saying post-refactor `type: integer` inputs would fail compatibility.

**Verified against code**: `src/pflow/runtime/template_validation/type_checker.py:56` has `"integer": ["any", "int", "integer", "float", "number", "str", "string"]`. The claim is false.

**Lesson**: reviewers are not infallible. When a claim names specific code, verify against that code before acting on it. Several of the "critical" findings above (signature mismatch, misleading NameError) WERE verified real; this one wasn't.

**Kept in plan as §11.2**: the `integer` row is verified present, no action needed.

### 2.9 Lower-priority but confirmed

- **Fuzzy cutoff 0.6, not 0.4** — prevents false positives at 7-item universe (`pool` ≈ `bool` at 0.4).
- **`Any` third-line suggestion** added to input-type-mismatch error ONLY, not result-mismatch — result annotations are author's own intent; suggesting `Any` there tells them to defeat their own contract.
- **Markdown parser line 147 hint change** promoted from OPTIONAL to REQUIRED because `test_markdown_parser.py:2355` asserts on the hint string.
- **Saved workflows** in `~/.pflow/workflows/*/` containing Python aliases will fail on next load/re-save. Changelog entry captures this; no automated migration tool provided (zero external users, manual `sed` is sufficient).
- **Lowercase `any` inside parameterized generics** (`list[any]`) NOT caught by `_check_annotation_vocabulary` — helper only checks outer name. **Correction (post-review)**: earlier draft claimed `list[any]` "will surface as a NameError at exec time." That claim is **false**. Python's `any` is a valid built-in (the `any()` function); `list[any]` evaluates cleanly via PEP 585's `list.__class_getitem__` and no error fires. The annotation is stored; the outer `list` isinstance check passes; the agent never learns `any` is the wrong spelling at S2 inside a generic. Documented limitation; no runtime safety net. Recursive-scan of generic parameters would catch it but is deferred — not a blocker because agents hitting the outer case (`x: any`) will learn the two-surface rule before nesting it.

---

## 3. Non-obvious implementer traps

A collection of "easy to get wrong" items surfaced during planning. None of these appear obvious from reading the plan alone.

### 3.1 The `scratchpad/type-vocabulary-incoherence/repro-files/` probes change behavior post-fix

This is intentional, not a regression:

- `A3-input-type-any.pflow.md` — currently FAILS (pflow rejects `type: any`). Post-fix: **should succeed**. Positive smoke test for the new vocabulary.
- `A1-input-type-dict.pflow.md` — currently succeeds. Post-fix: **should fail** with "Use 'object' if the value is a dict: - type: object" / "Use 'any' if the value can be any type: - type: any" numbered list.
- `A2-input-type-str.pflow.md` — currently succeeds. Post-fix: **should fail** with "Use 'string' instead of 'str'".
- `E-object-wildcard.pflow.md` — continues to parse (lenient coercion unchanged for this PR). Under future Task 120, strict runtime will reject non-dict values.

Do NOT "fix" these files. They're the canonical behavioral probes.

### 3.2 The markdown parser hint change and its test must be atomic

`markdown_parser.py:147` is the hint text `"    - type: str\n"`. `test_markdown_parser.py:2355` asserts `"- type: str" in err.suggestion`. Change one without the other and the test breaks.

Plan §5.3 + §4.11 both cover this — just do them in the same commit.

### 3.3 `TypeSpec.accepts()` has different semantics than `python_code._TYPE_MAP`

`TypeSpec("integer").accepts(True) is False` (JSON Schema strict — `bool` is not `int`).
`_TYPE_MAP["int"] == int` and `isinstance(True, int) is True` (Python lax).

Both coexist intentionally. `TypeSpec.accepts()` has no callers in this PR (it's for Task 120). But future readers will wonder; the `TypeSpec.accepts()` docstring must document this asymmetry so nobody "fixes" it.

### 3.4 `_get_suggestion()` signature change is load-bearing

Existing: returns `str`. Refactored: returns `tuple[str, dict[str, Any]]`.

EVERY existing branch in `_get_suggestion` must be wrapped to return `(existing_return_value, {})` — if any branch still returns a bare string, `validate_ir` crashes with "too many values to unpack" when that branch fires.

Plan §4.2.4 shows the pattern; the implementer needs to apply it to every `return` in the function.

### 3.5 `coerce_param_for_node` still accepts `"str"` — do NOT change it

Registry Interface docstrings use Python names. `coerce_param_for_node` is called at the node-execution boundary where registry metadata meets actual values. It must continue to accept `"str"`. Plan §4.4 is explicit; the test inventory at §6.3 keeps all `TestDictToStringCoercion.test_*_when_type_is_str` tests unchanged.

If you find yourself removing `"str"` support from param_coercion — STOP. That breaks every node that accepts `str`-typed params from registry metadata.

### 3.6 The six alias tests to REMOVE in `test_param_coercion.py` are specifically for `coerce_workflow_input`, not `coerce_param_for_node`

Plan §6.3 lists the six by name. They're at lines 204, 242, 267, 301, 344, 382. Don't confuse them with the `TestDictToStringCoercion` tests (which stay) — those exercise the OTHER function.

### 3.7 Test `test_type_string_conventions.test_type_convention_examples` lists Python names as valid — DO NOT modify

This test codifies the registry `Interface:` convention. Registry stays Python-named. Modifying it would unify S3 into S1, which is out of scope (see §1.8 above).

### 3.8 Claude Code `output_schema` example files parse with "wrong"-looking types

`examples/nodes/claude-code/claude-code-schema.pflow.md` has `type: str`, `type: int`, `type: list`, `type: bool` INSIDE a fenced `\`\`\`yaml output_schema` block. These are NOT workflow-level `## Outputs` declarations — they're a node param value (opaque dict to the outer parser). The IR schema enum shrink does NOT affect them.

Plan §10.6 includes a spot check that this file still validates post-refactor. If it fails, something leaked the schema-enum check into node params.

---

## 4. Implementation notes — what actually happened during coding

This section records the delta between the plan and the real implementation/debugging journey.

### 4.1 Additional workflow-facing test fixtures required migration

The plan's fixture inventory in §5.3 was directionally correct but incomplete.

During implementation, the first wave of failing tests revealed that the break on
workflow-level `inputs.*.type` / `outputs.*.type` affected more **programmatically
constructed IR dicts in tests** than the plan listed. These were not markdown
fixtures; they were direct Python dicts passed into validation, compilation, or
runner flows.

Files updated beyond the original narrow inventory included:

- `tests/test_core/test_output_source_validation.py`
- `tests/test_core/test_workflow_validator_outputs.py`
- `tests/test_execution/test_runner.py`
- `tests/test_mcp_server/test_registry_template.py`
- `tests/test_core/test_workflow_manager.py`
- `tests/test_integration/test_workflow_manager_integration.py`
- `tests/test_runtime/test_cache_integration.py`
- `tests/test_runtime/test_memoization_integration.py`
- `tests/test_runtime/test_initial_params_override_removal.py`
- `tests/test_runtime/test_trace_integration.py`
- `tests/test_cli/test_find.py`
- `tests/test_runtime/test_template_validation/test_type_checker.py`
- `tests/test_runtime/test_template_validation/test_validator.py`
- `tests/test_runtime/test_template_validation/test_unused_inputs.py`
- `tests/test_runtime/test_template_validation/test_batch_item_validation.py`

**Why this matters**: future vocabulary-breaking tasks should search not only for
`.pflow.md` examples and markdown fixture strings, but also for direct IR dicts in
tests. Those bypass the authoring surface but still exercise the same schema
validation path.

### 4.2 `TypeSpec.parse()` had a real precedence bug

The first implementation checked for internal whitespace before handling
parameterized generics.

That produced the wrong error for:

- `dict[str, int]`

Instead of:

- `"Parameterized generics not supported ... Use 'object'."`

it produced:

- `"Whitespace not allowed inside type names."`

This was incorrect because the generic-specific guidance is the actionable fix.

**Final decision**: generic detection must run before the internal-whitespace
check. This is now the actual behavior in `TypeSpec.parse()`.

### 4.3 Alias errors now populate `similar_names`, not just `suggestions_list`

The plan's structured-context work focused mainly on:

- `available_fields`
- `available_fields_label`
- `suggestions_list`

While debugging JSON/diagnostic expectations, it became clear that alias errors
also benefit from carrying the canonical replacement in `similar_names`. Example:

- `str` → `similar_names=["string"]`
- `dict` → `similar_names=["object"]`

**Why this was done**: downstream JSON/MCP consumers already understand the
`similar_names` channel. Reusing it for alias replacement makes these errors more
uniform with typo/fuzzy-match errors and keeps the diagnostic surface coherent.

### 4.4 The `integer -> int` bridge test required both compile-time and runtime seeding

The new test in `tests/test_core/test_ir_schema.py` went through three iterations:

1. Compile without `edges` → failed on compiler structure validation.
2. Compile with `edges`, but no `initial_params` → failed on required-input validation.
3. Compile with `initial_params`, but no `shared["value"]` before engine run → failed template resolution for `${value}`.

The subtle point is:

- `compile_workflow(..., initial_params=...)` satisfies compile-time input validation.
- `WorkflowEngine.run(workflow, shared)` still resolves templates from the **shared
  store context at runtime**.

So the correct end-to-end fixture for this test is:

- pass `initial_params={"value": 5}` to compilation
- seed `shared["value"] = 5` before execution

This is not a bug in Task 154; it is the expected separation between compilation
validation and runtime template resolution.

### 4.5 `TypeSpec.parse()` needed a small structural refactor after behavior was correct

After the implementation was functionally correct, static checks surfaced two
follow-up issues:

- Ruff: `parse()` exceeded the complexity threshold (`C901`)
- mypy: helper calls that always raise were typed as returning `None`, so mypy
  complained about a missing return path

**Final decision**:

- Extracted three helper functions:
  - `_raise_parameterized_generic_error(...)`
  - `_raise_alias_error(...)`
  - `_raise_unknown_type_error(...)`
- Typed them as `NoReturn`

This is a pure maintenance refactor; behavior was intentionally preserved.

### 4.6 Verification constraints in this agent environment were environmental, not code-related

In this coding environment:

- `uv run ...` failed due sandbox restrictions on `/Users/andfal/.cache/uv/...`
- forcing `UV_CACHE_DIR=/tmp/uv-cache` triggered a separate `uv` panic during env creation
- `.venv/bin/python` existed but did not have `pytest` installed

Because of that, verification here relied on:

- `python3 -m py_compile` over changed source and test files
- targeted grep/audit passes
- user-provided failing test output from a real project environment

**Important**: this should not be interpreted as a repository issue. The `uv`
failures observed during implementation were environment/sandbox-specific.

### 4.7 Documentation sweep result: grep hits must be interpreted by surface, not blindly removed

After the doc sweep, remaining grep hits for `type: str` / `type: list` / etc.
were mostly in:

- Claude Code `output_schema` examples
- registry Interface metadata examples
- architecture implementation docs describing registry/template-validation internals

Those are legitimate S3 / registry-Python surfaces, not missed S1 migrations.

**Operational lesson**: broad grep is necessary, but final judgment must be made by
surface:

- S1 workflow `inputs` / `outputs` examples → canonicalize
- S2 code annotations / S3 registry Interface / Claude `output_schema` → preserve

### 4.8 No production runtime strictness changes were made beyond the plan boundary

While fixing the failing tests, multiple places still exposed the pre-existing
semantic looseness around `object` and lenient coercion. None of those were
tightened in this task.

This boundary was consciously preserved:

- vocabulary and messaging changed
- coercion strictness did not
- runtime `object` enforcement remains Task 120

That boundary held during implementation despite several tempting adjacent fixes.

---

## 4. Verification strategy reasoning

The plan's §10 verification is structured this way on purpose. Context:

- **§10.1 automated gates** (`make test`, `make check`) — first line of defense
- **§10.2 probe-based manual verification** — catches behavioral regressions the automated tests don't cover (because tests use mocks; probes exercise the full CLI)
- **§10.3 error-message spot checks with CASE-SENSITIVE `grep`** — reviewers specifically asked for this because the initial draft used `grep -i` which would have hidden accidental case regressions. "Use 'string'" (capital U) is the contract; a refactor that lowercased it would silently pass `grep -i`.
- **§10.3 JSON output check** — validates the diagnostic context pipeline (the critical finding from §2.2). If prose works but structured context isn't populated, this test catches it.
- **§10.6 regression smoke tests** — specifically includes `claude-code-schema.pflow.md` to verify the "three vocabularies coexist" design (§1.8) didn't accidentally collapse.
- **§10.2 "Post-fix behavior" appendix to bug-report.md** — future readers see both the bug AND the fix captured in the same file. Avoids a stale bug report.

If you're tempted to skip any of these: they each catch a category of bug that the automated tests miss. Don't skip.

---

## 5. Methodology notes for future similar tasks

### 5.1 Agent-opinion polling worked

Two polls (P1: `any` semantics at S2, P3: breaking-change path) generated 3-4-agent unanimous consensus that validated non-obvious design calls. The methodology: describe the situation neutrally (no leading options), ask for unbiased preference, compare results.

**When to use**: agent-facing UX decisions where the "natural" answer isn't obvious from architecture principles.

**When NOT to use**: architectural decisions (§1.1 showed polls voted wrong relative to what external reviewers caught). Cross-check with reviewers or analogy to proven systems.

### 5.2 Five-reviewer plan review caught real bugs

`/code-review` with 5 specialized agents (`review-plan`, `review-impact-completeness`, `review-validation-consistency`, `review-feature-interactions`, `review-agent-ux`) ran in parallel. Caught:
- 1 crash-level bug (`_coerce_to_any` signature)
- 1 architectural mismatch (diagnostic context bypass)
- 1 agent-UX regression (parameterized generics wrong canonical name)
- 4 doc inventory omissions

Cost: ~15 minutes of reviewer time. Saved: hours of implementation rework if these had surfaced at test time.

**When to use this pattern again**: complex refactors that touch shared abstractions. Not for single-file bug fixes.

### 5.3 Trust-but-verify reviewer claims

Reviewer `review-validation-consistency` claimed `integer` was missing from `TYPE_COMPATIBILITY_MATRIX`. Reading the code showed it's at line 56. One false positive out of six critical findings — not bad, but always verify.

---

## 6. Implementation steps (reference)

Full step-by-step plan is in `implementation-plan.md` §8. Not duplicated here.

---

## 7. Live log

Append below as you work. Timestamp + what happened + what you learned. Keep entries append-only.

### [2026-04-16 pre-implementation] — Plan approved; progress log created

Plan reviewed by 5 specialized reviewers. 6 critical findings + 9 warnings + 6 suggestions applied. User approved plan via ExitPlanMode. Task 154 created. This progress log created to capture reasoning trail separately from the plan/spec.

**Next step**: begin implementation at §8 step 1 (create `src/pflow/core/types.py`).

---

### [2026-04-16 post-fix code review] — 4-agent code review + ten review-prompted fixes landed

What I'm doing: ran `/code-review` skill with 4 specialized agents on the staged PR (impact-completeness, agent-ux, feature-interactions, validation-consistency). Evaluated findings, classified confidence, implemented three rounds of fixes in priority order. Agents deployed in parallel; each reviewed from its specific blindspot category. This captures the delta from the pre-review staged state.

**Review inventory:**
- 1 critical finding (agent-ux + feature-interactions both flagged): parameterized-generic prose lost at rendered CLI/JSON layer — `suggestions_list` preempts `suggestion` in `SchemaValidationError.to_diagnostics()`, so the full "Parameterized generics not supported" message never reached users. Only the terse "Use 'array'" survived. Confirmed real.
- 7 confirmed warnings across the agents
- 6 suggestions, some out-of-scope
- 2 disputed (TypeVocabularyError base class, asymmetric diagnostic shape for `_check_annotation_vocabulary`)

**Pass 1 — minimum-viable merge set (items #1, #3, #6, #7, plus bonus)**:
- `src/pflow/core/types.py` — `_raise_parameterized_generic_error` now emits self-contained `suggestions_list=[f"Use '{canonical}' — parameterized generics not supported at ... (got {raw!r})"]`. Full WHY surfaces at both CLI and JSON output layers.
- `src/pflow/core/types.py` — `null` branch now carries `suggestions_list=["Use 'any' if the value may be None"]` for parity with alias errors.
- `src/pflow/core/ir_schema.py` — enum description strings now `f"Data type: one of {', '.join(CANONICAL_TYPES)}"` (drift-proof).
- `src/pflow/core/param_coercion.py` — `_TYPE_ALIASES` comment rewritten to cite the concrete production bypass path (template-referenced sub-workflows via `sub_workflow_resolver.py`) instead of generic "defense-in-depth."
- **Bonus simplification (null-through-markdown)**: during verification I noticed `type: null` in markdown parses to Python `None`, hitting jsonschema's `type` validator (not `enum`), so my #3 fix for `TypeSpec.parse("null")` was unreachable via the real markdown authoring path. Fixed at the routing layer instead:
  - `_get_suggestion` now uses a list-based path check (`len(path_list) >= 3 and path_list[0] in ("inputs", "outputs") and path_list[-1] == "type"`) — precise, catches both validator errors (`enum` AND `type`), and avoids the prior `"type" in path_str` substring fragility that accidentally matched `nodes[N].type`.
  - `_suggest_for_invalid_type` maps `offending is None` → `"null"` so it reaches the `TypeSpec.parse("null")` branch and produces the right suggestion.
  - `_get_output_suggestion` case 3 removed — dead code after the routing upstream refactor.
  - Added regression test `test_null_as_python_none_rejected_with_same_suggestion` in `test_ir_schema.py`.
- `progress-log.md` §2.9 corrected: the earlier claim that "lowercase `any` in `list[any]` will surface as a NameError at exec time" was **false**. Python's `any` is a valid built-in (the `any()` function); `list[any]` evaluates cleanly via PEP 585's `list.__class_getitem__`. Documented as a limitation without a runtime safety net; recursive-scan would catch it but deferred.

Result:
- ✅ All 4842 tests pass (+1 from baseline: the null-through-markdown regression guard)
- ✅ `make check` clean
- ✅ CLI/JSON output for `type: list[str]` now surfaces the full prose with canonical fix
- ✅ CLI/JSON output for `type: null` in markdown now surfaces "Use 'any' if the value may be None" instead of the generic "Change type from 'NoneType' to 'string'"

**Pass 2 — opinionated NameError hint + canonical syntax table (items #2, #5)**:
- `src/pflow/nodes/python/python_code.py` — extracted `_suggest_for_nameerror()` helper. Three categories, ONE canonical fix per case (no menus):
  - `_MODERN_GENERIC_NAMES = {"List", "Dict", "Tuple", "Set", "FrozenSet", "Type"}` → "Use '{lower}[...]' instead — Python 3.9+ supports lowercase built-in generics (PEP 585). Example: ..."
  - `"Union"` → "Use pipe syntax instead: 'A | B' (PEP 604). Example: ..."
  - `_REQUIRES_TYPING_IMPORT = {"Literal", "TypeVar", "Callable", "Final", "ClassVar", "Iterable", "Iterator", "Sequence", "Mapping"}` → "Add 'from typing import X'"
  - Not a known typing name → original input-variable suggestions
- `_format_exec_error` NameError branch simplified from ~40 lines of inline conditionals to 4 lines + delegation.
- Tests: renamed `test_nameerror_for_typing_symbol_suggests_import` → `test_nameerror_for_union_suggests_pipe_syntax`; added `test_nameerror_for_list_suggests_lowercase_generic`; added `test_nameerror_for_literal_suggests_import`. Each asserts the opinionated hint AND that the other fix isn't mentioned (no menu).
- `src/pflow/guide/nodes/code.md` — new "Type annotation syntax" section with the canonical table (Any, built-in scalars, list[T], dict[K,V], tuple[T,...], set[T], A | B, Optional[T] | T | None). Auto-inject list stated explicitly (`Any`, `Optional`, `typing`). Explicit "Not allowed" list for `List[T]`/`Dict`/`Union`/etc. Notes outer-type-only enforcement.
- `src/pflow/guide/core.md` — one-line pointer at the S1↔S2 bridge table directing to `pflow guide code`.
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` and `mcp-sandbox-agent-instructions.md` — the "Use `Any`..." bullet replaced with modern-syntax summary; pointer line added at the bridge table. Two mirror files kept in sync.

Rationale (FastAPI/Pydantic/Typer pattern): opinionated tools give ONE canonical answer per case, not a menu of options. The NameError hint for `List[str]` was previously a two-option menu with Union/Optional examples that didn't match the variable the agent typed — leading to an agent pattern-match failure. The opinionated hint now teaches PEP 585/PEP 604 as a side effect of the error itself.

Result:
- ✅ All 4844 tests pass (+2 from the prior step: List opinionated hint, Literal import suggestion)
- ✅ CLI output for `List[int]` now reads: "Use 'list[...]' instead — Python 3.9+ supports lowercase built-in generics (PEP 585). Example: 'x: list[str]' instead of 'x: List[str]'."
- ✅ CLI output for `Union[int, str]` reads: "Use pipe syntax instead: 'A | B' (PEP 604). Example: ..."
- ✅ CLI output for `Literal["a"]` reads: "Add 'from typing import Literal' at the top of your code block. (pflow auto-injects 'Any' and 'Optional' — other typing names need explicit import.)"

**Pass 3 — renderer cleanup + drift guards (items A, B, C)**:
- `src/pflow/core/diagnostic_render.py` — `_format_available_fields_block` truncation policy changed: show all entries when `len(available) <= 10`, truncate only beyond. Rationale: for a 7-item closed set (the canonical type vocabulary), hiding 2 types under "... and 2 more (in error details)" was actively hostile UX — the agent had to pivot to `--output-format json` to see them. Truncation was designed for 100-item registries, not small closed vocabularies. Change affects every error with `available_fields`, not just type errors.
- `tests/test_core/test_param_coercion.py` — new `TestTypeAliasesSyncWithCanonicalSource` class with `test_alias_maps_stay_in_sync`: asserts `param_coercion._TYPE_ALIASES == types.PYTHON_ALIASES_AT_S1`. Prevents silent drift between the runtime-lenience map and the validator error-suggestion source. Cheap regression guard against a real drift risk (both maps define the same 6 Python→canonical mappings; edit one without the other and template-referenced sub-workflows silently diverge from what `validate_ir` teaches).
- `tests/test_runtime/test_prepare_inputs_coercion.py` — `test_type_aliases_work` renamed to `test_type_aliases_work_as_defense_in_depth` with an expanded docstring warning future agents NOT to misread the test as "Python aliases are supported S1 vocabulary." They're rejected at the validator per Task 154; the test pins the DEFENSE-IN-DEPTH behavior for IR paths that legitimately skip validation (template-referenced sub-workflows). Without this clarification, a future cleanup agent could remove both the test AND `_normalize_type` together, breaking the bypass path.

Result:
- ✅ All 4845 tests pass (+1 from the prior step: alias-map sync guard)
- ✅ `make check` clean
- ✅ Rendered output for `type: str` now shows `Available types (showing 7 of 7):` with all types listed. No more "... and 2 more (in error details)" noise.

**Deliberately NOT done (reviewer findings deferred or disputed):**
- `TypeVocabularyError` continues to subclass `ValueError` not `PflowError`. Agent-UX review (S8) flagged this as a `core/CLAUDE.md` convention violation, but `TypeVocabularyError` is always caught internally by `_suggest_for_invalid_type` and converted to `SchemaValidationError` (which IS `PflowError`-derived). Switching the base would likely require a circular-import refactor. Flagged as a Task 120 concern if/when future callers raise without wrapping.
- `_check_annotation_vocabulary` keeps prose-based `NonRetriableError` without structured context. Agent-UX review (S9) flagged asymmetric diagnostic shape vs IR-schema-layer errors, but the audiences are genuinely different (authoring agent reading CLI vs external JSON/MCP consumers).
- `pflow describe` / `pflow list` spot check on old-vocab saved workflows (feature-interactions W1) — not run. Any issue here is a separate saved-workflow-display bug, not Task 154's vocabulary scope.
- `TypeSpec.parse` whitespace silent-accept kept (impact-completeness W2). Plan explicitly left this to implementer discretion; silent-accept is copy-paste-tolerant.
- Pre-existing `value:` hint in `markdown_parser.py:163` (impact-completeness W1 + agent-ux S10) — pre-existing bug from before Task 154. Scope-disciplined skip.
- Cascading spurious template-validation errors for typo/generic type rejections (validation-consistency W2) — cosmetic, not wrong. The authoritative schema error is first in the list. Follow-up candidate if it bites.

**Lessons worth keeping for future similar refactors:**
- **Reviewer cross-confirmation is the strongest confidence signal.** The parameterized-generic prose loss was flagged independently by both review-agent-ux and review-feature-interactions. That's what promoted it from "noted" to "critical fix."
- **"Prioritize simplicity of final code, not ease of getting there" (user principle) applied twice**: once pushing the NameError hint from category-with-menu to one-canonical-fix-per-case, once pushing the null-through-markdown fix from a special-case branch to a broadened list-based path check that deleted a dead code path. Both cases: the simpler final shape required more upfront thought than the patch-the-symptom fix.
- **The rendered-output probe that surfaced the null-through-markdown gap** (running the probe on the actual CLI, not just the unit test) caught the gap that unit tests missed. The unit test was passing because it called `TypeSpec.parse("null")` directly; the markdown authoring path never reaches that code. Integration probes > unit tests for user-facing error UX.

**Cumulative PR totals:**
- 4845 tests pass (+4 new regression guards: null-through-markdown, opinionated List hint, opinionated Literal import hint, alias-map drift guard)
- `make check` clean (ruff, ruff-format, mypy, deptry)
- 9 review findings closed as code changes, 1 closed as progress-log correction
- 6 findings deliberately deferred with documented rationale

Next: task ready for user review. PR branch `fix/type-vocab-incoherence` carries the complete refactor + review-prompted polish. Per user preference, no commits or pushes without explicit instruction.

**Pass 4 — one high-value cross-layer regression guard**:
- `tests/test_core/test_ir_schema.py::TestInputTypeAliases::test_full_render_pipeline_for_type_vocabulary_error` — single in-process test exercising the full pipeline: `validate_ir` → `SchemaValidationError.to_diagnostics()` → `format_diagnostic()` → rendered string.
- Asserts: (a) exact case-sensitive `"Use 'string' instead of 'str'"` (poll P3 contract), (b) `"Available types (showing 7 of 7)"` (Pass 3 A truncation policy), (c) all 7 canonical types listed, (d) `"Did you mean"` block present (similar_names threading).
- Decided in-process over subprocess: same coverage, ~160x faster (3ms vs 500ms). Subprocess only adds "does the CLI entry actually wire format_diagnostic" verification, which is a stable contract with no current risk. Per `core/CLAUDE.md`: "CLI, JSON, and MCP all flow through the same `format_diagnostic()` pipeline — the only place rendering happens" — testing it directly covers every consumer.
- Why this test is the single high-value addition: every existing test covers one layer in isolation (TypeSpec parse, TypeVocabularyError fields, Diagnostic context, format_diagnostic behavior). No existing test pins the full chain's output contract. Would have caught the critical review finding (parameterized-generic prose loss from Pass 1) before it shipped — the prose was in `SchemaValidationError.suggestion` but preempted by `suggestions_list` in `to_diagnostics`; any per-layer test passed. Only an end-to-end rendering test would have caught it.
- Failure modes it guards against: renderer refactor drops suggestions_list preemption, suggestion wording lowercase regression, available_fields truncation revert, similar_names threading breakage.

**Final cumulative totals:**
- 4846 tests pass (+5 new regression guards: null-through-markdown, opinionated List hint, opinionated Literal import hint, alias-map drift guard, full-render-pipeline cross-layer guard)
- `make check` clean
- 10 review findings closed as code changes, 1 closed as progress-log correction
- 6 findings deliberately deferred with documented rationale
- 1 high-value test added targeting the single gap unit tests can't cover (full rendering chain)

---

### [2026-04-16 post-implementation verification] — Full §10 verification run

What I'm doing: executing the plan's §10 verification checklist against the staged implementation in the user's real environment (previously blocked by sandbox `uv` failures per §4.6).

Result:

**Automated gates (§10.1):**
- ✅ `make check` → all pre-commit hooks pass (ruff, ruff-format, mypy, deptry). `Success: no issues found in 177 source files.`
- ✅ `make test` → **4841 passed in 13.44s**. Zero failures across the full suite including the 16 fixture-migrated test files from §4.1.

**Probe-based verification (§10.2):**
- ✅ `A3-input-type-any.pflow.md --validate-only` → `✓ Workflow is valid` (was failing pre-fix).
- ✅ `A1-input-type-dict.pflow.md` → rejected; rendered output shows the two-entry numbered list exactly as planned (`Use 'object' if the value is a dict` / `Use 'any' if the value can be any type`).
- ✅ `A2-input-type-str.pflow.md` → rejected with `→ Use 'string' instead of 'str'`.
- ✅ `B2-annot-Any.pflow.md` → runs successfully without `from typing import Any`; outputs `dict` as expected.
- ✅ `E-object-wildcard.pflow.md` → still parses (lenient coercion unchanged per scope boundary §1.7); produces `type=str value='hello'` — Task 120 will tighten.
- ✅ `integer→int` bridge probe (custom `/tmp/int-bridge.pflow.md`) → exits 0, result=10. The `integer` canonical name bridges cleanly to Python `int` via `TYPE_COMPATIBILITY_MATRIX`.

**Error-message wording spot-checks (§10.3):**
- ✅ `Use 'string'` (exact case, capital U) — case-sensitive grep match.
- ✅ `Use 'object' if the value is a dict` + `Use 'any' if the value can be any type` — both numbered-list entries present.
- ✅ `Did you mean 'string'` — fuzzy match fires for `strin` typo.
- ✅ `→ Use 'array'` — canonical replacement for `list[str]` generic (not `Use 'list'`, not `Use 'the base type'`).
- ✅ Outputs-side symmetry — `## Outputs` `type: str` produces same `Use 'string'` suggestion as inputs.

**JSON structured-context check (§10.3):**
- ✅ `--output-format json` diagnostics carry `context.similar_names=['string']`, `context.available_fields=['string','number','integer','boolean','array','object','any']`, `context.available_fields_label='types'`, `suggestions=["Use 'string' instead of 'str'"]`. Producers-are-self-describing pipeline intact.

**Any injection / lowercase-any rejection (§10.4–§10.5):**
- ✅ `x: Any` in code block works without import.
- ✅ Lowercase `x: any` rejected with `Use 'Any' (capitalized) in Python code blocks. pflow auto-injects typing.Any — no import needed.` — teaches the two-surface model.

**Regression spot checks (§10.6):**
- ✅ `examples/nodes/claude-code/claude-code-schema.pflow.md` does NOT regress from the IR enum shrink. The `type: str`/`int`/`list` inside the fenced `yaml output_schema` block is a node param value (opaque to the IR enum check). The file has pre-existing template-reference errors unrelated to this PR (`${input.code_content}` wiring); those are not Task 154's concern.
- ✅ `B1-annot-dict.pflow.md` — `type: object` with a dict value runs cleanly; lenient coercion path unchanged.

**Documentation spot-checks (§10.7):**
- ✅ `pflow guide core` renders `type (string|number|integer|boolean|array|object|any)` — seven canonical names including `integer` and `any`.
- ✅ `pflow guide code` renders `Use Any as the type when you don't want type validation (Any is auto-injected — no from typing import Any needed)`.

**bug-report.md appendix (§10.2):**
- ✅ Present at `scratchpads/type-vocabulary-incoherence/bug-report.md` lines 450–504. My earlier evaluation missed this because the scratchpads directory is untracked (not in `git diff --staged`); the file is on disk and the content matches the plan's requirement.

**Minor finding — documented here, not a blocker:**
- 💡 The `TypeVocabularyError` message for parameterized generics (`"Parameterized generics not supported in `## Inputs` / `## Outputs`. Got: 'list[str]'. Use 'array'."`) is preserved in the error's `.message` / `str(exc)` but the renderer surfaces only `suggestions_list=["Use 'array'"]` because `suggestions_list` preempts the `suggestion` string in `SchemaValidationError.to_diagnostics()` (`exceptions.py:199-204`). Plan §10.3 expected a grep for `"Parameterized generics not supported"` to return a line — at the rendered-CLI layer it doesn't, only at the unit-test layer (where `test_parse_rejects_parameterized_generics` in `test_types.py` asserts against the full message). The user-facing rendered output is still actionable — the jsonschema's own message (`'list[str]' is not one of [...]`) plus the `Use 'array'` fix together give the author enough to correct the type. If future work wants the full prose surfaced at the CLI too, populate `suggestions_list` with a single richer entry like `["Parameterized generics not supported — use 'array' (generic parameters aren't enforced at S1)"]`. Flagging as a **follow-up candidate, not a blocker** for this PR.

- 🔀 Decision: do not widen scope. The rendered output meets the "actionable fix" bar even without the full prose. The single-phrase suggestion (`Use 'array'`) is the canonical form used across all vocabulary errors — changing only the generic case would create inconsistency.

**Scope boundary held:**
- Lenient coercion on `coerce_workflow_input` untouched — `type: object` with non-dict values still passes through with a warning (Task 120's scope per §1.7).
- `_TYPE_ALIASES` + `_normalize_type` kept in `param_coercion.py` per §2.5 (defense-in-depth).
- Registry `Interface:` docstrings unchanged (S3 stays Python-named per §1.8).
- Claude Code `output_schema` Python names preserved (intentional third dialect).

Next: all verification gates green. PR is ready for user review. Recommended next step: user runs `git diff --staged` and decides on commit/push cadence (per their standing preference, I am NOT to commit or push without explicit instruction).

---

### [2026-04-16 post-merge-review round 2] — Second review pass + architecture-level simplification

What I'm doing: second code review came in (scratchpad `code-review-task-154.md` + PR comment #4263057796). Evaluated via 4 parallel `pflow-codebase-searcher` subagents with explicit framing "simplicity of final code, not ease of getting there — what would top-10% codebases do?"

**Findings inventory:**
- Critical #1 (scratchpad): runtime sub-workflow compilation accepts banned S1 aliases via `coerce_workflow_input`'s `_TYPE_ALIASES`. Template-ref children (`workflow: ${var}`) bypass `validate_ir`. Confirmed reachable via `examples/nested/deep-research/deep-research.pflow.md:72`.
- Warning #2 (both reviewers): `_check_annotation_vocabulary` only rejects outermost `any` — misses `list[any]`, `dict[str, any]`, `int | any`.
- Warning #3 (scratchpad): `TypeSpec.python_type()` encodes looser isinstance-compatible semantics than `accepts()` — zero production callers, reintroduces bool-coercion trap if ever used.
- Warning #1 (PR comment): Claude Code `output_schema` is a fourth surface still using Python aliases — undocumented in `types.py`.
- Warning #3 (PR comment): Redundant `similar_names` + `suggestions_list` for `dict` alias — agent sees `object` three times.

**The pivot — Option B → Option D for the critical finding:**

Initial plan: reject aliases inside `coerce_workflow_input` (Option B, local/safe). After searcher evidence I switched to Option D — add `validate_ir` at the one unvalidated entry point (`workflow_executor.py:202`) and delete the entire dual-map machinery. Agent 1 proved the mechanics:

- `coerce_workflow_input` has exactly ONE direct caller (`ir_preparation.py:155`).
- `coerce_param_for_node` does NOT use `_TYPE_ALIASES` — structurally independent (registry metadata consumers still read `"str"` literally).
- Every IR entry point hits `validate_ir` except `workflow_executor.py:202` (template-ref bypass).
- Adding one `validate_ir` call there makes `_TYPE_ALIASES` + `_normalize_type` + drift-guard test + defense-in-depth test provably dead.

Agent 4 confirmed `compilation/CLAUDE.md` documents a "dual-layer" convention, but the specific template-ref bypass is an *asymmetry* (not a deliberate layering choice — file/name/inline children DO validate recursively; only template-ref skips). Closing the asymmetry aligns with the codebase intent.

**Top-10% framing**: single validation invariant at `compile_workflow` entry > defense-in-depth tolerance on one path. Option D removes ~40 lines + 2 tests, adds 1 line + 1 test. Strictly simpler final state.

**Regex vs AST for `_check_annotation_vocabulary`:**

Agent 2 found that `ast` is already imported in `python_code.py` (used by `_extract_annotations`). AST walk is ~5 lines, handles `Literal['any']` correctly without the regex approach's quote-strip workaround. "Second paradigm" concern is weak when `ast` is already the file's parsing tool. Picked AST.

**Dropping `similar_names` for alias errors:**

Agent 3 found that 14 of 15 `similar_names` producers populate it for fuzzy-guessing (the rendered header literally says "Did you mean one of these?" — uncertainty framing). `_raise_alias_error` was the lone outlier using it in known-canonical sense. The `null` branch already followed the "suggestions_list only" pattern. Dropping aligns aliases with existing convention.

**Execution — changes landed:**

- `src/pflow/runtime/workflow_executor.py:~207` — added `normalize_ir(workflow_ir); validate_ir(workflow_ir)` before `compile_workflow(...)`. Import updated to `from pflow.core.ir_schema import normalize_ir, validate_ir`.
- `src/pflow/core/param_coercion.py:15-38` — DELETED `_TYPE_ALIASES` + `_normalize_type`. Call site at line 298 now uses `declared_type` directly.
- `src/pflow/nodes/python/python_code.py:197-223` — rewrote `_check_annotation_vocabulary` as `ast.parse(mode="eval")` + `ast.walk` looking for `ast.Name(id="any")`. Hoisted `from pflow.nodes.file.exceptions import NonRetriableError` to module top.
- `src/pflow/core/types.py:177-198` — removed `similar_names=[canonical]` from both branches of `_raise_alias_error` (dict two-suggestion case AND single-canonical case). Added docstring explaining the channel split.
- `src/pflow/core/types.py:127-143` — DELETED `TypeSpec.python_type()`. Zero production callers; Task 120's documented extension point is `accepts()`.
- `src/pflow/core/types.py` module docstring — added paragraph acknowledging Claude Code `output_schema` as deliberate fourth Python-aliased surface (embedded literally into LLM prompts by `_build_schema_prompt`).
- `tests/test_core/test_param_coercion.py` — DELETED `TestNormalizeType` + `TestTypeAliasesSyncWithCanonicalSource` (drift-guard vacuous without duplication). Removed `_normalize_type` from imports.
- `tests/test_runtime/test_prepare_inputs_coercion.py:184-210` — DELETED `test_type_aliases_work_as_defense_in_depth`. Its reason for existing (pinning the bypass behavior) is gone.
- `tests/test_core/test_types.py:136-144` — DELETED `TestTypeSpecPythonType.test_python_type_mapping`.
- `tests/test_core/test_types.py:174` — updated `similar_names` assertion from `["string"]` to `[]` on alias error.
- `tests/test_core/test_ir_schema.py:560` — updated JSON context test: `similar_names` now `[]` for alias errors.
- `tests/test_core/test_ir_schema.py:603` — updated `test_full_render_pipeline_for_type_vocabulary_error`: assertion inverted from `"Did you mean" in rendered` to `"Did you mean" not in rendered`. Updated docstring to reflect the new contract.
- `tests/test_nodes/test_python/test_python_code.py` — added 5 tests: `test_lowercase_any_in_list_generic_rejected`, `test_lowercase_any_in_dict_value_rejected`, `test_lowercase_any_in_pipe_union_rejected`, `test_lowercase_any_in_optional_rejected`, `test_literal_string_any_not_rejected` (pins the carve-out — `Literal['any']` passes as `ast.Constant`, not `ast.Name`).
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py` — added `TestTemplateRefSubWorkflowValidation` with two tests: `test_compile_rejects_python_alias_in_child_ir` (pin the bypass close) and `test_compile_accepts_canonical_type_in_child_ir` (pin canonical still works).
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py:477-502` — `test_compilation_error` fixture IR updated from `{"invalid": "ir"}` to `simple_workflow_ir` so validate_ir passes and the mocked `compile_workflow` is what raises (the path this test actually pins).

**Stumbles encountered + resolved:**

- First test run: 31 failures. Root cause — `validate_ir` requires `ir_version`, but many runtime/test paths construct IRs without it. Fix: added `normalize_ir(workflow_ir)` before `validate_ir` (mirrors `validator.py:731` — `normalize_ir` is the canonical pre-validation step). Failures dropped to 3.
- `test_compile_rejects_python_alias_in_child_ir` expected `SchemaValidationError` but `_compile_sub_workflow` wraps all exceptions in `CompilationError`. Updated test to assert on `CompilationError` with `"Use 'string' instead of 'str'"` in the message — exception path pins both the rejection AND the structured suggestion survives the wrapping.
- `test_python_aliases_no_longer_coerce` (my own test) asserted wrong behavior — deleted it. The behavior is now pinned at the workflow_executor level where it actually matters.
- `ruff-format` / `end-of-file-fixer` auto-fixed trailing whitespace and formatting on two test files. Re-ran `make check` — clean.

**Final cumulative totals after round 2:**
- ✅ **4849 tests pass** (was 4846 before this round; +5 nested `any` tests + 2 template-ref regression tests – 2 deleted drift-guards – 1 deleted defense-in-depth pin – 1 deleted python_type pin – 1 redundant new-test deletion = net +3)
- ✅ `make check` clean (ruff, ruff-format, mypy, deptry)
- ✅ **Net code delta: deletions > additions.** ~40 lines removed (`_TYPE_ALIASES`, `_normalize_type`, `python_type`, 3 obsolete tests); 1 line + ~5 lines + ~5 tests + 1 docstring paragraph added.
- ✅ CLI rendered output verified via in-process probe: `type: str` → directive `→ Use 'string' instead of 'str'` (no "Did you mean"); `type: dict` → numbered list "1. Use 'object'... 2. Use 'any'..."; `type: strin` (typo) → keeps "Did you mean 'string'" (typo channel intact).
- ✅ Nested `any` probe verified: `list[any]`, `dict[str, any]`, `int | any`, `Optional[any]` all rejected; `Literal['any']` passes through; `Any` (capitalized) unaffected.

**Invariants established:**
- **Single validation boundary at `compile_workflow` entry**: every IR path now runs through `validate_ir` before reaching coercion. No production path tolerates Python aliases; `_TYPE_ALIASES` is gone, not "deprecated."
- **Uniform alias-error convention**: `similar_names` is strictly the typo / "Did you mean" channel; `suggestions_list` is the directive / known-fix channel. Dropping the blur between them matches 14 of 15 existing producers.
- **AST-based annotation vocabulary check**: `list[any]` and all generic-nested variants are caught at the same layer as `x: any`. No runtime-only escape hatch.
- **Claude Code `output_schema` is documented as the deliberate fourth surface**: future agents won't mistake its Python aliases for leaked S1 vocabulary.

**Patterns worth keeping for future similar refactors:**
- **"Simplest final code > smallest local change"** — the Option B→D pivot came from asking the searchers to frame options by end-state simplicity. Option B would have worked; Option D deleted more code and restored a cleaner invariant.
- **Check if the language primitive is already imported before adding a new paradigm.** `ast` was already in `python_code.py` for `_extract_annotations`; adding AST-walk for `_check_annotation_vocabulary` added zero imports. The "second paradigm" objection was weak when checked against the file.
- **"Did you mean" framing is the semantic test for similar_names usage.** The rendered template says it literally; any known-canonical case that populates it fights the renderer's intent.

Next: task complete. PR branch `fix/type-vocab-incoherence` carries two consolidation passes (post-merge review round 1 from previous entry + this round 2 architecture pass). Per user preference, no commits or pushes without explicit instruction.

---

### [2026-04-16 round-2 verification + follow-ups]

What I'm doing: end-to-end verification of round-2 changes ("try to break it, don't confirm it works"), then addressing one doc gap that became obvious during verification.

**Verification — all 14 authoritative probes pass the post-fix contract (`bug-report.md:450-504`):**
- A1/A2/A3 via real CLI: `type: dict` → numbered list; `type: str` → directive `→ Use 'string'`; `type: any` → accepted. No "Did you mean" on alias errors; preserved on typos (`strin`).
- B1/B2/B3: all three run cleanly, confirmed with `--no-cache` to bust memoization (first run showed `↻ cached` which could have been pre-refactor results).
- C/C4/D1-D3/E/F/G: runtime behavior matches scope-boundary expectations. `E-object-wildcard` leniency preserved (Task 120 territory).

**Custom probes that matter:**
- Template-ref bypass close — ran parent with `workflow: ${child_path}` → legacy child with `type: str`. At runtime: `Failed to compile sub-workflow... Use 'string' instead of 'str'`. The bypass is closed on the exact path the reviewer identified.
- Saved legacy workflow planted at `~/.pflow/workflows/` — rejected at load AND run with canonical suggestion.
- Happy-path nested workflow via template ref — runs end-to-end. New `validate_ir` does NOT false-positive on valid children.
- 16 AST edge cases for nested `any` rejection — all correct. Notably, `Literal['any']`, `Annotated[int, 'any']`, `typing.any` (attribute), `T_any`/`any_var` (substring identifiers) are correctly NOT rejected. `Callable[..., any]`, `dict[str, Callable[..., list[any]]]`, `tuple[int, any, str]`, `set[any]` all correctly rejected. This closes the `list[any]` "no runtime safety net" limitation documented in §2.9.
- Examples regression sweep — 39 pass / 10 fail. Stashed changes → identical 10 fail. Zero Task 154 regressions.

**Observed adjacent issues — filed separately, not bundled into PR:**
- **GH #292** — `pflow describe` raises uncaught `MarkdownParseError` Python traceback when saved workflow has parse errors. Pre-existing; likely related to #224 (CLI handlers bypassing diagnostic pipeline).
- **GH #293** — 8 example workflows fail `pflow --validate-only` but pass CI because `tests/test_docs/test_example_validation.py` only runs `validate_ir()` (schema-only), not the full `WorkflowValidator.validate()` 10-step pipeline. Root cause: test coverage gap lets examples rot. Three categories documented (undeclared inputs, stale `llm_usage` refs, stale `${input.x}` convention).

**Doc fix — `features/sub-workflows.md` template-ref form:**

During verification I noticed the guide documents only two `workflow:` forms (literal path, saved name) but the code supports a third (template reference via `${var}`). The production example `examples/nested/deep-research/deep-research.pflow.md:72` uses it; the guide doesn't mention it; my round-2 `validate_ir` call specifically protects it.

Fixed in same PR (not filed as separate issue) because:
1. The round-2 code change exists specifically to serve this pattern — shipping the fix while leaving the pattern undocumented is incoherent.
2. ~25 line doc addition, no scope creep risk.

Changes:
- `src/pflow/guide/features/sub-workflows.md` — updated opening capability bullet; added `### Dynamic Child Selection (Template References)` section with the deep-research fan-out pattern and the runtime-vs-validate-time trade-off.
- Verified via `pflow guide sub-workflows` renders cleanly.
- `make check` clean. `tests/test_docs/` 4/4 pass.

**Why the trade-off note matters for future agents:** the section explicitly calls out that invalid children surface as runtime errors, not validate-time errors. Without this note, an agent would assume `--validate-only` catches everything and be confused when a template-ref child fails only during actual execution.

**Final state for the PR:**
- 4849 tests pass, `make check` clean
- 13 files modified: 5 source, 1 guide, 7 tests (plus 1 progress-log)
- 2 follow-up issues filed (#292, #293) — pre-existing, not regressions
- 1 doc gap closed (sub-workflows template-ref) — adjacent scope, justified inclusion
- The formal post-fix contract in `bug-report.md` appendix holds for all 14 probes

---

### [2026-04-16 squash + rebase onto post-task-153 main]

What I'm doing: task 153 landed on main (PR #286, commit d3982fdf) while this branch was in progress. Squashed 5 review-pass commits into 1 (`feat: type vocabulary coherence refactor (task 154)`) and rebased onto origin/main.

Two text conflicts, both expected:

1. `src/pflow/guide/features/sub-workflows.md` — 153 added a "Heterogeneous Batch over Sub-Workflows" section, 154 round-2 had added "Dynamic Child Selection (Template References)". Resolution: kept both — 154's conceptual intro first, then 153's advanced pattern. Rewrote 154's example to use post-153 `inputs:` dict form (old form used top-level free-form params, which `ALLOWED_PARAMS` now rejects).

2. `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py:491` — 153 renamed `workflow_ir` → `child_ir` in `prep_res`; 154 had changed `{"invalid": "ir"}` → `simple_workflow_ir` (so `validate_ir` passes and the mocked `compile_workflow` is what raises). Synthesized: `"child_ir": simple_workflow_ir` — key from 153, value from 154.

Semantic fix without textual conflict:
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py::TestTemplateRefSubWorkflowValidation::test_template_ref_bypass_close_end_to_end_through_runner` — my round-2 regression test used pre-153 parent IR (`"params": {"workflow": ..., "message": "hello"}`). Post-153 rejects top-level `message` via `ALLOWED_PARAMS`. Rewrote to `"params": {"workflow": ..., "inputs": {"message": "hello"}}`.
- `test_workflow_executor_comprehensive.py::test_template_resolution_dict_and_list_inputs` — added by 153 with pre-154 vocab (`{"type": "dict"}`, `{"type": "list"}`). Now fails at 154's new `validate_ir` in `_compile_sub_workflow`. Migrated to canonical (`object`, `array`).

Verified validate_ir landed in the cache-miss branch of `_compile_sub_workflow` (post-rebase line 208-209, after cache early-return at line 192) — cache hits skip re-validation. 3-way merge placed it correctly; no manual fix needed.

Safety branch `fix/type-vocab-incoherence-pre-rebase` kept at the pre-squash tip for rollback.

Result: 4857 pass (+3 from post-rebase audit fixes, -2 from squash bookkeeping), `make check` clean. Force-pushed.

**Lesson for future rebases**: when two tasks each change a shared API shape (task 153 = child-inputs API, task 154 = vocabulary), the text-conflict count understates work. Auto-merging files can still encode semantic drift (pre-153 test fixtures with post-154 vocab rejection). Grep for API-shape markers from both tasks in every auto-merged file, not just the conflict-marked ones.

---

### [2026-04-16 cross-task audit cycle]

What I'm doing: user asked for a careful review of "potential issues the combination of task 153 and task 154 could cause." Ran 3 review agents in parallel (`review-feature-interactions`, `review-impact-completeness`, `review-silent-failures`). Synthesized findings and triaged.

**Real findings (fixed):**
- `architecture/architecture.md:497-499` — sub-workflow example taught pre-153 top-level free-form API. Updated to nested `inputs:`.
- `examples/nested/README.md:28-36` — same pre-153 example + now-false prose ("all other params are passed as child inputs"). Rewrote.
- `architecture/reference/template-variables.md` — 4 locations (~1052, ~1234, ~1349, ~1634) teaching pre-154 S1 vocab (`str`/`int`/`float`) in workflow-level `inputs:`. Migrated to canonical. Lines 680-685 stay Python-named (they're S3 node output metadata, not S1).
- `.taskmaster/tasks/task_154/task-review.md` — structurally stale vs round-2. Added Round-2 Addendum prepended at the top, explicitly contradicting the line 249 "Do NOT remove `_TYPE_ALIASES`" pitfall (the code was deleted in round-2). Several sections below (Two duplicated alias maps, drift-guard tests, TypeSpec.python_type extension) are also stale; the addendum calls these out rather than rewriting the whole doc.

**Review-agent findings I initially flagged as follow-ups, then retracted after user pushback**:
- F1: `error_action: continue` doesn't catch `validate_ir` errors. Not a bug — compilation errors SHOULD fail loud; error_action is for child-ran-and-returned-error semantics.
- F2: Top-level programmatic callers bypassing `validate_ir` silently skip coercion. Not reachable — all production entry points validate. Theoretical defense-in-depth for a path no caller takes.
- F3: `_expose_child_outputs` name-collision with `ALLOWED_PARAMS`. Conceptual confusion in the review — shared store keys and node parameter names live in different namespaces.

**User's framing** ("are you sure we should fix any of 5-7 issues?") caught me over-crediting review-agent findings. Lesson: review agents produce findings by design; the triage step is where engineering judgment happens. Don't pass through unchecked.

**CLAUDE.md audit**:
- `src/pflow/core/workflow/CLAUDE.md:13` — module listing said `sub_workflow_resolver.py # Shared sub-workflow resolution (inline IR, file, saved name)` but task 153 removed inline-IR support. Task 153's own diff updated this CLAUDE.md elsewhere (added `ALLOWED_PARAMS` coverage) but missed this line. Fixed to "file path or saved name".
- `src/pflow/core/CLAUDE.md:297` — `coerce_workflow_input` description used Python-named shorthand for dispatch (`str↔int, str↔bool`). Ambiguous post-154 since the dispatch keys are now S1 canonical. Rewrote to name the 7 canonical types explicitly and note Python aliases are rejected upstream.
- `src/pflow/core/CLAUDE.md` — task 154's new `types.py` wasn't in the module-structure listing or "Key Components" section. Added both. Initially over-wrote with 15 lines of S1/S2/S3 rationale; user corrected ("don't overfit to context window") — trimmed to match surrounding 2-3 line entries.

Result: 4857 pass, `make check` clean. Force-pushed.

---

### [2026-04-16 Python 3.14 CI failure — PEP 649 interaction]

What I'm doing: CI reported 3 failures on Python 3.14 only (3.10-3.13 passed):
- `test_nameerror_for_union_suggests_pipe_syntax`
- `test_nameerror_for_list_suggests_lowercase_generic`
- `test_nameerror_for_literal_suggests_import`

All 3 tests wrote code like `x: Union[int, str] = 1` and asserted `action == "error"` with opinionated hint text in `shared["error"]`. On 3.10-3.13 this worked because Python evaluated the annotation eagerly, raising NameError → `_format_exec_error` → `_suggest_for_nameerror` fired.

**Root cause**: PEP 649 lands as default in Python 3.14. Annotations are evaluated lazily (via `__annotate__` function) rather than at statement execution. `x: Union[int, str] = 1` stores the annotation as a deferred expression, assigns 1 to x, and never triggers NameError. Code runs to completion → action="default" → tests fail.

**Trade-off considered**:
- Option A: Skip tests on 3.14+. Minimal change, ships CI today. But on 3.14 users writing `List[int]` silently succeed with no opinionated hint — UX regression.
- Option B: Extend `_check_annotation_vocabulary` AST walker to catch typing names proactively at prep time. ~20-30 lines, works across Python versions.

User approved Option B: "carefully implement B".

**Key design refinement during implementation**: initial draft rejected ALL typing names (Union/List/Dict/Literal/etc.) unconditionally. But users who follow `_suggest_for_nameerror`'s own hint ("Add 'from typing import Literal'") would then get rejected by our AST walker — regressing legitimate imported usage. Added `_extract_imported_names(code)` helper; only reject names NOT in the import set. AST-based (`ast.ImportFrom` + `ast.Import` walk). Pattern: walk the whole code for imports, then check each annotation's Name nodes against the import set.

**Why one change, not two (the user's "simplicity of final code" principle)**: initially I thought about duplicating the opinionated-hint suggestion logic in both `_check_annotation_vocabulary` (AST-walk rejection) and `_suggest_for_nameerror` (NameError fallback for value-usage like `x = Union[int, str]`). Ended up reusing `_suggest_for_nameerror` directly in both paths — same canonical fix, different trigger.

Added constant `_REJECTED_ANNOTATION_NAMES = _MODERN_GENERIC_NAMES | {"Union"} | _REQUIRES_TYPING_IMPORT`. Helper `_extract_imported_names` uses AST to collect `ImportFrom` + `Import` bindings.

Tests:
- Renamed failing tests to `test_{union,list,literal}_in_annotation_rejected_with_*_hint` (accurate after mechanism change).
- Updated from `assert action == "error"` to `pytest.raises(NonRetriableError, match=...)` (NonRetriableError from prep propagates, doesn't convert to action).
- Added `test_typing_name_in_annotation_accepted_when_imported` — regression guard against future "simplification" of the import check.

Result: 4858 pass (+1 regression guard), `make check` clean. Force-pushed with `[skip review]` tag on the commit subject (minor review-prompted fix).

---

### [2026-04-17 code-review evaluation — W1/W2/S2 fixes]

What I'm doing: ran `/evaluate-review` on https://github.com/spinje/pflow/pull/290#issuecomment-4263676831. Reviewer produced 2 warnings (W1, W2), 3 suggestions, 2 nits. Triaged each against the code.

**Initial W1 plan (reviewer's proposed fix)**: insert `except PflowError as e: raise CompilationError(..., wrapped_diagnostics=e.to_diagnostics())` between the existing `except CompilationError` and `except Exception` branches. Uses the `wrapped_diagnostics` API to forward `SchemaValidationError`'s structured context (similar_names, available_fields, suggestions_list) through the CompilationError wrap.

**User pushback** ("we should prioritize simplicity of the final code, not how easy it is to get there... what's the right solution the top 10% would implement?"). Stepped back. Dispatched a searcher to map all callers and the CompilationError API surface.

**Key discovery the searcher surfaced**: `CompilationError.to_diagnostics()` has asymmetric behavior — when `wrapped_diagnostics` is set, it returns them verbatim, DISCARDING `details["sub_workflow_path"]`. The reviewer's fix as-stated preserves vocab structure but loses the "Sub-workflow: <path>" rendering line. Would ship a subtle new regression while fixing the old one.

**Revised plan — fix at two layers**:

1. **`CompilationError.to_diagnostics()` composes `wrapped_diagnostics` with `details`**. When both are present, iterate `wrapped_diagnostics` and merge `sub_workflow_path` into each diagnostic's `context` via `dataclasses.replace(d, context={"sub_workflow_path": ..., **(d.context or {})})`. setdefault semantics — inner-diagnostic context wins on key conflict. ~6 lines in `exceptions.py`.

2. **Add `except PflowError` branch in `_compile_sub_workflow`** as reviewer originally suggested. Uses `wrapped_diagnostics=e.to_diagnostics()`. With fix (1) in place, sub_workflow_path now composes correctly.

3. **Extract `_validate_and_compile_child` static helper** — adding the 3rd except branch pushed `_compile_sub_workflow` from 10 → 11 cyclomatic complexity, triggering ruff's C901. Moved the validate+compile+wrap sequence into the helper. User memory: no `# noqa` — fix the structure.

**W1 test update — critical lesson**. The existing `test_template_ref_bypass_close_end_to_end_through_runner` asserted `"Use 'string' instead of 'str'" in diagnostic_messages` (joined `.message` fields). This passed on the OLD flattened code because suggestion text was embedded in the exception's string representation. After fix, `"Use 'string' instead of 'str'"` lives in `.suggestions`, not `.message` — the structurally correct location. Test failed on my first run of the new code.

**The assertion was pinning a symptom of the bug, not the contract**. Rewrote to assert on structured fields directly:
- `vocab_diag.context["available_fields"]` == the 7 canonical types (rich rendering block preserved)
- `vocab_diag.context["sub_workflow_path"] == str(child_path)` (container context merged by fix 1)
- `vocab_diag.suggestions == ["Use 'string' instead of 'str'"]` (opinionated fix in structured field)

This is now the template for future cross-layer rendering tests.

**W2 fix — forward-reference annotation unwrap**. `_extract_annotations` runs `ast.unparse(node.annotation)` which preserves outer quotes, so `x: "list[any]"` becomes the string `"'list[any]'"`. `ast.parse(..., mode="eval")` on that sees `ast.Constant`, no `ast.Name(id="any")`, check silently passes. On 3.14+, PEP 649 means runtime doesn't catch it either. Fix: after initial parse, if `tree.body` is `ast.Constant` with string value, re-parse the inner string before walking. ~4 lines. Preserves existing behavior for inner `Literal['any']` Constants (those stay as-is, correctly ignored). Added regression test `test_lowercase_any_in_forward_reference_rejected`.

**S2 — one-line clarifying comment on `coerce_param_for_node`** about the S3-vs-S1 surface distinction (why it still accepts Python-aliased `"str"`/`"dict"` while `coerce_workflow_input` dropped aliases).

**Findings explicitly disputed/skipped**:
- S1 (redundant validate_ir for static-path children): reviewer themselves said "leave unless a profile shows it" — the "every path through compile_workflow is validated" invariant is worth more than the micro-redundancy.
- S3 (tighten message-based tests to assert on structured fields): the structured-field contract is already pinned by the dedicated `TestTypeVocabularyErrorFields` class; tightening the message tests too would test the same contract twice.
- 2 nits: pure style.

Result: 4859 pass (+1 forward-ref regression), `make check` clean. Force-pushed to `5b5a8cbd`.

**The user's "simplicity of final code" principle applied here**: the reviewer's fix was ~5 lines; my revised fix was ~8 lines. But the revised fix corrects a latent API design bug (`wrapped_diagnostics + details` composition) that benefits every future caller, not just sub-workflow compilation. Net-simpler final state despite slightly more lines.

---

### Template for future entries

```markdown
### [YYYY-MM-DD HH:MM] — [Short description]

What I'm doing: ...
Result:
- ✅ Worked: ...
- ❌ Failed: ...
- 💡 Insight: ...
- 🔀 Decision: ... (if any non-trivial call made)

Code that worked:
\`\`\`python
# snippet
\`\`\`

Next: ...
```
