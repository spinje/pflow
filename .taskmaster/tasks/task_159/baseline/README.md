# Task 159 Baseline — Index

**63 cases** captured across 8 surfaces (01–05 + 12–14). Read
[PLAN.md](./PLAN.md) for the full strategy and [FINDINGS.md](./FINDINGS.md)
for the **5 findings** (1 spec-vs-impl mismatch, 2 agent-UX issues, 1 false-
positive on greenfield analysis, 1 visualize/validate coupling) surfaced
during baseline construction.

## How to use this folder

```bash
# Re-run every case and write expected-* files (use after intentional behavior changes)
./regenerate.sh

# Re-run every case and DIFF against committed expected-* files (regression oracle)
./verify.sh

# Run a single surface or single case
./regenerate.sh 04-warning-catalog
./verify.sh 04-warning-catalog/01-cache.order-mismatch
```

`verify.sh` exit codes: 0 = all clean, 1 = drift, 2 = harness error.

## Status — what the implementing agent for surfaces 06+ inherits

| Phase | Status |
|---|---|
| Phase 0 — infrastructure (normalize.py, run-case.sh, regenerate.sh, verify.sh, .gitignore) | ✅ done |
| Surface 01 — parser errors (10 cases) | ✅ done; 1 finding (F-01) |
| Surface 02 — validator errors (8 cases) | ✅ done |
| Surface 03 — analyze-cache modes (8 cases, compressed from 17) | ✅ done |
| Surface 04 — warning catalog (20 cases, one per ID) | ✅ done; 15/20 trigger target ID; 5 documented in F-02 as TODOs |
| Surface 05 — advisory cases (5 cases) | ✅ done |
| **Surface 12 — real-world lyrics-generator (5 cases)** | ✅ done; 3 findings (F-03, F-04, F-05) |
| **Surface 13 — happy-path interactions (4 cases)** | ✅ done |
| **Surface 14 — Pitfall #19 defenses (3 cases)** | ✅ done |
| Surface 06 — dry-run nudge | ⏭ TODO (continue from PLAN.md §6.F) |
| Surface 07 — hash invariants | ⏭ TODO |
| Surface 08 — `--no-cache` flag | ⏭ TODO |
| Surface 09 — `--help` and guide | ⏭ TODO |
| Surface 10 — live recordings | ⏭ TODO (see RECORDING.md) |
| Surface 11 — end-to-end UX | ⏭ TODO |

> **Note on numbering**: surfaces 12–14 were added AFTER 01–05 because the
> Task 159 review surfaced their need (real-world integration, happy-path
> interactions, Pitfall #19 defenses — all critical, none in the original
> PLAN). The next agent should still build 06–11 from PLAN.md §6.F onward.
> Numbering preserves planned topology; chronology is in the git log.

> **Out of scope**: trace format 2.0.0 backcompat. The user has confirmed
> we don't need to test for old traces. The 2.0.0 stripped fixture was
> removed from `_shared/fixtures/`.

## Layout

```
baseline/
├── PLAN.md                         # full strategy
├── README.md                       # this file
├── FINDINGS.md                     # verification-specialist findings
├── RECORDING.md                    # how to record live API cases
├── normalize.py                    # redaction script
├── run-case.sh                     # per-case runner (write/diff)
├── regenerate.sh                   # top-level write
├── verify.sh                       # top-level diff
├── .gitignore                      # ignores .run-home, .raw-*
├── _shared/
│   ├── fixtures/
│   │   └── sample-2.1.0-trace.json          # real recorded trace (2.1.0)
│   ├── workflows/
│   │   ├── smoke-with-cache.pflow.md        # source workflow for the trace fixture
│   │   └── lyrics-generator/                # real Task 159 motivating workflow tree (17 .pflow.md files)
│   └── long-stable-text.txt                 # ~30k-char stable text for threshold-clearing inputs
├── 01-parser-errors/                  (10 cases)
├── 02-validator-errors/               (8 cases)
├── 03-analyze-cache-modes/            (8 cases)
├── 04-warning-catalog/                (20 cases)
├── 05-advisory-cases/                 (5 cases)
├── 12-real-world-lyrics-generator/    (5 cases)
├── 13-happy-path-interactions/        (4 cases)
└── 14-pitfall-19-defenses/            (3 cases)
```

