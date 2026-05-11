# 02 — Multi-segment dotted path (Pitfall #19)

**Surface**: 14-pitfall-19-defenses

**Triggers**: Cache chunks reference deeper paths through a dict —
`${concept.core_idea}` (1 segment past root) and `${concept.details.body}`
(2 segments past root). Tests the `_get_dict_value` recursion through
NamespacedSharedStore on multi-segment paths.

**Why this complements case 01**: case 01 tests single-segment dotted
paths (`${node.response}`). This case tests multi-segment paths through
nested dicts. A regression that affects only deep-nested resolution would
miss case 01 but trip here.

**Expected**: both chunks render correctly with cacheable_tokens > 0.
`writer` per_call row shows
`declared_prompt_cache: ["concept.core_idea", "concept.details.body"]`.

**Mutation contract**: any regression in multi-segment dict resolution
(e.g., `TemplateResolver._get_dict_value` recursing one level only)
manifests here. Single-segment resolution (case 01) would still pass,
making this case's signal load-bearing for the deeper-nested pattern.
