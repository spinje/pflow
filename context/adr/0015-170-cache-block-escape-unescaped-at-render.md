# `$${…}` in a `## Cache` block is honoured and unescaped at render, by one helper both the hash and the prepare site call

Status: accepted

Context: the `$${…}` escape yields a literal `${…}` in every template-bearing value since
#620 (PR #632), but `## Cache` prose is chunked by its own regex (`core/markdown_parser.py`
`_CACHE_TEMPLATE_RE`, no `$$` lookbehind, looser than the canonical grammar) and then
concatenated verbatim as `prose_before + value` at the hash site
(`runtime/engine/plan_node.py::_render_cache_for_hash`) and the prepare site
(`core/prompt_cache.py::build_cache_system_blocks`, reached from the LLM node and from the
batch prewarm path) — no layer unescapes it. Today `$${name}` is split as chunk `name` with a
stray `$` left in the preceding prose: a validation error when `name` is not a declared
reference (`$${HOME}`), and a **silent mis-render** when it is (`$${topic}` validates and
sends `$` + the value). Cache prose is special because hash and prepare must see identical
bytes per chunk (B3.3 hash/prep byte-equivalence, `prompt_cache.deterministic_serialize`
docstring; pinned by `test_prompt_cache_rendering.py::test_hash_render_and_prep_render_byte_equivalent_*`),
and chunk *names* are the raw source text between `${` and `}` that `prompt_cache:` lists
refer to.

Decision (Task 170, 2026-09-28): the escape is honoured in cache prose like everywhere else
(the chunk regex skips it) and unescaped at render time by **one helper that both the hash
site and the prepare site call**, so byte symmetry is structural rather than a two-site
convention. `CacheChunkIR.prose_before` stays escaped: it is re-emitted as *template text*
by graph build (`core/workflow/graph/build.py` `cached_prefix`), where a literal `${HOME}`
would be indistinguishable from a template. Chunk names keep being sliced from source spans,
never re-rendered from the parsed structure.

Considered and rejected: keeping `$${` verbatim in cache prose as a documented exception
(the docs promise "whatever follows `$${` is left alone", and one surface behaving
differently is the drift class this task exists to end); keeping today's behaviour (the
silent mis-render above); unescaping once at IR construction (breaks the `cached_prefix`
re-emission).

Consequence: a workflow containing `$${` inside a `## Cache` block changes behaviour — the
escaped span stops being a chunk, so a `prompt_cache:` list naming it becomes an
undeclared-chunk error, a block left with no `${var}` fails to parse, and later chunks'
`prose_before` (hence their cache key) changes. None exist in-tree at decision time; the
change is Task 170's one sanctioned cache-key delta and is recorded in its phase-1 corpus.
