# The template language is one parser/AST with separate runtime and validator walks — no shared-traversal abstraction

Status: accepted

The `${…}` template language consolidates into one module (`core/templates`): a single
error-tolerant parser producing a typed AST (expressions, Operands, path segments — dynamic
indices first-class, which retires both the string-rewrite pre-pass and the second
"permissive" grammar), one value-walk evaluator, and one home for the semantic judgments
that have historically drifted (stringification, traversability, type compatibility —
issue #460). The validator keeps its **own direct structure-walk** over the same AST
segments; the two walks are deliberately NOT unified behind a World/port abstraction,
although a fully worked ports-and-adapters design (ValueWorld/StructureWorld over a
two-method protocol with HIT/MISS/UNKNOWABLE outcomes) was on the table.

Rejected because the port fails the deletion test: deleting it yields two single-purpose
~60-line walks, each simpler to read than a generic loop + two adapters + a three-valued
outcome algebra — the adapters would hold all the real semantics anyway. Its claimed
type-forced correspondence also doesn't hold: a new traversal behavior lands in one
adapter's body, and nothing in the types forces the other adapter to react. Top-tier
implementations of the same two-worlds problem (CEL's checker/interpreter, actionlint,
JMESPath) share the AST and conformance tests, not the walk.

Drift protection instead comes from three places: both walks consume the same parsed
segments (segmentation cannot drift — the d5a1af8c class), both consume the shared rules
(judgment calls cannot drift — the #460 class), and parity drift tests pin the remainder
(a fixed table corpus plus the historical bugs as named fixtures — #441, #460, #266,
d5a1af8c, 8535ed9b, 6b7faf8f; a grammar-uniqueness AST-scan meta-test keeps new `${…}`
regexes from appearing outside the module). Property-test *generation* was also rejected
as premature — the table corpus covers every observed failure; build a generator only if
a drift ever escapes the table.

Recorded so a future architecture review does not re-suggest unifying the two walks (or
read the validator's separate walk as an unfinished consolidation violating the "shared
layers, not parallel logic" doctrine — the shared layers here are the AST and the rules,
deliberately not the loop).

## Amended 2026-09-28 (Task 170 spec battery, session-08)

Three refinements, none reversing the decision:

- **The grammar-uniqueness scan has a named allowlist**, one reason per entry, plus a second
  rule: no `re.*` call outside `core/templates` may reference one of its pattern attributes
  (the by-symbol copy — `TemplateResolver._VAR_NAME_PATTERN` composed into new regexes in
  `core/workflow/data_flow.py`, `core/cache_overlap.py`, `core/workflow/graph/scope.py` — is
  the historical drift vector, and a literal-only scan cannot see it).
  Allowlisted: `mcp/auth_utils.py` (MCP-config `${VAR:-default}` expansion is a different
  language), `core/yaml_utils.py` (a lexical YAML mask that deliberately allows one nested `{}`
  level and no `$$` handling — swapping in the canonical pattern breaks flow-style YAML for
  `$${y}` and `${a[${i}].x}`), `core/ir_schema.py` (jsonschema pattern strings). The allowlist describes the post-task
  state: it holds only once the other in-tree `\$\{` regexes (`markdown_parser._CACHE_TEMPLATE_RE`,
  `graph/scope._BRACE_BLOCK_RE`, `graph/renderers/mermaid.py`, `type_validation._QUOTED_TEMPLATE_PATTERN`,
  the validator's permissive patterns) have moved into `core/templates`. The web UI's
  TypeScript mirrors are outside the scan's scope by construction.
- **The validator's "own structure-walk" is one walk with one operand classifier**
  (field-checkable / root-only / skip) that every validation pass consumes. Before this task
  at least six passes each decided for themselves which operands to check, and at least two
  of them disagreed on `??` operands (Pass 5 path validation skips multi-operand `??`
  operands; Pass 8 batch-item validation field-checks them) — policy drift *between* validator passes is a drift class the
  shared AST and shared rules do not cover by themselves.
- **Parity is two-directional.** Besides "runtime resolves ⟹ no validator ERROR", the corpus
  pins the converse: "no validator ERROR ⟹ every unescaped `${` the validator treats as a
  template is routed by the runtime and either resolves or is reported unresolved". The
  silent class this task was reviewed against lives in the converse (a permissive-grammar
  match that the strict grammar rejects was routed as a static param and reached the node as
  literal text).

Footnote: the malformed-template false-positive fix cited above as 8535ed9b actually landed,
code and regression test, in its parent 4516cd72; 8535ed9b only names it in its message.
