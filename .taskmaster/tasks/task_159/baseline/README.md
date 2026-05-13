# Task 159 Baseline — Index

**75 runnable cases** captured across 11 surfaces (01–06, 10, 12–15).
`PLAN.md`, `RECORDING.md`, and the audit files are historical context; the
filesystem plus `./verify.sh` are the current source of truth. Read
[PLAN.md](./PLAN.md) for the original strategy and [FINDINGS.md](./FINDINGS.md)
for the initial construction findings.

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
| Surface 04 — warning catalog (26 cases: 24 IDs + subpath/text variants) | ✅ done; 23/26 trigger target ID; 3 non-trigger cases intentionally lock current silence |
| Surface 05 — advisory cases (5 cases) | ✅ done |
| **Surface 06 — dry-run nudge (3 cases)** | ✅ done; positive nudge, optimal silence, and structural cache error |
| **Surface 10 — live recordings (2 cases)** | ✅ partial; Gemini translation + real lyrics-generator trace committed |
| **Surface 12 — real-world lyrics-generator (5 cases)** | ✅ done; 3 findings (F-03, F-04, F-05) |
| **Surface 13 — happy-path interactions (4 cases)** | ✅ done |
| **Surface 14 — Pitfall #19 defenses (3 cases)** | ✅ done |
| **Surface 15 — run flag interactions (5 cases)** | ✅ done; `--only`, `--report`, partial traces, and dry-run/report conflict |
| Surface 07 — hash invariants | ⏭ TODO |
| Surface 08 — `--no-cache` flag | ⏭ TODO |
| Surface 09 — `--help` and guide | ⏭ TODO |
| Surface 11 — end-to-end UX | ⏭ partially covered by Surface 03 (`examples/core/prompt-caching.pflow.md` text/json/all-rows); remaining variants optional |

> **Note on numbering**: surfaces 12–15 were added AFTER 01–05 because the
> Task 159 review surfaced their need (real-world integration, happy-path
> interactions, Pitfall #19 defenses, and run-flag/report interactions — all
> critical, none in the original PLAN). Surfaces 07–09 remain optional
> follow-up work. Surface 11's highest-value reference-example analysis cases
> are already covered by Surface 03; surface 10 is partially complete despite the older
> RECORDING.md wording.

> **Out of scope**: trace format 2.0.0 backcompat. The user has confirmed
> we don't need to test for old traces. The 2.0.0 stripped fixture was
> removed from `_shared/fixtures/`.

## Layout

