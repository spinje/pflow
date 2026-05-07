# Task 159 Fix Brief 05 — Recommendation Actionability, Scope, and Copy/Paste Syntax

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`

## Purpose

This brief captures what is known about analyzer recommendations that may not
be safe for an agent to copy or act on directly.

The next agent's job is to research the current code deeply, reproduce the
current behavior, and discuss material design choices with the user before
implementing. Do not treat this as a mechanical patch list. The right outcome is
a simple final contract future agents can trust:

- if analyzer output gives an edit, the edit should be actionable;
- if it gives syntax, the syntax should be exact pflow syntax;
- if it names a target, the target workflow/file should be unambiguous.

There are no shipped users of `analyze-cache`. Compatibility with current
branch-only analyzer JSON/text is not a constraint. Prefer clear, correct
semantics over preserving misleading current output.

## Findings Covered

Primary:

- Final verification Finding 5: music `chorus-chooser` analyzer recommends a
  cache block that cannot provider-cache.
- Final verification Finding 10: `cache.sub-workflow-cache-undeclared`
  suggestion wording uses `$shared_doc` instead of `${shared_doc}`.
- Final verification Finding 11: `analyze-cache` JSON can lose workflow identity
  and use `scope_workflow: "<unknown>"`.

Related but covered elsewhere:

- Brief 01 covers the cost/savings semantics overlap of below-threshold
  suggestions.
- Brief 02 covers evidence scope and partial/dynamic trace truth.
- Brief 04 covers CLI stdout/exit-code contracts.

This brief is about the **actionability contract** for recommendations.

## Plain-Language Problem

Analyzer recommendations are not just commentary. Agents use them as edit
guidance.

Three verification findings point at copy/paste trust problems:

1. The analyzer can recommend adding a `## Cache` block, then say the proposed
   cache content is below the provider token threshold and will not fire.
2. A sub-workflow cache recommendation can use `$shared_doc` wording even though
   pflow template syntax is `${shared_doc}`.
3. JSON can report `scope_workflow: "<unknown>"` even when the workflow file is
   known.

The shared problem:

> If a recommendation is not actionable, syntactically correct, and scoped to
> the right workflow, it should not be presented as a normal recommended edit.

This does not mean every uncertain opportunity must disappear. It may be useful
to tell an agent "shared context exists, but no provider-cache edit is
actionable yet." The key is to distinguish advisory explanation from concrete
copy/paste edit instructions.

## Current Verification Status

### Finding 5 May Be Partially Fixed or Input-Dependent

The final verification report observed:

```text
Shared context undeclared — declare `concept.core_idea` in ## Cache
...
## Cache
${concept.core_idea}
...
threshold: 25 tokens / 4096 (anthropic/claude-haiku-4-5) BELOW THRESHOLD — cache will not fire as suggested
```

Current worktree behavior was rechecked on 2026-05-07.

With sandbox HOME and **no default model resolved**, the analyzer still emits a
suggested block for `concept.core_idea`, but threshold evidence is unavailable:

```text
3 LLM nodes, invocation count unavailable (2 dynamic batch nodes) (no model resolved — set settings.default_model)
...
1. Shared context undeclared — declare `concept.core_idea` in ## Cache
...
### score-choruses
- prompt_cache: [concept.core_idea]
- threshold: unable to estimate (no run data; first run will populate)
```

After setting the default model to `anthropic/claude-haiku-4-5`, the same
current worktree suppresses the suggested block and emits a note:

```text
1 opportunity (0 warnings, 1 info)
...
Prompt opaque to static analysis on generate-chorus-options ...
...
Notes
  · Suggested-blocks: shared refs were found, but every assigned LLM node is below
    the provider cache threshold under current model/token evidence; no
    provider-cache edit is actionable yet.
```

Trust boundary:

- Verified: current code has an all-below-threshold suppression path that works
  when threshold evidence is definitive.
- Verified: when no model is resolved, current code still emits a suggested
  block with threshold "unable to estimate."
- Not yet decided: whether "unable to estimate" should allow a concrete
  suggested edit, or whether it should render as a non-actionable advisory until
  model/token evidence exists.
- Do not assume the final report's exact Finding 5 output still reproduces in
  the current worktree without matching model/settings context.

### Finding 10 Still Needs Direct Reproduction

The final report says a child sub-workflow cache recommendation uses
`$shared_doc` instead of `${shared_doc}`.

Local code orientation found the catalog suggestion template currently says:

