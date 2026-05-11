# 05 — Batch-scoped `${item.X}` reference in cache (ADV)

**Surface**: 01-parser-errors

**Triggers**: A `## Cache` chunk references `${item.text}`. The `${item.X}`
namespace is batch-scoped — its value differs per call. Caching such a chunk
defeats the premise (every call would write a different prefix).

**Expected behavior**: Parse Error or validator error; non-zero exit. The
error must explain why batch-scoped references can't be cached.

**Mutation contract**: if batch-scoped refs are silently accepted, every batch
call writes its own cache entry — pure cost overhead with zero read benefit.
The whole batch-prewarm rationale becomes incoherent.
