# 03 — Two `${var}` references in single line of cache prose (FINDING)

**Surface**: 01-parser-errors (uses analyze-cache surface to avoid runtime LLM)

**Triggers**: A cache block contains a single line `The article ${article} is
about ${topic}.` with two `${var}` refs separated by prose. Spec
(task-159.md "## Cache Block Parsing") says **"Two or more `${var}` in a chunk
is a syntax error."**

**Observed behavior**: The parser silently SPLITS the line into two valid chunks
(`article` and `topic`), each with one var. No syntax error is raised. The
workflow parses successfully and `pflow analyze-cache` produces a normal
report.

**Whether this is a bug**: depends on interpretation. The chunking algorithm
defines a chunk as `[prose-before-var, ${var}]` — by construction every chunk
has exactly one var, so the spec's "two vars in a chunk" error is impossible
to reach from a `.pflow.md` file. The spec wording is misleading at minimum.
Logged as `FINDINGS.md` entry for Andreas to triage.

**Mutation contract**: this case locks the *current* behavior. If Task 160
changes chunking and starts rejecting two-vars-on-one-line, this case fails.
Likewise if the parser starts producing different chunk identifiers.
