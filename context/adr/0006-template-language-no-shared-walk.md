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
