# Task 170 Implementation Plan — One Template Language (`core/templates`)

Written 2026-09-28 by the task planner; self-reviewed by a seven-lens plan battery (dispositions
in Appendix A) and folded. Base at planning: `7dc5ad5d`; **the branch now carries the merge of
`origin/main` `7d7ffd44` (#628 sourceless outputs, #624, #639) as `c07acb4d`** — every line cite
below is re-measured on that merged head unless marked `@7dc5ad5d`. Supersedes
`implementation-plan-2026-06-12-SUPERSEDED.md` in full.

Authorities, in order: the spec's decision ledger + ADR-0006/0015 (locked) → `task-170.md`
(what/why) → this plan (how) → `progress-log.md` (what happened). Where this plan and the spec
disagree, the spec wins and the disagreement is a planning bug to report.

**Baselines captured 2026-09-28 on the merged head `c07acb4d`:** `make test` → **9276 passed**;
`make check` → green; `make test-e2e` → 46 passed, 2 skipped; the **freeze harness** (re-run before
every gate) → **812 passed**:
```
uv run pytest tests/test_runtime/test_template_resolver.py tests/test_runtime/test_template_escape.py \
  tests/test_runtime/test_nested_templates.py tests/test_runtime/test_template_coalesce.py \
  tests/test_runtime/test_null_defaults.py tests/test_runtime/test_template_validation/ \
  tests/test_core/test_cache_block_parser.py tests/test_core/test_prompt_cache.py \
  tests/test_nodes/test_llm/test_prompt_cache_rendering.py tests/test_runtime/test_node_wrapper.py \
  tests/test_core/test_workflow_validator.py tests/test_core/test_workflow_data_flow.py \
  tests/test_core/test_workflow_validator_outputs.py tests/test_runtime/test_output_resolver.py \
  tests/test_runtime/test_output_validation.py -q
```
Directory baselines: `tests/test_runtime` 2176, `tests/test_core` 3321, `tests/test_execution` 581,
`tests/test_integration` 296 (all passed, pre-merge head; re-measure if useful).

**Cross-task scan** (`./scripts/tasks`, 2026-09-28): no in-progress/blocked tasks. Overlapping
shipped tasks: 159 (cache block; its byte-symmetry tests are the net for phase 4c), 162/166 (loop
config; carry checks), 168 (graph model; `scope.py` + `web/src/graph/scan.ts` mirror), 135
(ADR-0014: resolution stays engine-driven). Unbuilt overlapping: 112/120 (type-check pointers —
updated in 4d), 118 (blocked on this task), 100 (reduce mode would add a `batch.initial` template
surface — the surface enumerator in §0.3 is where it goes), 167 (editor tokens — its spec points at
`TEMPLATE_PATTERN`; re-pointed to `Template` spans in 4d). Lane-B siblings: **#628 is merged and in
this branch**; #643 (entry-point asymmetry; the corpus states its entry point); #503 (`ValueError` →
`PflowError` on `engine/template_resolution.py`; never interleave with phase 2/4a); #520 (**its
first half — malformed templates in `batch.items` — is closed by phase 4b's Issue pass; the
dict-key half stays for the lane, building on `parse()`**).

---

## 0. Design (resolved; the phases implement this)

### 0.1 The module — `src/pflow/core/templates.py` (single file; split only if it grows past ~1000 lines)

Public surface after phase 5 (nothing else is imported from it anywhere):

```python
# ── AST (frozen dataclasses with slots; tuples never lists) ──────────────────
class Text:         text: str                       # unescaped literal text ("$${" already "${")
class Field:        name: str
class Index:        value: int
class DynamicIndex: ref: Reference                  # inner ${…}: ONE level, a plain static Reference (no ?? / no nesting)
Segment = Field | Index | DynamicIndex
class Reference:    root: str; path: tuple[Segment, ...]; raw: str   # raw = operand source text
class Literal:      raw: str                        # JSON literal per the literal grammar; .value → json.loads(raw)
                                                    # computed FRESH on every access (a cached [] / {} shared across
                                                    # batch threads would be a mutation hazard)
Operand = Reference | Literal
class Expression:   operands: tuple[Operand, ...]; raw: str; span: tuple[int, int]
                    # len(operands) > 1 ⇔ coalesce; raw = inner text; span = [start of "${", end after "}")
                    # .references → every Reference INCLUDING DynamicIndex inner refs (depth-first) — the
                    #   DEPENDENCY view (data_flow roots, forward refs, unused inputs, graph edges)
                    # .operands  → value-position operands only — the VALUE view (typing, absence, resolution)
class Issue:        raw: str; span: tuple[int, int]; kind: Literal["malformed", "bad_literal"]
                    # an unescaped "${" that is not an Expression; span runs to the first "}" after it
                    # (inclusive) or to end-of-string; kind == "bad_literal" iff raw contains "??" and some operand
                    # passes is_literal_operand() but fails the literal grammar (today's _malformed_literal_operand_hint)
class Template:     source: str; segments: tuple[Text | Expression | Issue, ...]; escaped: bool
                    # .expressions, .issues, .references (union over expressions), .is_simple
                    # (exactly one segment and it is an Expression), .needs_resolution (expressions or escaped)

@functools.lru_cache(maxsize=4096)
def parse(source: str) -> Template          # pure, total (never raises), context-free, AUTHOR TEXT ONLY
def parse_path(path: str) -> Reference | None   # bare path grammar ("node.f[0].g", "a[${i}].x"); None if invalid

# ── Value walk ───────────────────────────────────────────────────────────────
class Resolution:
    value: Any
    unresolved: frozenset[str]   # Expression.raw of every expression left literal, over the whole value
    issues: frozenset[str]       # Issue.raw of every Issue routed through resolution (left verbatim)
    # ok ⇔ not unresolved and not issues. The two channels are DISTINCT so the deferred #621 ruling can
    # apply per-surface tolerance to `issues` without touching `unresolved`.
def resolve(value: Any, context: Mapping[str, Any], *, auto_parse: bool = False) -> Resolution
    # For a str: exactly today's resolve_template — NO top-level JSON-container auto-parse.
    # For dict/list: recursive. auto_parse=True adds today's resolve_nested leaf rule (a simple template's
    # resolved JSON-container STRING is parsed) at every string leaf INCLUDING a top-level string — i.e.
    # resolve_nested(v, c) == resolve(v, c, auto_parse=True).value and resolve_template(t, c) == resolve(t, c).value.
def lookup(ref: Reference, context: Mapping[str, Any]) -> tuple[bool, Any]   # ONE walk: (found, value)

# ── Rules (the judgment calls that drifted) ──────────────────────────────────
TRAVERSABLE_TYPES  = frozenset({"dict", "object", "any", "str", "string"})   # a Reference path may walk into
TRUSTED_TRAVERSABLE_TYPES = frozenset({"dict", "object", "any"})            # …without a JSON-at-runtime warning
CONTAINER_TYPES    = frozenset({"dict", "object", "list", "array"})          # JSON auto-parse targets
LIST_TYPES         = frozenset({"list", "array"})                            # index access targets
TYPE_COMPATIBILITY_MATRIX; def is_type_compatible(source_type, target_type) -> bool
                    # TEMPLATE-FLOW compatibility (today's type_checker.py:38-115 verbatim): "may a value of the
                    # declared source type flow through a template into a param of the target type" — it encodes
                    # auto-parse (str→dict) and stringification (int→str). NOT a value-vs-declared-type check
                    # (Tasks 112/120 need TypeSpec.accepts in core/types.py for literals; see 4d pointers).
def to_string(value: Any) -> str            # today's _convert_to_string rules, verbatim

# ── Permanent string-helper facade (the interface every long-tail caller uses today) ──
class TemplateResolver:
    TEMPLATE_PATTERN, SIMPLE_TEMPLATE_PATTERN     # REBUILT from the same grammar strings the tokenizer uses
                                                  # (dynamic-index alternative included) — static-discovery
                                                  # views; they cannot see escape CONSUMPTION (see grammar), so
                                                  # discovery over text that may contain escapes uses parse()
    TEMPLATE_EXTRACT_PATTERN                      # loose `(?<!\$)\$\{([^}]+)\}` discovery (unchanged)
    has_templates(value)            # needs_resolution over strings/dicts/lists (escape-only → True; #632) — an
                                    # UNCACHED regex scan, safe on resolved text
    has_references(value)           # NEW: any Expression anywhere (escape-only → False) — UNCACHED regex scan
    resolve_template(t, ctx), resolve_nested(v, ctx)          # = resolve(...).value (auto_parse per above)
    resolve_value(path, ctx), variable_exists(path, ctx)      # RAW-PATH MODE (below)
    resolve_coalesce(expr, ctx)                               # parses expr via the shared expression grammar
    extract_variables(s)            # {op.raw for op in VALUE-position operands that are References} —
                                    # `${a[${i}].x}` → {"a[${i}].x"} (today {"i"}); inner refs are NOT variables
    is_simple_template(s), extract_simple_template_var(s), is_coalesce_expression(s), is_literal_operand(op),
    split_coalesce_operands(s), extract_root_node_id(path),
    extract_first_field_segment(path)   # via parse_path (first Field after the root); lexical fallback
    _convert_to_string, _get_dict_value # kept: declared direct-test surface of test_template_resolver.py
```

Rejected: a separate span-yielding helper — `Expression.span`/`Issue.span` IS it (consumers:
`prompt_refs.py:61-82`, the cache chunker, the shell quoted-template check). Rejected:
`Literal.value` stored in the AST (mutation hazard through the cache). Rejected: a package. Rejected:
the June plan's `has_templates == bool(exprs)` (re-breaks #620) and counting Issues into
`has_templates` (an Issue-only param is static today and stays static — validation is its net; the
runtime `issues` channel exists for Issues that ride along a routed value).

**Two path readers, one walk (raw-path mode).** `-o result.@type`, `read-fields result.dc:title`,
MCP `read_fields result.my key`, `result.0` resolve today because `resolve_value`/`variable_exists`
split lexically (dots outside brackets; `[N]` indices, `[0][1]` chains accepted) with no identifier
grammar. That stays: the facade pair tokenizes lexically (`_split_raw_path`) and feeds the same
`_walk`; `parse_path` is the grammar reader for templates. Pinned by 1e/1f rows through BOTH readers.

**Grammar (regex-tokenized, ADR-0006).** One left-to-right candidate scan:
- `ESCAPE = \$\$\{(?:[^{}]|\{[^{}]*\})*\}` — a `$${` with a **brace-balanced** body (one nesting
  level) through its matching `}`; if no balanced close exists, only `\$\$\{` is consumed (today's
  behavior: `'Type $${ to open. Hi ${name}'` → `'Type ${ to open. Hi Al'`, executed). This is the
  ledger's "escape consumes through the closing `}`": `$${a[${i}]}` → `${a[${i}]}`, `$${FOO:-${bar}}`
  → `${FOO:-${bar}}`, `$${x} ${y}` → `${x}` + resolved `y`, `$$${x}` → `$${x}`, bare `$$` untouched.
  Executed 2026-09-28 on all five.
- `OPEN = (?<!\$)\$\{`. Every OPEN is an Expression or an Issue, never Text.
- At an OPEN, `_EXPR_AT.match(source, pos)` with the strict expression regex = today's
  `_COALESCE_EXPR_PATTERN` whose variable grammar gains one alternative:
  `SEGMENT = IDENT(?:\[(?:\d+|\$\{INNER\})\])?` with `INNER` = today's static var grammar (no `??`,
  no nesting). At most one index per segment (multi-index `${m[0][1]}` stays rejected on both sides).
  Match → Expression; no match → Issue (span to the first `}` after the OPEN, or EOS).
- Literal grammar: today's `_LITERAL_PATTERN` with the string branch tightened to JSON-valid escapes
  (`\\["\\/bfnrtu]`, `\uXXXX` = 4 hex, no raw control chars) so every literal match round-trips
  `try_parse_json` (`"\q"` / `"\u12"` / raw tab become `bad_literal` Issues — delta-2 class).
  Literal-first operand classification preserved. The class attribute `TemplateResolver._LITERAL_PATTERN`
  keeps its name through phase 4b so `template_validation/validator.py:50`'s by-symbol composition
  picks the tightened grammar up in the same phase (no validator/runtime window).
- `parse_path(path)` = fullmatch of the extended variable grammar → Reference.

