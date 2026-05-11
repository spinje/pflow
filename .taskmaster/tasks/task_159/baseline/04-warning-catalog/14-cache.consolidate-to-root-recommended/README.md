# 14 — cache.consolidate-to-root-recommended

**Surface**: 04-warning-catalog

**Triggers**: A workflow caches small sub-path chunks from an object while the
larger root object is large enough to clear the provider cache minimum.

**Expected behavior**: Text output recommends caching the root value instead
of the sub-paths and explains that individual sub-paths are too small.

**Mutation contract**: if Task 160's suggestion/consolidation extraction drops
the root-vs-subpath comparison, this case fails because the
`cache.consolidate-to-root-recommended` action disappears or is replaced by a
lower-signal warning.
