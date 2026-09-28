# Task 170 Implementation Plan — One Template Language (`core/templates`)

Written 2026-09-28 by the task planner against base `7dc5ad5d` (== `origin/main` at launch; that
commit is the refreshed spec + ADR-0006 amendment + ADR-0015). Supersedes
`implementation-plan-2026-06-12-SUPERSEDED.md` in full (kept only as history).

Authorities, in order: the spec's decision ledger + ADR-0006/0015 (locked) → `task-170.md`
(what/why) → this plan (how) → `progress-log.md` (what actually happened). Where this plan and
the spec disagree, the spec wins and the disagreement is a planning bug to report.

**Baseline captured 2026-09-28 on `7dc5ad5d`** (the freeze harness — re-run before every phase
gate): `uv run pytest tests/test_runtime/test_template_resolver.py tests/test_runtime/test_template_escape.py
tests/test_runtime/test_nested_templates.py tests/test_runtime/test_template_coalesce.py
tests/test_runtime/test_null_defaults.py tests/test_runtime/test_template_validation/
tests/test_core/test_cache_block_parser.py tests/test_core/test_prompt_cache.py
tests/test_nodes/test_llm/test_prompt_cache_rendering.py tests/test_runtime/test_node_wrapper.py
tests/test_core/test_workflow_validator.py tests/test_core/test_workflow_data_flow.py
tests/test_core/test_workflow_validator_outputs.py -q` → **772 passed, 0 failed**. The full
`make test` + `make check` baseline is captured by the implementer at phase-1 start (log it).

**Cross-task scan** (`./scripts/tasks`, 2026-09-28): no in-progress or blocked tasks. Shipped
tasks whose surface overlaps: 159 (cache block — `prompt_cache.py`, `plan_node.py` hash path; its
byte-symmetry tests are the net for phase 4d), 162/166 (loop config — `loop_control.py`,
carry checks in `engine.py`), 168 (graph model — `scope.py` + `web/src/graph/scan.ts`
mirror), 135 (engine reads `dict(shared)`; ADR-0014 — resolution stays engine-driven). Unbuilt
overlapping: 112/120 (type-compatibility matrix pointers — updated by 4e), 118 (blocked on this
task by ruling). Lane-B siblings: #628 (output-source validator region + `output_resolver.py`;
**if not merged when phase 4b/4c starts, the task orchestrator merges main first** — both
phases touch those files), #643 (entry-point asymmetry; the corpus states its entry point),
#503 (`ValueError` → `PflowError` on `engine/template_resolution.py`; never interleave with
phase 2/4b), #520 (build on `parse()` after 4c).

---

## 0. Design (resolved; the phases implement this)

### 0.1 The module — `src/pflow/core/templates.py` (single file; split only if >~1000 lines)

Public surface after phase 5 (nothing else is imported from it anywhere):

```python
# ── AST (all frozen dataclasses with slots; tuples never lists) ──────────────
class Text:         text: str                       # unescaped literal text ("$${" already "${")
class Field:        name: str
class Index:        value: int
class DynamicIndex: ref: Reference                  # inner ${…}: ONE level, plain Reference (no ?? / no nesting)
Segment = Field | Index | DynamicIndex
class Reference:    root: str; path: tuple[Segment, ...]; raw: str   # raw = operand source text
class Literal:      raw: str                        # JSON literal per the literal grammar; .value → json.loads(raw)
                                                    # computed FRESH on every access (a cached [] / {} shared
                                                    # across batch threads would be a mutation hazard)
Operand = Reference | Literal
class Expression:   operands: tuple[Operand, ...]; raw: str; span: tuple[int, int]
                    # len(operands) > 1 ⇔ coalesce; raw = inner text; span = [start of "${", end after "}")
                    # .references → every Reference incl. DynamicIndex inner refs (depth-first)
class Issue:        raw: str; span: tuple[int, int]; kind: Literal["malformed", "bad_literal"]
                    # an unescaped "${" that is not an Expression. span runs to the first "}" after it
                    # (inclusive) or to end-of-string. kind == "bad_literal" iff raw contains "??" and some
                    # operand passes is_literal_operand() but fails the literal grammar (today's
                    # _malformed_literal_operand_hint); consumers branch on exactly these two kinds.
class Template:     source: str; segments: tuple[Text | Expression | Issue, ...]; escaped: bool
                    # .expressions, .issues, .references (all, incl. dynamic inner), .is_simple
                    # (exactly one segment and it is an Expression), .needs_resolution
                    # (expressions or escaped — the has_templates contract post-#632)

@functools.lru_cache(maxsize=4096)
def parse(source: str) -> Template          # pure, total (never raises), context-free, AUTHOR TEXT ONLY
def parse_path(path: str) -> Reference | None   # bare path grammar ("node.f[0].g", "a[${i}].x"); None if invalid

# ── Value walk ───────────────────────────────────────────────────────────────
class Resolution:   value: Any; unresolved: frozenset[str]   # inner text (Expression.raw) of every
                                                             # expression left literal, over the whole value
def resolve(value: Any, context: Mapping[str, Any]) -> Resolution   # = today's resolve_nested + the set
def lookup(ref: Reference, context: Mapping[str, Any]) -> tuple[bool, Any]   # ONE walk: (found, value)

# ── Rules (the judgment calls that drifted) ──────────────────────────────────
TRAVERSABLE_TYPES  = frozenset({"dict", "object", "any", "str", "string"})   # a Reference path may walk into
TRUSTED_TRAVERSABLE_TYPES = frozenset({"dict", "object", "any"})            # …without a JSON-at-runtime warning
CONTAINER_TYPES    = frozenset({"dict", "object", "list", "array"})          # JSON auto-parse targets
def to_string(value: Any) -> str            # today's _convert_to_string rules, verbatim

# ── Permanent string-helper facade (the interface every long-tail caller uses today) ──
class TemplateResolver:
    TEMPLATE_PATTERN, TEMPLATE_EXTRACT_PATTERN, SIMPLE_TEMPLATE_PATTERN   # stay public (tests + .search users)
    has_templates(value)            # == needs_resolution over strings/dicts/lists (escape-only → True; #632)
    has_references(value)           # NEW: any Expression anywhere (the deferral predicate; escape-only → False)
    resolve_template(t, ctx), resolve_nested(v, ctx)          # = resolve(...).value
    resolve_value(path, ctx), variable_exists(path, ctx)      # RAW-PATH MODE (below)
    resolve_coalesce(expr, ctx), extract_variables(s), is_simple_template(s),
    extract_simple_template_var(s), is_coalesce_expression(s), is_literal_operand(op),
    split_coalesce_operands(s), extract_root_node_id(path), extract_first_field_segment(path)
    _convert_to_string, _get_dict_value    # kept: declared direct-test surface of test_template_resolver.py
```

Rejected: exposing a separate span-yielding `finditer` helper — `Expression.span`/`Issue.span`
on the parsed template IS the span helper (consumers: `prompt_refs.py:61-82`,
`markdown_parser._parse_cache_code_block`, `type_validation` quoted-template check). Rejected:
`Literal.value` stored in the AST (mutation hazard through the lru_cache — the June plan's
point stands). Rejected: a package `core/templates/` — nothing varies; one file reads whole.

**Two path readers, one walk (the raw-path mode).** `-o result.@type`, `read-fields
result.dc:title`, MCP `read_fields result.my key`, `result.0` resolve today because
`resolve_value`/`variable_exists` split lexically (dots outside brackets, `[N]` indices) with no
identifier grammar. That stays: the facade's `resolve_value`/`variable_exists` tokenize
lexically (`_split_raw_path`) and feed the same `_walk`; `parse_path` is the grammar reader
for templates. Both readers produce the segment tuple `_walk` consumes — the walk is shared,
the readers are not. Pinned by the phase-1 characterization rows for those four paths.