```python
"In {child_workflow}, add a ## Cache chunk for `${child_input_name}`."
"Add `{child_input_name}` to `prompt_cache:` on the child LLM nodes that reuse it."
```

This first sentence renders backticks around `$` + `{child_input_name}` via the
literal template string. It may be the source of `$shared_doc`, or the issue may
come from another text-rendering path. The next agent should reproduce from the
positive #21 fixture before assuming exact source.

### Finding 11 Has a Known Architecture Context

The analyzer's action scope comes from `Diagnostic.context["affected_workflow"]`.
`view_helpers.build_recommended_actions(...)` maps that to
`RecommendedAction.scope_workflow`, and `render_json` emits it.

The final report observed:

```json
scope_workflow: "<unknown>"
```

for:

```bash
.venv/bin/pflow analyze-cache scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md --format=json
```

The progress log already mentions a related known gap from prompt-body overlap
work: some compile/analyzer paths had to use `<unknown>` because `workflow_path`
was not threaded everywhere. The next agent should verify whether Finding 11 is
the same gap, a stale pre-fix report, or a separate analyzer path that still
loses workflow identity.

## Reproduction Commands

Use sandbox-safe invocation in Codex where possible.

### Finding 5 — Chorus-Chooser Suggested Block

No model resolved case:

```bash
CONCEPT="$(jq -c .concept scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"
CD="$(jq -r .creative_direction scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"
ARCH="$(jq -r .architecture scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"
BRIEF="$(jq -r .creative_brief scratchpads/stage2-verification/song-creator/chorus-chooser-inputs.json)"

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  concept="$CONCEPT" \
  creative_direction="$CD" \
  architecture="$ARCH" \
  creative_brief="$BRIEF"
```

Default Haiku case:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow settings llm set-default anthropic/claude-haiku-4-5

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  concept="$CONCEPT" \
  creative_direction="$CD" \
  architecture="$ARCH" \
  creative_brief="$BRIEF"
```

Expected current signal with Haiku default:

- no `Shared context undeclared — declare concept.core_idea` recommended action;
- no concrete `## Cache` block for `concept.core_idea`;
- note saying no provider-cache edit is actionable yet because all assignments
  are below threshold.

The future agent should decide with the user whether the no-model-resolved case
should still emit a concrete suggested block.

### Finding 10 — Positive Sub-Workflow Recommendation Path

The checked-in fixture suppresses the warning because the child has its own
`## Cache`. To reproduce the positive path, follow the README instructions:

```bash
DOC="$(cat scratchpads/stage2-verification/gemini-smoke/reference.md)"

# Make a scratch copy of scratchpads/stage2-verification/cross-workflow-test/
# Remove the child ## Cache block and child prompt_cache declarations.
# Point the parent workflow at the scratch child copy.

HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  <scratch-parent.pflow.md> \
  shared_doc="$DOC"
```

Then inspect text and JSON for:

- `cache.sub-workflow-cache-undeclared`;
- suggestions using `$shared_doc` versus `${shared_doc}`;
- whether the child workflow path is clearly identified.