## Coverage summary

### Surface 01 — Parser errors (10/10 pass)

01-empty-cache-block · 02-multiple-cache-blocks · 03-two-vars-in-chunk (FINDING F-01) ·
04-duplicate-chunk-id · 05-batch-scoped-ref · 06-invalid-ttl-30m · 07-unresolved-var ·
08-prose-only-no-vars · 09-prompt-body-shadows-cache · 10-crlf-line-endings

### Surface 02 — Validator errors (8/8 pass)

01-prompt-cache-out-of-order · 02-prompt-cache-undeclared-name ·
03-prompt-cache-on-shell-node · 04-prompt-cache-empty-list ·
05-subworkflow-references-parent-chunk · 06-cache-content-below-min-tokens ·
07-unused-chunk · 08-analyze-cache-surfaces-undeclared-name

### Surface 03 — analyze-cache modes (8/8 pass)

01-greenfield-text · 02-greenfield-json · 03-steady-state-text ·
04-steady-state-json · 05-trace-from-trace · 06-no-trace-autoload ·
07-json-error-envelope-unknown-workflow · 08-all-rows-flag

### Surface 04 — Warning catalog (20/20 cases captured; 15 trigger target ID)

| # | ID | Triggered |
|---|---|---|
| 01 | cache.order-mismatch | ✓ |
| 02 | cache.unused-chunk | ✓ |
| 03 | cache.invalid-on-non-llm | ✓ |
| 04 | cache.shared-context-undeclared | ✓ |
| 05 | cache.sub-workflow-cache-undeclared | ✓ |
| 06 | cache.batch-prewarm-recommended | ⏭ (F-02 TODO) |
| 07 | cache.dynamic-before-static | ⏭ (F-02 TODO) |
| 08 | cache.padding-advisory | ⏭ (F-02 TODO) |
| 09 | cache.below-min-tokens | ✓ |
| 10 | cache.cross-workflow-prose-mismatch | ✓ |
| 11 | cache.cross-workflow-rename-detected | ✓ |
| 12 | cache.discrepancy | ⏭ (F-02 TODO — needs trace) |
| 13 | cache.prewarm-no-prefix | ✓ |
| 14 | cache.consolidate-to-root-recommended | ⏭ (F-02 TODO) |
| 15 | cache.heterogeneous-models-fragment-cache | ✓ |
| 16 | cache.first-call-write-penalty | ✓ |
| 17 | cache.opaque-prompt | ✓ |
| 18 | cache.prompt-body-duplicates-cache | ✓ |
| 19 | cache.prompt-body-shadows-cache | ⏭ (F-02 TODO — fires duplicates instead) |
| 20 | llm.thinking-temperature-mismatch | ✓ |

The 5 untriggered cases STILL serve as regression gates: they capture the
analyzer's current output on the fixture; if a code change makes one of these
IDs start firing on the existing fixture, the case fails, surfacing the
behavior change for review.

### Surface 05 — Advisory (5/5 pass)

01-prewarm-savings-below-5pct-silent (silence captured) ·
02-prewarm-explicit-false-suppresses-warning (silence captured) ·
03-prewarm-explicit-true-no-warning (silence captured) ·
04-model-fragmentation-with-write-penalty (co-emission captured) ·
05-cost-projection-excludes-heterogeneous-cohort (cohort exclusions captured)

### Surface 12 — Real-world lyrics-generator (5/5 pass)

01-analyze-cache-text · 02-analyze-cache-json · 03-analyze-cache-song-creator-text ·
04-guide-auto-detect (locks F-03) · 05-visualize-mermaid (song-creator after F-05)

The real lyrics-generator workflow (17 .pflow.md files, 25 LLM nodes
across 15 sub-workflows, 3-level nesting, ~181 LLM calls/run) is the
canonical "does it work at scale" baseline. Catches integration bugs that
minimal fixtures can't.