**Grammar (regex-tokenized, ADR-0006).** The existing patterns become the tokenizer:
- Candidate scan, one left-to-right pass: `ESCAPE = \$\$\{[^}]*\}?` (an escape consumes through
  the first `}` after it, or to end-of-string — decision ledger "escape consumes through `}`") |
  `OPEN = (?<!\$)\$\{`. Escapes become Text with one `$` stripped (`$${x}` → `${x}`, `$$${x}` →
  `$${x}`, bare `$$` untouched — the #632 pins). Every OPEN is an Expression or an Issue, never Text.
- At an OPEN, `_EXPR_AT.match(source, pos)` with the strict expression regex — today's
  `_COALESCE_EXPR_PATTERN` with the variable grammar extended by one dynamic-index alternative:
  `SEGMENT = IDENT(?:\[(?:\d+|\$\{INNER\})\])?` where `INNER` is today's static var grammar
  (identifier + optional `[N]` + dotted fields; no `??`, no nesting). At most one index per
  segment (multi-index `${m[0][1]}` stays rejected on both sides — freeze). Match → Expression;
  no match → Issue (span to the first `}` or EOS).
- Literal grammar: today's `_LITERAL_PATTERN` with the string branch tightened to JSON-valid
  escapes only (`\\["\\/bfnrtu]`, `\uXXXX` = 4 hex, no raw control characters) so every
  literal-grammar match round-trips `try_parse_json` (the spec's grammar-coherence property; the
  three known mismatches `"\q"` / `"\u12"` / raw tab become `bad_literal` Issues — delta 2 class).
  Literal-first operand classification (keywords beat same-spelled identifiers) preserved.
- `parse_path(path)` = fullmatch of the extended variable grammar → Reference; used by the
  validator-side segment consumers and `infer_template_type`. Never used on user-typed paths.

**Resolution semantics** (unchanged from today except the sanctioned deltas):
- `resolve(str)`: simple template (one Expression, nothing else) → value with type preserved;
  literal-only → its JSON value; coalesce → first operand that resolves (literal always resolves;
  a Reference resolves iff `lookup` found it, root absent OR field absent both fall through —
  #441; found value `None` is returned, not skipped — `test_template_coalesce.py:299/:370` and
  the array variant `${x[0] ?? "f"}` with `x=[None]` → `None`, executed 2026-09-28). Complex
  template → single left-to-right pass over segments: Text emitted (unescaped), Expression →
  `to_string(value)` or its raw `${…}` text when unresolved (and its `raw` joins `unresolved`),
  Issue → its source text verbatim (NOT in `unresolved` — a syntax error is not missing data;
  validation is the net). Substituted values are never re-scanned (#632).
- A DynamicIndex resolves its inner Reference through `lookup`; the inner must be found and be
  an `int` (bool excluded — `True` is not an index); otherwise the whole outer Reference is not
  found (ledger: "a dynamic-index template is one Reference"). No pre-pass, no text rewrite.
- `lookup` = today's traversal (`_get_dict_value` Mapping access with JSON-container auto-parse
  on `str`; `[N]` requires a list — after auto-parse — and `0 <= N < len`; `None` mid-path → not
  found; final value may be `None` with found=True — `test_null_defaults.py:20-49`,
  `test_workflow_output_handling.py:1522-1538` pin these).
- JSON auto-parse of a simple template's resolved string into a container happens in
  `resolve_nested`/engine exactly as today (containers only; numeric strings stay strings).

**`resolve()` on resolved runtime values never happens.** `parse` is cached on author text.
The cost-analysis sites that inspect RESOLVED text (`row_builder.py:928`,
`token_estimation.py:414/:448/:452`, `sub_workflow_walker.py:537`, `engine.py:400`) keep calling
the compiled `TEMPLATE_PATTERN` / `has_references` (an uncached regex search) — they never call
`parse`. Rule stated in the module docstring; the by-symbol meta-test does not forbid
`.search`/`.finditer` on the public compiled patterns (that is *using* the grammar, not copying it).

### 0.2 The unresolved set through the engine (phase 2; #630)

`engine/template_resolution.py`:
- `resolve_template_parameter(key, template, context)` → `(value, is_simple, unresolved)`;
  `resolve_templates` replaces `contains_unresolved_template(resolved_value, template)` with
  `if unresolved:` — one set feeds the strict raise and the permissive record.
- `resolve_templates` KEEPS its `(merged_params, last_resolutions, template_errors)` return
  (26 direct call sites in 11 test files; a 4-tuple is not a sanctioned test change). The
  permissive error entry gains `"unresolved_expressions": tuple(sorted(unresolved))` — the
  entry dict is already an untyped bag read only by the runner (`diagnostic` key) and it never
  reaches the trace (`__template_errors__` is not captured; `last_resolutions` is — so the set
  must never ride on `last_resolutions`: **no new trace field**).
- `inject_none_for_optional_inputs(..., unresolved)`: an optional input whose template's
  expressions are ALL in `unresolved` and whose roots are all absent → `None` (today's
  "value == template" test, made structural; partial resolution still keeps the literal).
- Loop carry (`engine.py:242-258`): `unresolved = key not in resolved_inputs or
  _plan_left_unresolved(plan, template)` where the helper reads the `inputs` entry of
  `plan.template_errors` (permissive) — in strict mode an unresolved carry raises inside
  `plan_node` and the existing `diag` branch handles it, unchanged. `contains_unresolved_template`
  and `_check_string_unresolved` are deleted in phase 2 (their only two consumers migrate here);
  `TestContainsUnresolvedTemplate` (`test_node_wrapper.py:196-222`) is deleted with them
  (spec-sanctioned). `TestDepthLimit` (`test_node_wrapper_template_validation.py:295-313`) must
  stay green — `resolve()` recurses the 105-level structure the same way `resolve_nested` does.
- Other text-comparison consumers switched in phase 2 (all become `r = resolve(...)`;
  `if r.unresolved`): `engine._resolve_template_string` (:393-402 — batch warm-up `model`/`system`;
  a `$${x}` in `system` stops dropping the user system prompt), `output_resolver`
  (`resolve_output_source`, `populate_declared_outputs`), `batch_executor.resolve_batch_items`
  (string form only; the inline-list form never checked unresolved-ness and keeps not doing so —
  named corpus row), `prompt_cache._resolve_chunk_value` (echo → `_CHUNK_ABSENT`).
  `_resolve_static_prefix_for_cache` waits for the AST (4d). `classify_unresolved_references`
  is diagnostic policy and keeps re-deriving per-operand status from the author template (4b
  migrates it to the AST).

Rejected: re-resolving the carry template at the check site (a second walk — the thing this task
removes); a 4-tuple return (test blast radius); putting the set on `last_resolutions` (trace).

### 0.3 Validator-side operand classifier (phase 4c; ADR-0006 amendment)

Home: `runtime/template_validation/validator.py` (validator *policy* stays in the package).

```python
class OperandPolicy(Enum):
    FIELD_CHECK = "field-check"   # bare reference: root AND every path segment checked (Pass 5 / Pass 8)
    ROOT_ONLY   = "root-only"     # operand of a multi-operand ?? chain: only the root must exist (#441)
    # SKIP is not a policy value: Literal operands are not References and never reach the classifier
def classify_operand(*, in_coalesce: bool) -> OperandPolicy
def _iter_template_operands(workflow_ir) -> Iterator[tuple[Reference, OperandPolicy, str /*node_id*/]]
```
`_iter_template_operands` walks `_node_template_value_sources` (params, `batch.items`, loop
`while`/`until`/`max_iterations` — unchanged surface set) with `parse()`, yielding every
Reference including DynamicIndex inner refs (delta 6), each with the enclosing operand's policy.
Consumers: Pass 5 (`FIELD_CHECK` only — today), unused-inputs (all), **Pass 8**
(`batch_item_validation` — switches from its own `extract_variables` walk to this iterator:
the Pass-5/Pass-8 `??` disagreement closes; `${item.maybe ?? "none"}` on a batch item stops
erroring — the spec's xfail row flips). `ROOT_ONLY` operands' roots are checked by
`data_flow.py` (the dependency checker — its surface set gains `batch.items` in 4c so
`items: ${typo.x ?? a.stdout}` stops being silent; the two surface sets are then equal, pinned by
a corpus row per surface). Type passes 6/7/9 keep using `extract_variables` (they type each
operand; not a field-existence policy).

### 0.4 Type-rule homes (phase 4e)

- **Traversability + container sets → `core/templates`** (`TRAVERSABLE_TYPES`,
  `TRUSTED_TRAVERSABLE_TYPES`, `CONTAINER_TYPES`): they answer "what may a Reference path walk
  into / what does the runtime auto-parse" — language semantics with four consumers
  (`path_validation.py:186-190/:291/:327/:335/:342`, `type_checker.py:223/:250`,
  `template_resolution.py:351-360/:153-167`, `type_validation.py:143`). The
  `type_checker`↔`path_validation` disagreement resolves toward runtime truth (`str` IS
  traversable — the resolver auto-parses JSON containers on traversal); executed reading: every
  consumer of `_infer_nested_type` treats `None` and `"any"` alike, so aligning it changes no
  diagnostic today (pinned by a corpus row so a future consumer that starts distinguishing them
  sees the rule).
- **Type-compatibility matrix + `is_type_compatible` → `core/types.py`** beside
  `outer_base_type` (which it already calls). Deletion test: the matrix has ONE consumer
  (`type_validation.py:18`) plus tests; folding it into `core/templates` would add ~80 lines
  of parameter-type vocabulary to the language module for no second consumer, while Tasks
  112/120 (pending, on the board) explicitly want a *non-template* compatibility primitive —
  `core/types.py` is the leaf module they can import without pulling
  `runtime.template_validation`. `type_checker.py` keeps `infer_template_type` (validator-side
  structure inference; consumes `parse_path` + the sets). `TypeVocabularyError(ValueError)` in
  `core/types.py` is pre-existing and out of scope (note for #503's sibling).
- `to_string` (stringification) → `core/templates`; `prompt_cache.deterministic_serialize` is
  deliberately different and stays (spec). `coerce_param_for_node`'s `json.dumps` (simple
  template → `str` param) is a third encoding — out of scope, named in §6.

### 0.5 The three meta-tests

1. **Parity corpus** — `tests/test_integration/test_template_parity.py` (cross-layer; per
   `tests/CLAUDE.md`) + `tests/test_core/test_template_grammar.py` (pure grammar rows). Rows are
   frozen dataclasses in Python (not a data file: no TS/167 consumer exists yet — deletion test;
   a JSON export is a one-afternoon follow-up if one appears). Every row carries `id`,
   `mutation` (the production change that trips it) and, when divergent on main,
   `xfail="<issue or delta>"` applied as `pytest.mark.xfail(strict=True, reason=...)`.
   Doctrine line in the module docstring: *"If a row fails, fix the divergence, never the row"*
   (from phase 2 on).
2. **Grammar uniqueness** — `tests/test_core/test_template_grammar_seam.py`, mirroring
   `test_litellm_runtime.py:912-1004` mechanics (`_find_repo_root`, `rglob`, prefilter
   `"$" in source`, `ast.parse`). Two rules over every `.py` under `src/pflow/`:
   - **Rule A (literal grammar):** no `ast.Constant` string (including f-/rf-string fragments,
     module-level constants and `BinOp` concatenation operands) whose value contains `\$\{` or
     `\${` outside the allowlist. Scanning constants (not only `re.*` arguments) is what catches
     `validator.py:47 _PERM_VAR` (a constant fed to a later `re.compile`) and the `ir_schema`
     strings, which is why the allowlist must name `ir_schema.py`.
     **Allowlist** (frozenset of repo-relative paths, one reason each — verbatim in the test):
     - `src/pflow/core/templates.py` — the seam itself.
     - `src/pflow/mcp/auth_utils.py` — `${VAR:-default}` MCP-config env expansion is a
       different language (bash-style), not pflow templates.
     - `src/pflow/core/yaml_utils.py` — a lexical YAML mask (allows one nested `{}` level,
       deliberately no `$$` handling) whose over-capture is harmless because the mask/restore
       round-trip is verbatim; swapping in the canonical pattern breaks flow-style YAML for
       `$${y}` and `${a[${i}].x}` (executed by the spec battery); own guard in
       `test_yaml_shielding_hygiene.py` + pin rows added in phase 5 (`test_yaml_utils.py`
       `TestBraceAwareTemplates`: `$${y}` and `${a[${i}].x}` in a flow mapping).
     - `src/pflow/core/ir_schema.py` — jsonschema `pattern` strings (`^\$\{.+\}$` ×5) are
       schema *shape* checks, never compiled by pflow.
   - **Rule B (by-symbol):** no `re.<fn>(...)` call outside the allowlist whose pattern argument
     AST references a name imported from `pflow.core.templates` or an attribute of
     `TemplateResolver` (`ast.Attribute`/`ast.Name`/`JoinedStr` walk). Catches the historical
     drift vector (`data_flow.py:34`, `cache_overlap.py:32`, `scope.py:56`,
     `validator.py:50/:652`) that a literal scan cannot see. Calling `.search`/`.finditer`/
     `.sub` ON a public compiled pattern is not a `re.*` call and is allowed.
   - Scope: Python under `src/pflow/` only; the web TypeScript mirrors are out of scope by
     construction (docstring says so). Failure message lists `file:line` + fix hint pointing at
     `core/templates.py`.
3. **Layering pin** — rule 4 in `tests/test_import_hygiene.py`: no module under
   `src/pflow/core/` imports `pflow.runtime.template_resolver` (the shim) — any scope, matching
   `test_runtime_does_not_import_ui`'s shape (prefilter `"template_resolver"`, AST, absolute
   imports; also match `alias.name` for `from pflow.runtime import template_resolver`). NOT "core
   imports nothing from runtime" — nine non-template edges are sanctioned (`prompt_cache.py:163`,
   `trace_report.py:30`, `trace_loading.py:138/:221`, `predict.py:472/:504`,
   `core/workflow/validator.py:96/:446/:787`, `data_flow.py:566`).
   Plus the **litellm/runtime pin** for the new module: an e2e subprocess test beside
   `test_litellm_runtime.py:882` — `import pflow.core.templates` in a clean interpreter and
   assert no `litellm*` AND no `pflow.runtime*` module in `sys.modules` (executed 2026-09-28:
   `pflow.core.json_utils` loads only `pflow.core.*` + jsonschema; today
   `pflow.runtime.template_resolver` drags 29 runtime modules via `runtime/__init__`).

### 0.6 Planner rulings (importance ≤ 2, visible, reversible; overrule at launch if wanted)

