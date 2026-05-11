# 01 — Empty cache block

**Surface**: 01-parser-errors

**Triggers**: `## Cache` section with a tagged ```cache code block that contains
no `${var}` reference.

**Expected behavior**: `pflow run` exits non-zero with a Parse Error diagnostic.
The error names `## Cache`, says "must contain at least one `${var}` reference",
cites the source line, and shows a paste-ready cache block as the fix hint.

**Mutation contract**: if the parser silently accepts an empty cache block (e.g.
the "≥1 var" check is removed), this case fails because the workflow proceeds
past parsing and either (a) the workflow runs (worst — silent accept), or
(b) a different downstream error fires (still wrong — message lies about cause).