### Finding 11 — `<unknown>` Scope

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  --format=json
```

Inspect:

```bash
... | jq '.blocking_errors, .recommended_actions, .warnings'
```

Look specifically for:

- `scope_workflow`;
- `context.affected_workflow`;
- messages mentioning `<unknown>`;
- whether the issue is on `cache.prompt-body-duplicates-cache`,
  `cache.order-mismatch`, or both.

## Most Relevant Code Areas

Read before editing.

### Suggested Block Generation and Thresholds

- `src/pflow/core/cache_analysis/analyze.py`
  - `SuggestedBlock`, `SuggestedBlockChunk`, `PerNodeThresholdEntry`.
  - `_populate_suggested_blocks(...)`.
  - `_build_suggested_chunks_and_assignments(...)`.
  - `_thresholds_for_assignments(...)`.
  - `_threshold_entry_for_node(...)`.
  - `_all_assignments_definitively_below_threshold(...)`.
  - `_savings_for_shared_ref(...)`.
  - `_compute_prompt_body_cleanup(...)`.
- `src/pflow/core/cache_analysis/render_text.py`
  - suggested block renderer.
  - `_format_threshold_line(...)`.
- `src/pflow/core/cache_analysis/render_json.py`
  - `_block_to_dict(...)`.
- `src/pflow/core/cache_analysis/below_min_tokens_detector.py`
  - provider threshold semantics.
- `src/pflow/core/llm_capabilities.py`
  - provider/model minimum cache token thresholds.

Current code fact:

- `_populate_suggested_blocks(...)` suppresses all suggested blocks when
  `_all_assignments_definitively_below_threshold(per_node_thresholds)` is true.
- That only triggers when every entry is definitively `meets_threshold is False`.
  If threshold evidence is `None`, the block may still render.

### Sub-Workflow Cache Recommendation Syntax

- `src/pflow/core/cache_analysis/warning_catalog.py`
  - `cache.sub-workflow-cache-undeclared` catalog entry.
  - `suggestions_template`.
  - headline/message templates.
- `src/pflow/core/cache_analysis/analyze.py`
  - `_emit_sub_workflow_cache_findings(...)`.
  - candidate construction around `_SubWorkflowCacheCandidate`.
- `src/pflow/core/cache_analysis/render_text.py`
  - recommended actions and sub-workflow boundary rendering.
- `tests/test_core/test_cache_analysis_per_id_emission.py`
  - producer tests for `cache.sub-workflow-cache-undeclared`.
- `tests/test_core/test_cache_analysis_renderers.py`
  - rendering tests for sub-workflow recommendation text.

Current code fact:

- The catalog suggestion currently uses a string that appears intended to render
  pflow syntax with `${child_input_name}`. Verify actual output before deciding
  whether this is just a missing brace in text, a Markdown/backtick issue, or
  a deeper template construction smell.

### Workflow Scope / `<unknown>`

- `src/pflow/core/cache_analysis/analyze.py`
  - `_cache_validator_findings(...)`.
  - calls to `make_diagnostic(... affected_workflow=...)`.
  - `context_extra.setdefault("affected_workflow", ...)` in discrepancy code.
- `src/pflow/core/cache_analysis/view_helpers.py`
  - maps `context["affected_workflow"]` to `RecommendedAction.scope_workflow`.
- `src/pflow/core/cache_analysis/render_json.py`
  - emits `scope_workflow`.
- `src/pflow/core/workflow/data_flow.py`
  - validator-side diagnostics for cache ordering/overlap.
- `src/pflow/core/workflow/validator.py`
  - workflow path threading into validation.
- `src/pflow/execution/workflow_resolver.py`
  - file path resolution before analyzer/run.

Current code fact:

- `src/pflow/core/cache_analysis/CLAUDE.md` says `_cache_validator_findings`
  enriches validator diagnostics with `affected_workflow` because validator
  constructors are workflow-agnostic.
- If `<unknown>` appears, the bug may be:
  - analyzer called validation with no workflow path;
  - validation produced a diagnostic with fallback `<unknown>` before analyzer
    enrichment;
  - analyzer enrichment used `setdefault`, preserving stale `<unknown>`;
  - JSON action view read a diagnostic not enriched by `_cache_validator_findings`;
  - or the final report is stale versus current code.

Verify which before fixing.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Detect prompt-body / prompt_cache overlap (2026-05-04)`
  - Introduced `cache.prompt-body-duplicates-cache` and
    `cache.prompt-body-shadows-cache`.
  - Discusses `affected_workflow="<unknown>"` fallback and a known workflow-path
    threading gap.
  - Important for Finding 11.
- `Stage 2 follow-up — Findings #9/#10 + phantom-savings: unified below-min-token detection`
  - Introduced unified below-min detection and phantom-savings suppression.
  - States threshold gating must happen at provider-cache granularity.
  - Important for Finding 5.
- `Stage 2 follow-up — post-implementation review + tightening`
  - Reinforces "honest unmeasurable" when telemetry/evidence is absent.
  - Relevant to deciding whether threshold `None` should allow copy/paste
    suggested edits.
- `Stage 2 follow-up — Finding #21: child-scoped sub-workflow cache recommendations`
  - Introduced `cache.sub-workflow-cache-undeclared`.
  - Explains why child cache declarations are child-owned and parent cache does
    not suppress child recommendations.
  - Important for Finding 10.
- `Stage 2 follow-up — Findings #13/#18 wording cleanup`
  - Relevant for exact syntax/wording discipline in agent-facing docs.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero`
  - Not directly about this brief, but useful context for the general "one field
    carries one meaning" discipline.

Also read:

- `scratchpads/stage2-verification/README.md`
  - `cross-workflow-test/` instructions.
  - `song-creator/` and `chorus-chooser/` fixture context.
  - final verification trust boundary.
- `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
  - Findings 5, 10, and 11.
- `src/pflow/core/cache_analysis/CLAUDE.md`
  - current analyzer architecture and suggested-block/action rendering notes.

