# 01 — analyze-cache on real lyrics-generator (text)

**Surface**: 12-real-world-lyrics-generator

**Triggers**: Runs `pflow analyze-cache` against the real Task 159 motivating
workflow (committed snapshot at
`_shared/workflows/lyrics-generator/lyrics-generator.pflow.md`). 17 .pflow.md
files, 25 LLM nodes across 15 sub-workflows, ~181 LLM calls per run, 3-level
nesting (parent → song-creator → chorus-chooser).

**Expected**: text-mode report that:
- Walks all 15 sub-workflows.
- Reports cost projection partials (`(partial)` labels because the workflow
  uses sub-workflow file refs that resolve correctly).
- Emits cross-workflow rename detection
  (`creative-direction.response` ↔ `creative_direction`).
- Emits opaque-prompt warning on chorus-chooser's `generate-chorus-options`
  (prompt is `${item.prompt}` from a code node).
- Emits sub-workflow-cache-undeclared on chorus-chooser.
- Emits per-node below-min-tokens warnings for chunks that resolve to LLM
  responses (analyzer estimates these as small literals because there's no
  run history — see F-04 in FINDINGS.md).

**Why this case is load-bearing**: this is the integration test the minimal
fixtures can't substitute for. ONE run that walks 15 sub-workflows + multi-
level nesting + heterogeneous batch + cross-workflow rename + opaque-prompt
detection + per-node threshold warnings exercises every analyzer pathway
that the spec promises. If the analyzer scales poorly to N=181 calls / 17
files / 3-level nesting, this case catches it. If sub-workflow walking
regresses, this case catches it. If cross-workflow rename detection
regresses, this case catches it.

**Mutation contract**: any mutation that breaks sub-workflow walking,
cross-workflow rename detection, opaque-prompt detection, OR cost
projection cohort logic across mixed priced/unpriced models will visibly
shift this output.
