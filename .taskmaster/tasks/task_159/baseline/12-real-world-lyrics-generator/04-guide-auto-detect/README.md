# 04 — `pflow guide` auto-detection on lyrics-generator (FINDING)

**Surface**: 12-real-world-lyrics-generator

**Triggers**: `pflow guide <workflow-path>` should auto-detect topics
relevant to the workflow tree.

**Observed behavior** — manually verified during baseline construction:

The lyrics-generator parent workflow uses cache heavily THROUGH SUB-WORKFLOWS
(`song-creator.pflow.md` declares the `## Cache` block; the parent doesn't).
`pflow guide ./lyrics-generator.pflow.md` does NOT include the `caching`
topic in its output, even though 8 nodes across the tree use `prompt_cache:`.

`pflow guide ./song-creator/song-creator.pflow.md` (run directly on the
sub-workflow that has `## Cache`) ALSO does not surface the caching topic.
Only `batch`, `code`, `llm`, `sub-workflows` are detected.

**This is a finding.** Documented as F-03 in FINDINGS.md.

**Why this case matters**: agents working on a real cache-using workflow
ask `pflow guide` for relevant docs. They don't get the caching guide. The
auto-detect doesn't recurse into sub-workflows for topic detection AND
doesn't trigger on the `## Cache` / `prompt_cache:` keywords inside the
workflow body. Agents have to know to ask for `pflow guide caching`
explicitly.

**Mutation contract**: this case captures the *current* output. If a
future change adds caching to the auto-detect, this case fails — we'd
update the expected output and ship the fix. If a future change drops
another detected topic that IS present, this case fails — preventing
silent regression of `batch` / `llm` detection on workflows that use them.