**Resolution semantics** (today's, except the sanctioned deltas):
- str: simple → value, type preserved; literal-only → its JSON value; coalesce → first operand that
  resolves (a literal always resolves; a Reference resolves iff `lookup` found it; root absent OR field
  absent falls through — #441; a found `None` is returned, not skipped — `test_template_coalesce.py:299/:370`
  and the array variant `${x[0] ?? "f"}` with `x=[None]` → `None`, executed). Complex → single
  left-to-right pass: Text emitted unescaped; Expression → `to_string(value)` or its raw `${…}` (raw
  joins `unresolved`); Issue → verbatim (raw joins `issues`). Substituted values never re-scanned (#632).
- A DynamicIndex resolves its inner Reference through `lookup`; the inner must be found and be an `int`
  (`bool` excluded); otherwise the whole outer Reference is not found (ledger). A non-int inner keeps
  today's `logger.warning` (a `??` fall-through on a bad index would otherwise be invisible).
- `lookup` = today's traversal (`_get_dict_value` Mapping access with JSON-container auto-parse on
  `str`; `[N]` requires a list after auto-parse and `0 <= N < len`; `None` mid-path → not found; final
  `None` with found=True — `test_null_defaults.py:20-49`, `test_workflow_output_handling.py:1522-1538`).

**`parse()` runs on author text only.** `has_templates`/`has_references` are uncached regex scans
and are the only helpers that may run on resolved runtime values. After phase 4a **no site scans
resolved text to decide unresolved-ness**: the four cost-analysis sites that resolve author text then
`TEMPLATE_PATTERN.search` the output (`row_builder.py:916-928`, `token_estimation.py:407-414/:440-453`,
`sub_workflow_walker.py:533-537`) switch to `resolve(...)` and its channels in 4a (they are #630-pattern
sites; a `$${…}` escape in a prompt is reported "partial" today). Module docstring states the rule.

### 0.2 The unresolved set through the engine (phase 2; #630)

`engine/template_resolution.py`:
- `resolve_template_parameter(key, template, context)` → `(value, is_simple, resolution)`.
  `resolve_templates` replaces `contains_unresolved_template(resolved_value, template)` with
  `if not resolution.ok:` (unresolved OR issues — Issues that ride along a routed value keep today's
  loud outcome; executed: `inputs: {x: ${src.result.items.0}, y: ${src.result.name}}` raises today).
- **`inputs` is resolved per key** (it is already special-cased for ordering):
  `for k, v in template["inputs"].items(): r_k = resolve(v, context, auto_parse=True)`; an optional
  key whose expressions are ALL in `r_k.unresolved`, with no issues, and whose value-position operand
  roots (outer roots only — a present `__index__` inside `[…]` must not block injection; ledger:
  "Optional inputs get `None`") are all absent → `None` and `r_k` is dropped; the remaining keys'
  channels are unioned. A required sibling sharing the same expression text keeps its own channel
  (executed: `{opt: ${b.stdout}, req: "prefix ${b.stdout}"}` raises today and must keep raising).
  `inject_none_for_optional_inputs` becomes `inject_none_for_optional_inputs(resolved_inputs, template_inputs,
  context, optional_input_keys, resolutions_by_key) -> tuple[dict, frozenset[str] /*injected keys*/]`;
  its 7 direct test calls (`test_node_wrapper_template_validation.py:434-501`) are a **sanctioned edit** (§5).
- `resolve_templates` KEEPS its 3-tuple return (26 test call sites). The permissive error entry
  gains `"unresolved_expressions": tuple(sorted(...))` and `"issues": tuple(sorted(...))` — the entry
  is an untyped bag read only by the runner (`diagnostic` key); `__template_errors__` never reaches the
  trace (`workflow_trace.py:1318` drops `__` keys); the set never rides `last_resolutions` (traced).
  **No new trace field.**
- **One set feeds check and diagnostic alike (spec):** `build_template_error_diagnostic(key, template,
  context, resolution, …)` and `classify_unresolved_references(expressions: Iterable[str], context)`
  classify exactly the expressions in `resolution.unresolved` (phase 2: `split_coalesce_operands` per
  expression text; 4a: parsed operands). This also fixes the interim generic message for a rewritten
  `${a[0].x}` (its root `a` succeeded → `path_error` named). `output_resolver` passes `r.unresolved`.
  Direct test callers of `classify_unresolved_references` (grep `tests/` in phase 2) → sanctioned
  mechanical edit if any.
- Loop carry (`engine.py:242-258`): `unresolved = key not in resolved_inputs or _plan_left_unresolved(plan,
  template)`; the helper selects the `inputs` entry (`"unresolved": ["inputs"]`) of `plan.template_errors`
  (permissive) and tests `extract_simple_template_var(template) in entry["unresolved_expressions"] or
  entry["issues"]`. Strict: `plan_node` raised; the `diag` branch is unchanged.
  `contains_unresolved_template` + `_check_string_unresolved` deleted (their two consumers migrate here;
  R8); `TestContainsUnresolvedTemplate` (`test_node_wrapper.py:196-222`) deleted — **but its four cases
  land first as phase-1 corpus rows** (fully resolved; simple unresolved; partially resolved complex;
  resolved data containing `${OLD_VAR}` → not unresolved). `TestDepthLimit` stays green.
- Other consumers switched in phase 2 (all `r = resolve(...)`; failure ⇔ `not r.ok`):
  `engine._resolve_template_string` (:393-402 — batch warm-up `model`/`system`; a `$${x}` in `system`
  stops dropping the user system prompt); `output_resolver.resolve_output_source` (:39-44) and
  `populate_declared_outputs` (:155-172) (executed: plain `source: s.stdout.0` passes validation and
  fails loudly today — must keep failing); `batch_executor.resolve_batch_items` (:108-131, string form;
  the inline-list form never checked and keeps not checking — §6 + handback); `prompt_cache._resolve_chunk_value`
  (:136-176; the ABSENT pre-check on the var's root stays; echo → `not r.ok` → `_CHUNK_ABSENT`).
  `_resolve_static_prefix_for_cache` waits for the AST (4c).

Rejected: re-resolving the carry at the check site; a 4-tuple return; the set on `last_resolutions`;
subtracting injected expressions from a dict-wide set (hides a sibling sharing the text).

### 0.3 Validator-side: one surface enumerator, one Issue pass, one operand classifier (phase 4b)

- **Surface enumerator** — NEW `core/workflow/template_surfaces.py` (~40 lines):
  `iter_template_surfaces(workflow_ir) -> Iterator[TemplateSurface(node_id: str | None, kind, path: str, value: Any)]`
  with `kind ∈ {"param", "batch_items", "loop", "carry", "output_source", "cache_var", "cache_prose"}`;
  `value` is the raw IR value (consumers recurse dict/list strings). Consumers: the Issue pass, the
  operand iterator, `data_flow._validate_node_params` (core → core import), `path_validation._find_template_source_file`.
  Deletion test: four walks today, one enumeration after; Task 100's `batch.initial` lands as one line.
  `_node_template_value_sources` (`template_validation/validator.py:764-780`) is deleted in favour of it.
- **The ONE Issue→ERROR pass** — `template_validation/validator.py::_validate_malformed_templates`
  rewritten over the enumerator: for every string reached, `for issue in parse(value).issues` → ERROR.
  One diagnostic per value (message keeps today's shape — "found N '${' but only M valid template(s)",
  N = expressions+issues, M = expressions — so `test_malformed.py`'s five count-phrase assertions and
  `len(errors) == 1` stay green with zero edits; a `bad_literal` first Issue selects the targeted
  literal message, absorbing `_malformed_literal_operand_hint`). Surfaces: params, `batch.items`,
  loop `while`/`until`/`max_iterations`, **carry values**, **output `source:`** (raw text, NOT
  normalized — so `source: prefix ${n.stdout}` stays OK: the recorded prose-wrap drift is not fixed
  here), **cache `var`s**, **cache `prose_before`** (dict IR may carry `${…}` there: an Expression or
  Issue in prose is an ERROR "cache prose may not contain template references"; markdown-built IR
  never has one). `core/workflow/validator.py::_validate_template_in_source` and
  `data_flow._validate_cache_block` stop doing their own Issue/malformed checks and only root-check
  References. The Issue policy (which Issues are ERRORs on which surface — the #621 seam) now has
  exactly one home; `MarkdownParseError` is never raised for a template Issue (R2 revised).
- **Operand classifier** (validator policy; ADR-0006 amendment):
  ```python
  class OperandPolicy(Enum): FIELD_CHECK = "field-check"; ROOT_ONLY = "root-only"
  # Literal operands are not References and never reach the classifier (that is the "skip" case).
  def classify_operand(*, in_coalesce: bool) -> OperandPolicy
  def _iter_template_operands(workflow_ir) -> Iterator[tuple[str /*node_id*/, str /*path*/, Reference, OperandPolicy]]
  ```
  Walks the enumerator (`param`, `batch_items`, `loop` kinds — carry stays with the carry pass, outputs
  with the output pass, cache with the cache pass, to avoid double diagnostics) with `parse()`, yielding
  every Reference **including DynamicIndex inner refs** (delta 6) tagged with the enclosing operand's
  policy. Consumers: Pass 5 (`FIELD_CHECK` only), unused-inputs (all), **Pass 8** (`FIELD_CHECK` only,
  **filtered by `node_id`** and root == alias — the Pass-5/Pass-8 `??` disagreement closes; `${item.maybe
  ?? "none"}` stops erroring). `ROOT_ONLY` roots are checked by `data_flow` — whose walk now covers
  `batch.items` too (surface parity by construction: both consume the enumerator). **Type passes 6/7/9
  consume value-position operands only** (`extract_variables` = operands): an index key is not a
  candidate value — typing `idx: int` against a `dict` param is the false error delta 6 removes
  (executed: `http params: ${p.result[${__index__}]}` fails validate-only today with "${__index__} has
  type 'int' but parameter expects 'dict'"; the runtime resolves a dict). Passes 6/7/9 keep their own
  param-scoped walks (they select params by key/type, not operands by existence policy) — a follow-up
  may fold them onto the iterator; named in the handback for the simplicity lens.
- **Nested-index rule shared by Pass 5 and `infer_template_type`** (a pre-existing over-rejection found
  by execution: `validate_template_path("p.out.items[0].x")` → `(False, None)` because
  `validate_nested_path` looks up the literal key `"items[0]"`, while `infer_template_type` strips `[N]`
  and the runtime resolves): a list-typed field's `structure` IS its element structure; batch
  `results` uses `items`. One helper `_descend_index(field_info) -> structure | None` used by both.
  Corpus row (xfail → 4b) + negative partner (`${p.out.items[0].nope}` must still error).

### 0.4 Type-rule homes (phase 4d)

- **`core/templates`** owns the traversability/container/list sets (§0.1) AND the template-flow
  compatibility matrix + `is_type_compatible`. Why not `core/types.py`: the matrix is template-flow
  semantics (executed: `is_type_compatible("int","str")` and `("string","object")` are True because
  templates stringify and auto-parse) — Tasks 112/120's literal-value checks would be WRONG on it
  (task-112.md:207 expects `{"model": 6}` to error; task-120.md:99 expects `"not json"` → `object` to
  error). Their pointers get corrected text in 4d: vocabulary from `core/types.py` (`TypeSpec.accepts`
  for values), never this matrix. `type_checker.py` keeps `infer_template_type` (validator-side
  structure inference over `parse_path` segments + the shared sets). The `type_checker`↔`path_validation`
  traversability disagreement resolves toward runtime truth (`str` traversable); every consumer of
  `_infer_nested_type` treats `None` and `"any"` alike (verified by reading all four), so no diagnostic
  changes — pinned by a corpus row.
- `to_string` → `core/templates`; `prompt_cache.deterministic_serialize` stays (spec);
  `coerce_param_for_node`'s `json.dumps` is a third encoding — §6.

### 0.5 The three meta-tests

1. **Parity corpus** — `tests/test_integration/test_template_parity.py` (cross-layer) +
   `tests/test_core/test_template_grammar.py` (pure grammar rows). Rows are frozen dataclasses in
   Python (JSON export is a follow-up if the TS mirror ever consumes it — the `react_flow_contracts`
   generator is the seam). **Row shape and discipline** (folded from the battery):
   - `Row(id, surface, template, payload, declared_inputs, params, mode, validator: Expect, runtime: Expect,
     mutation: str)` where `Expect(today, after=None, flips_in=None)` and each side is one of
     `Ok`, `Error(substring)`, `Resolves(value)`, `Unresolved(refs)`, `StaticLiteral`, `Raises(type, substring)`,
     `Absent`. **Two pytest items per side per row**: `today` asserted as a plain passing test in phase 1;
     when `after` is set, a second item asserts `after` under `pytest.mark.xfail(strict=True,
     raises=AssertionError, reason=f"{flips_in}: …")`. The flipping phase deletes the `today` item and
     the marker. A harness bug can therefore never masquerade as an expected failure, and an early
     XPASS names the phase whose diff caused it: at every gate, XPASS rows are re-derived — a flip the
     phase's diff explains is logged and the marker removed; one nobody can explain is a STOP.
   - Every `Error` carries a message substring or context template; every `Unresolved` names the
     reference(s); every `Resolves` is a literal. Every direct-driver test first asserts the producer
     namespace equals the payload (no empty-store free passes). Every "now clean" row has a same-surface
     negative partner that must still error (table in Phase 1).
   - Whole-table invariants assert their row counts (never vacuous).
   - Doctrine line in both module docstrings: *"If a row fails, fix the divergence, never the row"*
     (from phase 2 on).
2. **Grammar uniqueness** — `tests/test_core/test_template_grammar_seam.py`, mirroring
   `test_litellm_runtime.py:912-1004` mechanics. Prefilter: `"$" in source or "TemplateResolver" in source
   or "templates" in source` (Rule B violations contain no `$`). Two rules over every `.py` under `src/pflow/`:
   - **Rule A (literal grammar):** no `ast.Constant` string (f-/rf-string fragments, module constants and
     `BinOp` operands included) whose value contains `\$\{` or `\${` outside the allowlist.
     **Allowlist** (repo-relative paths, reason verbatim in the test):
     - `src/pflow/core/templates.py` — the seam.
     - `src/pflow/mcp/auth_utils.py` — `${VAR:-default}` MCP-config env expansion is a different language.
     - `src/pflow/core/yaml_utils.py` — a lexical YAML mask (one nested `{}` level, deliberately no `$$`
       handling; over-capture is harmless because mask/restore is verbatim); swapping in the canonical
       pattern breaks flow-style YAML for `$${y}` and `${a[${i}].x}`; own guard in
       `test_yaml_shielding_hygiene.py` + pin rows added in phase 5.
     - `src/pflow/core/ir_schema.py` — jsonschema `pattern` strings (`^\$\{.+\}$` ×5) are schema shape
       checks compiled by jsonschema, not pflow's grammar.
   - **Rule B (by-symbol):** no `re.<fn>(...)` call outside the allowlist whose pattern argument AST
     references a name imported from `pflow.core.templates` (any alias form) or an attribute of
     `TemplateResolver`. Calling `.search`/`.finditer`/`.sub` ON a public compiled pattern is not a `re.*`
     call and is allowed.
   - **Non-vacuity:** the scan function runs over planted temp files for every spelling (raw, rf-fragment,
     `BinOp`, module constant, `re.compile(f"{TemplateResolver.TEMPLATE_PATTERN.pattern}")`,
     `from pflow.core import templates as t; re.compile(t.X)`) and must flag each; and each allowlisted file
     must yield ≥ 1 Rule-A hit (proves the detector fires and stale allowlist entries are noticed).
   - Scope: Python under `src/pflow/` only (the TS mirrors are out of scope by construction).
3. **Layering pin** — rule 4 in `tests/test_import_hygiene.py`: no module under `src/pflow/core/`
   imports `pflow.runtime.template_resolver` (any scope; prefilter `"template_resolver"`; match
   `alias.name` too). After phase 5 deletes the shim this rule is vacuous by construction; the durable
   guarantee is the **subprocess pin** beside `test_litellm_runtime.py:882`: `import pflow.core.templates`
   in a clean interpreter → no `litellm*` and no `pflow.runtime*` in `sys.modules` (executed: `json_utils`
   loads only `pflow.core.*`; today the resolver drags 29 runtime modules).

### 0.6 Planner rulings (importance ≤ 2, visible, reversible; overrule at launch if wanted)

| # | Ruling | Why | Reversal cost |
|---|---|---|---|
| R1 | A loop `while:`/`until:`, a `carry:` value, and the loop-shape check accept a dynamic-index simple template (today: validator shape error; runtime stop / carry self-ref error) — all in **4a** (the facade flips them together with the runtime walk that can resolve them) | Consequence of "one Reference"; nobody could have written one | One `if` each |
| R2 | A template Issue in `## Cache` prose or a chunk var is reported by the validator's Issue pass (ERROR), never raised by the markdown parser; the chunker treats Issues as prose (so `${}` stays prose; an unclosed `${a` no longer swallows text to the next `}`) | Issue policy has one home (#621 seam); a parse-time exception could not be relaxed per surface | Two lines in the chunker |
| R3 | An output `source:` with no **Expression** (escape-only `$${a.x}`, or prose-only) is an ERROR "output source has no template expression"; literal-only `${"v1"}` / `${0}` stay valid (they resolve) | Keeps today's error outcome with a truthful message; no over-rejection | Message text |
| R4 | The runtime-only "dollar prefix" output source form `$node.x` is **removed** (`_normalize_source` drops its `startswith("$")` branch) so validator and runtime agree by rejecting it | The validator always rejected it, so no saved workflow uses it; widening the validator instead would open an authoring door (arch-fit) | Restore the branch |
| R5 | A `??` chain as a `## Cache` chunk var is **rejected explicitly** at parse ("coalesce is not supported in a ## Cache chunk"); a batch-alias root anywhere in the var (inner dynamic-index refs included) is rejected by the existing batch-scoped rule | Executed: the runtime drops such chunks today (`_resolve_chunk_value` gates on the whole var's root → ABSENT), so accepting them would be a silent divergence; today's outcome is an error either way | Lift the rejection once the runtime resolves per operand |
| R6 | The `has_templates` deferral sites (`core/workflow/validator.py:1004/:1043/:1151/:1258`, `template_validation/validator.py:1226/:1142`, `sub_workflow_resolver.py:93`) switch to `has_references`; an escape-only value is statically checked on its **unescaped** text (`resolve(value, {}).value` — exact when no references exist) | Spec Parity; the node receives the unescaped value, so that is what to check; `has_references` is a regex scan, safe on the resolved values `sub_workflow_resolver` also sees | Swap the predicate back |
| R7 | Matrix + `is_type_compatible` and the traversability sets → `core/templates` | §0.4 | Move a block |
| R8 | Phase 2 deletes `contains_unresolved_template` | No consumer remains; a dead heuristic invites a re-fork | Restore from git |
| R9 | Pass 5 and `infer_template_type` share the nested-index rule (§0.3) — the `[N]`-in-nested-structure over-rejection flips in 4b | One-way soundness ("fix the divergence") | Keep the literal-key lookup |
| R10 | A strict-mode template failure during the parallel sub-workflow **pre-warm** (`batch_executor._pre_warm_compile_cache`, executed: item[0]'s miss fails the whole run even under `error_handling: continue`) is caught and the pre-warm skipped, so the per-item loop applies the error mode | Pre-existing; delta 3 widens it (item[0] dynamic-index misses now raise there) — "a gap your change widens is yours to close"; cleanly revertible | One `except` |
| R11 | Dry-run per-item child inputs (`execution/plan.py:1547`) report `not r.ok` through the existing per-item WARNING mechanism (`:1549-1560`) | Delta 3's new per-item failures were invisible in `--dry-run` | Delete the branch |
| R12 | The inline-list form of `batch.items` keeps NOT checking unresolved elements (literal item, no error) | Outside the sanctioned deltas; recorded in §6 + handback follow-up | One line on the set |

No user checkpoints are embedded. No trace-format change anywhere.

**Planner-visible consequences outside deltas 1–6** (all validator-only corrections the spec's
Parity section forces — over-rejections the runtime resolves, under-checks the runtime does not
catch — recorded in the spec's Sanctioned-deltas paragraph added by the planner): #262 flips as a
consequence of Pass 5 consuming `parse_path` segments (no point fix); R9; coalesce roots in
`batch.items` root-checked; Issues on every surface; delta-4's validator half (an input used only
inside an escape becomes "never used" — the escape IS literal); R1/R3/R4/R5/R6 as above.

---

## 1. Verified truth tables (2026-09-28, executed — the corpus encodes these as `today` values)

**Dynamic index** (`resolve_template`; `cut` = `contains_unresolved_template`):

| template | context | today | strict today | after (delta 3) | flips in |
|---|---|---|---|---|---|
| `${a[${i}].x}` | i=0, a=[{x:v}] | `'v'` | ok | `'v'` | — |
| `${a[${i}].x}` | i=0, a=[{y:v}] | `'${a[0].x}'` | **silent** | unresolved → strict error | **2** (rewritten `a[0].x` is in the set) |
| `${a[${i}].x}` | i="abc" | `'${a[abc].x}'` + warning | silent | unresolved (warning kept) | 4a |
| `${a[${i}].x}` | i=5 (OOB) | `'${a[5].x}'` | silent | unresolved | 2 |
| `${a[${i}].x}` | i absent | unchanged | error | unchanged / error | — |
| `${a[${i}].x}` | i=True / None / "1\n" / -1 | rewritten or unchanged | silent | unresolved | 4a |
| `${a[${i}].x ?? b}` | i="s", b="fb" | `'${a[s].x ?? b}'` | silent | `'fb'` | 4a |
| `${a[${i}].x ?? b}` | i=0, a=[{y:v}], b="fb" | `'fb'` | ok | `'fb'` (pin) | — |
| `${r[${i}]}` | i=0, r=[{k:1}] | `{'k': 1}` | ok | dict | — |
| `${r[${i}]}` | r=['{"a":1}'] via a typed `dict` sink param | `'{"a":1}'` str (engine `is_simple` False → no auto-parse) | ok | `{'a':1}` | 4a |
| `$${a[${i}]}` | i=0 | `'${a[0]}'` | — | `'${a[${i}]}'` | 4a (delta 4) |
| `$${FOO:-${bar}}` | bar=B | `'${FOO:-B}'` | — | `'${FOO:-${bar}}'` | 4a (delta 4) |
| `Type $${ to open. Hi ${name}` | name=Al | `'Type ${ to open. Hi Al'` | ok | same (unclosed escape consumes `$${` only) | — (pin) |
| `${x} $${x}` | x=hi | `'hi ${x}'` | **error** (#630) | ok | 2 (delta 1) |
| `${arr[${idx ?? 0}]}` | arr=[1,2] | `'${arr[0]}'` | silent | Issue: literal (runtime), validator ERROR | 4b (validator); runtime `issues` from 4a |

**Grammar edge today** (`has_templates` / `is_simple` / `extract_variables`): `${c.result.0}` →
False/False/∅ (static, literal reaches the node); `${data.result.}` same; `${m[0][1]}` same;
`${a ?? "${b}"}` → True/**True**/{a}, resolves to `'${b}'`, validator says malformed literal;
`[${none_val}]` with none_val=None → `'[]'` (`test_template_resolver.py:179` — must survive the
dynamic-index grammar); `extract_variables('${a[${i}].x}') == {'i'}`; `TEMPLATE_PATTERN.finditer`
on it yields only `${i}`; `SIMPLE_TEMPLATE_PATTERN` no match.

**Walk pair today** (`variable_exists` / `resolve_value`): `x[0]` on `{x:[None]}` → True/None; `x.k`
on `{x:{k:None}}` → True/None; `x.k.j` on `{x:{k:'{"j":1}'}}` → True/1; `x.k.j` on `{x:{k:None}}` →
False/None; `x.k[0]` on `{x:{k:"s"}}` → False/None; `x.k[0].z` on `{x:{k:[None]}}` → False/None;
`x.k[0]` on `{x:{k:"[5]"}}` → True/5; `x[0]` on `{x:"[5]"}` → True/5; raw `n.items[${idx}]` → False (the
raw reader cannot walk a dynamic index — why loop_control must migrate with the facade in 4a).

**Loud-today Issue shapes** (the `issues` channel keeps these loud after phase 2): dict param
`inputs: {x: ${src.result.items.0}, y: ${src.result.name}}` → strict raises; output `source:
${src.result.items.0}` and plain `s.stdout.0` → `OutputResolutionError`; cache var `plan.result.0` →
`_CHUNK_ABSENT`; carry `${tick.result.0}` → `LoopCarryError` (inferred from the same mechanism — row
verifies).

**Converse-silent class today** (validator OK → runtime static literal, exit 0): `${c.result.0}`,
`${data.result.}`, `${data..result.x}` (`test_validator.py:298-311` passes for the wrong reason),
`${src.stdout.0}`, `${arr[${idx ?? 0}]}`, `${lsit[${__index__}].x ?? "default"}`, `batch.items:
["${data.result[0]"]`, `## Cache` `${plan.stdot}` (chunk silently ABSENT).

**Output `source:` today** (validator / runtime on `{n:{stdout:'OK'}}`): `${n.stdout}` ok/OK;
`$n.stdout` **error**/OK (R4: becomes error/error); `n.stdout` ok/OK; `n.stdout ?? n.x` ok/OK;
`prefix ${n.stdout}` ok/`'${prefix OK}'` (recorded drift, not fixed); `${"v1"}` ok/`"v1"` (stays);
`$${a.x}` error("malformed")/`'${V}'`-ish (R3: error with the new message).

**Validator over-rejections today** (one-way soundness; flip in 4b): `${items[0]}` on a declared list
input (#262); `${p.out.items[0].x}` on a declared nested `list[dict]` field (literal-key lookup);
`${p.out_list[0]}` on a `list`-typed registry output (`_validate_array_access` accepts only `"array"`);
`${item.maybe ?? "none"}` on a batch item (Pass 8).

**Cache chunk vars today:** `topic ?? "x"` → validator error (dotless root) AND runtime ABSENT;
`a.x ?? b.y` → validator OK (root `a`) but runtime ABSENT even when `b.y` resolves (silent) → R5.

---

## 2. Phases

Common per-phase gate: `make check` + `make test` green; the freeze harness green **with zero test
edits except the sanctioned ones listed for that phase (§5)**; the corpus green with every remaining
xfail strict (`raises=AssertionError`) and every XPASS re-derived per §0.5.1. Every phase ends with a
progress-log entry and a commit on the feature branch (deliberate staging). Effort follows
ORCHESTRATION → Model routing; all phases are Opus.

### Phase 1 — Parity corpus + characterization (tests only; no production change)

**Goal.** Land the fence: today's behavior as `today` rows, the historical bugs as named fixtures (only
the halves not already pinned elsewhere), every known divergence as an `after` item under strict
xfail citing its issue/delta and predicted phase, `WorkflowRunner` characterization of every
dynamic-index consumer, and an executed mutation ledger — all green on the merged head.

**Files.** NEW `tests/test_core/test_template_grammar.py`, NEW `tests/test_integration/test_template_parity.py`,
NEW `tests/fixtures/template_corpus/nodes/producer.py` (two node classes: producer + typed sink),
`tests/CLAUDE.md` (one row). No `src/` edits.

**Harness (decided; the battery's defects folded).**
- **Registry.** `_SCAN = scan_for_nodes([<src>/pflow/nodes, tests/fixtures/template_corpus/nodes])`
  computed once at module level; `Registry().update_from_scanner(_SCAN)` per test (the autouse
  `isolate_pflow_config` gives each test its own registry path; `update_from_scanner` is a full
  replace + save; `tests/shared/registry_utils.ensure_test_registry` is the precedent).
- **Producer** `TemplateCorpusProducer` (`type: template-corpus-producer`). Params: `payload_file: str`
  (a JSON file in `tmp_path` — NEVER a `payload: dict` param: upstream data containing `${…}` text must
  not pass through the producer's own template resolution). Writes, with the enhanced nested-structure
  docstring form (`llm.py:1010-1016`): `out: dict` {`text: str`, `num: int`, `flag: bool`, `nested: dict`
  {`k: str`}, `items: list[dict]` {`x: str`} — the nested-index over-rejection row, `json_str: str`,
  `maybe: any`}; `out_str: str`; `out_list: list` (the list-typed over-rejection row); `out_arr: array`
  (**index rows that must be reachable TODAY go through this, batch `results`, or a declared list
  input**); `out_any: any`. `post` writes each declared key present in the payload. Executed 2026-09-28
  by the test-fidelity lens: the extractor builds `structure` for the nested dict fields as expected.
- **Sink** `TemplateCorpusSink` (`type: template-corpus-sink`): typed top-level params `sink: dict`,
  `sink_list: list`, `sink_str: str`, `sink_any: any` — the only way `resolve_template_parameter` takes
  the **str path** so the engine's simple-template gate (auto-parse at `template_resolution.py:351-360`,
  coercion `:362-365`, `validate_resolved_type` `:367-375`) is exercised. Writes `received: any`.
- **Code consumer** for type-preserving rows: `inputs: {v: <template>}`, body `v: Any` / `result: Any =
  v` (annotations are mandatory — `test_plan_drift.py:52-60` precedent); specific annotations only on
  the delta-6 type rows.
- **Validator side** = `WorkflowRunner().validate(workflow, params, source_file_path=…)` called directly
  (it accepts markdown text AND IR dicts, `runner.py:600-610`) — never a hand-copied call (that is how
  #643-class drift starts). The module docstring names the entry point and #643. Assert
  `row.params ⊆ declared_inputs` so `run()`'s real-params validation cannot silently disagree.
- **Runtime side per surface** (a runner run cannot reach a validator-rejected template, so each surface
  has a direct driver; validator-OK rows ALSO run end to end via `WorkflowRunner().run(ir, params,
  config=RunnerConfig())` asserting `result.shared_after` / `result.status` / `result.diagnostics`):
  `param` → `compile_workflow` + `resolve_templates(config.template_config, shared, node_id)` with
  `shared` seeded from the producer's real run (assert the namespace equals the payload); strict
  `ValueError` classified by the presence of `_pflow_template_diagnostic` (unresolved) vs its absence
  (type error); `static_params` membership → `StaticLiteral`. `batch_items_*` → `resolve_batch_items`;
  `loop_while`/`loop_until` → `evaluate_loop_condition`; `loop_max` → `resolve_loop_cap`; `loop_carry` →
  full runner; `output_source` → `populate_declared_outputs`; `cache_var`/`cache_prose` → **markdown
  text** through `WorkflowRunner().validate` and `_resolve_chunk_value` / `_render_cache_for_hash` vs
  `build_cache_system_blocks` (dict IR skips the chunker where delta 5/R2 live); `sub_inputs`/`sub_workflow`
  → `resolve_templates` on the `workflow` node + full runner with a child in `tmp_path`. Mode via the IR
  key `template_resolution_mode`.

**Row groups** (the FULL table is the deliverable; the implementer extends it where a measured
behavior is missing, never trims it):

1a. *Grammar table* (`test_template_grammar.py`, ~75 rows): per row today's `TEMPLATE_PATTERN` matches,
`_PERMISSIVE_PATTERN` matches (re-targeted to `parse()` in 4a — only the column FUNCTION changes; no
expected cell changes except rows tagged `flips_in="4a"`), `has_templates`, `is_simple_template`,
`extract_variables`, `resolve_template` on a small context. Rows: every §1 grammar-edge shape; hyphens;
`[${a}]` outside braces; all literal edges (`007`, `[1,2]`, `"a??b"` no; `"\q"`/`"\u12"`/raw tab →
after: `bad_literal`, 4a); `$${var}`, `$${}`, `$${unclosed`, `$$${x}`, `$$`, `Type $${ to open. Hi ${name}`,
`$${a[${i}]}`, `$${FOO:-${bar}}` (delta 4, 4a); bash `${VAR:-x}`, `${#x}`; `${a[${i}]}`, `${a[${i}].x}`,
`${a[${i}].x ?? b}`, `${a[${i ?? 0}]}` (Issue), `${a[${i.j}]}`, `${a[${b[${c}]}]}` (Issue), `${a ?? "${b}"}`
(validator flips 4b). Invariants (with counts): every literal-grammar full-match round-trips
`try_parse_json` (xfail rows excluded until 4a); **after 4a** the Expression/Issue spans cover exactly
the unescaped `(?<!\$)\$\{` occurrences that survive escape consumption, and the segments reassemble
the source losslessly (replaces the tautological "strict ⇒ discoverable").

1b. *Surface parity* (`TestSurfaceParity`, ~70 rows): per surface × {bare ref, nested field, index via
`out_arr`/`results`/list input, str-JSON auto-parse, union, `any`, batch shapes (`results[0].x`, item
alias, dotted item — d5a1af8c class), `??` literal fallback, `??` root-absent, `??` field-absent
(#441), `??` all-absent, escape-only, escape+ref same param (delta 1 → 2), upstream value containing
`${b}` text (delta 1 → 2), the four `TestContainsUnresolvedTemplate` cases as runner rows (→ green
before phase 2 deletes the class), every converse-silent shape (delta 2 → 4b), every loud-today Issue
shape (pin: stays loud in 2), `${a ?? "${b}"}` (validator → 4b), `${arr[0]}` on a declared list input
(#262 → 4b) + partner `${arrr[0]}`, `${p.out.items[0].x}` / `${p.out_list[0]}` over-rejections (R9 → 4b)
+ partners `${p.out.items[0].nope}` / `${p.out_list[0].nope}`-class, `${item.maybe ?? "none"}` (→ 4b) +
partner `${item.missing}`, `$n.stdout` source (R4: error/OK → error/error, 4b) + `$typo.stdout`,
escape-only source (R3 message, 4b), `${"v1"}` source (stays), `prefix ${n.stdout}` source (stays OK;
runtime literal — pin), `items: ${typo.x ?? a.stdout}` in `batch.items` (→ 4b), inline batch list with an
unresolved element (R12, pinned as-is), prewarm `system` `$${x}` (delta 1 → 2), cache var typo
(pinned ABSENT; §6), cache var `topic ?? "x"` and `a.x ?? b.y` (R5 → 4c), cache prose `$${topic}` with
declared `topic` (delta 5 → 4c), cache prose `${}` and unclosed `${a` (R2 → 4c), `workflow: ${child}`
(no template pass for the child — named), `workflow: $${x}` (R6 → 4b), delta-4 validator half
(`$${FOO:-${bar}}` with `bar` a declared input used nowhere else: today OK; after 4b "never used"
ERROR) + partner (`bar` used unescaped elsewhere stays OK), parallel sub-workflow pre-warm under
`error_handling: continue` with a bad item[0] (R10 → 4a), the deferral sites' escape-only values (R6 →
4b), dynamic-index rows from §1 through `resolve_templates`/the sink (per the table's `flips in`).

1c. *Historical fixtures* — reference the existing named tests instead of duplicating (#441
`test_branch_convergence.py:189/219/240`; #460 `test_node_wrapper_json_parsing.py:179` +
`test_code_annotation_validation.py:162/175`; d5a1af8c `test_workflow_data_flow.py:678-735`;
4516cd72 validator half `test_malformed.py:331-354`; #620 `test_template_escape.py`); ADD only the
missing cross-layer halves: `test_4516cd72_nested_index_coalesce_resolves` (`${a[${i}] ?? b[${i}]}` →
`"x"`), `test_266_escape_not_flagged_as_template`, `test_6b7faf8f_batch_over_workflow_node_results_index`
(child in `tmp_path`), `test_630_*` ×2 (`after` items → 2).

1d. *Dynamic-index characterization through `WorkflowRunner`* (`TestDynamicIndexConsumers`, plain
tests with `Mutation:` docstrings, `today` + `after` items): shape (JSON-string element via the sink:
str → dict, 4a), strict check (outer path missing via `out_arr`: literal shipped, exit 0 → strict error,
2), declared output (`source: ${p.out_arr[${idx}].x}` with input `idx`: literal written → error, 4a —
**see handback Q1 on the ledger's "skip"**), Optional code input over an absent root (literal → `None`,
4a), diagnostics (inner missing → names `idx`; outer missing → names `p.out_arr[${idx}].x`, 4a; also
`a[${item.i}].x` — the field-segment renderer must not print `'i}]'`), `??` non-int inner (4a), loop
`while:` over a dynamic index (shape error → accepted AND resolvable, 4a — R1) + partner
`while: ${typo[${idx}]}`, carry `${loop.items[${i}]}` (R1, 4a), type pass (`row: dict` over
`${p.out_arr[${idx}]}` → false ERROR today → clean, 4b — delta 6) + partner (mismatched annotation),
unused input used only inside `[${idx}]` (ERROR today → clean, 4b) + partner (a genuinely unused
input), `examples/test-nested-index.pflow.md` runs unchanged (no `after`).

1e. *Raw-path characterization* (`TestRawPaths`): `-o result.@type`, `result.dc:title`, `result.my key`,
`result.0`, `batch.results[0].result` through `resolve_value`/`variable_exists` AND the CLI `-o` path AND
`read_fields` — and through `resolve("${path}")` where the grammar accepts the path (the two readers
must agree there).

1f. *Walk-pair consistency rows* (`test_template_grammar.py`): §1's walk-pair table verbatim + the
array-`??`-`None` case, each through both readers.

1g. **Mutation ledger** (a phase-1 deliverable, logged): apply each named mutation to a scratch copy
of the code — drop the `(?<!\$)` lookbehind; narrow `_PERM_VAR` to `\w`; derive `found` from
`value is not None`; `has_templates == bool(TEMPLATE_PATTERN.search)`; drop a surface from
`_node_template_value_sources`; make Pass 5 field-check `??` operands; skip the `[${` nested count —
run the corpus, and record which rows go red. A mutation that turns nothing red means a missing row.

**Failure scenarios** — the mutation ledger above is the list.

**Gate.** Corpus green (`today` items pass; `after` items xfail strictly); `make test` green; the
implementer logs the full baseline delta vs this plan's numbers and the mutation ledger. **Stop after
this phase** (a measured `today` value that contradicts §1 or the spec's freeze is a hand-back with
the row; the merged-main output-source region must be re-read before writing those rows).

**Model/effort/agent.** Opus, `high`. Agent **A**. Direct `test-reflect`. No mid-task review.

### Phase 2 — One internal walk + the unresolved/issues channels (#630) — ENGINE CONTACT

**Goal.** Merge the duplicated traversal loops into `_walk`; add `Resolution` + module-level
`resolve(value, ctx, *, auto_parse=False)`; the engine's strict check, per-key `inputs` resolution +
`inject_none`, the loop-carry helper, `_resolve_template_string`, `output_resolver`,
`resolve_batch_items` (string form), `_resolve_chunk_value`, and `build_template_error_diagnostic`/
`classify_unresolved_references` consume the channels; delete `contains_unresolved_template`. Delta 1 flips.

**Files.** `src/pflow/runtime/template_resolver.py`; `src/pflow/runtime/engine/template_resolution.py`;
`src/pflow/runtime/engine/template_errors.py` (:126-161 signature; :336 caller); `src/pflow/runtime/engine/engine.py`
(:242-258, :393-402); `src/pflow/runtime/output_resolver.py`; `src/pflow/runtime/engine/batch_executor.py`
(:108-131); `src/pflow/core/prompt_cache.py` (:136-176); `tests/test_runtime/test_node_wrapper.py` (delete
`TestContainsUnresolvedTemplate` :196-222 — sanctioned); `tests/test_runtime/test_node_wrapper_template_validation.py:434-501`
(7 `inject_none` calls — sanctioned); direct `classify_unresolved_references` test callers if any
(sanctioned, mechanical); NEW `tests/test_runtime/test_template_walk_differential.py` (gate; deleted at
phase end); NEW exact-channel unit tests in `tests/test_runtime/test_template_resolver.py` (see below).
Serialization: engine seam; #503 never interleaved.

**Decisions.**
- `_walk(segments, context) -> (found, value)`; raw segments from `_split_raw_path` (today's
  `\.(?![^\[]*\])` split, then `^([^[]+)((?:\[\d+\])+)$` per part; `[0][1]` chains accepted in raw mode).
  Truth table = §1 walk pair. `variable_exists = _walk(...)[0]`; `resolve_value = value if found else None`;
  `resolve_coalesce` one `_walk` per operand; `_resolve_inline_expr` one call. Delete `_traverse_path_part`,
  `_check_array_indices`.
- `resolve()` per §0.1: the string path still runs the nested-index pre-pass in this phase (deleted in
  4a); the `issues` channel is computed as "unescaped `${` openings in the string not matched as an
  expression (after the pre-pass)" — exactly the class today's echo check catches; in 4a it becomes
  `parse().issues`. `unresolved` holds each expression's inner text that stayed literal (the rewritten
  `a[0].x` for the int-inner/missing-outer case — delta 1).
- Engine per §0.2 (per-key `inputs`; `not resolution.ok`; permissive entry fields; carry helper;
  classify-from-the-set; outer-root absence rule for injection).
- `_resolve_template_string`, `output_resolver`, `resolve_batch_items` (string), `_resolve_chunk_value`
  per §0.2 (failure ⇔ `not r.ok`; `resolve_output_source` → `None`; `populate_declared_outputs` → all-absent
  coalesce skip else failure; chunk → `_CHUNK_ABSENT`).
- Exact-channel unit tests (new class in `test_template_resolver.py`): escaped text excluded; Issues in
  `issues` not `unresolved`; nested dict/list aggregated; rewritten `a[0].x` included; a resolved value
  containing `${OLD}` excluded; `auto_parse` flag semantics (`'{"a":1}'` top-level str stays str without
  it, becomes dict with it).
- Differential gate: vendor `variable_exists`, `resolve_value` AND every transitive private helper
  (`_traverse_path_part`, `_check_array_indices`, `_get_dict_value`, `_try_parse_json_for_traversal`)
  from `git show 7dc5ad5d:src/pflow/runtime/template_resolver.py` into the test as `_legacy_*` (so the
  legacy side never calls live code); commit the test BEFORE any `src/` edit; ≥150 path×context combos
  (paths from §1 + `a`, `a.b`, `a.b.c`, `a[0]`, `a.b[1].c`, `a[0][1]`, `a.b[9]` × contexts {dict, list,
  JSON-string, None-mid-path, OOB, non-list index, numeric-string leaf, nested Mapping proxy}).

**Failure scenarios.** found derived from non-None (1f); an unresolved expression not reported
(`${x} $${x}`; rewritten `${a[0].x}`); a resolved value containing `${…}` text reported as unresolved
(upstream-`${b}` row; the `${OLD_VAR}` row); an Issue-bearing routed value going silent (the four
loud-today rows: dict sibling, output source, plain `s.stdout.0`, cache var, carry); `inject_none`
injecting for a partially resolved input or for a required sibling sharing the text (`test_branch_convergence.py`
green; the shared-text row); permissive carry no longer detected (`test_loop_config.py:870/:1045`);
prewarm `system` with `$${x}` dropped (row flips); `_CHUNK_ABSENT` no longer produced for an absent
upstream (byte-symmetry `..._with_absent_chunks` green); `resolve()` auto-parsing a top-level string for a
consumer that must not (output source `${sh.stdout}` over JSON stays a str; loop `until: ${n.list}` over a
JSON-list string still raises `LoopConditionError`; chunk over a JSON string keeps its bytes).

**Rows that flip.** Delta 1: escape+ref same param; upstream `${b}` text; `${a[${i}].x}` int inner +
missing outer / OOB (strict error); prewarm `system` `$${x}`; `test_630_*`; the rewritten-index
diagnostic names `a` (path_error).

**Handoff.** Freeze harness green with only the sanctioned edits; corpus per above; differential
green then deleted; grep `contains_unresolved_template|_check_string_unresolved|_traverse_path_part|_check_array_indices`
over `src/ tests/` → nothing; `template_resolutions` tests green unmodified; no new trace field.

**Model/effort/agent.** Opus, `high`. Agent **B**. **Triggers mid-task review**: `review-silent-failures`
(channel completeness; `inject_none`) + `review-impact-completeness` (all consumers switched; the
cost-analysis sites deliberately wait for 4a and are named).

### Phase 3 — Relocate to `core/` (mechanical) — bundled with phase 2 (Agent B, resumed)

**Goal.** `runtime/template_resolver.py` → `core/templates.py`; shim at the old path; every `src/`
importer re-pointed; the accessor dies; the layering pin + subprocess pin land; instruction files updated.

**Files (inventory verified 2026-09-28 — re-run the grep).**
- `git mv`; shim = `from pflow.core.templates import TemplateResolver, Resolution, resolve  # noqa: F401`
  + docstring "shim; deleted in phase 5". Identity: add to the shim's test
  `pflow.runtime.template_resolver.TemplateResolver is pflow.core.templates.TemplateResolver` (three
  monkeypatch sites patch the class object: `test_cache_analysis_token_estimation.py:508/:528`,
  `test_cache_analysis_analyze.py:5930`).
- `core/` importers → MODULE-level `from pflow.core.templates import TemplateResolver`:
  `cache_overlap.py:27`, `prompt_refs.py:18`, `workflow/validator.py:16`, `workflow/data_flow.py:26`,
  `prompt_cache.py:164/:244`, `trace_report.py:518`, `workflow/graph/scope.py:41`,
  `prompt_cache_analysis/context.py:54/:269/:339/:404/:452`, `sub_workflow_walker.py:530/:553/:579`,
  `trace_loading.py:557`, `token_estimation.py:247/:399/:432/:458/:478/:678`. Delete the
  `template_resolver()` accessor (`context.py:47-56`, `__all__` :539) and hoist its four consumers
  (`stages/row_builder.py:16/:915-928`, `stages/discrepancy/predict.py:15/:373-416`,
  `stages/cross_workflow.py:16/:393-395`, `stages/warnings.py:22/:481-531`). **Cycle check** from a clean
  interpreter: `uv run python -c "import pflow.core.workflow.validator, pflow.core.workflow.graph.scope, pflow.core.prompt_cache_analysis"`.
- `runtime/` (10 files; `engine/error_context.py:13` is the one RELATIVE import; drop the redundant lazy
  re-import at `template_resolution.py:261`), `execution/` (3), `cli/` (2), `nodes/llm/llm.py:621` (lazy),
  `mcp_server/services/field_service.py:11`.
- Tests: 17 files import the old path — re-pointed in **phase 5** with the shim deletion.
- Meta-tests: rule 4 in `test_import_hygiene.py`; the subprocess pin (§0.5.3, e2e-marked).
- Instruction/doc files (the shim keeps `test_agent_references.py` green, so staleness is invisible):
  `.claude/agents/pflow-codebase-searcher.md:124`, `review-architecture-fit.md:36`,
  `review-silent-failures.md:33`, `review-plan.md:104`, `review-feature-interactions.md:77`,
  `review-validation-consistency.md:44/:81/:82` → `make sync-claude-assets`; `src/pflow/core/CLAUDE.md:156`;
  `src/pflow/runtime/CLAUDE.md:13` + "Template resolution" section; `architecture/architecture.md:526`;
  `architecture/reference/template-variables.md:158/:922`; `architecture/core-concepts/data-type-coercion.md:73/:90`
  (drop stale line numbers); code comments `type_checker.py:32`, `template_resolution.py:38`,
  `type_validation.py:627`; `template_validation/CLAUDE.md`: add the current patterns to the regex table
  (the "three views" rewrite waits for 4b).

**Failure scenarios.** A lazy import left behind (rule 4 scans any scope); a duplicated class object
(identity assertion); an import cycle (the clean-interpreter command).

**Handoff.** Full suite green with zero test edits; rule 4 green; the e2e pin green (`make test-e2e`);
`make check` incl. asset sync; grep `runtime.template_resolver` under `src/` → only the shim.

**Model/effort.** Opus, `medium`. Agent B resumed after the phase-2 review is dispositioned.

### Phase 4 — Typed parse + drift-site migration (4a–4d; each a resting point)

Order is load-bearing: 4a (the language + every RUNTIME consumer — one atomic step, because the
facade's new semantics reach the engine, loop control and diagnostics the moment they land) → 4b
(validator consumers) → 4c (cache block) → 4d (graph + type-rule homes + display). No site outside the
spec's phase-4 list moves except the ones this plan names (§6 is the long tail).

#### Phase 4a — The AST, `parse()`, the facade, and the runtime consumers (deltas 3 and 4) — ENGINE CONTACT

**Goal.** `core/templates.py` gains the AST + `parse` + `parse_path` + `lookup` + the rules constants
(traversability/container/list sets; matrix moves in 4d) per §0.1; every `TemplateResolver` method is
reimplemented over them (public patterns rebuilt from the grammar); the pre-pass and
`_INTERPOLATION_PATTERN` die; the literal grammar tightens; `has_references` added; and every runtime
consumer whose behavior the facade shifts migrates in the same phase.

**Files.** `src/pflow/core/templates.py`; runtime consumers per the table; tests per §5;
NEW `tests/test_core/test_templates.py` (AST shapes, spans, immutability pin — `FrozenInstanceError`,
tuples not lists, fresh `Literal.value` across two resolves of `${a ?? []}`; boundedness pin
`parse.cache_info().maxsize is not None`; `parse` never raises on ~200 fixed strings incl. every §1
shape, lone `$`, `${`, `}`, unicode; `parse_path` segment rows — the eight `TestSplitTemplatePath`
expectations re-homed here).

**Runtime consumer table** (line cites on the merged head):

| Site | Today | After |
|---|---|---|
| `engine/template_resolution.py:189-192` | `is_simple_template(template)` | `parse(template).is_simple` (dynamic index → simple: auto-parse + type validation apply; JSON-string element row flips) |
| `:253-266 all_variables_from_absent_nodes` | `extract_variables` | value-position operand roots (outer only) |
| `:269-303 inject_none` (phase-2 shape) | `TEMPLATE_PATTERN`-based expression list | `parse(t).expressions` |
| `:351-360 / :153-167` type tuples | inline | `CONTAINER_TYPES` / `LIST_TYPES` from `core.templates` |
| `engine/template_errors.py:126-161 classify_unresolved_references` | per-expression `split_coalesce_operands` (phase 2) | parsed operands; a Reference with DynamicIndex segments: classify each inner ref FIRST (an unresolved inner is the cause and is reported, as today); only when every inner resolves classify the outer via `lookup`; `"absent"` keeps deriving from `NodeStatus.ABSENT`, never from `lookup` (failed-node invariant) |
| `:302-322 _suggest_field_correction`, `extract_first_field_segment` callers (:242/:307), `core/diagnostic_render.py:735 _extract_field_path` | lexical `split(".")` / `[2:-1]` | `parse_path` segments (`extract_first_field_segment('a[${item.i}].x')` → `x`; `_extract_field_path` → `var[len(root):].lstrip(".")`) — executed today they print `'i}]'` |
| `:36 build_type_error_message` | `TEMPLATE_EXTRACT_PATTERN.search` | first Expression's raw (or the template) |
| `engine/engine.py:130-167 _diagnose_carry_ref` | `extract_simple_template_var` + `split("[",1)[0]` | `parse(template)`: not simple / coalesce → `None`; Fields walked; Index/DynamicIndex → defer `None` |
| `engine/loop_control.py:131-153 evaluate_loop_condition` | `extract_simple_template_var` → pair | `t = parse(cond)`; not simple → `False`; else `r = resolve(cond, context)`; `None` if `not r.ok` (str guard unchanged) — **must move here**: with the old raw-path pair a dynamic-index condition walks to `None` and loops to `max_iterations` silently |
| `:178-188 resolve_loop_cap` | `resolve_template` | unchanged |
| `runtime/output_resolver.py:81-101 _is_all_absent_coalesce` | `extract_simple_template_var` + `is_coalesce_expression` | `t = parse(normalized)`; `t.is_simple and len(operands) > 1` (stricter all-absent semantics kept) |
| `runtime/output_resolver.py:47-53 _normalize_source` | `${…}` / `$x` / `x` | R4: `source if has_templates(source) else "${" + source + "}"` — the `$x` branch deleted |
| `batch_executor._pre_warm_compile_cache:180-230` | strict `ValueError` propagates | R10: catch the strict template `ValueError` (`_pflow_template_diagnostic` present), log at debug, skip the pre-warm |
| `execution/plan.py:1547` | `resolve_nested` | `resolve(raw_inputs_template, ctx, auto_parse=True)`; `not r.ok` → the per-item WARNING mechanism (:1549-1560) — R11 |
| `execution/plan.py:2037`, `core/workflow/validator.py:1729`, `error_context.py:35` | inherit / `extract_variables` | inherit / operands |
| cost analysis `row_builder.py:916-928`, `token_estimation.py:407-414/:440-453`, `sub_workflow_walker.py:533-537` | `resolve_template` then `TEMPLATE_PATTERN.search(output)` | `r = resolve(...)`; unresolved ⇔ `r.unresolved`; `:448-453`'s lower bound strips the unresolved expressions from the value by their raw text (no rescan) |
| `engine.py:393-402 _resolve_template_string` | phase 2 | unchanged |

**Facade decisions.** `is_simple_template = parse(s).is_simple`; `extract_variables` = value-position
operand References (outer; delta 6 precondition); `extract_simple_template_var` returns the inner raw
text (non-None for dynamic-index simple templates — R1); `resolve_coalesce` parses via the shared
expression grammar; `extract_root_node_id`/`split_coalesce_operands`/`is_literal_operand`/`is_coalesce_expression`
stay lexical. `data_flow.py:623 _validate_loop_carry_value_self_ref` and the loop-shape check
(`template_validation/validator.py:258-266`) flip in this phase through the facade (R1) — no edit
needed there; the rows are re-labelled 4a.

**Failure scenarios.** An unescaped `${` becoming Text (grammar table asserts Expression-or-Issue for
every candidate); the balanced escape not consuming `$${a[${i}]}` / consuming past an unclosed `$${`
(both rows); a DynamicIndex inner accepting `??`/nesting; `[${a}]` outside braces parsed as an index;
multi-index accepted; `$$${x}`/bare `$$` regressions; single-pass regression
(`TestEscapeAndSinglePassInterpolation`); `Literal.value` sharing a mutable; a `bool` inner index
accepted; `resolve` raising; the public `TEMPLATE_PATTERN` still yielding only `${i}` on a dynamic
index (row); loop `until:` over a dynamic index looping to the cap; a `path_error` ref whose root
FAILED reported as absent (`test_failed_node_invariant.py`); the pre-warm row under `continue`;
diagnostics printing `'i}]'`.

**Rows that flip.** Delta 3 (all runtime-side rows incl. shape, `??` non-int, Optional `None`,
declared output error, diagnostics naming the outer ref, loop/carry acceptance — R1), delta 4
(both escape rows), literal-grammar rows, R10, R11, the cost-analysis `$${` row, the pin flip in
`test_nested_templates.py:54-59`.

**Handoff.** Freeze harness green (sanctioned edits only); corpus per above; `make check`; grep in
`runtime/engine/`, `runtime/output_resolver.py`, `core/prompt_cache_analysis/` for
`split(".")|split("[")|TEMPLATE_PATTERN.finditer|TEMPLATE_PATTERN.search|TEMPLATE_EXTRACT_PATTERN` →
none on resolved text; `resolve_nested_index_templates|_BRACKET_INDEX_PATTERN|_INTERPOLATION_PATTERN`
have no callers (delete now or in 5); `test_trace_integration.py` green unmodified (no trace field).

**Model/effort/agent.** Opus, `high`. Agent **C** (fresh — phase 4 is ~half the task). **Triggers
mid-task review**: `review-silent-failures` (Text/Issue boundary, escape consumption, the channels
through every runtime consumer) + `review-impact-completeness` (every facade consumer whose meaning
shifted migrated in this phase) + `review-test-fidelity` (the grammar-table re-target and the
invariants). Direct `test-reflect`.

#### Phase 4b — Validator consumers on the AST (deltas 2 and 6; the enumerator, the Issue pass, the classifier) — CROSSES LAYERS

**Goal.** §0.3 in full: the surface enumerator module; the ONE Issue pass over every surface (params,
`batch.items`, loop fields, carry, output sources, cache vars, cache prose); every validation pass
consumes `parse`/`parse_path` segments and the classifier; `data_flow` consumes references (inner refs
included) and walks `batch.items`; output-source and cache-var validation root-check References only;
the deferral sites key on `has_references`; the nested-index rule (R9). Delta 2, delta 6, #262, the
Pass-8 policy, R3/R4(validator side unchanged)/R5(validator side)/R6/R9 land here.

**Files + per-site decisions** (merged-head cites):

| Site | Today | After |
|---|---|---|
| NEW `core/workflow/template_surfaces.py` | — | `iter_template_surfaces` (§0.3) |
| `template_validation/validator.py:664-739 _validate_malformed_templates` | counts over `params` only | the ONE Issue pass over the enumerator (§0.3); one diagnostic per value with today's message shape; `bad_literal` → the targeted message; paths `nodes[id=X].params.<p>` / `.batch.items[<i>]` / `.loop.<key>` / `.loop.carry.<key>` / `outputs.<name>.source` / `cache.items[name=<n>].var` / `.prose_before` |
| `:747-761 _operands_in_string`, `:764-780 _node_template_value_sources`, `:783-806 _iter_template_operands` | `_PERMISSIVE_PATTERN` | delete the first two; the iterator per §0.3 (yields `(node_id, path, Reference, OperandPolicy)`; Issues skipped — the Issue pass owns them) |
| `:809-828 _extract_all_templates / _field_checkable_templates` | `set[str]` | `set[str]` of `ref.raw` for unused-input accounting (inner refs included — delta 6); `set[Reference]` filtered `FIELD_CHECK` for Pass 5 |
| `:831-876 _extract_cache_templates_for_unused_check` | manual `??` split | `parse("${" + var + "}").references` roots |
| `:273-280`, `:390-412`, `:457-486`, `:519-545`, `:645-660` | `split_coalesce_operands` / `TEMPLATE_EXTRACT_PATTERN` | `parse(...).expressions[i].operands`; `:645-660` deleted (absorbed) |
| `path_validation.py:73-126 validate_template_path(template: str, …)` | `split_template_path` | `ref = parse_path(template)` (`None` → `(False, None)` + debug log); root-keyed `initial_params` lookup (**#262 flips**); `validate_namespaced_output(ref, …)` / `validate_nested_path(segments, …)`: `Field` → structure key; `Index`/`DynamicIndex` → `_descend_index(field_info)` (batch `items`, else a list-typed field's `structure` — R9); `_validate_array_access` accepts `LIST_TYPES ∪ {"any"}` plus `str` with the JSON warning (the `list`-typed over-rejection flips) and keeps the continue-mode block (:169-174; `test_array_notation.py:328-340`); type lists → the shared sets |
| `:366-406 create_template_diagnostic` + `_create_*` | `split_template_path` | segments; messages unchanged |
| `batch_item_validation.py:62-98 _infer_batch_item_structure`, `:101-137 _extract_item_field_refs`, `:140-170`, `:225-303` | `TEMPLATE_PATTERN.findall` / own `extract_variables` walk / `split(".")` | operands via `parse`; the field refs from `_iter_template_operands` filtered `node_id == this node`, `ref.root == alias`, `FIELD_CHECK` (**Pass-8 `??` row flips**); segment-based checks |
| `type_checker.py:118-256 infer_template_type` | `split(".")` + `re.sub(r"\[\d+\]")` | `parse_path(template)` → segments; `Index`/`DynamicIndex` → `_descend_index`; traversable checks via the shared sets |
| `type_validation.py:29/:176-188 _QUOTED_TEMPLATE_PATTERN` | own regex | quoted ⇔ the char before `e.span[0]` and the char at `e.span[1]` are `'`; `_build_quoted_templates` keeps its name/signature (`test_template_extract_pattern.py:14`) |
| `type_validation.py:135/:239/:406-412/:708` | `extract_variables` (now operands-only — done in 4a) | no change beyond consuming `parse_path` where a segment is needed; `_infer_code_input_type` picks deterministically (sorted) |
| `type_validation.py:955 _traverse_to_structure`, `:582` | `split(".")` | `parse_path` / `extract_root_node_id` |
| `core/workflow/data_flow.py:34 _PFLOW_VAR_RE`, `:284-288`, `:772-844 _check_param_value`, `:847-933 _validate_node_params` | `TEMPLATE_EXTRACT_PATTERN` + gate | `for ref in parse(value).references: _validate_template_reference(ref.raw, …)` (Issues skipped; delete `_PFLOW_VAR_RE`); surfaces from the enumerator (`param`, `batch_items`, `loop`) — **`batch.items` walked** (coalesce roots there checked); inner refs are references (delta 6) |
| `data_flow.py:1139-1159 cache root check` | whole-var root | each Reference root of `parse("${"+var+"}")` (single operand after R5) incl. inner dynamic-index refs for the batch-alias rejection; Issues → the Issue pass |
| `core/workflow/validator.py:516-583 _validate_output_sources` + `:587-648 _validate_template_in_source` | `"${" in source` / `TEMPLATE_EXTRACT_PATTERN.findall` | `t = parse(source)` on the RAW text: no Expression → R3 ERROR; each Reference root ∈ valid_sources; Issues → the Issue pass (not here); plain `node.x` → root check as today; `$node.x` → no Expression → R3 |
| `data_flow._validate_loop_carry_value_self_ref:622-627` | facade (flipped in 4a) | `parse(value).is_simple` + root (no behavior change beyond R1) |
| deferral sites `core/workflow/validator.py:1004/:1043/:1151/:1258`, `template_validation/validator.py:1226/:1142`, `sub_workflow_resolver.py:93` | `has_templates` / `"${" in` | `has_references`; escape-only values checked on `resolve(v, {}).value` (R6) |
| `template_validation/CLAUDE.md` | "three patterns, do not unify" | three VIEWS over one parse; the Issue pass + enumerator; "never `str.split('.')`" now true; drop `split_template_path`; correct "data_flow still checks their roots" |

**Failure scenarios.** Every converse-silent row (validator ERROR); `${a ?? "${b}"}` clean; #262 clean
+ `${arrr[0]}` error; R9 rows clean + partners error; Pass 8 `??` clean + `${item.missing}` error; two
batch nodes sharing alias `item` not cross-checked; a malformed `batch.items` element / carry value /
cache var / cache prose caught; `items: ${typo.x ?? a.stdout}` caught; input used only in `[${idx}]`
clean + genuinely unused input error; `${typo[${i}].x}`, `${data[${typo}].x}`, the `b.y` partner
caught; continue-mode index block fires for `[${i}]`; escape-only deferral values checked (rows);
`$n.stdout` error (both sides); escape-only source error with the R3 message; literal-only source
clean; `prefix ${n.stdout}` source stays clean; `test_validator.py:298-311` passes for the right
reason (+ positive control); `test_malformed.py` count assertions unchanged.

**Rows that flip.** Delta 2 (all), delta 6 (validator side), #262, R9, Pass-8, R3, R4 (validator side
already errors — the runtime side flipped in 4a), R5 validator side, R6, delta-4 validator half.

**Handoff.** Freeze harness green except the two sanctioned edits (§5); corpus per above; grep
`_PERMISSIVE_PATTERN|_TEMPLATE_OPEN|_PERM_VAR|split_template_path|_PFLOW_VAR_RE|_QUOTED_TEMPLATE_PATTERN|_node_template_value_sources`
under `src/` → definitions only where phase 5 deletes them (`cache_overlap.py`'s `_PFLOW_VAR_RE` → 5).

**Model/effort/agent.** Opus, `high`. Agent C resumed if <~400k, else a fresh Opus **C2** packeted
with this plan + the log tail. **Triggers mid-task review**: `review-validation-consistency` (every
surface, both directions) + `review-impact-completeness` (every pass on the enumerator/classifier;
nothing left on the permissive grammar).

#### Phase 4c — Cache block: chunking on spans + ADR-0015 helper + static-prefix interpolator (delta 5, R2, R5)

**Goal.** `_parse_cache_code_block` chunks on `parse(content).expressions` spans; escapes in cache
prose are honoured; a `??` chunk is rejected (R5); Issues stay prose (R2); ONE helper renders
`(name, unescaped prose, value)` for the hash and prepare sites; `_resolve_static_prefix_for_cache`
interpolates over segments.

**Files + decisions.**
- `core/markdown_parser.py:161-167` + `:1721-1773`: `t = parse(content)`; each single-operand
  `Expression` is a chunk: `name = var_expr = content[span[0]+2:span[1]-1]` (assert `== expr.raw`);
  `prose_before = content[last_end:span[0]]` (escaped, verbatim); `chunk_line` from
  `content.count("\n", 0, span[0])`; a multi-operand Expression → `MarkdownParseError` "coalesce is not
  supported in a ## Cache chunk" (R5); Issues are prose (R2 — the Issue pass reports them from
  `prose_before`); duplicate-name / no-chunk / trailing-prose-discard unchanged (21 tests green; add
  rows: `$${x}` in prose is prose; `${}` and unclosed `${a` are prose and a validator ERROR; a trailing
  `$${x}` is discarded like any trailing prose; `${a ?? b}` chunk rejected).
- `core/prompt_cache.py`: NEW `render_cache_chunks(cache_ctx, shared) -> list[RenderedChunk]` (frozen
  `RenderedChunk(name, prose, value)`): prose = `parse(prose_before)` rendered segment by segment —
  Text unescaped, any other segment verbatim (NO assert; dict IR may carry `${…}` in prose and the
  validator reports it); value = `deterministic_serialize(_resolve_chunk_value(...))`, ABSENT filtered.
  `plan_node._render_cache_for_hash` (:160-201) → `[{"name": c.name, "prose": c.prose, "value": c.value} …]`
  (hash dict shape unchanged); `build_cache_system_blocks` (:367-446) → `prose + value` per chunk
  (LLM node AND prewarm `batch_executor.py:640-647`). `CacheChunkIR.prose_before` stays escaped
  (`graph/build.py:680-684` re-emits template text; `cross_workflow.py:131/:185/:285/:509` escaped-to-escaped).
  `test_prompt_cache_rendering.py:427` pins `plan_node._resolve_chunk_value` as a local attribute →
  **sanctioned retarget** to `render_cache_chunks`.
- `_resolve_static_prefix_for_cache` (:224-256): `parse(text).segments`: Text → unescaped; Expression
  → resolved value → `_deterministic_serialize`, else raw; Issue → verbatim (fixes the prewarm static
  prefix sending literal `$${HOME}`). Stale docstring ("Python repr") corrected.
- Byte-symmetry: third test in `test_prompt_cache_rendering.py` — prose with `$${HOME}` AND a chunk
  VALUE containing literal `$${x}`: hash texts == prepare texts == the unescaped prose + the VERBATIM
  value (an implementation that unescapes `prose + value` together fails).
- Docs: `docs/how-it-works/prompt-caching.mdx:46` ("verbatim" → "verbatim except `$${` escapes, which
  render as `${`"); `src/pflow/guide/features/prompt-caching.md` if it repeats the claim.

**Failure scenarios.** Hash/prepare divergence on an escaped chunk; the value unescaped; `$${topic}`
parsed as a chunk; `prose_before` unescaped in IR (graph `cached_prefix` fixture
`web/src/test/fixtures/contracts/prompt-caching-multi-chunk.json` + `test_graph_build.py`); chunk name ≠
raw slice; an Issue in prose becoming a chunk or a parse exception (R2 rows); the prewarm static prefix
still containing `$${`; a `??` chunk accepted.

**Rows that flip.** Delta 5; R2; R5 (parse side); the static-prefix `$${` row.

**Handoff.** `test_cache_block_parser.py`, `test_prompt_cache*.py`, `test_prompt_cache_rendering.py`,
`test_graph_build.py` green (+ new rows); the Task-159 baseline `.taskmaster/tasks/task_159/baseline/verify.sh`
run and logged (not a trace-format change — `llm_system` text changes only for `$${` blocks).

**Model/effort/agent.** Opus, `medium`. Agent C/C2 resumed.

#### Phase 4d — Graph scope + web mirror, type-rule homes, display strippers

**Files + decisions.**
- `core/workflow/graph/scope.py`: `refs_with_path_in(value)` over `parse(value).references` (inner refs
  of a DynamicIndex included → edges from BOTH the outer root and the index source; today none):
  `(root, first Field after root or None, remaining Field names)`; `Index`/`DynamicIndex` skipped in the
  field tuple — `${data[0].field}` → `("data", "field", ())` (**accepted characterization delta**; new pin
  in `test_graph_build.py:1330-1344`). Delete `_BRACE_BLOCK_RE`/`_REF_IN_BLOCK_RE` and the reach.
- `web/src/graph/scan.ts:46-60` + `paramTextReads` (:99-131): mirror the same changes AND the
  balanced-escape rule (delta 4: `$${FOO:-${n.result}}` yields no read); `scan.test.ts` gains bracket,
  dynamic-index and escape rows with a "Runtime parity (mirrors scope.py)" comment. **`web/node_modules`
  is absent in this worktree: run `npm ci` in `web/` first**, then `npx vitest run src/graph/scan.test.ts`.
  Verify via `screenshot-pflow-web-ui` on `examples/test-nested-index.pflow.md` (the DATA_FLOW edge from
  `process-batch` into the consumer with the `stdout` label) — the one UI surface; not design-bearing.
- Type-rule homes (§0.4): matrix + `is_type_compatible` → `core/templates` (`type_validation.py:18`
  imports from there; `test_type_checker.py:9` re-points — **sanctioned**); `type_checker.py:223/:250`,
  `path_validation` lists, `template_resolution.py` tuples, `type_validation.py:143` → the shared sets
  (delete the copies). Pointers: `task_112/task-112.md:11/:71/:136/:164/:174/:194` + `research/output-field-validation.md:44/:114`,
  `task_120/task-120.md:11/:13/:66` — corrected TEXT: template-flow compatibility lives in
  `core/templates.is_type_compatible` and is not a literal-value check; literal/coerced values use
  `TypeSpec.accepts` (`core/types.py`). `architecture/reference/template-variables.md:599/:608`;
  `src/pflow/core/CLAUDE.md` types section; `template_validation/CLAUDE.md:15`; Task 167
  (`task_167/task-167.md:134-135/:182` → `Template.segments` spans in `core/templates`).
- `core/workflow/graph/renderers/mermaid.py:790` → render `parse(text)` with Expressions as `raw`;
  `:836-842 _strip_template` → `extract_simple_template_var` with the loose fallback.
- `core/prompt_cache_analysis/stages/warnings.py:485/:528` `stripped[2:-1]` → `extract_simple_template_var`.
- `graph/build.py:692-694` (output-source edges require `${`) — unchanged; plain `node.x` sources get no
  edge today (pre-existing; noted, not fixed).

**Failure scenarios.** An edge lost for `${data[0].field}`; web scan disagreeing with Python edges
(vitest rows + screenshot); `is_type_compatible` behavior change (its 45 assertions — same values,
one home); the #460 fixture.

**Handoff.** Suite green with the sanctioned re-point; web tests green; screenshot evidence in the
task folder; pointers updated.

**Model/effort/agent.** Opus, `medium`. Agent C/C2 resumed.

### Phase 5 — Sweep and seal

**Deletions (each after a grep proves zero users):** `core/templates.py`: `resolve_nested_index_templates`,
`_BRACKET_INDEX_PATTERN`, `_INTERPOLATION_PATTERN`, the class-level `_VAR_NAME_PATTERN`/`_LITERAL_PATTERN`
aliases (module-private; grep `tests/` first). `template_validation/validator.py`: `_PERM_VAR`,
`_PERM_OPERAND`, `_PERMISSIVE_PATTERN`, `_TEMPLATE_OPEN`, `_malformed_literal_operand_hint`,
`_node_template_value_sources`. `template_validation/utils.py::split_template_path` + export (:7/:19) +
`tests/test_runtime/test_nested_templates.py:71-130 TestSplitTemplatePath` (sanctioned — its rows live in
`test_templates.py` since 4a). `core/cache_overlap.py:32 _PFLOW_VAR_RE` + `:124-136` → `parse` (gate
`parse_path(operand) is not None`; `_canonicalize_path` :57-89 stays — §6). `cli/workflow_output.py:295
_PATH_SEGMENT_PATTERN` stays (raw-path mode). The shim + the 17 test import re-points.
- Meta-test 2 (§0.5.2) lands and is green on first run (a failure is a missed site — migrate, never allowlist).
- `test_yaml_utils.py::TestBraceAwareTemplates`: `$${y}` and `${a[${i}].x}` flow-mapping pin rows.
- `.claude/agents/review-validation-consistency.md:158/:219` (`_PFLOW_VAR_RE`) rewritten around `parse()`;
  `make sync-claude-assets`.
- Instruction files: `src/pflow/core/CLAUDE.md` (`templates.py` row + "Template language" section: AST,
  `parse`/`resolve`/`lookup`, the two channels, raw-path mode, the author-text-only rule),
  `runtime/CLAUDE.md`, `runtime/engine/CLAUDE.md` ("Parameters, reuse, and templates": channels, per-key
  inputs, no text comparison), `core/workflow/CLAUDE.md:59`, `template_validation/CLAUDE.md` (final),
  `tests/CLAUDE.md`, `.claude/agents/pflow-codebase-searcher.md`, `docs/how-it-works/template-variables.mdx`
  (escape: balanced through the closing `}`; dynamic index: one reference), `src/pflow/guide/features/batch.md:160-173`
  (per the 1d characterization — the `${my_input[${__index__}]}` claim is verified in phase 1),
  `context/CONTEXT.md` (no new nouns expected; propose in the handback if "Issue"/"dynamic index" crystallize).
- Final grep list (empty under `src/`): `_PERMISSIVE_PATTERN|_TEMPLATE_OPEN|_PERM_VAR|split_template_path|_CACHE_TEMPLATE_RE|_BRACKET_INDEX_PATTERN|_INTERPOLATION_PATTERN|resolve_nested_index_templates|_BRACE_BLOCK_RE|_REF_IN_BLOCK_RE|_PFLOW_VAR_RE|_QUOTED_TEMPLATE_PATTERN|contains_unresolved_template|_node_template_value_sources|TemplateResolver\._VAR_NAME_PATTERN|TemplateResolver\._LITERAL_PATTERN|runtime\.template_resolver`.
- LOC: `git diff --stat main..HEAD -- src/` logged; target ≤ baseline for `src/` (measure, do not chase).

**Failure scenarios.** Meta-test 2 false negatives (planted spellings); a stale `.claude/agents` path
after the shim deletion (`test_agent_references`).

**Handoff.** `make check` + `make test-all-local` green; three meta-tests green; grep list empty; §4's
manual list executed and logged; spec `## Status` → `done` + `## Completed` (close-out).

**Model/effort/agent.** Opus, `medium`. C/C2 resumed or a fresh Opus **D**.

---

## 3. Agent assignment and bundling

| Phase | Agent | Model / effort | Stop after? | Mid-task review |
|---|---|---|---|---|
| 1 | A (fresh) | Opus / high | **Yes** — a surprising `today` value changes the plan | none; `test-reflect` directed |
| 2 | B (fresh) | Opus / high | Yes — review dispositions | `review-silent-failures`, `review-impact-completeness` |
| 3 | B (resumed) | Opus / medium | Yes (boundary) | none |
| 4a | C (fresh) | Opus / high | Yes — freeze gate + review | `review-silent-failures`, `review-impact-completeness`, `review-test-fidelity`; `test-reflect` |
| 4b | C or C2 | Opus / high | Yes — review | `review-validation-consistency`, `review-impact-completeness` |
| 4c | C/C2 (resumed) | Opus / medium | Yes | none (byte-symmetry tests + Task-159 script) |
| 4d | C/C2 (resumed) | Opus / medium | Yes | none |
| 5 | C/C2 or D | Opus / medium | — | completion gate: full battery incl. `review-falsifier` (direct), `review-spec-conformance`, `review-simplicity`, `review-feature-interactions`, `review-agent-ux` (diagnostic wording changed) |

Rotate C at ~400k. One job per resume message.

---

## 4. Verification beyond the per-phase gates

- **Manual end to end** after 4d and at completion (`uv run pflow …`; commands + outputs logged): the
  #620 docs example; both #630 repros; a batch with `${p.results[${__index__}].x}` into a dict param and
  one with an out-of-range index (strict error names the outer reference); a `## Cache` block containing
  `$${HOME}` (validates; `--dry-run` and a run agree; `llm_system` in the trace shows `${HOME}`); a
  prewarm batch prompt containing an escape; `pflow <wf> -o result.@type`, `pflow read-fields <run>
  result.0`; a parallel sub-workflow batch under `error_handling: continue` with a bad item[0] (R10);
  a byte-identical run of every `examples/**/*.pflow.md` that needs no API key (pick by
  `examples/CLAUDE.md`; capture `--output-format json` before phase 1 — a phase-1 deliverable kept
  under the task folder — and after phase 5).
- **Windows gate:** the corpus prefers `code`/sink consumers; the few shell rows use `echo` with no
  quoting — the blocking `tests-windows` job runs the parity file.
- **Trace format:** untouched by construction (§0.2); the Task-159 baseline script after 4c.
- **Structure properties** pinned by meta-tests 2/3, the subprocess pin, the immutability and
  boundedness pins, the phase-5 grep list.

---

## 5. Sanctioned test changes (complete; anything else is a deviation to log)

| Phase | Test | Change |
|---|---|---|
| 2 | `tests/test_runtime/test_node_wrapper.py:196-222` | delete `TestContainsUnresolvedTemplate` (cases live as corpus rows since phase 1) |
| 2 | `tests/test_runtime/test_node_wrapper_template_validation.py:434-501` | 7 `inject_none_for_optional_inputs` calls → new signature |
| 2 | direct callers of `classify_unresolved_references` in `tests/` (grep) | new first argument (mechanical) |
| 4a | `tests/test_runtime/test_nested_templates.py:54-59` | flip: non-int inner → template unchanged (delta 3) |
| 4a | `tests/test_core/test_template_grammar.py` | the permissive column's FUNCTION re-targeted to `parse()`; expected cells unchanged except `flips_in="4a"` rows |
| 4b | `tests/test_runtime/test_template_validation/test_validator.py:298-311` | assert the malformed message (right reason) + positive control |
| 4c | `tests/test_nodes/test_llm/test_prompt_cache_rendering.py:427` | identity pin retargeted to `render_cache_chunks` |
| 4d | `tests/test_runtime/test_template_validation/test_type_checker.py:9` | import re-point |
| 5 | `tests/test_runtime/test_nested_templates.py:71-130` | delete `TestSplitTemplatePath` |
| 5 | 17 test files importing `pflow.runtime.template_resolver` | import re-point |
| 1–5 | corpus `today` items and xfail markers | removed exactly in the phase named on the row (or re-derived at a gate per §0.5.1) |

---

## 6. What stays unmigrated, and why (the honest seal)

- **String-helper long tail on the facade (permanent):** `core/prompt_cache_analysis/*` except the
  four resolve-then-scan sites migrated in 4a (context.py's six equality sites, `trace_loading.py`,
  `predict.py`, `token_estimation.py:461/:691`), `core/prompt_refs.py` (span consumer; its
  `first_per_item_position` tearing a nested index at 23 is a recorded bug for a lane),
  `core/trace_report.py:495-567` (display-only; the :526 heuristic stays — no trace field),
  `core/cache_overlap.py:57-89 _canonicalize_path`, `sub_workflow_walker.py:106/:119-123/:448-453`,
  `suggestions.py:150/:526`, `execution/formatters/*`, `mcp_server/services/field_service.py`.
- **~35 lexical `"${" in x` presence checks** (17 files) + 7 `startswith("${")` checks: prefilters.
- **Raw user-typed paths:** the raw-path mode; `cli/workflow_output.py:295-346` stays.
- **Output `source:` prose wrap** (`prefix ${n.stdout}` → `'${prefix OK}'`): recorded, not fixed.
- **Inline-list `batch.items` unresolved elements** stay literal (R12) — follow-up in the handback.
- **`coerce_param_for_node`'s `json.dumps`** (third stringification): named, not unified.
- **Cache var typo silently ABSENT** (`${plan.stdot}`): root-only validation stays (spec); an INFO
  advisory at runtime is a handback follow-up.
- **Web TypeScript mirrors other than `scan.ts`**: a separate issue (spec).
- **`TypeVocabularyError(ValueError)`**, **#503's `ValueError` contract**: untouched.
- **Passes 6/7/9's own param-scoped walks** (they consume `parse` through `extract_variables`, not
  the operand iterator): a follow-up simplification, named for the completion-gate simplicity lens.
- **`graph/build.py:692-694`** plain `node.x` sources get no edge (pre-existing).

---

## 7. Risks and their nets

| Risk | Net |
|---|---|
| Tokenizer diverges from today's regexes on an unenumerated shape | 1a table + never-raises fuzz + the span-coverage invariant; 4a lenses |
| A consumer of "unresolved by text" or of a shifted facade helper missed | phase-2 and 4a `review-impact-completeness`; the 4a handoff grep; corpus rows per consumer |
| `resolve()` auto-parse contract misapplied at a consumer | the `auto_parse` unit rows + per-consumer JSON-string rows (output, chunk, loop, prewarm) |
| `Literal` mutable sharing through the cache | immutability pin |
| `str` traversability alignment changes a diagnostic | corpus row pins "inert"; `test_type_checker.py` values unchanged |
| Hash change for `$${` cache blocks surprises a fixture | none in-tree; the third byte-symmetry test |
| Windows: corpus shell rows | code/sink consumers preferred |
| Collisions | #628 merged in; #520 after 4b; #503 never interleaved |
| Context exhaustion in phase 4 | C→C2 rotation at ~400k |

---

## Appendix A — Plan self-review dispositions (seven lenses, 2026-09-28)

Lenses: `review-plan`, `review-architecture-fit`, `review-validation-consistency`,
`review-silent-failures`, `review-impact-completeness`, `review-feature-interactions`,
`review-test-fidelity` (all Opus, direct launch — plan mode). Every Critical below was verified by
the planner (executed or read at the cited line) before folding.

| Finding (lenses) | Verdict | Fold |
|---|---|---|
| `resolve()` string semantics undefined — consumers switched from `resolve_template` would auto-parse JSON strings (outputs, chunks, loop, prewarm) (feature C1, plan C2) | Confirmed (`template_resolver.py:866` vs `resolve_template`) | §0.1 `auto_parse` flag; rows |
| Issues absent from the set → today's loud malformed detection lost at runtime through 4b (silent C1, plan C4, valcon W3) | Confirmed by execution (dict sibling raises; output source raises; chunk ABSENT) | `Resolution.issues`; `ok`; phase-2 issue detection |
| `inject_none` × a dict-wide set (silent C2, plan C1, feature W1, impact W3) | Confirmed by execution (injection clears the check today; shared-text sibling must stay loud) | per-key `inputs` resolution; sanctioned test edit |
| Inner refs leak into type/absence passes; delta-6 row cannot flip (plan C3, valcon W1, impact W2, feature W2) | Confirmed by reading `type_validation.py:701-722` + the executed false error | `extract_variables` = value operands; `references` for accounting; outer-root absence |
| Corpus producer shape unreachable today; strict xfail without `raises=` hides it; dict IR skips the chunker; `code.inputs` never hits the engine gate (test-fidelity C/W1–W3, silent W1) | Confirmed by the lens's execution | Phase-1 harness rewritten: `out_arr`, sink, `raises=AssertionError`, today/after items, markdown for cache rows, `WorkflowRunner().validate` |
| Pre-existing Pass-5 over-rejection of `[N]` in nested structures; `list`-typed outputs rejected (valcon W5, test-fidelity C) | Confirmed by the lens's execution | R9; rows + partners |
| 4a facade changes flip runtime consumers early; loop_control silent window (valcon W2, plan W1) | Confirmed by reasoning + the raw-walk execution | 4a = language + runtime consumers |
| Escape regex swallows a later real reference after an unclosed `$${` (silent W2, plan S2, feature S2) | Confirmed by execution | balanced escape with `$${`-only fallback |
| Matrix pointed at Tasks 112/120 approves their counterexamples (arch W1) | Confirmed by execution (`int→str`, `string→object` True) | matrix → `core/templates`; pointer text |
| Issue policy in four homes incl. a parser exception; two surface enumerations (arch W2, plan W7) | Confirmed | enumerator module; one Issue pass; R2 revised |
| Public patterns speak the old grammar after 4a; Task 167 points at them (arch W3, impact W5) | Confirmed by execution | rebuilt from the grammar; 167 pointer |
| R4 opens an authoring door (arch open decision) | Accepted the conservative option | R4 = narrow |
| R5: runtime drops `??` chunks anyway (impact C1, valcon W6, plan W4) | Confirmed by execution | R5 = explicit rejection; batch-alias rule per root |
| R3 rejects literal-only sources; escape-only sources normalize into an Issue (plan W3b, valcon W4) | Confirmed by execution | R3 keyed on "no Expression"; validator parses the raw source |
| Prose-wrap drift would be "fixed" via normalization (plan W3a) | Confirmed | validator parses raw source (stays OK) |
| Ledger says declared outputs "skip" for a failed dynamic index; plan/today: error (feature W3) | Real wording conflict | **Handback Q1** (plan proceeds on "error unless all-absent coalesce") |
| Pre-warm compile bypasses `continue`; delta 3 widens it (feature W4) | Confirmed by the lens's execution | R10 |
| Dry-run per-item unresolved invisible (feature S4) | Confirmed | R11 |
| Inline batch list unresolved elements silent (silent W3) | Confirmed | R12 + §6 + handback |
| Non-int index warning downgraded (silent W4) | Accepted | warning kept |
| Cost-analysis resolve-then-scan sites are #630-pattern, not "resolved values" (impact W4) | Confirmed | migrated in 4a |
| Diagnostic renderers print `'i}]'` for outer dynamic refs (impact W6) | Confirmed by the lens's execution | 4a table |
| Pass 8 alias cross-check across nodes; `_infer_batch_item_structure` unlisted (valcon S3, impact S) | Confirmed | 4b table |
| R6 extra sites + resolved-value callers (impact S, valcon S1, silent S) | Confirmed | R6 list; `has_references` regex-only; unescaped-value check |
| `test_malformed.py` count phrase / `len==1` (test-fidelity W4) | Confirmed | one diagnostic per value, message shape kept — zero edits |
| Differential must vendor transitive helpers (test-fidelity W5) | Confirmed | phase 2 |
| Meta-test prefilter misses Rule B; non-vacuity (test-fidelity W6) | Confirmed | §0.5.2 |
| Negative partners; executed mutation ledger; tautological invariant; 1c duplication; boundedness pin; byte-symmetry strength; both readers (test-fidelity W7–W9, S1–S5) | Accepted | folded |
| #628 already merged; cites shift (plan W5, impact note) | Confirmed | merged `c07acb4d`; cites re-measured |
| "One set feeds check and diagnostic" not honoured; `engine.py:400` contradiction (plan W6) | Confirmed | classify-from-the-set; §0.1 list corrected |
| Classifier not consumed by every pass (arch handoff, valcon S4) | Acknowledged | §0.3 states which passes and why; §6 names the follow-up |
| `prose_before` from dict IR (valcon S2, silent S) | Confirmed | no assert; validator reports; render verbatim |
| Task 100 `batch.initial` (arch W2 weak evidence) | Noted | enumerator is the one-line home |

Disputed: none. Needs investigation: none beyond Handback Q1.