## Research Questions for the Next Agent

Answer these before designing a fix:

1. What should the analyzer do when it finds shared refs but cannot resolve the
   model or threshold?
   - Emit a concrete suggested block?
   - Emit only an advisory/note?
   - Ask the agent to run with a model/default first?
2. What should the analyzer do when all known assigned nodes are below threshold?
   - Current code suppresses the concrete block; is that the final desired
     contract?
3. Should a suggested block require at least two eligible provider-cache
   consumers before rendering?
4. Should "not actionable yet" states live in Recommended actions, Notes, or a
   separate section?
5. Where should pflow template syntax be constructed so `$name` versus
   `${name}` cannot drift across catalog/renderers?
6. Should `prompt_cache:` entries use bare names while `## Cache` chunks use
   `${name}` in text? If so, make this distinction explicit in tests.
7. Why does `<unknown>` survive into JSON scope?
8. Should analyzer enrichment overwrite `<unknown>` with a known workflow path
   rather than using `setdefault`?
9. Are validator diagnostics and analyzer diagnostics using the same workflow
   scoping contract?

## Design Decisions to Bring to the User

Likely decisions:

- Suppress uncertain suggested blocks vs show them with explicit "needs one run
  / model" caveat.
- Whether a concrete `## Cache` block is allowed when threshold evidence is
  unavailable.
- Whether below-threshold shared refs should become expansion guidance instead
  of a cache edit. Example: "concept.core_idea is too small; consider caching
  `${concept}` if it crosses threshold."
- Whether recommendation syntax should be generated from structured objects
  rather than free-text catalog templates.
- Whether `<unknown>` should ever be allowed in agent-facing JSON when the user
  passed an actual workflow path.

Importance:

- Finding 5 policy is medium-high because it determines whether agents apply
  non-functional cache edits.
- Finding 10 is low-medium but easy to underestimate: syntax examples are
  copied verbatim by agents.
- Finding 11 is low-medium in one-file cases but more important for
  sub-workflow/multi-file workflows.

## Desired UX Properties

Outcome constraints, not a patch recipe:

- A normal "Recommended action" should be actionable as written.
- If no provider-cache edit is useful yet, say that plainly and avoid rendering
  a copy/paste `## Cache` block as the main recommendation.
- Any rendered `## Cache` chunk uses exact pflow syntax: `${name}` /
  `${path.to.value}`.
- Any rendered `prompt_cache:` declaration uses exact pflow syntax for that
  field: bare cache item names in declared order.
- JSON `scope_workflow` should be a known workflow path/basename whenever the
  analyzed workflow path is known.
- `<unknown>` should be treated as an explicit evidence gap, not a silent normal
  value.
- Text and JSON should agree about whether a recommendation is actionable.

## Test/Verification Expectations

Useful test shapes:

- Greenfield workflow with shared ref below threshold and known model.
- Greenfield workflow with shared ref but no model resolved.
- Greenfield workflow with shared ref above threshold and known model.
- Child sub-workflow missing its own `## Cache` declaration.
- Parent/child same node ids to verify workflow scope remains disambiguating.
- Order-mismatch fixture that also triggers prompt-body overlap diagnostics.

Likely test files:

- `tests/test_core/test_cache_analysis_analyze.py`
- `tests/test_core/test_cache_analysis_renderers.py`
- `tests/test_core/test_cache_analysis_per_id_emission.py`
- `tests/test_core/test_cache_analysis_per_id_coverage.py`
- `tests/test_core/test_cache_analysis_warnings.py`
- `tests/test_cli/test_analyze_cache.py`
- possibly `tests/test_core/test_prompt_cache_validation.py`

Manual/free checks:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  scratchpads/stage2-verification/error-ux-tests/order-mismatch.pflow.md \
  --format=json
```

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow analyze-cache \
  /Users/andfal/projects/music-generation/workflows/lyrics-generator/song-creator/chorus-chooser/chorus-chooser.pflow.md \
  concept="$CONCEPT" creative_direction="$CD" architecture="$ARCH" creative_brief="$BRIEF"
```

For positive `cache.sub-workflow-cache-undeclared`, use a scratch copy of the
cross-workflow fixture as described above.

## Non-Goals for This Brief

- Do not start Task 160 structural refactor here.
- Do not solve cost percentage/math bugs from Brief 01 unless they directly
  control whether a recommendation appears.
- Do not solve dynamic batch trace model truth from Brief 02.
- Do not assume the final verification report exactly matches current worktree
  behavior. Reproduce first.