| # | Ruling | Why | Reversal cost |
|---|---|---|---|
| R1 | A loop `while:`/`until:` over a dynamic-index simple template (`${n.items[${idx}]}`) becomes VALID and resolvable (today: validator shape error, runtime stop) | Direct consequence of "a dynamic-index template is one Reference"; nobody could have written one (it errored) | One `if` in the loop-shape check |
| R2 | A malformed unescaped `${` in `## Cache` PROSE (`${}` — today silent prose; `${a\n…}` — today a chunk named across lines) is a `MarkdownParseError` | "Every unescaped `${` is an Expression or an Issue, never Text" + "every Issue on every surface is an ERROR" (spec Parity); non-grammar prose like `${HOME:-x}` already errored via the root check | Treat Issues as prose in the chunker (2 lines) |
| R3 | An output `source:` with no Reference (escape-only `$${a.x}`, or prose-only) is a validator ERROR "output source has no template reference" (today: "malformed template", by accident of the extract regex) | Keeps today's outcome (error) with a truthful message; the runtime's `_normalize_source` would otherwise wrap it into garbage | Message text only |
| R4 | `$node.x` output sources (runtime-accepted "dollar prefix" form, `output_resolver.py:47-53`) become validator-ACCEPTED (today: rejected as source `$n`) — the validator normalizes exactly like the runtime before checking | One-way soundness violation found by execution; "fix the divergence, never the test"; the form is in the resolver's docstring contract | Reject the form on both sides instead (then a runtime change) |
| R5 | `##  Cache` chunk vars with `??` are root-checked per operand by `data_flow._validate_cache_block` (today the whole `a ?? b` string is the "root" → always an error) | Runtime resolves them (`_resolve_chunk_value` → `resolve_template`); validator should not over-reject | Keep the whole-string root check |
| R6 | The `has_templates` deferral sites (`core/workflow/validator.py:1008/:1047/:1155/:1262`, `template_validation/validator.py:1226`, `sub_workflow_resolver.py:93`) switch to `has_references`; an escape-only value is then statically checked AS WRITTEN (`$${x}` literal) | Spec Parity: defer on "contains a Reference", not "needs rewriting"; checking the escaped text is at worst wrong on absurd inputs, and never silent | Swap the predicate back |
| R7 | Type-compatibility matrix → `core/types.py`; traversability sets → `core/templates` | §0.4 deletion-test argument | Move a 60-line block |
| R8 | Phase 2 deletes `contains_unresolved_template` (spec: "goes only once no consumer depends on it" — after phase 2 none does) | Leaving a dead heuristic beside the new set invites a re-fork | Restore from git |

No user checkpoints are embedded in this plan. No trace-format change anywhere (verified per
phase in the handoff points: `last_resolutions` shape untouched; `__template_errors__` not traced).

---

## 1. Verified truth tables (2026-09-28, executed on `7dc5ad5d` — the corpus encodes these)

**Dynamic index today** (`resolve_template`; `cut` = `contains_unresolved_template`):

