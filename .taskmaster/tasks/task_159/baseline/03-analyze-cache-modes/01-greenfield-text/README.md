# 01 — Greenfield mode (text)

**Triggers**: Workflow has 3 LLM nodes sharing `${article}` but no `## Cache`
declared.

**Expected**: `cache.shared-context-undeclared` info; suggested ## Cache block
with `<DESCRIBE...>` placeholders.

**Mutation contract**: if the shared-context detector regresses, an author who
hasn't yet declared `## Cache` gets no signal — the whole greenfield
suggestion path silently breaks.