### Surface 13 — Happy-path interactions (4/4 pass)

01-batch-cache-prewarm-happy (no warnings — already optimal) ·
02-subworkflow-with-own-cache (no warnings — properly declared) ·
03-three-level-nesting (cross-workflow walker traverses 3 levels) ·
04-parallel-batch-with-cache (parallel batch with prompt_cache attribution)

These were absent from PLAN.md but added after task-review.md surfaced
that the original plan had only error-case batch/sub-workflow tests.

### Surface 14 — Pitfall #19 defenses (3/3 pass)

01-dotted-path-chunk (Bug #2 vector — `${node.response}` through
NamespacedSharedStore proxy) ·
02-multi-segment-dotted-path (deeper through-dict nesting) ·
03-file-resolved-system-prompt (Path 1 boundary contract — `prompt:
./file.md` resolves to file content not filename string)

## Conventions

- **Each case folder contains**: `README.md` (what + mutation contract),
  `workflow.pflow.md` (or `fixture/`), `command.sh`, `expected-stdout.txt`,
  `expected-stderr.txt`, `expected-exit-code.txt`. Optional sub-workflow files
  under `sub/`.
- **Commands run with `HOME=$BASELINE_CASE_DIR/.run-home`** for filesystem
  isolation. `pflow` uses `Path.home()` everywhere; HOME redirect is
  necessary and sufficient.
- **Normalization** redacts: timestamps, paths, MD5 hashes, jittery cost
  dollars, `cache_age_sec`, durations. Warning IDs, severity levels, JSON
  key ordering, and section ordering are NEVER normalized — those are the
  contract.
- **Never blanket-normalize `\$\d+\.\d+`**. Cost regressions in Task 160 are
  exactly what the baseline must catch.
- **The mutation contract** in each case's README is the test's reason for
  existing. If you can't articulate what production-code change would make
  the case fail, the case is decorative — drop or rewrite.

## Adding new cases (for surfaces 06+)

```bash
mkdir baseline/06-new-surface/01-foo
cd baseline/06-new-surface/01-foo
cat > workflow.pflow.md << 'EOF'
# minimal triggering workflow
...
EOF
cat > command.sh << 'EOF'
#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --no-trace-autoload --format=json
EOF
chmod +x command.sh
cat > README.md << 'EOF'
# 01 — foo
**Triggers**: ...
**Expected**: ...
**Mutation contract**: ...
EOF
../../run-case.sh "$(pwd)" --write
# inspect expected-stdout.txt to verify
../../run-case.sh "$(pwd)" --diff   # should be clean
```

## Found issues during baseline construction

See [FINDINGS.md](./FINDINGS.md):
- **F-01**: Parser silently splits two `${var}` on one line into two chunks
  rather than rejecting per spec. Spec-vs-impl mismatch.
- **F-02**: 5 catalog warning IDs need more elaborate fixtures than minimal
  patterns. The case folders are populated; trigger conditions left as TODOs.
- **F-03**: `pflow guide <workflow>` auto-detect misses `caching` topic on
  cache-using workflows. Affects every agent onboarding to a cache-using
  project.
- **F-04**: `cache.below-min-tokens` false-positive on greenfield analysis
  when chunks resolve to LLM responses (analyzer can't measure node-output
  token sizes without run history). Wastes agent time before first run.
- **F-05**: `pflow visualize` validates before rendering, blocking on
  unrelated unknown-node-types (e.g., user-configured MCP servers in
  sub-workflows). Workaround: visualize the LLM-only sub-workflow.

## Personal-eyes review note

I (the implementing agent for Phase 0 + surfaces 01-05) read
≥10 expected-stdout.txt files before declaring done. JSON parses cleanly,
text formatting holds, error messages are agent-actionable with file:line
citations, warning IDs match the catalog. The structural integrity of the
captured outputs is sound; the F-02 misses are about trigger-condition
subtlety, not output quality.