| template | context | today | strict today | after (delta 3) |
|---|---|---|---|---|
| `${a[${i}].x}` | i=0, a=[{x:v}] | `'v'` | ok | `'v'` (unchanged) |
| `${a[${i}].x}` | i=0, a=[{y:v}] | `'${a[0].x}'` | **silent** (cut=False) | unresolved → strict error (**phase 2**, delta 1: the rewritten expression `a[0].x` is in the set) |
| `${a[${i}].x}` | i="abc" | `'${a[abc].x}'` + warning log | silent | unresolved (phase 4a: the outer is an Expression) |
| `${a[${i}].x}` | i=5 (OOB) | `'${a[5].x}'` | silent | unresolved (phase 2 for the int case) |
| `${a[${i}].x}` | i absent | unchanged | error | unchanged / error |
| `${a[${i}].x}` | i=True / None / "1\n" / -1 | rewritten or unchanged | silent | unresolved (4a) |
| `${a[${i}].x ?? b}` | i="s", b="fb" | `'${a[s].x ?? b}'` | silent | `'fb'` (4a) |
| `${a[${i}].x ?? b}` | i=0, a=[{y:v}], b="fb" | `'fb'` | ok | `'fb'` (unchanged — pin it) |
| `${r[${i}]}` | i=0, r=[{k:1}] | `{'k': 1}` (type kept by the pre-pass) | ok | dict (unchanged) |
| `${r[${i}]}` | r=['{"a":1}'] (JSON-string element) | `'{"a":1}'` str (no auto-parse: `is_simple` on original = False) | ok | `{'a':1}` dict (4a: `resolve_nested` gate; 4b: engine gate) |
| `$${a[${i}]}` | i=0 | `'${a[0]}'` | — | `'${a[${i}]}'` (4a, delta 4) |
| `$${FOO:-${bar}}` | bar=B | `'${FOO:-B}'` | — | `'${FOO:-${bar}}'` (4a, delta 4) |
| `${x} $${x}` | x=hi | `'hi ${x}'` | **error** (#630) | ok (phase 2, delta 1) |
| `${arr[${idx ?? 0}]}` | arr=[1,2] | `'${arr[0]}'` (the inner coalesce interpolates) | silent | validator ERROR (4c, delta 2); resolver: Issue, literal |

**Grammar edge today** (`has_templates` / `is_simple` / `extract_variables`):
`${c.result.0}` → False/False/∅ (static param, literal reaches node); `${data.result.}` same;
`${m[0][1]}` same; `${a ?? "${b}"}` → True/**True**/{a}, resolves to `'${b}'`, validator says
malformed literal; `[${none_val}]` with none_val=None → `'[]'` (a bracket OUTSIDE `${}` is text —
`test_template_resolver.py:179`, must survive the dynamic-index grammar).

**Walk pair today** (`variable_exists` / `resolve_value`): `x[0]` on `{x:[None]}` → True/None;
`x.k` on `{x:{k:None}}` → True/None; `x.k.j` on `{x:{k:'{"j":1}'}}` → True/1 (JSON mid-path);
`x.k.j` on `{x:{k:None}}` → False/None; `x.k[0]` on `{x:{k:"s"}}` → False/None; `x.k[0].z` on
`{x:{k:[None]}}` → False/None; `x.k[0]` on `{x:{k:"[5]"}}` → True/5; `x[0]` on `{x:"[5]"}` → True/5.

**Converse-silent class today** (validator OK → runtime static literal, exit 0): `${c.result.0}`,
`${data.result.}`, `${data..result.x}` (`test_validator.py:298-311` passes for the wrong reason —
no node named `data`), `${src.stdout.0}`, `${arr[${idx ?? 0}]}`, `${lsit[${__index__}].x ??
"default"}` (root typo hidden), `batch.items: ["${data.result[0]"]` (malformed pass walks params
only), `## Cache` `${plan.stdot}` (chunk silently ABSENT).

**Output `source:` today** (validator / runtime on `{n:{stdout:'OK'}}`): `${n.stdout}` ok/OK;
`$n.stdout` **error**/OK; `n.stdout` ok/OK; `n.stdout ?? n.x` ok/OK; `prefix ${n.stdout}`
ok/`'${prefix OK}'` (recorded drift, not fixed — spec).

---

## 2. Phases

Common per-phase gate: `make check` + `make test` green; the freeze-harness command from the
header green **with zero test edits except the sanctioned ones listed in that phase**; the
phase-1 corpus green with its xfail rows still strict (only the rows the phase names flip).
Every phase ends with a progress-log entry (ORCHESTRATION format) and a commit on the feature
branch (deliberate staging). Effort follows ORCHESTRATION → Model routing; all phases are Opus.

### Phase 1 — Parity corpus + characterization (tests only; no production change)

**Goal.** Land the fence: the language's current behavior as executable rows, the historical
bugs as named fixtures, the known divergences as strict xfails citing their issue/delta, and
`WorkflowRunner` characterization of every dynamic-index consumer — all green on `7dc5ad5d`.

**Files.** NEW `tests/test_core/test_template_grammar.py`, NEW
`tests/test_integration/test_template_parity.py`, NEW `tests/fixtures/template_corpus/nodes/producer.py`
(the corpus producer node), `tests/CLAUDE.md` (one row in "Find the test owner").
No `src/` edits. No spec edits beyond what the planner already made.

**Harness (decided).**
- **Registry.** A real registry: `scan_for_nodes([<src>/pflow/nodes, tests/fixtures/template_corpus/nodes])`
  computed once at module level, `Registry().update_from_scanner(_SCAN)` per test (the autouse
  `isolate_pflow_config` gives each test its own registry path; `update_from_scanner` is a full
  replace + save — `tests/shared/registry_utils.ensure_test_registry` is the precedent).
- **Producer node** `TemplateCorpusProducer` (`- type: template-corpus-producer`): `- Params:
  payload: dict`; `- Writes: shared["out"]: dict` with the enhanced nested-structure docstring
  form (`llm.py:1010-1016` is the syntax precedent — indented `- field: type  # desc` lines):
  `text: str`, `num: int`, `flag: bool`, `nested: dict` {`k: str`}, `items: list[dict]` {`x: str`},
  `json_str: str`, `maybe: any`; plus `shared["out_str"]: str`, `shared["out_list"]: list`.
  `post` writes each declared key present in `payload`. This makes the validator see declared
  STRUCTURE (field errors are real) while the runtime executes a real node.
- **Consumers.** `code` node with `inputs: {v: <template>}` and body `result = v`
  (type-preserving: `shared_after["c"]["result"]`); `shell` `echo` only where stringification is
  the point (keep Windows-safe: no quoting tricks — the `tests-windows` gate runs this file).
- **Validator side** = exactly `runner.validate`'s call:
  `WorkflowValidator.validate(ir, extracted_params=generate_dummy_parameters(inputs) + {"_pflow_workflow_file": path},
  registry=registry, skip_node_types=False, workflow_file=Path(path))` → `errors` (ERROR only).
  The corpus module docstring states this entry point and names #643 (save-path params differ).
- **Runtime side per surface** (a full `WorkflowRunner().run` cannot reach a validator-rejected
  template, so each surface has a direct driver; rows that the validator accepts ALSO run end to
  end through `WorkflowRunner().run(ir, params, config=RunnerConfig())` and assert on
  `result.shared_after` / `result.status` / `result.diagnostics`):
  `param` → `compile_workflow(ir, registry, initial_params)` + `resolve_templates(config.template_config, shared, node_id)`
  (strict raises `ValueError` → "unresolved"; a param in `static_params` → "static-literal");
  `batch_items_str`/`batch_items_list` → `resolve_batch_items`; `loop_while`/`loop_until` →
  `evaluate_loop_condition`; `loop_max` → `resolve_loop_cap`; `loop_carry` → full runner only;
  `output_source` → `populate_declared_outputs`; `cache_var` → `_resolve_chunk_value`
  (+ `_render_cache_for_hash` vs `build_cache_system_blocks` texts for the byte-symmetry rows);
  `sub_inputs`/`sub_workflow` → `resolve_templates` on the `workflow` node's config + full runner
  with a child written to `tmp_path`. Mode via the IR key `template_resolution_mode`.
- Row dataclass: `Row(id, surface, template, payload, declared_inputs, params, mode,
  expect_validator: "ok"|"error"|("error", substring), expect_runtime: Resolves(value)|Unresolved|StaticLiteral|Value(...)|Raises(type),
  xfail: str|None, mutation: str)`. pytest ids from `row.id`.

**Row groups and the rows each phase later flips** (the deliverable of this phase is the
FULL table; the implementer extends it where a verified behavior is missing, never trims it):

1a. *Grammar table* (`test_template_grammar.py`, ~70 rows, pure): each row asserts today's
`TEMPLATE_PATTERN` matches, `_PERMISSIVE_PATTERN` matches (imported from
`template_validation.validator` — re-targeted to `parse()` in 4a), `has_templates`,
`is_simple_template`, `extract_variables`, `resolve_template` on a small context. Rows: every
shape in §1's grammar-edge list; hyphen identifiers; `[${a}]` literal bracket; all literal edges
(`007` no, `[1,2]` no, `"a??b"` no, `"\q"`/`"\u12"`/raw-tab **xfail(delta 2 / literal grammar,
4a)**: today matched, must round-trip `try_parse_json`); `$${var}`, `$${}`, `$${unclosed`,
`$$${x}`, `$$`; bash `${VAR:-x}`, `${#x}`; `${a[${i}]}`, `${a[${i}].x}`, `${a[${i}].x ?? b}`,
`${a[${i ?? 0}]}`, `${a[${i.j}]}`, `${a[${b[${c}]}]}` (two-level: rejected), `${a ?? "${b}"}`
(**xfail delta 2, 4c** on the validator side). Plus two invariants over the whole table: every
strict full-match is also permissive-discovered; every literal-grammar full-match round-trips
`try_parse_json` (xfail rows excluded until 4a).

1b. *Surface parity* (`test_template_parity.py::TestSurfaceParity`, ~60 rows): per surface ×
{bare ref, nested field, index, str-JSON auto-parse, union type, `any`, batch shapes
(`results[0].x`, item alias, dotted item), `??` with literal fallback, `??` root-absent,
`??` field-absent (#441), `??` all-absent, escape-only, escape+ref same param
(**xfail delta 1, phase 2**), upstream value containing `${b}` text (**xfail delta 1, phase 2**),
every converse-silent shape from §1 (**xfail delta 2, 4c** — validator must ERROR),
`${a ?? "${b}"}` (**xfail delta 2 — validator side, 4c**), `${arr[0]}` on a declared list
input (**xfail #262, 4c**), `${item.maybe ?? "none"}` on a batch item (**xfail Pass-8 policy,
4c**), `$n.stdout` output source (**xfail R4, 4c**), escape-only output source (row: ERROR
today and after; message class changes in 4c — assert on severity only), `items: ${typo.x ??
a.stdout}` in `batch.items` (**xfail 4c: data_flow surface set**), batch prewarm `system`
containing `$${x}` (**xfail delta 1, phase 2** — verify the read-only claim: user system dropped
today), inline batch list with an unresolved element (named under-check row: literal item, no
error — pinned as-is), cache var typo `${plan.stdot}` (chunk ABSENT — under-check row, pinned as-is
with an INFO advisory listed in §6 as follow-up), cache prose `$${topic}` with declared `topic`
(**xfail delta 5, 4d**: today duplicate-chunk/undeclared-chunk error or stray `$`), sub-workflow
`workflow: ${child}` (child gets no template pass — named row), `workflow: $${x}`
(**xfail R6, 4c**), dynamic-index rows from §1 through `resolve_templates`
(**xfail delta 3: int-inner/missing-outer → phase 2; non-int/OOB/bool/None → 4a; `??` non-int → 4a**),
`${r[${i}]}` JSON-string element shape (**xfail delta 3, 4a/4b**).
Assert both directions: `expect_validator` AND `expect_runtime`; the module docstring names
the two parity properties (one-way soundness; the converse).

1c. *Historical fixtures* (named tests, one per bug, docstring cites issue/commit, each
revert-checked mentally — "would this fail if the fix were undone?"):
`test_441_coalesce_absent_field_falls_through` (validator clean + `"x"`),
`test_460_generic_param_auto_parses` (**must** go through `build_type_cache(interface)` +
`resolve_templates` with a `list[str]`-declared param and a JSON-array-string value → parsed list;
`resolve_nested` alone cannot show it), `test_266_escape_not_flagged_as_template`,
`test_d5a1af8c_batch_alias_dotted_refs` (full `WorkflowValidator` — the fix is in `data_flow`),
`test_6b7faf8f_batch_over_workflow_node_results_index` (child workflow file in `tmp_path`),
`test_4516cd72_nested_index_coalesce_not_malformed` (`${a[${i}] ?? b[${i}]}` validator clean AND
resolves to `"x"` — 8535ed9b only names the fix), `test_620_docs_escape_example` (the docs
workflow verbatim through the runner — already in `test_template_escape.py`; reference it, do
not duplicate), `test_630_escape_and_reference_same_param` (**xfail(strict) → phase 2**),
`test_630_upstream_value_containing_template_text` (**xfail(strict) → phase 2**).

1d. *Dynamic-index characterization through `WorkflowRunner`* (`TestDynamicIndexConsumers`,
each a plain test with a `Mutation:` docstring, each **xfail(strict, "delta 3 …")** naming the
phase that flips it): shape (JSON-string element: str today → dict, 4a/4b), strict check
(outer path missing: literal shipped, exit 0 → strict error, phase 2 for int inner), declared
output (`source: ${p.out.items[${idx}].x}` with input `idx`: literal written → error/skip, 4b),
Optional code input (`row: Optional[dict]` over an absent root: literal → `None`, 4b),
diagnostics (inner missing → names `idx` today; outer missing → names `p.out.items[${idx}].x`
after, 4b), `??` with non-int inner (literal → fallback, 4a), loop `while:` over a dynamic index
(validator shape error → accepted, 4c — R1), type pass (`row: dict` annotated code input over
`${p.out.items[${idx}]}` → false ERROR today → clean, 4c — delta 6), unused-input (input used only
inside `[${idx}]` → "never used" ERROR today → clean, 4c — delta 6), `examples/test-nested-index.pflow.md`
runs unchanged (int inner, outer present — no xfail).

1e. *Raw-path characterization* (`TestRawPaths`): `-o result.@type`, `result.dc:title`,
`result.my key`, `result.0`, `batch.results[0].result` through `resolve_value`/`variable_exists`
AND through the CLI `-o` path (`workflow_output`) and `read_fields` — pins the raw-path mode.

1f. *Walk-pair consistency rows* (in `test_template_grammar.py`): §1's walk-pair table verbatim,
plus `${x[0] ?? "f"}` with `x=[None]` → `None` (the unpinned array variant).

**Failure scenarios the tests must catch** (each row's `mutation`): dropping the `(?<!\$)`
lookbehind; narrowing `_PERM_VAR` to `\w`; deriving `found` from `value is not None`
(flips 1f); making `has_templates == bool(exprs)` (re-breaks #620: escape-only params static);
counting Issues into `has_templates` (unvalidated IR runs flip); a validator pass that starts
field-checking `??` operands; a surface dropped from `_node_template_value_sources`.

**Gate.** File passes on unmodified production code with every xfail STRICT; `make test`
green; the implementer logs the full `make test`/`make check` baseline. **The gate outcome
changes the next instruction** (a row whose measured value contradicts §1 or the spec's freeze
is a STOP → hand back with the row): do not bundle with phase 2.

**Model/effort/agent.** Opus, `high` (the corpus's value is one mind holding all edge cases;
the rows are enumerated here but their expected values are measured, not copied). Agent **A**
(`task-phase-implementer`). Direct it to `test-reflect` (rows are easy to under-assert).
No mid-task review (tests only) — but the orchestrator reads the log's "surprises" line.

### Phase 2 — One internal walk + the unresolved set (#630) — ENGINE CONTACT

**Goal.** Merge `resolve_value`/`variable_exists`/`_traverse_path_part`/`_check_array_indices`
into one `_walk`; add `Resolution` + module-level `resolve()`; the engine's strict check,
`inject_none`, the loop-carry check, `_resolve_template_string`, `output_resolver`,
`resolve_batch_items` (string form) and `_resolve_chunk_value` consume the set; delete
`contains_unresolved_template` (R8). Sanctioned delta 1 flips.

**Files.** `src/pflow/runtime/template_resolver.py`; `src/pflow/runtime/engine/template_resolution.py`;
`src/pflow/runtime/engine/engine.py` (:242-258 carry check, :393-402); `src/pflow/runtime/output_resolver.py`;
`src/pflow/runtime/engine/batch_executor.py` (:108-131); `src/pflow/core/prompt_cache.py` (:136-176);
`tests/test_runtime/test_node_wrapper.py` (delete `TestContainsUnresolvedTemplate` :196-222 — sanctioned);
NEW `tests/test_runtime/test_template_walk_differential.py` (the phase gate; deleted at the end
of this phase once green — the consistency rows carry the pin forward).
Serialization: engine seam — no other producer touches `runtime/engine/` while this phase is live;
#503 must not be interleaved.

**Decisions (all resolved).**
- `_walk(segments, context) -> tuple[bool, Any]` where segments come from `_split_raw_path(path)`
  (lexical: split on dots outside brackets — today's `\.(?![^\[]*\])` — then per part
  `^([^[]+)((?:\[\d+\])+)$`; NOTE today's grammar-side `[N]` is at most one per segment but the
  raw walk accepts `[0][1]` chains; keep accepting them in raw mode — `resolve_value` does today).
  Truth table = §1 walk pair. `variable_exists = _walk(...)[0]`; `resolve_value = value if found else None`;
  `resolve_coalesce` one `_walk` per operand; `_resolve_inline_expr` one call. Delete
  `_traverse_path_part`, `_check_array_indices` (no external callers — verified).
- `resolve(value, context) -> Resolution` module-level in `template_resolver.py`;
  `resolve_template`/`resolve_nested` delegate. The set holds each expression's inner text that
  stayed literal, over the whole nested value. In this phase the string path still runs the
  nested-index pre-pass (deleted in 4a), so a rewritten `${a[0].x}` whose outer fails yields
  `a[0].x` in the set (delta 1's "partially rewritten dynamic index now errors"); the non-int
  case stays silent until 4a (its outer is not an expression yet).
- Engine changes per §0.2. `inject_none_for_optional_inputs` signature gains `unresolved:
  frozenset[str]`; `_expressions_of(template_str)` in this phase = `TEMPLATE_PATTERN.findall`
  (replaced by `parse` in 4b).
- `output_resolver.populate_declared_outputs`: `r = resolve(normalized, shared)`; if
  `r.unresolved`: all-absent-coalesce → skip, else failure; else write when `r.value is not None`.
  `resolve_output_source` → `None if r.unresolved else r.value`.
- `resolve_batch_items` string form: `None if r.unresolved else r.value` (then the JSON-list
  auto-parse as today). Inline list: `resolve(list).value` (unchanged semantics; named row).
- `_resolve_chunk_value`: `_CHUNK_ABSENT if r.unresolved else r.value`.
- Differential gate test: copy today's `variable_exists`/`resolve_value` bodies into the test as
  `_legacy_*` and assert equality with the new pair over an enumerated grid (paths from §1's
  walk-pair table + `a`, `a.b`, `a.b.c`, `a[0]`, `a.b[1].c`, `a[0][1]`, `a.b[9]` × contexts
  {dict, list, JSON-string, None-mid-path, OOB, non-list index, numeric-string leaf, nested
  Mapping proxy}). ≥150 combos.

**Failure scenarios the tests must catch.** found derived from non-None (1f rows); an
unresolved expression not reported (`${x} $${x}` row; `${a[0].x}` rewritten row); a resolved
value that legitimately contains `${…}` text reported as unresolved (upstream-`${b}` row;
`test_resolved_data_with_dollar_sign` logic moves into the corpus as a runner row);
`inject_none` injecting `None` for a partially resolved input; carry check in permissive mode
no longer detecting an unresolved carry (`test_loop_config.py` permissive carry tests must stay
green); prewarm `system` with `$${x}` dropped (row flips); `_CHUNK_ABSENT` no longer produced
for a chunk whose upstream is absent (byte-symmetry `..._with_absent_chunks` stays green).

**Rows that flip (xfail → pass, remove the marker):** delta-1 rows: escape+ref same param;
upstream `${b}` text; `${a[${i}].x}` int inner + missing outer (strict error); prewarm
`system` `$${x}`; `test_630_*` fixtures. No other corpus row changes.

**Handoff.** Freeze harness green with only the sanctioned deletion; corpus green (delta-1
rows unmarked, all other xfails strict); `test_template_walk_differential.py` was green then
deleted; grep `contains_unresolved_template|_check_string_unresolved|_traverse_path_part|_check_array_indices`
over `src/ tests/` → nothing; `last_resolutions` shape unchanged (grep `template_resolutions`
tests green); no new trace field.

**Model/effort/agent.** Opus, `high` (engine seam). Agent **B**. **Triggers mid-task review**
(engine contact): `review-silent-failures` (the set's completeness — a consumer left on text
comparison is silent) + `review-impact-completeness` (all seven text-comparison sites switched;
`_resolve_static_prefix_for_cache` deliberately deferred to 4d and said so). Same ownership
split as the completion gate.

### Phase 3 — Relocate to `core/` (mechanical) — bundled with phase 2 (Agent B, resumed)

**Goal.** `runtime/template_resolver.py` → `core/templates.py`; a re-exporting shim stays at
the old path; every `src/` importer points at the new home; the accessor indirection dies; the
layering pin + the litellm/runtime pin land; instruction files stop naming the old path.

**Files (the full importer inventory, verified 2026-09-28 — trust the grep, re-run it).**
- Move: `git mv src/pflow/runtime/template_resolver.py src/pflow/core/templates.py`; new
  `runtime/template_resolver.py` = 3 lines (`from pflow.core.templates import TemplateResolver,
  Resolution, resolve  # noqa: F401` + docstring "shim; delete in phase 5"). The class object must
  be the SAME object (three monkeypatch sites patch the class: `test_cache_analysis_token_estimation.py:508/:528`,
  `test_cache_analysis_analyze.py:5930`).
- `core/` importers → `from pflow.core.templates import TemplateResolver` at MODULE level
  (the laziness existed only for the layering violation — `context.py:47-56` docstring says so):
  `core/cache_overlap.py:27`, `core/prompt_refs.py:18`, `core/workflow/validator.py:16`,
  `core/workflow/data_flow.py:26`, `core/prompt_cache.py:164/:244`, `core/trace_report.py:518`,
  `core/workflow/graph/scope.py:41`, `core/prompt_cache_analysis/context.py:54/:269/:339/:404/:452`,
  `sub_workflow_walker.py:530/:553/:579`, `trace_loading.py:557`, `token_estimation.py:247/:399/:432/:458/:478/:678`.
  Delete the `template_resolver()` accessor (`context.py:47-56`, `__all__` :539) and hoist its
  four consumers (`stages/row_builder.py:16/:915-928`, `stages/discrepancy/predict.py:15/:373-416`,
  `stages/cross_workflow.py:16/:393-395`, `stages/warnings.py:22/:481-531`) to the module import.
  **Import-cycle check is part of this phase**: `uv run python -c "import pflow.core.workflow.validator, pflow.core.workflow.graph.scope, pflow.core.prompt_cache_analysis"`
  from a clean interpreter, plus the whole suite.
- `runtime/`, `execution/`, `cli/`, `nodes/`, `mcp_server/` importers (11 + 3 + 2 + 1 + 1 files;
  `runtime/engine/error_context.py:13` is the one RELATIVE import; `template_resolution.py:261`
  has a redundant lazy re-import — drop it).
- Tests: 17 files import the old path; re-point them in **phase 5** with the shim deletion
  (keeping phase 3 zero-test-edit apart from nothing — the shim keeps them green).
- Meta-tests: rule 4 in `tests/test_import_hygiene.py` (§0.5.3); the subprocess pin next to
  `test_litellm_runtime.py:882` (asserts no `litellm*` and no `pflow.runtime*` after
  `import pflow.core.templates`).
- Instruction/doc files naming `runtime/template_resolver.py` (the shim keeps
  `test_agent_references.py` green, so staleness is invisible — do it now):
  `.claude/agents/pflow-codebase-searcher.md:124`, `review-architecture-fit.md:36`,
  `review-silent-failures.md:33`, `review-plan.md:104`, `review-feature-interactions.md:77`,
  `review-validation-consistency.md:44/:81/:82` → then `make sync-claude-assets` (the `.codex/`
  mirrors are generated; `make check` enforces sync). `src/pflow/core/CLAUDE.md:156`,
  `src/pflow/runtime/CLAUDE.md:13` + its "Template resolution" section (point at core),
  `architecture/architecture.md:526`, `architecture/reference/template-variables.md:158/:922`,
  `architecture/core-concepts/data-type-coercion.md:73/:90` (drop the stale line numbers).
  `template_validation/CLAUDE.md`: add the current patterns to the regex table now; the
  "three patterns, do not unify" rewrite waits for 4c.

**Decisions.** Logger name changes to `pflow.core.templates` (no test pins the old one —
verified). `TEMPLATE_PATTERN`/`TEMPLATE_EXTRACT_PATTERN`/`SIMPLE_TEMPLATE_PATTERN` stay class
attributes. The three private reaches (`data_flow.py:34`, `cache_overlap.py:32`, `scope.py:56`)
and `validator.py:50/:652` keep working through the shim/class in this phase; they die in 4c/4e/5.

**Failure scenarios.** A lazy import left behind that dodges the layering pin (the pin scans any
scope); the class object duplicated (a monkeypatch site stops intercepting →
`test_cache_analysis_*` would still pass silently — so ADD an identity assertion
`pflow.runtime.template_resolver.TemplateResolver is pflow.core.templates.TemplateResolver`
to the shim's test); a cycle at import (the clean-interpreter import command).

**Handoff.** Full suite green with zero test edits; `test_import_hygiene.py` rule 4 green;
the e2e pin green (`make test-e2e` — it is `@pytest.mark.e2e`); `make check` green incl. asset
sync; grep `runtime.template_resolver` under `src/` → only the shim.

**Model/effort.** Opus, `medium` (spelled out). Agent B resumed after the phase-2 review is
dispositioned — the gate outcome cannot change these instructions, so no stop between 2 and 3
beyond the review.

### Phase 4 — Typed parse + drift-site migration (split into 4a–4e; each a resting point)

Order is load-bearing: 4a (the language) → 4b (runtime consumers) → 4c (validator consumers) →
4d (cache block) → 4e (graph + type-rule homes + display). 4b–4e each migrate only sites the
spec names; **no site outside the spec's phase-4 list moves** (the long tail is §6).

#### Phase 4a — The AST, `parse()`, and the facade over it (delta 3 resolver-side, delta 4)

**Goal.** `core/templates.py` gains the AST + `parse` + `parse_path` + `lookup` per §0.1; every
`TemplateResolver` method is reimplemented over them; the nested-index pre-pass and
`_INTERPOLATION_PATTERN` become dead (deleted in 5); the literal grammar is tightened;
`has_references` added.

**Files.** `src/pflow/core/templates.py`; `tests/test_core/test_template_grammar.py`
(re-target the `_PERMISSIVE_PATTERN` column to `parse()`: strict full-match ⇒ one Expression,
no Issue; permissive-discovered-but-strict-rejected ⇒ Issue — keep every `mutation`);
`tests/test_runtime/test_nested_templates.py:54-59` (**sanctioned flip**:
`test_non_integer_index_partial_resolve` now asserts the template is returned unchanged —
rename to `..._leaves_template_unresolved`, docstring cites delta 3); NEW
`tests/test_core/test_templates.py` (the module's direct tests: AST shapes, spans, immutability
pin — `FrozenInstanceError` on attribute set, tuples not lists, `Literal.value` fresh objects
across two `resolve` calls of `${a ?? []}`; cache bounded: `parse.cache_info().maxsize == 4096`;
`parse` never raises on 200 fuzz-ish fixed strings incl. every §1 shape, lone `$`, `${`, `}`,
unicode).

**Decisions.** Grammar per §0.1. `is_simple_template(s) = parse(s).is_simple` (a dynamic-index
simple template is now simple → `resolve_nested`'s auto-parse gate at the old `:866` applies —
the JSON-string-element shape row flips resolver-side). `extract_variables(s) = {r.raw for r in
parse(s).references}` — includes DynamicIndex inner refs AND the outer ref (delta 6 precondition;
today `{'i'}` becomes `{'a[${i}].x', 'i'}`) — `has_templates` unchanged in meaning
(`needs_resolution`); `has_references` new. `extract_simple_template_var` returns the inner raw
text (unchanged for static shapes; now non-None for dynamic-index simple templates — R1).
`split_coalesce_operands`, `is_literal_operand`, `is_coalesce_expression`, `extract_root_node_id`,
`extract_first_field_segment` stay lexical (they serve raw text too). `resolve_coalesce(expr, ctx)`
parses via `_parse_expression(expr)` (shared with `parse`), so an operand the grammar rejects is
skipped with a debug log (today: `try_parse_json` failure → skipped). The non-int-index
`logger.warning` (:152-156) becomes `logger.debug` (the reference is now reported as unresolved
through the normal channel — a warning AND an error would double-report).

**Failure scenarios.** An unescaped `${` becoming Text (converse-silent rows — the grammar
table asserts Expression-or-Issue for every candidate); an escape not consuming through `}`
(delta-4 rows); a DynamicIndex inner accepting `??`/nesting (`${a[${i ?? 0}]}`,
`${a[${b[${c}]}]}` → Issue); `[${a}]` outside braces parsed as an index; multi-index accepted;
`$$${x}`/bare `$$` regressions; single-pass re-scan regression (`TestEscapeAndSinglePassInterpolation`);
`Literal.value` sharing a mutable across calls; a `bool` inner index accepted; `resolve` raising
on any input.

**Rows that flip.** Delta 3 resolver-side: non-int / OOB / bool / None / `"1\n"` / `-1` inner →
unresolved; `??` with non-int inner → fallback; `${r[${i}]}` JSON-string element via
`resolve_nested` → dict. Delta 4: `$${a[${i}]}`, `$${FOO:-${bar}}`. Literal-grammar rows
(`"\q"`, `"\u12"`, raw tab). Engine-side dynamic-index rows stay xfail until 4b.

**Handoff.** Freeze harness green (only the one sanctioned flip); corpus as above; `make check`.
Grep: `resolve_nested_index_templates|_BRACKET_INDEX_PATTERN|_INTERPOLATION_PATTERN` have no
callers (definitions may linger for phase 5's sweep — or delete now if trivially dead).

**Model/effort/agent.** Opus, `high` (the parser is the riskiest piece; grammar spelled out but
the tokenizer's edge handling is real work). Agent **C** (fresh — phase 4 is ~half the task;
give it a clean window). **Triggers mid-task review**: `review-silent-failures` (Text/Issue
boundary, escape consumption) + `review-test-fidelity` (the grammar table re-target is where a
tautology could hide). Direct `test-reflect`.

#### Phase 4b — Runtime consumers on the AST (delta 3 engine-side) — ENGINE CONTACT

**Goal.** The engine and its runtime neighbours consume `parse`/`lookup` instead of regexes and
`str.split`; dynamic-index references get the simple-template treatment end to end.

**Files + per-site decisions** (line numbers as of `7dc5ad5d`):

| Site | Today | After |
|---|---|---|
| `engine/template_resolution.py:189-192` | `is_simple_template(template)` on original text | `parse(template).is_simple` (dynamic index → simple: auto-parse :351-360 + type validation :367-375 apply) |
| `:269-303 inject_none_for_optional_inputs` | `_expressions_of` via `TEMPLATE_PATTERN` (phase 2) | `parse(t).expressions`; `all_variables_from_absent_nodes` roots via `parse(t).references` |
| `:253-266 all_variables_from_absent_nodes` | `extract_variables` | `parse(template).references` roots (inner refs included) |
| `:351-360, :153-167` type literals | inline tuples | `CONTAINER_TYPES` (4e moves the constant; import here in 4e — in 4b keep the tuple, note it) |
| `engine/template_errors.py:126-161 classify_unresolved_references` | `TEMPLATE_PATTERN.finditer` + split + `variable_exists` | iterate `parse(template_str).expressions` → operands; Reference: classify the outer via `lookup(ref, context)` (status `path_error` ⇔ root SUCCEEDED and not found); for a Reference with DynamicIndex segments, FIRST classify each inner ref — an unresolved inner is the cause and is reported (as today); only when every inner resolves is the outer classified. `"absent"` keeps deriving from `NodeStatus.ABSENT`, never from `lookup` (a FAILED node's data lives in `__failures__` — `output_resolver._is_all_absent_coalesce` depends on it) |
| `:302-322 _suggest_field_correction` | `var.split(".", 1)` rebuild | rebuild from `parse_path(var)` segments (replace the first Field name; render segments back) |
| `:36 build_type_error_message` | `TEMPLATE_EXTRACT_PATTERN.search` | `parse(template_str).expressions[0].raw` (or the raw template when none) |
| `engine/engine.py:130-167 _diagnose_carry_ref` | `extract_simple_template_var` + `seg.split("[",1)[0]` | `parse(template)`: not simple / coalesce → `None`; `ref.path` Fields walked, any Index/DynamicIndex → defer `None` (may still resolve) |
| `engine/loop_control.py:131-153 evaluate_loop_condition` | `extract_simple_template_var` → `resolve_coalesce`/pair | `t = parse(condition)`; not simple → `False` (unchanged backstop); one Expression → `r = resolve(condition, context)`; value `None` if `r.unresolved` (str-value guard unchanged) — one walk, no pair |
| `:178-188 resolve_loop_cap` | `resolve_template` | unchanged (a str cap fails `int()` loudly already) |
| `runtime/output_resolver.py:81-101 _is_all_absent_coalesce` | `extract_simple_template_var` + `is_coalesce_expression` | `t = parse(normalized)`; `t.is_simple and len(t.expressions[0].operands) > 1`; keeps its stricter all-absent semantics (spec) |
| `engine/batch_executor.py:108-131` | done in phase 2 | unchanged |
| `execution/plan.py:1547/:2037` | `resolve_nested` / `resolve_output_source` | unchanged (inherit) |
| `core/workflow/validator.py:1733` | `resolve_nested` | unchanged (inherit); `_params_reference_alias` :1745 via `extract_variables` (now sees dynamic inner refs — desired) |
| `error_context.py` `extract_node_ids_from_template` | (check) | roots via `parse(...).references` |

**Failure scenarios.** Delta-3 characterization rows (1d): shape, strict error, declared
output skip/error, Optional `None`, diagnostics naming the outer ref, `??` fallback; a
`path_error` ref whose root FAILED being reported as absent (failed-node invariant tests
`tests/test_integration/test_failed_node_invariant.py` stay green); loop condition over a
resolved-`None` coalesce still stopping; `_diagnose_carry_ref` claiming absence through an
index (defer rows); type validation now firing on a dynamic-index dict param bound to `str`
(new strict error — a corpus row records it under delta 3).

**Rows that flip.** All remaining delta-3 rows in 1b/1d except the validator-side ones (loop
`while:` accept, type pass, unused input → 4c).

**Handoff.** Freeze harness green; corpus per above; `make check`; grep in `runtime/engine/`
for `split(".")|split("[")|TEMPLATE_PATTERN.finditer|TEMPLATE_EXTRACT_PATTERN` → only the
`engine.py:400`-style `.search` on RESOLVED text remains (allowed); no trace field added
(`test_trace_integration.py` green unmodified). #628 merged into the branch before this phase
starts (touches `output_resolver.py`).

**Model/effort/agent.** Opus, `high`. Agent C resumed. Mid-task review: **covered by 4a's and
4c's lenses** — the engine risk here is the set (already reviewed in phase 2) plus the
classifier of diagnostics; the orchestrator adds `review-agent-ux` on the diagnostic text
change (outer-ref naming) only if the 1d diagnostics row's wording looks off.

#### Phase 4c — Validator consumers on the AST (deltas 2 and 6; the classifier) — CROSSES LAYERS

**Goal.** Every validation pass consumes `parse()`/`parse_path()` segments and the operand
classifier; the malformed pass covers the same surfaces as reference extraction; `data_flow`
consumes references (inner refs included) and walks `batch.items`; output-source and cache
validation consume parsed operands; the deferral sites key on `has_references`. Delta 2
(strict grammar wins), delta 6, #262, the Pass-8 policy, R1/R3/R4/R5/R6 all land here.

**Files + per-site decisions.**

| Site | Today | After |
|---|---|---|
| `template_validation/validator.py:664-739 _validate_malformed_templates` | counts `_TEMPLATE_OPEN` vs `_PERMISSIVE_PATTERN` over `params` only | for each value from `_node_template_value_sources(node)` (params, `batch.items`, loop `while`/`until`/`max_iterations`), recursive over dict/list strings: `for issue in parse(value).issues` → ERROR; `kind == "bad_literal"` → today's targeted literal message (moved from `_malformed_literal_operand_hint`, which is deleted); else the generic message (drop the counts: "Malformed template syntax in '<raw>'" + the existing suggestion). Path/context keys unchanged (`nodes[id=X].params.<path>`; new: `nodes[id=X].batch.items[<i>]`, `nodes[id=X].loop.<key>`) |
| `:747-761 _operands_in_string` + `:783-806 _iter_template_operands` | `_PERMISSIVE_PATTERN.findall` + split | `parse(value)`; yield `(Reference, OperandPolicy, node_id)` for every reference in every Expression (DynamicIndex inner refs yielded with the enclosing operand's policy); Issues skipped (the malformed pass owns them) |
| `:809-828 _extract_all_templates / _field_checkable_templates` | `set[str]` | keep `set[str]` of `ref.raw` for unused-input accounting; `_field_checkable_templates` → `set[Reference]` filtered `FIELD_CHECK` (dedup by `raw`) |
| `:831-876 _extract_cache_templates_for_unused_check` | manual `??` split | `parse("${" + var + "}").references` roots |
| `:258-266 loop condition shape` | `extract_simple_template_var` | `parse(cond).is_simple` (accepts dynamic index — R1); operator-char rejection unchanged |
| `:273-280` loop-condition typing, `:390-412` carry unknown-output, `:457-486` carry prompt usage, `:519-545` literal-fallback warning, `:645-660` | `split_coalesce_operands`/`TEMPLATE_EXTRACT_PATTERN` | `parse(...).expressions[i].operands` |
| `path_validation.py:73-126 validate_template_path(template: str, …)` | `split_template_path` | `ref = parse_path(template)`; `None` → `(False, None)` (an unparseable string reaching Pass 5 is a bug elsewhere — log at debug); root = `ref.root`; `base_var in initial_params` keyed on ROOT (**#262 flips**); `validate_namespaced_output(ref, …)` / `validate_nested_path(ref.path[…], …)` take segments: `Field` → structure key; `Index`/`DynamicIndex` → descend into `items` when present (`_validate_array_access` dispatch unchanged incl. the continue-mode block at :169-174 — it must keep firing for dynamic indices: `test_array_notation.py:328-340`); type lists → `TRAVERSABLE_TYPES`/`TRUSTED_TRAVERSABLE_TYPES` imported from `core.templates` (4e moves them; 4c imports from their current home and 4e re-points — or land the constants in 4a: **decision: land the three constants in `core/templates.py` in 4a** so 4b/4c import them directly and 4e only deletes the copies) |
| `:366-406 create_template_diagnostic` + `_create_*_diagnostic` | `split_template_path` + string slicing | segments; message text unchanged (`test_enhanced_errors.py` green) |
| `batch_item_validation.py:101-137 _extract_item_field_refs` | own `extract_variables` walk | consume `_iter_template_operands` filtered `ref.root == alias` and `FIELD_CHECK` (**Pass-8 `??` row flips**); `_check_batch_item_ref`/`_build_batch_item_nested_diagnostic` take `ref.path` segments (`Index` stripped for structure lookup as today) |
| `type_checker.py:118-256 infer_template_type` | `split(".")` + `re.sub(r"\[\d+\]")` | `parse_path(template)` → segments; `Index`/`DynamicIndex` descend into `items` (the dynamic-index code-input false ERROR at `type_validation.py:701-705` disappears — delta 6 row); traversable checks use the shared sets (`str` now traversable → returns `"any"`, inert today — row pins it) |
| `type_validation.py:29/:176-188 _QUOTED_TEMPLATE_PATTERN` | own regex | quoted ⇔ `value[e.span[0]-1:e.span[0]] == "'" and value[e.span[1]:e.span[1]+1] == "'"` over `parse(value).expressions`; delete the pattern (`test_template_extract_pattern.py:14` imports `_build_quoted_templates` — keep that function name, change its body) |
| `type_validation.py:955 _traverse_to_structure`, `:582` fallback split | `split(".")` | `parse_path` segments / `extract_root_node_id` |
| `core/workflow/data_flow.py:34 _PFLOW_VAR_RE`, `:284-288`, `:772-844 _check_param_value` | `TEMPLATE_EXTRACT_PATTERN.finditer` + split + grammar gate | `for ref in parse(value).references: _validate_template_reference(ref.raw, …)` (Issues skipped — the malformed pass reports them; delete `_PFLOW_VAR_RE` and the :287 gate); `_validate_node_params` also walks `batch.items` (surface parity with `_node_template_value_sources`; a corpus row per surface asserts data_flow and template_validation cover the same set); DynamicIndex inner refs are references → forward-ref/undefined-input checks apply (delta 6) |
| `data_flow.py:1139-1159 cache root check` | `extract_root_node_id(var_expr)` | `parse("${"+var+"}")`: Issue → ERROR (chunk var malformed); each Reference root checked (R5) |
| `core/workflow/validator.py:516-652 output sources` | `"${" in source` / `TEMPLATE_EXTRACT_PATTERN.findall` | normalize like `output_resolver._normalize_source` (R4), then `t = parse(normalized)`: Issues → ERROR (malformed); no references → ERROR (R3); each Reference root ∈ valid_sources; message texts unchanged where they exist |
| deferral sites `core/workflow/validator.py:1008/:1047/:1155/:1262`, `template_validation/validator.py:1226`, `core/workflow/sub_workflow_resolver.py:93` | `has_templates` / `"${" in` | `has_references` (R6) |
| `template_validation/CLAUDE.md` | "three patterns, do not unify" table | rewrite as three VIEWS over one parse (strict = `Expression`; discovery = `Expression ∪ Issue`; simple = `is_simple`); "never `str.split('.')`" now true; drop `split_template_path` pointer (dies in 5); fix "data_flow still checks their roots" (true again after the batch.items walk — say so precisely) |

**Failure scenarios.** Every converse-silent row (validator must ERROR); `${a ?? "${b}"}`
validator-clean; `${arr[0]}` on a list input clean; Pass 8 no longer erroring on `??`; a
malformed `batch.items` element caught; `items: ${typo.x ?? a.stdout}` caught by data_flow;
input used only in `[${idx}]` no longer "unused"; `${typo[${i}].x}` and `${data[${typo}].x}`
both caught; `${a[${i}].x ?? b.y}` partner checked; the continue-mode index block still fires
for `[${i}]`; escape-only agent param / `output_schema` / `model` now statically checked
(rows); `$n.stdout` source accepted; escape-only source still an ERROR; cache var `a ?? b`
root-checked per operand; `test_validator.py:298-311` now passes for the RIGHT reason (assert
the malformed message, and add the positive control: a declared `data` node still errors).

**Rows that flip.** Delta 2 (all), delta 6 (all), #262, Pass-8 `??`, R1, R3–R6 rows, the
loop-`while`/type-pass/unused-input rows of 1d.

**Handoff.** Freeze harness green except the two sanctioned edits named above
(`test_validator.py:298-311` message assertion; `test_template_extract_pattern.py` if
`_build_quoted_templates`'s signature had to change — prefer not); corpus per above; grep
`_PERMISSIVE_PATTERN|_TEMPLATE_OPEN|split_template_path|_PFLOW_VAR_RE|_QUOTED_TEMPLATE_PATTERN`
under `src/` → definitions only (deleted in 5; `cache_overlap.py`'s `_PFLOW_VAR_RE` → 5).

**Model/effort/agent.** Opus, `high` (heaviest phase). Agent C resumed if its window is
<~400k, else a fresh Opus agent **C2** packeted with this plan + the progress-log tail + 4a/4b
entries (the continuity rationale expires once 4a's module docstring exists). **Triggers
mid-task review** (the validator contract changes here): `review-validation-consistency`
(validator vs runtime on every surface, both directions) + `review-impact-completeness`
(every pass switched; no pass left on the permissive grammar or `extract_variables`-as-policy).

#### Phase 4d — Cache block: chunking on spans + ADR-0015 helper + static-prefix interpolator (delta 5)

**Goal.** `_parse_cache_code_block` chunks on `parse(content)` spans; escapes in cache prose
are honoured; ONE helper renders `(name, unescaped prose, value)` for both the hash and prepare
sites; `_resolve_static_prefix_for_cache` interpolates over segments (unescapes) with its own
serializer.

**Files + decisions.**
- `core/markdown_parser.py:161-167` (`_CACHE_TEMPLATE_RE` + stale comment) and `:1721-1773`:
  `t = parse(content)`; each `Expression` is a chunk: `name = var_expr = content[span[0]+2:span[1]-1]`
  (assert `== expr.raw`); `prose_before = content[last_end:span[0]]` (escaped, verbatim);
  `chunk_line` from `content.count("\n", 0, span[0])`; each `Issue` → `MarkdownParseError`
  "Malformed template in '## Cache' block" at its line (R2); duplicate-name / no-chunk /
  trailing-prose-discard behaviors unchanged (`test_cache_block_parser.py` 21 tests green;
  add rows: `$${x}` in prose is prose, `${}` errors, unclosed `${a` errors, a trailing `$${x}`
  is discarded like any trailing prose).
- `core/prompt_cache.py`: NEW `render_cache_chunks(cache_ctx, shared) -> list[RenderedChunk]`
  (frozen `RenderedChunk(name, prose, value)`; prose = the Text of `parse(prose_before)` —
  assert the parse has no Expression, which holds by construction; value =
  `deterministic_serialize(_resolve_chunk_value(...))`; ABSENT filtered). `plan_node._render_cache_for_hash`
  (:160-201) → `[{"name": c.name, "prose": c.prose, "value": c.value} for c in render_cache_chunks(...)]`
  (hash dict shape unchanged → hashes change only for blocks containing `$${`, the ADR's
  sanctioned consequence); `build_cache_system_blocks` (:367-446) → `prose + value` per rendered
  chunk (reaches LLM node AND prewarm `batch_executor.py:640-647`). `CacheChunkIR.prose_before`
  stays escaped (`graph/build.py:680-684` re-emits it as template text; `cross_workflow.py:131`
  compares escaped-to-escaped; `suggestions.py:735` token estimate counts one extra char per
  escape — negligible, noted).
- `_resolve_static_prefix_for_cache` (:224-256): iterate `parse(text).segments`: Text → text
  (unescaped — fixes the prewarm static prefix sending literal `$${HOME}`, found 2026-09-28),
  Expression → `lookup`-based value → `_deterministic_serialize`, unresolved → raw `${…}`
  text, Issue → verbatim. Its stale docstring ("Python repr") corrected. `test_prompt_cache.py:186-201`
  stays green; add a `$${` row.
- Byte-symmetry: `tests/test_nodes/test_llm/test_prompt_cache_rendering.py:466/:1108` — add a
  third test whose chunk prose contains `$${HOME}` and asserts hash texts == prepare texts ==
  the unescaped form.
- Docs: `docs/how-it-works/prompt-caching.mdx:46` ("verbatim" → "verbatim except `$${` escapes,
  which render as `${`"); `src/pflow/guide/features/prompt-caching.md` if it repeats the claim.

**Failure scenarios.** Hash/prepare divergence on an escaped chunk (the third byte-symmetry
test); a `$${topic}` in prose parsed as a chunk (delta-5 rows: validates, renders `${topic}`);
`prose_before` unescaped in IR (graph `cached_prefix` fixture `web/src/test/fixtures/contracts/prompt-caching-multi-chunk.json`
+ `test_graph_build.py` unchanged); a chunk name that differs from the raw source slice
(the assert); an Issue in prose silently becoming prose (R2 row); the prewarm static prefix
still containing `$${` (row through `_resolve_static_prefix_for_cache`).

**Rows that flip.** Delta 5 (cache prose escape; hash == prep); R2; the static-prefix `$${` row.

**Handoff.** `test_cache_block_parser.py`, `test_prompt_cache*.py`, `test_prompt_cache_rendering.py`,
`test_graph_build.py` green (+ new rows); the Task-159 baseline `.taskmaster/tasks/task_159/baseline/verify.sh`
run as the outer net (not a trace-format change — the trace's `llm_system` stores rendered
text, which changes only for `$${` blocks; verify the script passes and log it).

**Model/effort/agent.** Opus, `medium` (fully spelled out). Agent C/C2 resumed.

#### Phase 4e — Graph scope + web mirror, type-rule homes, display strippers

**Goal.** `scope.py` consumes the AST (and `scan.ts` mirrors it in the same step); the type
rules move to their homes (§0.4); the two mermaid strippers and the cost-analysis
`[2:-1]` strips use the facade.

**Files + decisions.**
- `core/workflow/graph/scope.py`: `refs_with_path_in(value)` = for each `Reference` in
  `parse(value).references` (inner refs of a DynamicIndex included → edges from BOTH the outer
  root and the index source; today: none): `(root, first Field name after root or None, tuple of
  remaining Field names)`; `Index`/`DynamicIndex` segments are skipped in the field tuple —
  `${data[0].field}` → `("data", "field", ())` (**accepted characterization delta**, spec-named;
  no test pins the old `("data", None)` — add the new pin in `test_graph_build.py:1330-1344`).
  Delete `_BRACE_BLOCK_RE`/`_REF_IN_BLOCK_RE` and the `_VAR_NAME_PATTERN` reach.
- `web/src/graph/scan.ts:46-60` + `paramTextReads` (:99-131): mirror the same three changes
  (skip `[N]` and `[${…}]` index segments; yield the inner ref of a dynamic index; keep the
  `$$` lookbehind); `web/src/graph/scan.test.ts` gains the bracket + dynamic-index rows with a
  "Runtime parity (mirrors scope.py)" comment. Verify with the web test runner (`cd web && npm
  test -- scan` or the project's equivalent — check `web/package.json`) AND via the
  `screenshot-pflow-web-ui` skill on `examples/test-nested-index.pflow.md` (the canvas must show
  the DATA_FLOW edge from `process-batch` into the consumer with the `stdout` label) — the one
  UI surface this task touches; not design-bearing (no taste), so Opus.
- `core/types.py`: receives `TYPE_COMPATIBILITY_MATRIX` + `is_type_compatible`
  (`type_checker.py:38-115` verbatim); `type_validation.py:18` imports from `core.types`;
  `tests/test_runtime/test_template_validation/test_type_checker.py:9` re-points its import
  (**sanctioned mechanical edit**). `type_checker.py:223/:250`, `path_validation` lists,
  `template_resolution.py:351-360/:153-167`, `type_validation.py:143` → the `core.templates`
  sets (delete the copies). Pointers: `.taskmaster/tasks/task_112/task-112.md:11/:71/:136/:164/:174/:194`
  (and `research/output-field-validation.md:44/:114` — stale `runtime/type_checker.py`),
  `task_120/task-120.md:11/:13/:66`; `architecture/reference/template-variables.md:599/:608`;
  `src/pflow/core/CLAUDE.md` types section; `template_validation/CLAUDE.md:15`.
- `core/workflow/graph/renderers/mermaid.py:790` → render `parse(text)` segments with
  Expressions as their `raw` (behavior identical: strips `${`/`}`); `:836-842 _strip_template`
  → `extract_simple_template_var` with the loose fallback (accepts coalesce as today).
- `core/prompt_cache_analysis/stages/warnings.py:485/:528` `stripped[2:-1]` after an
  `is_simple_template` check → `extract_simple_template_var` (two-line change; the spec's
  Structure names them in the out-of-scope long tail, but they sit one line from a facade call —
  do it, it deletes two ad-hoc parsers).

**Failure scenarios.** An edge lost for `${data[0].field}` (new pin); web scan disagreeing with
Python edges (vitest rows + screenshot); `is_type_compatible` behavior change (its 45
assertions in `test_type_checker.py` — same values, one home); the `#460` fixture.

**Handoff.** Suite green with the two sanctioned import re-points; web tests green;
screenshot evidence in the task folder; Tasks 112/120 pointers updated.

**Model/effort/agent.** Opus, `medium`. Agent C/C2 resumed (UI-driving is one screenshot — no
rotation trigger).

### Phase 5 — Sweep and seal

**Goal.** Delete every superseded regex/splitter/pre-pass and the shim; land meta-test 2 with
its allowlist; re-point the 17 test imports; finish instruction files; net LOC at or below
baseline.

**Deletions (each after a grep proves zero users):** `core/templates.py`:
`resolve_nested_index_templates`, `_BRACKET_INDEX_PATTERN`, `_INTERPOLATION_PATTERN`, the
class-level `_VAR_NAME_PATTERN`/`_LITERAL_PATTERN` aliases (module-private now; grep `tests/`
for reaches first — none expected). `template_validation/validator.py`: `_PERM_VAR`,
`_PERM_OPERAND`, `_PERMISSIVE_PATTERN`, `_TEMPLATE_OPEN`, `_malformed_literal_operand_hint`.
`template_validation/utils.py::split_template_path` + its `__init__.py` export (:7/:19) +
`tests/test_runtime/test_nested_templates.py:71-130 TestSplitTemplatePath` (sanctioned — its
eight expectations already live in `test_templates.py` as `parse_path` segment rows; verify
before deleting). `core/cache_overlap.py:32 _PFLOW_VAR_RE` + `:124-136` finditer → `parse`
(the grammar gate becomes `parse_path(operand) is not None`; `_canonicalize_path` :57-89 stays
— an accepted survivor over canonical tuples, §6). `cli/workflow_output.py:295
_PATH_SEGMENT_PATTERN` stays (raw-path mode, no `\$\{` — §6). The shim
`runtime/template_resolver.py` + the 17 test import re-points (`from pflow.core.templates
import TemplateResolver`). `contains_unresolved_template` already gone (phase 2).
- Meta-test 2 (`tests/test_core/test_template_grammar_seam.py`, §0.5.2) lands and is green on
  first run (if it is not, the phase found a missed site — migrate it, do not allowlist it).
- `test_yaml_utils.py::TestBraceAwareTemplates`: add the `$${y}` and `${a[${i}].x}` flow-mapping
  pin rows (the allowlist reason for `yaml_utils`).
- `.claude/agents/review-validation-consistency.md:158/:219` cite `_PFLOW_VAR_RE` (symbol check
  in `test_agent_references.py`) → rewrite those lines around `parse()`; `make sync-claude-assets`.
- Instruction files: `src/pflow/core/CLAUDE.md` (new `templates.py` row + a short "Template
  language" section: AST, `parse`/`resolve`/`lookup`, the raw-path mode, the no-`parse`-on-resolved-text
  rule), `runtime/CLAUDE.md` (Template resolution section points at core; the nested-index
  paragraph rewritten), `runtime/engine/CLAUDE.md` (the "Parameters, reuse, and templates"
  paragraph: unresolved set, no text comparison), `core/workflow/CLAUDE.md:59` (`_PFLOW_VAR_RE`
  paragraph → parse), `template_validation/CLAUDE.md` (views table final), `tests/CLAUDE.md`
  (corpus row), `.claude/agents/pflow-codebase-searcher.md` (recipe line + a "template
  language" pointer), `docs/how-it-works/template-variables.mdx` (escape section: "consumes
  through the closing `}`"; dynamic index: one reference, failures inside it are unresolved),
  `src/pflow/guide/features/batch.md:160-173` (correct per the 1d characterization — the
  `${my_input[${__index__}]}` claim is verified in phase 1), `context/CONTEXT.md` (no new
  nouns expected; if "Dynamic index" or "Issue" crystallize, propose them in the handback, do
  not edit).
- Final grep list (must be empty under `src/`): `_PERMISSIVE_PATTERN|_TEMPLATE_OPEN|_PERM_VAR|split_template_path|_CACHE_TEMPLATE_RE|_BRACKET_INDEX_PATTERN|_INTERPOLATION_PATTERN|resolve_nested_index_templates|_BRACE_BLOCK_RE|_REF_IN_BLOCK_RE|_PFLOW_VAR_RE|_QUOTED_TEMPLATE_PATTERN|contains_unresolved_template|TemplateResolver\._VAR_NAME_PATTERN|TemplateResolver\._LITERAL_PATTERN|runtime\.template_resolver`.
- LOC: report `git diff --stat main..HEAD -- src/` in the log; the target is ≤ baseline for
  `src/` (June estimate; measure, do not chase).

**Failure scenarios.** Meta-test 2 false-negative (a `\$\{` constant inside an f-string
fragment or a `BinOp` — the test's own fixture rows: a temp file with each spelling must be
caught; a `re.compile(f"{TemplateResolver.TEMPLATE_PATTERN.pattern}")` composition must be
caught by rule B); the shim deletion leaving a stale `.claude/agents` path (test_agent_references).

**Handoff.** `make check` + `make test-all-local` green; all three meta-tests green; grep list
empty; the manual end-to-end list (§4) executed and logged; spec `## Status` → `done` +
`## Completed` (task-orchestrator close-out).

**Model/effort/agent.** Opus, `medium`. Agent C/C2 resumed, or a fresh Opus agent **D** if the
window is spent (the sweep is grep-driven; a fresh agent loses little).

---

## 3. Agent assignment and bundling (summary)

| Phase | Agent | Model / effort | Stop after? | Mid-task review |
|---|---|---|---|---|
| 1 | A (fresh) | Opus / high | **Yes** — a surprising row changes the plan | none (tests only); `test-reflect` directed |
| 2 | B (fresh) | Opus / high | Yes — review dispositions | `review-silent-failures`, `review-impact-completeness` |
| 3 | B (resumed) | Opus / medium | Yes (phase boundary commit) | none |
| 4a | C (fresh) | Opus / high | Yes — freeze gate | `review-silent-failures`, `review-test-fidelity`; `test-reflect` directed |
| 4b | C (resumed) | Opus / high | Yes | (covered by 2 + 4c; optional `review-agent-ux`) |
| 4c | C or C2 | Opus / high | Yes | `review-validation-consistency`, `review-impact-completeness` |
| 4d | C/C2 (resumed) | Opus / medium | Yes | none (byte-symmetry tests are the net; Task-159 baseline script) |
| 4e | C/C2 (resumed) | Opus / medium | Yes | none |
| 5 | C/C2 or D | Opus / medium | — | completion gate: full battery incl. `review-falsifier` (direct launch), `review-spec-conformance`, `review-simplicity`, `review-feature-interactions` |

Bundle-vs-resume litmus applied: phases 2→3 and 4b→4c→4d→4e are "continue as planned"
resumes (one message each, one job each); the stops after 1, 2 (review), 4a (freeze gate) and
4c (review) are the ones whose outcome can change the next instruction. Rotate C at ~400k.

---

## 4. Verification beyond the per-phase gates

- **Manual end to end** after 4e and at completion (`uv run pflow …`, results logged with the
  exact commands and outputs): the #620 docs example; both #630 repros (`echo "${greeting} |
  $${greeting}"`; upstream `${b}` text + `${b}` ref); a batch with `${p.results[${__index__}].x}`
  into a dict param (shape preserved) and one with an out-of-range index (strict error names the
  outer reference); a `## Cache` block containing `$${HOME}` (validates; `pflow --dry-run`
  and a run agree on the rendered prefix — `llm_system` in the trace shows `${HOME}`); a prewarm
  batch prompt containing an escape (the warm-up user block contains `${…}`, not `$${…}`);
  `pflow <wf> -o result.@type` and `pflow read-fields <run> result.0`; a byte-identical run of
  every `examples/**/*.pflow.md` that needs no API key (shell/code/file-only — pick by reading
  `examples/CLAUDE.md`; compare `--output-format json` before phase 1 and after phase 5; the
  "before" capture is a phase-1 deliverable stored under the task folder's `implementation/`
  as a gitignored scratch or committed if small).
- **Windows gate:** the corpus prefers `code` over `shell` consumers; the two shell rows use
  `echo` with no quoting — the blocking `tests-windows` job runs the parity file.
- **Trace format:** untouched by construction (§0.2); the Task-159 baseline script runs after
  4d as an outer net; any need for a new trace field is a hand-back, not a bump.
- **Structure properties** (spec) pinned by: meta-test 2 (one grammar home + by-symbol),
  meta-test 3 (layering), the litellm/runtime subprocess pin, the immutability pin, the
  `cache_info` bound pin, the phase-5 grep list.

---

## 5. Sanctioned test changes (the complete list; anything else is a deviation to log)

| Phase | Test | Change |
|---|---|---|
| 2 | `tests/test_runtime/test_node_wrapper.py:196-222` | delete `TestContainsUnresolvedTemplate` (function deleted) |
| 4a | `tests/test_runtime/test_nested_templates.py:54-59` | flip: non-int inner → template unchanged (delta 3) |
| 4a | `tests/test_core/test_template_grammar.py` | re-target the permissive column to `parse()` (phase-1 file, planned re-target) |
| 4c | `tests/test_runtime/test_template_validation/test_validator.py:298-311` | assert the malformed message (right reason) + positive control |
| 4e | `tests/test_runtime/test_template_validation/test_type_checker.py:9` | import re-point (`core.types`) |
| 5 | `tests/test_runtime/test_nested_templates.py:71-130` | delete `TestSplitTemplatePath` (function deleted; rows live in `test_templates.py`) |
| 5 | 17 test files importing `pflow.runtime.template_resolver` | import re-point |
| 1–5 | the corpus xfail markers | removed exactly in the phase named on the row |

---

## 6. What stays unmigrated, and why (the honest seal)

- **String-helper long tail on the facade (permanent, by design):** every `TemplateResolver.*`
  caller outside the spec's phase-4 site list — `core/prompt_cache_analysis/*` (context.py's six
  equality sites, `token_estimation.py`, `trace_loading.py`, `sub_workflow_walker.py`,
  `predict.py`, `row_builder.py`), `core/prompt_refs.py` (span consumer — moves to
  `parse().expressions` spans only if touched later; its `first_per_item_position` tearing a
  nested index at position 23 is a recorded existing bug for a lane, not fixed here),
  `core/trace_report.py:495-567` (display-only suggestion walker; the :526 heuristic is
  required to stay — no trace field), `core/cache_overlap.py:57-89 _canonicalize_path`
  (canonical-tuple walker), `diagnostic_render.py:735 _extract_field_path`,
  `sub_workflow_walker.py:106/:119-123/:448-453`, `suggestions.py:150/:526`,
  `execution/formatters/*`, `mcp_server/services/field_service.py`.
- **The ~35 lexical `"${" in x` presence checks** (17 files; count from 2026-09-28) and the 7
  `startswith("${")`/`endswith("}")` checks: prefilters, out of scope (spec).
- **Raw user-typed paths** (`-o`, `read-fields`, MCP `read_fields`, `node_output_formatter`,
  `cross_workflow` synthetic refs): the raw-path mode of `resolve_value`/`variable_exists`;
  `cli/workflow_output.py:295 _PATH_SEGMENT_PATTERN` + `_diagnose_path_failure` stay as they are
  (no `\$\{`, no grammar copy).
- **Output `source:` prose wrap** (`prefix ${n.stdout}` → `'${prefix OK}'`): recorded, not fixed.
- **`coerce_param_for_node`'s `json.dumps`** (a third stringification for simple-template
  dict/list → `str` params; `ensure_ascii=True` vs `to_string`'s `False`): named, not unified —
  outside the spec's freeze.
- **Cache var typo silently ABSENT** (`${plan.stdot}`): root-only validation stays (the spec
  records it); an INFO advisory when a chunk is dropped at runtime is a follow-up suggestion
  in the handback, not built here.
- **Web TypeScript mirrors other than `scan.ts`** (`sourceDecorate.ts:32`, `batchItems.ts:26`,
  `format.ts:9` — no `$$` lookbehind): a separate issue (spec).
- **`TypeVocabularyError(ValueError)`**, **#503's `ValueError` contract** in
  `template_resolution.py`: untouched (never interleave).
- **`extract_root_node_id` / `extract_first_field_segment` / `split_coalesce_operands`**
  stay lexical helpers (they serve raw text and diagnostics).

---

## 7. Risks and their nets

| Risk | Net |
|---|---|
| The parser's tokenizer diverges from today's regexes on an unenumerated shape | 1a grammar table (~70 rows) + `parse`-never-raises fuzz rows; 4a's review lenses |
| A consumer of "unresolved by text" missed | phase-2 `review-impact-completeness`; the grep in the phase-2 handoff; corpus rows per consumer |
| `Literal` mutable sharing through the cache | immutability pin (fresh objects across two resolves) |
| `str` traversability alignment changes a diagnostic | the corpus row pins "inert"; `test_type_checker.py` unchanged values |
| Hash change for `$${` cache blocks surprises a fixture | none in-tree (verified); byte-symmetry third test |
| Windows: corpus shell rows | `code` consumers preferred; two `echo` rows only |
| Phase 4c collides with #628/#520 | #628 merged before 4b; #520 builds on `parse()` after 4c (packet note) |
| Context exhaustion in phase 4 | C→C2 rotation rule at ~400k; the plan + log are the packet |
