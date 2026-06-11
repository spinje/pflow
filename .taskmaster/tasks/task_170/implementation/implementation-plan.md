# Task 170 Implementation Plan — One Template Language (`core/templates`)

## Context

pflow's `${…}` template language has no owning module. Evidence (architecture review
2026-06-11, recorded in `.taskmaster/tasks/task_170/task-170.md`): 7 regex families parse the
syntax, 6+ independent path walkers exist (two near-duplicates *inside* `TemplateResolver`
itself), the type-judgment rules are encoded 4×, 13 files split `??` operands themselves, and
the static validator is a hand-written model of the runtime resolver kept in sync only by
comments — ≥7 shipped drift bugs (#441, #460, #266, d5a1af8c, 6b7faf8f, 8535ed9b), zero parity
tests. 15 `core/` files import the resolver from `runtime/` (layering inversion).

This plan implements Task 170: one module `core/templates` owning grammar, value walk, and
semantic rules; the validator keeps its own structure walk but consumes the same parsed
segments and rules; three meta-tests make drift loud. The decided shape and the rejected
alternatives (shared-walk World port, hand-written scanner, property-test generator) are
recorded in `context/adr/0006-template-language-no-shared-walk.md` — do NOT re-open them.
Vocabulary (Template, Reference, Coalesce, Operand) is fixed in `context/CONTEXT.md`.

**Prime directive: zero user-facing behavior change in every phase.** The existing test suite
is the freeze harness; phase 1's drift tests must pass against UNMODIFIED production code.

## Phase structure (order is load-bearing)

1. **Parity drift tests** — land the fence before touching production code.
2. **One internal walk** — merge the duplicated traversal loops in `TemplateResolver`.
3. **Relocate to `core/`** — fix the 16-file layering inversion; shim in `runtime/`.
4. **Typed parse + drift-site migration** — the AST; migrate validation passes, data_flow,
   engine resolution, error classification, cache chunking, scope.py.
5. **Sweep and seal** — delete superseded machinery; grammar-uniqueness AST-scan meta-test.

Each phase ends with `make test` + `make check` green and is a legitimate stopping point.

## Frozen behaviors (the spec for every phase — violating any of these is a bug)

- JSON auto-parse on traversal: containers only; numeric strings stay strings.
- Simple templates (`${var}` exactly) preserve type; complex templates stringify via
  `_convert_to_string` rules verbatim (None/""→"", False→"False", True→"True", 0→"0",
  []→"[]", {}→"{}", dict/list→json.dumps ensure_ascii=False, else str()).
- `$$` escape prevents resolution but does NOT strip the extra `$`.
- `??` falls through on absent root OR absent field; literal operand always resolves and ends
  the chain; literal-first classification (keyword literals beat same-spelled identifiers).
- Literal grammar: no leading-zero numbers, no `??` inside strings, only `[]`/`{}` composites.
- Identifiers allow hyphens (`[a-zA-Z_][\w-]*`).
- Dynamic index `${a[${i}].x}` — VERIFIED truth table (run against live resolver; the naive
  "left unchanged" description is WRONG for two of three cases):
  | inner index | outer ref | today's output | strict-mode outcome |
  |---|---|---|---|
  | resolves to int | NOT resolvable | `${a[0].x}` — index SUBSTITUTED, rest unresolved | contains_unresolved=False → SILENT pass-through |
  | resolves non-int (`"abc"`) | — | `${a[abc].x}` — inner SUBSTITUTED via complex-interpolation | logger.warning (resolver :147-150) + SILENT pass-through (pinned: tests/test_runtime/test_nested_templates.py:54-60) |
  | inner var missing | — | text fully unchanged | contains_unresolved=True → strict error / permissive DEGRADED |
  Phase-4 DynamicIndex resolution MUST reproduce all three rows (emit re-rendered source
  text with resolved inner substitutions applied, outer wrapper intact; keep the non-int
  logger.warning). Case 1 is pinned by NO existing test — phase 1 adds a pin row for it.
- Unresolved templates remain textually unchanged; strict-mode erroring stays engine policy.
- `output_resolver._is_all_absent_coalesce` keeps its stricter semantics — NOT absorbed.

## Phase 1 — Parity drift tests

**New file: `tests/test_runtime/test_template_drift.py`.** Pure in-process, no marker (runs in
`make test`). Must pass against UNMODIFIED production code before any other phase starts.

Follow the repo's established idioms exactly:

- **Harness**: build workflow IR as inline dicts (`{"nodes": [{"id", "type", "params"}], "edges": []}`)
  — the idiom of `tests/test_runtime/test_template_validation/test_validator.py:214-228`.
  Define a file-local `create_mock_registry()` returning `Mock()` with
  `get_nodes_metadata = Mock(side_effect=...)` serving
  `{"interface": {"inputs": [...], "outputs": [{..., "structure": {...}}], "params": [], "actions": [...]}}`
  per node type (copy the shape from `test_validator.py:12-127`). The package CLAUDE.md says
  each file defines its own mock registry — do NOT extract to conftest.
- **Validator side**: `tests/shared/diagnostic_helpers.split_template_diagnostics(workflow_ir, params, registry)`
  → `(errors, warnings)` of typed `Diagnostic`s.
- **Resolver side**: static calls, `TemplateResolver.resolve_nested(params, context)` — the
  end-to-end precedent is `tests/test_runtime/test_template_feature_combinations.py:100-172`.
- **Docstring contract**: module docstring "Drift-catcher tests: template validator vs runtime
  resolver. If a test here fails, fix the divergence, never the test." Each test carries a
  **Mutation:** clause naming the production change that would trip it — the
  `test_plan_drift.py` convention (see its per-test docstrings, e.g. lines 320-331).

Three test groups:

**1a. Grammar-coherence table (pure regex assertions, no workflow).** One parametrized corpus
(module-level list of ~80 rows: `(template_string, expectations)`) covering: hyphenated
identifiers, `$${var}` escapes, single/multi bracket indices, nested dynamic index
`${a[${i}].x}`, `??` chains (ref??ref, ref??literal, literal-only), every literal edge
(leading-zero numbers must NOT match, `??` inside quoted strings must NOT split, `[]`/`{}`
match, `[1,2]` must NOT, keywords vs `truthy_value`), malformed shapes (`${}`, `${a..b}`,
unclosed `${a`), bash syntax (`${VAR:-x}`, `${#arr[@]}`), AND escaped-malformed shapes
(`$${var}` → silent; `$${unclosed` and `$${}` → malformed ERROR today — pin these; no
existing test covers `$$`+malformed), permissive-accepted/strict-rejected path shapes
(`${a.0}`, `${a.}` — today: NOT malformed, surface as pass-5 path errors; pin that class),
dynamic-index partial-substitution rows (pin the verified truth table from Frozen
behaviors — especially case 1, `${results[${__index__}].field}` with `results` absent →
`${results[0].field}` silent pass-through, pinned by NO existing test), and
`extract_variables` expectations on dynamic-index forms
(`extract_variables("${a[${i}].x}") == {"i"}` today — the outer ref is invisible to the
strict pattern; the phase-4 facade must preserve this, NOT return `{"a[${i}].x"}`).
Each corpus row carries a `mutation` field (the production change that would trip it —
e.g. hyphen row ← "narrow `_PERM_VAR` to `\w`"; escape row ← "drop the `(?<!\$)`
lookbehind"), since one parametrized test can't carry per-row Mutation docstrings.

Also pin the PERMISSIVE∖STRICT grammar gap at the DIAGNOSTICS level (verified live, these
are today's outcomes — the parser's two-tier rule must reproduce them):
- `${first.stdout.}` (trailing dot, valid root) → silent at EVERY layer (validates clean,
  ships literal text);
- `${a..b}` → NOT malformed; pass-5 path error ("no valid source");
- `${first.1x}` (digit-leading field) → NOT malformed; pass-5 error ("does not output '1x'");
- `$${undefined.field}` → pass-5 ERROR today (permissive findall has no `$$` lookbehind, so
  ESCAPED content is discovered by the validator even though runtime treats it as inert
  text) — this is **characterization delta: escaped-visibility**: under the planned parser,
  cleanly-escaped candidates are invisible to validation, so this flips ERROR→silent, and
  an input referenced ONLY as `$${input}` flips used→unused-ERROR. Recommended: accept
  (escaped = inert everywhere — today's behavior is itself validator/runtime drift), pin
  the NEW behavior with tests, document in the PR. Never silent.

Assert per row:
- if `TEMPLATE_PATTERN` fully matches → `_PERMISSIVE_PATTERN` (import from
  `pflow.runtime.template_validation.validator`) must also discover it (validator may never
  call resolvable syntax malformed — the #266/8535ed9b class);
- every `_LITERAL_PATTERN` full-match must round-trip `try_parse_json` (the resolver
  docstring's prose invariant, mechanized). NOTE: this invariant cannot catch widening
  toward valid JSON (e.g. accepting `[1,2]` round-trips fine) — the explicit
  `[1,2]`-must-NOT-match row carries that load; keep both.
Known decision this table forces: `_PERMISSIVE_PATTERN` has no `$$`-escape lookbehind, so
`$${var}` content IS discovered at validation today. Pin CURRENT behavior with a comment
(`# documented permissiveness — see template_validation/CLAUDE.md`), do not "fix" it.

**1b. Soundness corpus (validator ⟺ resolver on the same artifact).** Parametrized rows of
`(node_outputs_structure, template, conforming_context)` — declared structure for a producer
node, a template referencing it, and a context whose shapes conform to the declaration.
For each row: run `split_template_diagnostics` on a 2-node IR (producer → consumer with the
template in consumer params); run `TemplateResolver.resolve_nested` against the conforming
context. HARNESS MANDATES (each prevents a verified false-confidence trap):
- Refs are NAMESPACED (`${producer.out…}`) and contexts are shared-store-shaped
  (`{"producer": {"out": …}}`) — `extract_node_outputs` registers BOTH flat and namespaced
  keys, and the flat legacy key validates against a context shape production never produces.
- Consumer mock declares an `any`-typed input for the template param (prevents pass-6
  type-matching noise contaminating rows) and the IR declares no unused inputs.
- Use custom mock type names (`producer`/`consumer`), NOT real node types — `code` and
  `workflow` hit special-cased branches in extract_node_outputs; only deliberate rows use
  those.
- ORACLE: each row carries `expected_value`; assert
  `TemplateResolver.resolve_nested({"p": template}, context)["p"] == expected_value`
  EXACTLY (rows are deterministic) and `errors == []` for the whole single-template
  workflow. Do NOT use `result != template text` as the resolution oracle (fails on partial
  resolution, None-valued simple templates, value-equals-text).
- SCOPE: the no-ERROR assertion applies to grammar/path/existence diagnostics only.
  Passes 6 (typed primitive sinks), 7 (shell safety: dict into `command` ERRORs while
  runtime serializes fine), and 10 (loop checks) DELIBERATELY over-reject resolvable
  templates — they are exempt by policy, named as such in the test docstring. Do NOT
  assert the converse anywhere (the validator legitimately under-checks: user params,
  `??` chains, unknown types).
Rows must cover: nested dict paths, array indices, str-typed fields containing JSON
(auto-parse), union types (`list|string`), `any`, batch shapes (`results` + item alias —
the d5a1af8c/6b7faf8f class), `??` with literal fallbacks, dotted refs on batch outputs.

**1c. Historical regressions (six named tests).** One test per drift bug, docstring citing
issue/commit, encoding the exact scenario:
- `test_441_coalesce_optional_field_not_field_checked` — `${ran_node.optional_field ?? "x"}`
  validates clean and resolves to fallback. (Standard harness — verified writable.)
- `test_460_generic_type_traversal` — HARNESS DEVIATION REQUIRED: the #460 mechanism is
  `_runtime_base_type` in `engine/template_resolution.py:30-44`, which
  `TemplateResolver.resolve_nested` never reaches (a resolve_nested-based test stays green
  with the bug reverted). This test must call `build_type_cache(interface_metadata)` +
  `resolve_templates(...)` from `pflow.runtime.engine.template_resolution` (import
  precedent: `tests/test_runtime/test_null_defaults.py:8-12`) with a `list[str]`-declared
  output whose value is a JSON-array STRING, and assert the resolved param `== ["a", "b"]`
  (parsed list, not the string) AND the validator accepts.
- `test_266_escaped_template_not_flagged` — `$${var}` produces no has-templates positive.
- `test_d5a1af8c_batch_dotted_item_refs` — HARNESS DEVIATION REQUIRED: the d5a1af8c fix
  lives in DATA_FLOW (`core/workflow/data_flow.py` — batch alias missing from
  declared_inputs), which `validate_workflow_templates` never runs. Use
  `split_validator_diagnostics` (`tests/shared/diagnostic_helpers.py:16`, runs the full
  `WorkflowValidator.validate` including data_flow). `${item.field}` in a batch context →
  no errors.
- `test_6b7faf8f_batch_on_workflow_node` — the fix is in extract_node_outputs' workflow
  branch (batch-on-workflow skipped batch-output registration). Write a real child
  workflow to `tmp_path` and reference it by file path (the autouse `isolate_pflow_config`
  means a NAMED child won't resolve); batch over it; `${node.results[0].field}` access
  validates clean.
- `test_8535ed9b_nested_index_coalesce_not_malformed` — CORRECTED POINTER: the fix is in
  commit **4516cd72** (8535ed9b's diff does NOT contain the fix or template — verified).
  Template: `${a[${i}] ?? b[${i}]}`, already validator-pinned at
  `tests/test_runtime/test_template_validation/test_malformed.py:293-316`. The drift
  version adds what that pin lacks: the RESOLVER side — against
  `{"a": ["x"], "b": ["y"], "i": 0}` it resolves to `"x"`.

Gate: full suite green (`make test`), file passes with zero production edits.

## Phase 2 — One internal walk

**File: `src/pflow/runtime/template_resolver.py` only. All public signatures unchanged.**

Today there are two traversal loops in the class: `resolve_value` (:558-627, returns value or
None) and `variable_exists` → `_traverse_path_part` → `_check_array_indices` (:453-556,
returns bool — note `_traverse_path_part` returns the CONTAINER on the last segment, and
`_check_array_indices` skips applying the final index: existence-only semantics). They share
the same dot-split regex (:545/:579) and bracket regex (:498/:585). `resolve_coalesce`
(:360-361) and `_resolve_complex_match` (:785+:780) each call BOTH — double traversal, and
the two loops can in principle disagree.

Change:
1. Add private `_walk(var_name: str, context: Mapping) -> tuple[bool, Any]` — ONE traversal
   returning `(found, value)`. Semantics: value side = today's `resolve_value` (applies all
   indices, JSON auto-parse via `_get_dict_value`/`_try_parse_json_for_traversal`, OOB index
   → not found, None mid-path → not found); found side = today's `variable_exists` truth
   table (None/empty/0/False all EXIST; missing key / null parent do not — pinned by
   `tests/test_runtime/test_null_defaults.py:20-49`).
2. Reimplement: `variable_exists` = `_walk(...)[0]`; `resolve_value` = value where found else
   None; `resolve_coalesce` = one `_walk` call per operand (replaces :360-361);
   `_resolve_complex_match` = one call (replaces the :780/:785 pair).
3. Delete `_traverse_path_part` and `_check_array_indices` (no external callers — verified;
   `_get_dict_value` stays: `tests/test_runtime/test_template_resolver.py` imports it).

**MUST-PRESERVE pin**: `tests/test_cli/test_workflow_output_handling.py:1522-1538` pins the
missing-vs-None distinction by design ("a future refactor that uses just resolve_value and
checks for None would fail this test"). `_walk`'s found flag is what keeps that working.

**Do NOT touch the external exists-then-resolve pair callers** (`loop_control.py:150-153`,
`workflow_output.py:182-183/:332-334`, `success_formatter.py:206-207`,
`node_output_formatter.py:48/:52`, `cross_workflow.py:393-395`, `read_fields.py:61`,
`field_service.py:74`): their behavior is pinned and their signatures are the public API.
The only pair-caller that migrates later is `workflow_output._diagnose_path_failure`
(phase 4 table). The rest stay on the pair permanently.

Gate: full existing resolver suites pass unmodified (3,373 lines across 11 files — the
freeze harness), especially `test_null_defaults.py`, `test_template_resolver_arrays.py`,
and the consistency classes (`test_template_resolver_json_parsing.py:133`,
`test_template_resolver_inline_object_parsing.py:311`). MANDATORY (not optional): extend
the consistency class with edge rows — JSON-string mid-path, None mid-path, OOB index,
dict-in-list, and the one genuinely UNPINNED disagreement surface:
`${a[0] ?? "f"}` with `a = [None]` — today `variable_exists` True / `resolve_value` None /
coalesce returns **None, not "f"** (the dict-field variant is pinned at
test_template_coalesce.py:371-374; the array-element variant is pinned by NOTHING — a
merged `_walk` deriving found from value-is-non-None flips it silently). Land these rows
BEFORE the merge.

## Phase 3 — Relocate to core/

1. **Move** `src/pflow/runtime/template_resolver.py` → `src/pflow/core/templates.py`
   verbatim (collision verified: nothing named `templates` exists in src/). Promote
   `_VAR_NAME_PATTERN` → `VAR_NAME_PATTERN` and `_LITERAL_PATTERN` → `LITERAL_PATTERN`
   (keep underscore class aliases until phase 5 — `template_validation/validator.py:27`
   and tests import the privates).
2. **Shim**: `runtime/template_resolver.py` becomes
   `from pflow.core.templates import TemplateResolver  # noqa: F401` + a docstring pointing
   at the new home. Patterns are class attributes, so the class re-export covers every
   consumer.
3. **Re-point ALL src importers** to `pflow.core.templates`. Regenerate the inventory
   with BOTH greps (≈28 src files / 43 lines @ 9ebd6280 — trust the grep, not the count):
   `grep -rn "runtime.template_resolver" src/ --include='*.py'` AND
   `grep -rn "from \.\.template_resolver\|from \.template_resolver" src/ --include='*.py'`.
   While re-pointing, fix the two private-pattern reaches to use the promoted constants:
   `core/cache_overlap.py:32` and `core/workflow/data_flow.py:33` switch from
   `TemplateResolver._VAR_NAME_PATTERN` to `VAR_NAME_PATTERN` (data_flow's `_PFLOW_VAR_RE`
   dies entirely in phase 4, but must not reference a private meanwhile).
   Traps:
   - `runtime/engine/error_context.py:13` uses a RELATIVE import
     (`from ..template_resolver import`) — absolute greps miss it.
   - 13 lazy in-function imports across `core/prompt_cache_analysis/*` + `core/prompt_cache.py`,
     `core/trace_report.py:482`, `core/workflow/graph/scope.py:28`, `nodes/llm/llm.py:543`.
4. **Simplification that comes free** (do it — it deletes a workaround):
   `core/prompt_cache_analysis/context.py:47-54`'s `template_resolver()` accessor and the
   lazy-import pattern exist SOLELY because of the core→runtime layer violation (its
   docstring says so). Delete the accessor, hoist all its call sites
   (`stages/row_builder.py:916/:928`, `stages/discrepancy/predict.py:368-411`,
   `stages/cross_workflow.py:393-395`, `stages/warnings.py:482-531`, `context.py` itself)
   and the other core/ lazy imports to top-level
   `from pflow.core.templates import TemplateResolver`. Same for the
   `data_flow.py:1421-1424` lazy import + comment.
5. **Test updates**: only 3 monkeypatch sites import lazily and need the new path
   (`tests/test_core/test_cache_analysis_analyze.py:5800`,
   `test_cache_analysis_token_estimation.py:501/:521` — they patch the CLASS object, safe
   across the move once the import line is updated). Verified: ZERO string-path patch
   targets, ZERO importlib strings, ZERO caplog pins on the resolver's logger name.
6. **Layering meta-test**: add to `tests/test_core/` an AST-scan (mirror
   `test_litellm_runtime.py:837-920` mechanics) asserting NO module under `src/pflow/core/`
   imports `pflow.runtime.template_resolver` or `pflow.runtime.template_validation`
   (empty allowlist). Scope it to template modules ONLY — core→runtime imports exist
   elsewhere (trace_report→workflow_trace, prompt_cache→node_state, trace_loading→cache);
   those are pre-existing and OUT OF SCOPE; a blanket test would fail today.
7. **Doc updates**: `runtime/CLAUDE.md:14/:58`, `runtime/engine/CLAUDE.md:342`,
   `template_validation/type_checker.py:32` (comment), `architecture/architecture.md:526`,
   `architecture/reference/template-variables.md:158/:922`,
   `architecture/core-concepts/data-type-coercion.md:73/:90` (these two cite line numbers —
   replace with the new path, drop line numbers).

Note: `runtime/template_validation/` does NOT move (it imports core — the allowed
direction). Only the resolver moves.

## Phase 4 — Typed parse + drift-site migration

### 4.1 The module interface (`src/pflow/core/templates.py` — single file)

```python
# ── Grammar constants (the single definition; exported) ──
VAR_NAME_PATTERN: str            # promoted from TemplateResolver._VAR_NAME_PATTERN
LITERAL_PATTERN: str             # promoted from TemplateResolver._LITERAL_PATTERN
TEMPLATE_PATTERN: re.Pattern     # strict (unchanged semantics, $$-lookbehind)
TEMPLATE_EXTRACT_PATTERN: re.Pattern  # loose (unchanged semantics)

# ── AST (frozen dataclasses, slots) ──
@dataclass(frozen=True) class Index:        value: int
@dataclass(frozen=True) class DynamicIndex: ref: "Ref"   # inner ${var} — plain Ref ONLY
                                                          # (today's _BRACKET_INDEX_PATTERN
                                                          # accepts only a simple var inside)
@dataclass(frozen=True) class Field:
    name: str
    indices: tuple[Index | DynamicIndex, ...]             # a.b[0][1] → Field("b",(Index(0),Index(1)))
@dataclass(frozen=True) class Ref:
    segments: tuple[Field, ...]   # segments[0] is the root (root may carry indices: data[0])
    raw: str                      # original operand text — display, dedup, set membership
    @property def root(self) -> str: ...                  # segments[0].name
@dataclass(frozen=True) class LiteralOperand:   # NOT "Literal" — collides with typing.Literal
    raw: str
    value: Any                    # via try_parse_json. MUTABILITY RULE: parse() is lru_cached,
                                  # so a stored [] / {} would be ONE shared instance handed to
                                  # every resolution process-wide (batch threads, loop
                                  # iterations) — a node mutating it would corrupt the cached
                                  # AST. Store the parsed value for immutable scalars only;
                                  # re-parse (fresh object) composite literals ([], {}) at
                                  # resolution time
    valid: bool                   # looks-literal (coarse first-char check) but failed grammar
Operand = Ref | LiteralOperand
@dataclass(frozen=True) class Expr:
    operands: tuple[Operand, ...] # len > 1 ⇔ coalesce chain
    span: tuple[int, int]         # offsets of ${...} in the source string, inclusive of ${ }
    raw: str                      # inner text
    resolvable: bool              # TWO-TIER acceptance, load-bearing: Expr-acceptance uses
                                  # the PERMISSIVE shape (so `${a.0}`/`${a.}` stay visible
                                  # to pass 5 as path errors, as today — NOT malformed
                                  # errors); resolvable=True only for the resolution grammar
                                  # (strict + dynamic-index). resolve() acts ONLY on
                                  # resolvable Exprs; the malformed pass errors ONLY on
                                  # Issues. This reproduces today's split where the runtime
                                  # silently ignores `${a.0}` while pass 5 reports a path
                                  # error on it
@dataclass(frozen=True) class Issue:
    raw: str; span: tuple[int, int]
    kind: Literal["malformed", "bad_literal"]  # ONLY kinds consumers branch on today:
                                  # bad_literal = the _malformed_literal_operand_hint case
@dataclass(frozen=True) class ParsedTemplate:
    source: str
    exprs: tuple[Expr, ...]       # grammar-valid templates (strict view)
    issues: tuple[Issue, ...]     # ${-candidates that failed the grammar
    @property def is_simple(self) -> bool                 # source is exactly one Expr

@functools.lru_cache(maxsize=4096)
def parse(source: str) -> ParsedTemplate   # pure, total, never raises on user input

def parse_ref(path: str) -> Ref | None     # bare path WITHOUT ${…} wrapper ("node.field[0]")
                                            # → Ref via full-match of the var grammar; None if
                                            # not a valid ref. Required by two consumers that
                                            # hold path strings, not templates: type_checker's
                                            # infer_template_type (called with bare operands)
                                            # and workflow_output's -o path diagnoser

def strip_template_markers(text: str) -> str  # "${x} y ${z}" → "x y z"; today's loose
                                               # display-stripping (mermaid.py:775 — strips
                                               # even empty/escaped, [^}]* semantics). Moves
                                               # here so the grammar-uniqueness scan stays
                                               # clean; mermaid calls this helper

# ── Value walk (built on phase 2's _walk) ──
class LookupStatus(Enum): FOUND; ROOT_ABSENT; PATH_ABSENT
def lookup(ref: Ref, context: Mapping) -> tuple[LookupStatus, Any]
def resolve(value: Any, context: Mapping) -> Any          # = today's resolve_nested semantics

# ── Semantic rules (the #460 drift class — REQUIRED, this is a stated purpose of the
#    task; do not drop). One home for the judgment calls currently encoded twice: ──
TYPE_COMPATIBILITY_MATRIX / is_type_compatible(source, target)  # moves from type_checker.py:38-115
TRAVERSABLE_TYPES / TRUSTED_TYPES / STRING_TYPES                 # the lists at path_validation.py:327/:335/:342
                                                                  # and the inline copy at :291
def runtime_base_type(type_str: str) -> str   # = engine/template_resolution._runtime_base_type
                                              # (:30-44, generics-stripping incl. the union
                                              # exception) — engine imports it from HERE
def to_string(value: Any) -> str              # _convert_to_string rules, verbatim
# Consumers after phase 4: type_checker.py + path_validation.py + type_validation.py import
# the sets/matrix; engine/template_resolution.py imports runtime_base_type + the auto-parse
# eligibility set (("dict","list","object","array") literals at :347-354). Zero logic change
# — same values, one home, pinned by test_460 + the 1b union rows.

# ── Facade definitions that must be stated (silent-failure guards) ──
# has_templates(source) == bool(parse(source).exprs)  — EXPRS ONLY, not exprs-or-issues.
#   Today `${}`/`${a`/`${a..b}` have has_templates=False → split_params classifies them
#   static → silent passthrough to the node. Counting issues would flip unvalidated dict-IR
#   runs from silent passthrough to strict errors.
# Permissive-tier segmentation must reproduce split_template_path: empty path segments are
#   DROPPED (trailing-dot `${first.stdout.}` is silent at EVERY layer today — verified live:
#   validates clean, has_templates False, literal text ships. Preserve exactly.)

# ── TemplateResolver stays, as the permanent string-helper facade ──
# All existing public methods keep their exact signatures, reimplemented over
# parse()/lookup()/resolve(). The long tail (prompt_cache stack etc.) never migrates.
```

Parser implementation rules (regex-TOKENIZED — no hand scanner, per ADR-0006):
- Scan for `${` candidates left-to-right. A `$$`-escaped candidate that PARSES CLEANLY
  produces NOTHING (no Expr, no Issue) — resolution leaves its text untouched,
  has_templates stays False for it, the malformed check stays silent (today: permissive
  findall has no lookbehind, so `$${var}` counts 1-valid-of-1). BUT an escaped candidate
  that is itself malformed (`$${unclosed`, `$${}`) still yields an Issue — today these
  ERROR (count 1 `${`, permissive findall 0). The escape skip applies ONLY to
  cleanly-parsing candidates. Phase-1 corpus rows pin both cases (no existing test covers
  `$$`+malformed — verified).
- A candidate matching the strict grammar (extended with dynamic-index brackets) → Expr.
  A candidate that does not → Issue; kind="bad_literal" iff it contains `??` and some
  operand passes `is_literal_operand` but fails `LITERAL_PATTERN` fullmatch (this is
  exactly `_malformed_literal_operand_hint`, validator.py:628-657); else "malformed".
- DynamicIndex parsing replaces `_PERMISSIVE_PATTERN`'s reason to exist: `${a[${i}].x}`
  parses directly (inner = plain Ref, one level — reject nesting deeper, as today).
- Literal-first operand classification (keyword literals beat identifiers) — preserved.
- The phase-1 corpus is the acceptance test for all of the above. Where the parser's
  natural behavior would differ from today's counting logic, TODAY WINS.

### 4.2 Per-site migration (exact inventory; signatures verified @ 9ebd6280)

Internal package signatures MAY change; `validate_workflow_templates(workflow_ir,
available_params, registry) -> list[Diagnostic]` and `extract_node_outputs(...)` MUST NOT.

| Site | Today (verified) | After |
|---|---|---|
| `template_validation/validator.py::_validate_malformed_templates` (:660-735) | counts `${` vs `_PERMISSIVE_PATTERN.findall` + nested-count crediting (:682-697); targeted literal msg via `_malformed_literal_operand_hint` | `p = parse(value)`; error iff `p.issues`; kind=="bad_literal" → the targeted message, else the generic one. Counting + crediting logic deleted (absorbed by parser). Scope unchanged: walks only `node.params` (NOT batch/loop fields) — preserve this quirk |
| `validator.py::_operands_in_string` (:743-757) | `_PERMISSIVE_PATTERN.findall` + `split_coalesce_operands` + literal drop | `for expr in parse(value).exprs: for op in expr.operands: if isinstance(op, Ref): yield (op, len(expr.operands) > 1)` — now yields `Ref` objects |
| `validator.py::_extract_all_templates` (:805) / `_extract_cache_templates_for_unused_check` (:827) | `set[str]` of operand text | UNCHANGED return type (`set[str]` via `ref.raw`) so `_validate_unused_inputs` and the :116 union are untouched |
| `validator.py::_field_checkable_templates` (:815-824) | `set[str]`, filtered `not in_coalesce` | yields `Ref`s (dedup by `.raw`); Pass 5 consumes segments directly. #441 policy (coalesce operands excluded) stays HERE, unchanged |
| `path_validation.py::validate_template_path` (:73-79) + `validate_namespaced_output` (:207, inline bracket parse :225-232) + `validate_nested_path` (:253) | `split_template_path` (:97,:386) + hand-rolled `output_part[:bracket_pos]` slicing | take `Ref`; `parts` = `ref.segments`; bracket slicing replaced by `Field.indices`. The structure-walk LOGIC (lookup keys `f"{base_var}.{base_output}"`, `_validate_array_access` dispatch) is UNCHANGED — but `check_type_allows_traversal`'s type lists (:327/:335/:342, plus the inline copy at :291) now IMPORT the shared rules sets from 4.1 (same values, one home) |
| `type_checker.py::infer_template_type` (:118, splits :141/:145/:169/:231) | `template.split(".")` + 3× `re.sub(r"\[\d+\]","",…)` | NOTE: it receives BARE operand strings (no `${…}` wrapper) — use `parse_ref(template)`, not `parse()`. Consume `Ref.segments` (`Field.name`, `bool(field.indices)` replaces the indexed-access detection at :178). `parse_ref` returns None → keep today's fallthrough. `TYPE_COMPATIBILITY_MATRIX`/`is_type_compatible` (:38-115) MOVE to the 4.1 rules home (type_checker imports them); union split `:222` stays here (type-string policy) |

| `runtime/engine/template_resolution.py` (:30-44 `_runtime_base_type`, :121-167 `validate_resolved_type`, :347-354 auto-parse type literals) | hand-mirrored copies of the validator's type rules — born from drift bug #460 | import `runtime_base_type` and the auto-parse eligibility set from the 4.1 rules home. ZERO logic change — same values, one home. This row is the #460 fence made structural; without it the rules stay two manually-synced encodings |
| `batch_item_validation.py::_check_batch_item_ref` (:150-151), `_build_batch_item_nested_diagnostic` (:253-254), `_extract_item_field_refs` (:127-135) | `field_path.split(".")` + `.split("[")[0]` + startswith/slice | consume segments; prefix matching via `ref.root == item_alias` + `segments[1:]` |
| `validator.py::_loop_declared_outputs` (:378) | `key[len(node_id)+1:].split(".",1)[0].split("[",1)[0]` over node_outputs keys | NOTE: operates on node_outputs KEYS (not templates) — keep as-is but switch the segment strip to a shared helper if trivial; do not force-fit the AST |
| `core/workflow/data_flow.py::_check_param_value` (:778-800) | `TEMPLATE_EXTRACT_PATTERN.finditer` + `split_coalesce_operands` + `is_literal_operand` + `_PFLOW_VAR_RE` gate (:286) | `for expr in parse(value).exprs: for op in expr.operands:` skip `LiteralOperand`; ALSO skip any operand containing a `DynamicIndex` (today the extract pattern truncates at the inner `}` so dynamic-index templates are INVISIBLE to data_flow — checking them would add forward-ref errors and double diagnostics with pass 5; preserve invisibility). Pass `op.raw` to `_validate_template_reference` (signature unchanged). Issues skipped silently — replaces the `_PFLOW_VAR_RE` gate (bash → Issue → skipped, same outcome). KNOWN NARROWING (accept + note in PR): a coalesce mixing a valid ref with a bad literal (`${second.stdout ?? [1,2]}`) is one Issue, so data_flow stops checking the valid ref — today it errors at BOTH entry points; after, only the WorkflowValidator-side malformed pass reports (direct `compile_workflow()` callers lose the check; all CLI/MCP paths validate first). Delete `_PFLOW_VAR_RE` (:33). Dict/list recursion (:801-819) unchanged |
| `engine/template_errors.py::classify_unresolved_references` (:126-187) | `TEMPLATE_PATTERN.finditer` + split + literal skip; per-operand `get_node_status` + `variable_exists` (:173,:176) | iterate `parse(template_str).exprs`/operands; replace the exists-call with `lookup(ref, context)` (status PATH_ABSENT ⇔ today's path_error branch). `get_node_status` root check stays (node-state policy). INVARIANT: the `"absent"` string status must continue to derive from `NodeStatus.ABSENT` (which checks `__failures__` first), NEVER from `LookupStatus.ROOT_ABSENT` — a FAILED node's data lives in `__failures__` so its root is absent from the lookup context; deriving "absent" from the walk would make `output_resolver._is_all_absent_coalesce` silently skip a declared output whose primary FAILED instead of raising (the regression runtime/CLAUDE.md flags). `_suggest_field_correction` (:320-322) path rebuild → segment-based. DYNAMIC-INDEX content rule: when a dynamic-index Expr's INNER ref is the unresolved one (truth-table case 3), the diagnostic must name the inner ref (`${i}`), as today — the strict pattern only ever saw the inner; naming the full outer ref is a message change |
| `core/markdown_parser.py::_parse_cache_code_block` (:1716-1768) | `_CACHE_TEMPLATE_RE.finditer` (:166); prose = inter-match slice (:1733); chunk_line from `content.count("\n",0,match.start())` (:1739) | iterate `parse(content)` in span order; prose/lines from spans identically. CHUNK-BOUNDARY RULE: a boundary is an Expr OR an Issue whose candidate has a closing `}` and non-empty inner text (today's `[^}]+` shape) — unclosed `${a` and empty `${}` are NOT boundaries, preserving the "must contain at least one ${var}" error for a `${}`-only block. Add pin rows for `${}`/unclosed to test_cache_block_parser.py first. CHARACTERIZATION DELTA: `_CACHE_TEMPLATE_RE` has no `$$` lookbehind; `parse` skips cleanly-escaped. Before switching, add a test pinning current `$$`-in-cache-block behavior; surface the decision in the PR — do not change silently. Duplicate-name/zero-template/trailing-prose-discard behaviors unchanged (covered by tests/test_core/test_cache_block_parser.py, 21 tests) |
| `core/workflow/graph/scope.py::source_refs_in` (:26-40) | `_BRACE_BLOCK_RE` + `_REF_IN_BLOCK_RE` (accepts digit-leading roots) | per Expr → per Ref → `(ref.root, segments[1].name if len(segments)>1 else None)`. TWO CHARACTERIZATION DELTAS, both test-pinned + PR-noted: (1) digit-leading roots no longer extracted (validator-rejected input anyway); (2) indexed roots — `${data[0].field}` today yields `("data", None)` (the `_REF_IN_BLOCK_RE` boundary class makes post-bracket `.field` unreachable), new code yields `("data", "field")`, changing the output_field label on DATA_FLOW graph edges in `pflow visualize`. Recommended: accept both as corrections; pin the NEW behavior with tests and document the delta — never silent |
| `engine/engine.py::_diagnose_carry_ref` (:75-112) | `seg.split("[",1)[0] for seg in var.split(".")` | `parse(template)`; reuse `Ref.segments` for the dict walk; coalesce/complex defer rule (:96) unchanged |
| `cli/workflow_output.py::_diagnose_path_failure` (:289-337) | `_PATH_SEGMENT_PATTERN.findall` + per-prefix `variable_exists` (O(n²)) | NOTE: receives a BARE `-o` path — use `parse_ref(key)`; None replaces the reconstruction guard (invalid chars → generic syntax hint, same behavior). Build prefix Refs from segments; one `lookup` per prefix. The `[N]`-bracket nudge behavior is pinned by an existing test — keep it |

Order within phase 4: (1) build `parse()` + AST against the phase-1 corpus; (2) reimplement
`TemplateResolver` methods over it (all existing resolver suites must pass UNMODIFIED — this
is the freeze gate); (3) migrate sites in table order, running the relevant suite after
each — EXCEPT rows 2–5 plus the path_validation row, which are ONE ATOMIC STEP: the chain
`_operands_in_string` → `_iter_template_operands`/`_node_template_value_sources`
(validator.py:760-802, the traversal pivot) → `_extract_all_templates`/
`_field_checkable_templates` → `validate_template_paths` (path_validation.py:30, its
`set[str]` parameter becomes `Ref`s) shares types end-to-end; making row 2 yield `Ref`s
breaks downstream consumers until they migrate in the same change. The suite cannot be
green between those rows — land them together.

## Phase 5 — Sweep and seal

**Deletions** (each only after grep confirms zero remaining users):
- `template_validation/validator.py`: `_PERM_VAR`, `_PERM_OPERAND`, `_PERMISSIVE_PATTERN`
  (:46-50), `_malformed_literal_operand_hint` (absorbed into parser), the counting logic
- `template_validation/utils.py`: `split_template_path` (+ its re-exports in `__init__.py`;
  update `tests/test_runtime/test_nested_templates.py` imports — its 8 cases move to the
  parser's segment tests, same expectations)
- `core/templates.py` (post-move resolver internals): `resolve_nested_index_templates` +
  `_BRACKET_INDEX_PATTERN` (DynamicIndex made them dead), the second traversal loop
  (already dead after phase 2)
- `core/markdown_parser.py`: `_CACHE_TEMPLATE_RE` (:166)
- `core/workflow/graph/scope.py`: `_BRACE_BLOCK_RE`, `_REF_IN_BLOCK_RE` (:11-12)
- `core/workflow/data_flow.py`: `_PFLOW_VAR_RE` (:33) [if not already removed in phase 4]
- `runtime/template_resolver.py` shim — 18 TEST files import it (all import only the
  `TemplateResolver` class — verified), so "zero importers" will NOT hold unless tests are
  re-pointed. DECIDE NOW: re-point the 18 test imports in phase 5 (mechanical,
  `from pflow.core.templates import TemplateResolver`) and delete the shim. Do that.
- type_checker's `re.sub` index-stripping sites (dead after segment migration)
- `cli/workflow_output.py`: `_PATH_SEGMENT_PATTERN` (:286 — dead after the parse_ref
  migration)
- The underscore pattern aliases on `TemplateResolver` (`_VAR_NAME_PATTERN`,
  `_LITERAL_PATTERN`) — all reaches were re-pointed in phase 3 (`cache_overlap`,
  `data_flow`) or deleted in phase 4/5 (`validator.py:49` dies with `_PERMISSIVE_PATTERN`).
  The private METHODS `_convert_to_string`/`_get_dict_value` are KEPT — they are the
  declared direct-test surface of `tests/test_runtime/test_template_resolver.py`.

**Two remaining `${…}` regexes need explicit treatment** (the meta-test fails otherwise):
- `runtime/template_validation/type_validation.py:29` `_QUOTED_TEMPLATE_PATTERN`
  (`r"'\$\{([^}]+)\}'"` — shell single-quote escape hatch): rebuild it FROM the exported
  grammar — `re.compile(rf"'{TEMPLATE_EXTRACT_PATTERN.pattern}'")` — so the string literal
  no longer restates `\$\{` (the scan checks literals, so derivation passes naturally) and
  the grammar has one home. Behavior identical (same inner `[^}]+`).
- `src/pflow/mcp/auth_utils.py:14` `ENV_VAR_PATTERN` (`${VAR:-default}` bash-style env
  substitution in MCP configs): a FOREIGN grammar, not pflow templates — ALLOWLIST it in
  the meta-test with a rationale comment at both sites.
- `core/workflow/graph/renderers/mermaid.py:775` (`re.sub(r"\$\{([^}]*)\}", r"\1", text)`,
  display-only marker stripping): replace with the `strip_template_markers` helper from
  4.1 (behavior identical — loose `[^}]*`, strips escaped/empty too).
- `core/workflow/graph/renderers/mermaid.py:821-828` `_strip_template` — a SECOND manual
  stripper in the same file (`value[2:-1].strip()` after startswith/endswith checks, used
  by `_loop_label`): migrate to `extract_simple_template_var` with a fallback to
  `strip_template_markers` (it is looser than the strict grammar — accepts any inner
  including coalesce; preserve that acceptance).
- `core/prompt_cache_analysis/stages/warnings.py:485` and `:528` — `stripped[2:-1]`
  immediately after an `is_simple_template` check: two-line migration to
  `extract_simple_template_var`. Do it.

**Accepted ad-hoc survivors** (named so the "one grammar home" seal is honest — these are
string-helper-territory reimplementations, meta-test-blind by nature, accepted as-is; do
NOT migrate them in this task): `core/cache_overlap.py:57-90 _canonicalize_path` (hand
segment-walker over canonical path tuples — and note its OWN `_PFLOW_VAR_RE` at :32/:131
stays alive on the promoted constant), `core/prompt_cache_analysis/sub_workflow_walker.py`
:105/:113-123/:440-452 (root/tail extraction + `_extract_template_inner`),
`core/prompt_cache_analysis/stages/suggestions.py:150/:526`, `core/prompt_refs.py:118-130`
(`_split_head`/`_extract_template_inner`), `core/trace_report.py:504-531`
(`_check_path_against_upstream`, display-only suggestion walker — no bracket handling,
known-degraded for indexed paths). If any of these is touched for OTHER reasons later,
migrate it then.

**Phase-1 drift file update (sanctioned, pre-declared)**: 1a's permissive-side assertions
import `_PERMISSIVE_PATTERN`, which this phase deletes. Re-target those assertions to
`parse()` (strict full-match ⇒ Expr with no Issue; permissive-discovery ⇒ Expr-acceptance
per the two-tier rule), keeping every Mutation clause. This is a sanctioned re-target — the
implication becomes partly tautological once both sides derive from one parser; that is the
consolidation working, and the grammar-uniqueness meta-test inherits the mutation target.

**Grammar-uniqueness meta-test** — new test in `tests/test_core/test_template_grammar_seam.py`,
mirroring `tests/test_core/test_litellm_runtime.py:837-920` exactly: module-level allowlist
`frozenset({"core/templates.py", "mcp/auth_utils.py"})` (each with a why-comment),
`_find_repo_root()` via pyproject.toml parents-walk, `sorted(src_root.rglob("*.py"))`, text
prefilter `if "$" not in source` (NOT `"${"` — the violation spelling `\$\{` does not
contain the contiguous substring `${`; the litellm precedent's prefilter works because
"litellm" appears verbatim in violations, which doesn't transfer here), then `ast.parse` +
walk for `re.compile`/`re.match`/`re.search`/`re.findall`/`re.finditer`/`re.sub`/`re.subn`/
`re.split` calls whose first arg contains `\$\{` or `\${` — checking plain string
constants, module-level string assignments, AND the constant fragments of JoinedStr
(f-/rf-strings): that is what lets the sanctioned derivation
`re.compile(rf"'{TEMPLATE_EXTRACT_PATTERN.pattern}'")` pass naturally (its constant
fragments are just quotes) while a restated `rf"\$\{{…"` is caught. Deliberately OUT of
the test's scope (note in its docstring): `core/ir_schema.py:87-187`'s five jsonschema
`^\$\{.+\}$` pattern strings — dict values, not `re.*` calls; documented-loose by design
(validator.py:259). Violations → `pytest.fail` with file:line list and a fix-hint pointing
at `core/templates.py`. No marker (in-process).

**Doc updates in passing**: `template_validation/CLAUDE.md` (delete the stale
`compile_validation.py imports validate_workflow_templates` row; update the 3-regex-role
table to point at core/templates), `runtime/CLAUDE.md` Template System section,
`core/CLAUDE.md` (new module entry), create `core/templates` section documenting the AST.

## Phase 4/5 addendum — facts from the consumer inventory

- The **public surface** `TemplateResolver` must keep forever (union of all external use):
  `has_templates, resolve_template, resolve_nested, resolve_value, variable_exists,
  extract_variables, split_coalesce_operands, is_literal_operand, is_coalesce_expression,
  is_simple_template, extract_simple_template_var, extract_root_node_id,
  extract_first_field_segment, resolve_coalesce` + patterns `TEMPLATE_PATTERN,
  TEMPLATE_EXTRACT_PATTERN, SIMPLE_TEMPLATE_PATTERN` (+ promoted `VAR_NAME_PATTERN`,
  `LITERAL_PATTERN`).
- `resolve_nested_index_templates` has ZERO external callers (verified) — make it private/
  delete in phase 5 once DynamicIndex resolution replaces it internally.
- Tests importing privates `_convert_to_string` (×12) and `_get_dict_value` (×1) live in
  `tests/test_runtime/test_template_resolver.py` — keep those privates (they're the
  declared direct-test surface) or update the tests in the same PR that moves them.
- `tests/test_core/test_prompt_cache.py:190-203` pins TEMPLATE_PATTERN agreement with the
  cache-prefix resolver — runs unchanged; do not break.

## Verification

**Per-phase gates** (every phase): `make test` and `make check` green; no existing test
modified except where a phase explicitly says so (phase 3 import-path updates; phase 5
`test_nested_templates.py` migration; phase 4/5 characterization deltas, each with an
explicit decision recorded in the PR description).

- **Phase 1**: new `tests/test_runtime/test_template_drift.py` passes against UNMODIFIED
  production code. Run `uv run pytest tests/test_runtime/test_template_drift.py -x -q`.
- **Phase 2**: `uv run pytest tests/test_runtime/ tests/test_cli/test_workflow_output_handling.py -q`
  — all green with zero test edits. Grep confirms `_traverse_path_part`/`_check_array_indices`
  gone.
- **Phase 3**: full suite green; layering meta-test green; subprocess lazy-import test
  (`tests/test_cli/test_lazy_imports.py`, e2e) still green —
  `uv run pytest -m e2e tests/test_cli/test_lazy_imports.py` (the moved module must not
  drag litellm into the CLI chain; it imports only stdlib + `core.json_utils`, so this is
  a confirmation, not a risk).
- **Phase 4**: after step (2) — resolver suites pass UNMODIFIED (the freeze gate). After
  each table-row migration — that site's suite (`test_template_validation/`,
  `test_core/test_cache_block_parser.py`, `test_core/test_graph_build.py` +
  `test_core/test_mermaid.py` for scope.py, etc.). Phase-1 drift file green throughout.
- **Phase 5**: grammar-uniqueness meta-test green; grep
  `_PERMISSIVE_PATTERN|split_template_path|_CACHE_TEMPLATE_RE|_BRACKET_INDEX_PATTERN`
  returns only historical references in docs/task files, and
  `grep -rn _PFLOW_VAR_RE src/pflow/core/workflow/` returns nothing — NOTE:
  `core/cache_overlap.py` has its OWN same-named `_PFLOW_VAR_RE` (:32, live use :131)
  which deliberately survives on the promoted constant; do not let the grep claim trip
  on it.

**Final acceptance** (the task's Requirements, mechanized):
1. `tests/test_runtime/test_template_drift.py` — soundness + grammar coherence + 6 named
   historical regressions, all green.
2. Grammar-uniqueness AST-scan green (exactly one `${…}` grammar home).
3. Layering AST-scan green (core never imports runtime template modules).
4. Full `make test` + `make check` + `make test-e2e` green.
5. Behavioral spot-check (manual, end-to-end): run an example workflow exercising
   templates+coalesce+batch (e.g. from `examples/`) before phase 1 and after phase 5;
   outputs byte-identical. `uv run pflow <example>.pflow.md` — traces land in
   `~/.pflow/debug/` for comparison.

## Implementation guardrails

- NEVER weaken a drift test to make a phase pass — fix the divergence (the
  `test_plan_drift.py` contract).
- When the parser's natural behavior differs from today's regex behavior, TODAY WINS;
  any deliberate delta (the two characterization deltas in phase 4/5) needs its own test
  + an explicit note, never a silent change.
- Raise `PflowError` subclasses only (never vanilla exceptions) — though this plan should
  add NO new raise sites: parse is total, resolve never raises, error policy stays with
  existing callers.
- Each phase is a separate commit series ending green; do not interleave phases.
- If a phase reveals a behavior question this plan doesn't answer, the phase-1 corpus is
  the arbiter; if it's not in the corpus, STOP and surface the question rather than guess
  (epistemic manifesto: ambiguity is a stop signal).

## Reference anchors (read before starting)

- `.taskmaster/tasks/task_170/task-170.md` — the what/why, frozen-behavior list, scope
- `context/adr/0006-template-language-no-shared-walk.md` — decided shape + rejected
  alternatives (do not re-open: no World port, no hand scanner, no test generator)
- `context/CONTEXT.md` — Template / Reference / Coalesce / Operand vocabulary
- `src/pflow/runtime/template_resolver.py` — read in full first (884 lines)
- `src/pflow/runtime/template_validation/CLAUDE.md` — pass map, 3-regex-role contract
  (note: its claim that compile_validation imports validate_workflow_templates is STALE)
- `tests/test_execution/test_plan_drift.py` — the drift-test idiom to mirror
- `tests/test_core/test_litellm_runtime.py:837-920` — the AST-scan idiom to mirror
