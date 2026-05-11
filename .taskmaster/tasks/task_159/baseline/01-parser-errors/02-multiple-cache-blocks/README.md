# 02 — Multiple cache blocks

**Surface**: 01-parser-errors

**Triggers**: A `## Cache` section that contains two ```cache fenced code
blocks. Spec says exactly one is allowed.

**Expected behavior**: Parse Error citing the duplicate block; non-zero exit.

**Mutation contract**: if the parser concatenates the second block silently,
this case fails because the workflow proceeds — and the bytes shipped to the
LLM diverge from what the author wrote, the highest-stakes class of bug for a
caching surface.
