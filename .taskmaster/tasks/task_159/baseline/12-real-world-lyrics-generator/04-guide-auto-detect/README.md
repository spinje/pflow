# 04 — `pflow guide` auto-detection on lyrics-generator (F-03 RESOLVED)

**Surface**: 12-real-world-lyrics-generator

**Triggers**: `pflow guide <workflow-path>` should auto-detect topics
relevant to the workflow tree.

**Current behavior** — `pflow guide ./lyrics-generator.pflow.md` now
includes the `caching` topic. Detection looks for `ir["cache"]`,
`node["prompt_cache"]`, and `node["prewarm"]` on the parsed IR, AND walks
into sub-workflow files via `resolve_sub_workflow` so a parent that
dispatches to children with caching declarations still surfaces it.

**F-03 fix landed**: `src/pflow/guide/__init__.py` — `detect_topics_from_ir`
checks the three caching signals; `_topics_from_workflow_file` recurses
through `workflow:` nodes via `_collect_topics`. Saved-name CLI form
(`pflow guide my-saved-workflow`) routes through the same walker.

**Mutation contract**: this case now locks the FIXED behavior.
- If a future change loses caching detection on the parent → case fails
  (regression of F-03 fix).
- If a future change loses sub-workflow recursion → case fails (caching
  comes only from the song-creator child, which is reached only via
  recursion).
- If a future change drops another detected topic (batch / llm / etc.) →
  case fails, preventing silent regression of unrelated detection paths.