```
baseline/
├── PLAN.md                         # full strategy
├── README.md                       # this file
├── FINDINGS.md                     # allready fixed previous findings
├── RECORDING.md                    # how to record live API cases
├── normalize.py                    # redaction script
├── run-case.sh                     # per-case runner (write/diff)
├── regenerate.sh                   # top-level write
├── verify.sh                       # top-level diff
├── .gitignore                      # ignores .run-home, .raw-*
├── _shared/
│   ├── fixtures/
│   │   ├── sample-2.1.0-trace.json          # real recorded trace (2.1.0)
│   │   ├── live-gemini-translation.trace.json
│   │   └── live-gemini-lyrics-generator.trace.json
│   ├── workflows/
│   │   ├── smoke-with-cache.pflow.md        # source workflow for the trace fixture
│   │   └── lyrics-generator/                # real Task 159 motivating workflow tree (17 .pflow.md files)
│   └── long-stable-text.txt                 # ~30k-char stable text for threshold-clearing inputs
├── 01-parser-errors/                  (10 cases)
├── 02-validator-errors/               (8 cases)
├── 03-analyze-cache-modes/            (8 cases)
├── 04-warning-catalog/                (26 cases)
├── 05-advisory-cases/                 (5 cases)
├── 06-dry-run-nudge/                  (3 cases)
├── 10-live-recordings/                (2 cases)
├── 12-real-world-lyrics-generator/    (5 cases)
├── 13-happy-path-interactions/        (4 cases)
├── 14-pitfall-19-defenses/            (3 cases)
└── 15-run-flag-interactions/          (5 cases)
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

`03-steady-state-text`, `04-steady-state-json`, and `08-all-rows-flag` run
`examples/core/prompt-caching.pflow.md` directly. These cover the original
Surface 11 reference-example text/json/all-rows scenarios without duplicating
cases. The remaining original Surface 11 variants (`with-fixture-trace` and
example dry-run footer) are optional because trace mode is covered by Surface
03/10 and dry-run behavior is covered by Surface 06.

### Surface 04 — Warning catalog (26/26 cases captured; 23 trigger target ID)

| # | ID | Triggered |
|---|---|---|
| 01 | cache.order-mismatch | ✓ |
| 02 | cache.unused-chunk | ✓ |
| 03 | cache.invalid-on-non-llm | ✓ |
| 04 | cache.shared-context-undeclared | ✓ |
| 05 | cache.sub-workflow-cache-undeclared | ✓ |
| 05b | cache.sub-workflow-cache-undeclared-subpath | ✓ |
| 06 | cache.batch-prewarm-recommended | ⏭ (intentional silence fixture) |
| 07 | cache.dynamic-before-static | ⏭ (intentional silence fixture) |
| 08 | cache.padding-advisory | ✓ |
| 09 | cache.below-min-tokens | ✓ |
| 10 | cache.cross-workflow-prose-mismatch | ✓ |
| 11 | cache.cross-workflow-rename-detected | ✓ |
| 12 | cache.discrepancy | ✓ |
| 13 | cache.prewarm-no-prefix | ✓ |
| 14 | cache.consolidate-to-root-recommended | ✓ |
| 15 | cache.heterogeneous-models-fragment-cache | ✓ |
| 16 | cache.first-call-write-penalty | ✓ |
| 17 | cache.opaque-prompt | ✓ |
| 18 | cache.prompt-body-duplicates-cache | ✓ |
| 19 | cache.prompt-body-shadows-cache | ⏭ (intentional silence fixture — fires duplicates instead) |
| 20 | llm.thinking-temperature-mismatch | ✓ |
| 21 | cache.prompt-cache-incomplete | ✓ |
| 22 | cache.batch-prewarm-below-min | ✓ |
| 23 | cache.batch-prewarm-lower-bound-recommended | ✓ |
| 23b | cache.batch-prewarm-lower-bound-recommended-text | ✓ |
| 24 | cache.shared-context-undeclared-conditional | ✓ |

The 3 untriggered cases STILL serve as regression gates: they capture the
analyzer's current output on the fixture; if a code change makes one of these
IDs start firing on the existing fixture, the case fails, surfacing the
behavior change for review.

### Surface 05 — Advisory (5/5 pass)

01-prewarm-savings-below-5pct-silent (silence captured) ·
02-prewarm-explicit-false-suppresses-warning (silence captured) ·
03-prewarm-explicit-true-no-warning (silence captured) ·
04-model-fragmentation-with-write-penalty (co-emission captured) ·
05-cost-projection-excludes-heterogeneous-cohort (cohort exclusions captured)

### Surface 06 — Dry-run nudge (3/3 pass)

01-actionable-shared-context-nudge (`--dry-run` emits
`cache.opportunities-available`) ·
02-optimal-workflow-silent (already optimal workflows stay quiet) ·
03-structural-cache-error-blocks (`cache.order-mismatch` blocks dry-run before
planning)

### Surface 10 — Live recordings (2/2 pass)

03-gemini-translation · 05-gemini-lyrics-generator

These are committed trace fixtures; verify mode does not call live providers.
`05-gemini-lyrics-generator` is the load-bearing real trace for the motivating
17-file workflow.

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

### Surface 15 — Run flag interactions (5/5 pass)

01-partial-trace-analyze-cache (truncated trace executed-subset framing) ·
02-report-cache-telemetry (`## Cached System` + `## Cache telemetry`) ·
03-report-with-only (`--report --only` snapshot + target path) ·
04-dry-run-report-conflict (hard error) ·
05-print-only-mode-signal (`-p --only` keeps mode signal)

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

## Personal-eyes review note

I (the implementing agent for Phase 0 + surfaces 01-05) read
≥10 expected-stdout.txt files before declaring done. JSON parses cleanly,
text formatting holds, error messages are agent-actionable with file:line
citations, warning IDs match the catalog. The structural integrity of the
captured outputs is sound; the F-02 misses are about trigger-condition
subtlety, not output quality.
