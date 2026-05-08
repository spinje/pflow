# 01 — Dotted-path cache chunk via NamespacedSharedStore proxy (Bug #2)

**Surface**: 14-pitfall-19-defenses

**Triggers**: A `## Cache` chunk references `${produce.response}` (dotted
path — node-id + field). At runtime this resolves through the
`NamespacedSharedStore` proxy. Two downstream LLM nodes opt into the
chunk via `prompt_cache: [produce.response]`.

**Why this is the Bug #2 regression vector** — per task-review.md:

> `NamespacedSharedStore` was duck-typed but not type-tagged. It implemented
> dict-like methods but didn't inherit `dict` or any ABC.
> `TemplateResolver._get_dict_value` did `isinstance(value, dict)` → False
> → silent template echo → `_resolve_chunk_value`'s permissive-echo branch
> fired → `_CHUNK_ABSENT` → cache rendering silently dropped every
> dotted-path chunk in production. Pure-greenfield smoke tests didn't catch
> it because synthetic fixtures used raw dicts.

**Expected**: `consume-1` and `consume-2` per_call rows show the chunk
correctly attributed in `declared_prompt_cache: ["produce.response"]` and
the cacheable_tokens > 0. If the proxy/dotted-path path silently drops
the chunk, both rows would show `cacheable_tokens: 0` AND
`cacheable_data_source: unavailable`.

**Mutation contract**: revert `NamespacedSharedStore` to a non-`Mapping`
class, OR change `TemplateResolver._get_dict_value` back to
`isinstance(value, dict)`, AND this case fails because chunks render as
absent.

This case complements `test_hash_render_and_prep_render_byte_equivalent_through_namespaced_store`
in the unit test suite; it covers the user-visible analyzer surface.
