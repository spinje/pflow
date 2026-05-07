# Task 159 Fix Brief 06 — Guide and Warning Catalog Drift

Status: research handoff, not an implementation plan
Prepared: 2026-05-07
Source verification report: `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`

## Purpose

This brief captures what is known about `pflow guide caching` being stale
relative to the live cache warning catalog.

The next agent should treat this as a research-first documentation and
agent-UX task. Do not assume the right fix is only to add a few missing
bullets. First inspect the current guide system, catalog, MCP tool docs, and
tests that already protect catalog/doc parity. Then decide with the user
whether the best final shape is manual prose with drift tests, generated
catalog text, or another simple local pattern.

Prefer simplicity of the final code and documentation model over ease of
patching. This is not about adding infrastructure for its own sake; it is about
making warning IDs reliable anchors for future agents.

## Finding Covered

Final verification Finding 1:

- `pflow guide caching` is stale versus the warning catalog.

Scope for this brief:

- `pflow guide caching`.
- Live warning IDs in `warning_catalog.py`.
- Any MCP or docstring surfaces that list warning IDs.
- Drift tests or generation strategy.

Out of scope:

- Ruff/test lint failures from the final verification report. Those are release
  hygiene, but they are not the same agent-UX issue and should get a separate
  brief if needed.

## Plain-Language Problem

Task 159 made warning IDs part of the agent-facing contract. An agent may see a
warning such as:

```text
cache.first-call-write-penalty
cache.heterogeneous-models-fragment-cache
cache.prompt-body-duplicates-cache
llm.thinking-temperature-mismatch
```

The expected loop is:

1. Agent sees a warning ID in text, JSON, report, runtime output, or MCP output.
2. Agent uses the warning ID as a stable handle.
3. Agent consults `pflow guide caching` for what the warning means and what to
   do next.

The verification report found that `pflow guide caching` omits multiple live
IDs. That breaks the loop. The agent has to grep source or guess.

This is most visible for JSON/MCP/agent workflows, but it is not only a JSON
problem. The guide is the human-readable canonical reference for cache warning
IDs across all surfaces.

## Current Evidence

From `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`, missing
IDs observed by comparing guide output to the cache warning catalog:

```text
cache.consolidate-to-root-recommended
cache.first-call-write-penalty
cache.heterogeneous-models-fragment-cache
cache.prompt-body-duplicates-cache
cache.prompt-body-shadows-cache
llm.thinking-temperature-mismatch
```

The report's reproduction commands:

```bash
.venv/bin/pflow guide caching
rg -n "CACHE_WARNING_CATALOG|cache\\.first-call|cache\\.heterogeneous|llm\\.thinking-temperature" src tests
```

Expected:

- The guide explains every warning ID an agent is expected to act on, or it
  clearly points to a generated/current catalog.

Actual:

- The guide omits multiple live IDs.

Impact:

- Agents can encounter an analyzer/runtime warning and then find no matching
  remediation context in the official guide.

## Severity and UX Impact

Severity: medium.

This does not make provider prompt caching execute incorrectly. It does make
Task 159 less agent-usable. Since prompt caching is primarily an agent-facing
cost/performance feature, warning IDs need reliable documentation.

Impact is highest for:

- `analyze-cache --format=json` consumers.
- MCP `analyze_cache` consumers.
- Agents that use warning IDs for dispatch and remediation.
- Runtime/report warnings that surface catalog-backed IDs such as
  `cache.below-min-tokens`.

Impact is lower, but still real, for a human reading plain text output when the
diagnostic message itself is already self-explanatory.

## Reproduction Commands

Use sandbox-safe invocation:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow guide caching
```

Compare against the live catalog:

```bash
rg -n "CACHE_WARNING_CATALOG|CacheWarningSpec|llm\\.thinking-temperature|cache\\.first-call|cache\\.heterogeneous|cache\\.prompt-body" \
  src/pflow/core/cache_analysis/warning_catalog.py \
  src/pflow/guide \
  src/pflow/mcp_server \
  tests
```

If the future agent wants an exact set comparison, inspect the catalog in
Python or with a short one-off script, but avoid making the script itself the
fix unless generation/drift testing is the chosen design.

## Most Relevant Code Areas

Start with:

- `src/pflow/core/cache_analysis/warning_catalog.py`
  - Live catalog of warning IDs and message/headline templates.
  - `RECOMMENDED_ACTION_PRIORITY`.
  - `make_diagnostic(...)` and dispatch-specific required context.
- `src/pflow/guide/features/caching.md`
  - Current `pflow guide caching` source.
- `src/pflow/guide/entry.md`
  - Feature-topic menu / guide navigation.
- `src/pflow/cli/commands/guide.py` or nearby guide command code.
  - How guide markdown files are loaded and rendered.
- `src/pflow/mcp_server/tools/execution_tools.py`
  - MCP analyze-cache tool docstring may list warning IDs.
- `tests/test_core/test_cache_analysis_warnings.py`
  - Catalog integrity tests.
- `tests/test_core/test_cache_analysis_per_id_coverage.py`
  - Per-ID diagnostic coverage.
- MCP tests around analyze-cache docstrings, if present.

Do not edit all of these blindly. First identify which surfaces are intended to
be canonical and which are supplementary.

## Relevant Progress-Log Context

Read these sections from
`.taskmaster/tasks/task_159/implementation/implementation-progress-log.md`:

- `Segment 4 — Analyzer + Docs`
  - Initial `pflow guide caching` topic was added here.
  - Catalog was originally smaller; guide drift may be from later warning ID
    additions.
- `Post-segment-4 follow-up: cost wiring + honest loose-ends audit`
  - Establishes that analyzer UX and tri-state cost language are load-bearing.
- `Detect prompt-body / prompt_cache overlap (2026-05-04)`
  - Added `cache.prompt-body-duplicates-cache` and
    `cache.prompt-body-shadows-cache`.
  - Notes that catalog-list docstrings drift silently and that tests caught MCP
    docstring drift.
- `Stage 2 follow-up — Finding #1: thinking + temperature validate-time check`
  - Added `llm.thinking-temperature-mismatch`, the first non-`cache.*` entry in
    the catalog.
- `Stage 2 follow-up — Findings #11/#12: exact-model fragmentation + lone-write penalty`
  - Added `cache.heterogeneous-models-fragment-cache` and
    `cache.first-call-write-penalty`.
- `Stage 2 follow-up — Findings #11/#12: post-review fixes`
  - Emphasizes catalog message consistency and avoiding embedded-currency drift.
- `Stage 2 follow-up — Finding #21: child-scoped sub-workflow cache recommendations`
  - Added `cache.sub-workflow-cache-undeclared` and mentions guide wording was
    manually checked.
- `Stage 2 follow-up — Findings #13/#18 wording cleanup`
  - Updated stale `--no-cache` and TTL guide wording.
- `Stage 2 follow-up — Finding #17: all-memo trace cost is known zero`
  - Mentions stale guide wording was still discovered by tests.

Also read:

- `scratchpads/stage2-verification/README.md`
  - Free CLI UX checks and guide expectations.
- `scratchpads/stage2-verification/FINAL-VERIFICATION-REPORT.md`
  - Finding 1 details and final recommendation priority.
- `src/pflow/core/cache_analysis/CLAUDE.md`
  - Current analyzer package notes, warning catalog role, and planned Task 160
    refactor.

## Research Questions for the Next Agent

Answer these before proposing a fix:

1. Which warning IDs are currently live in `warning_catalog.py`?
2. Which of those IDs can appear in:
   - validation output,
   - runtime warnings,
   - `--report`,
   - `analyze-cache` text,
   - `analyze-cache --format=json`,
   - MCP `analyze_cache`,
   - `--dry-run` nudges?
3. Does every live ID need detailed prose in `pflow guide caching`, or should
   some be documented through a compact generated/current catalog table?
4. Is there already a test pattern that asserts MCP docstrings list every
   catalog ID?
5. Is there an existing guide test style that can cheaply protect
   `caching.md` from drifting?
6. Would generating a warning table from the catalog fit the existing guide
   architecture, or would it add more complexity than it removes?
7. Should non-cache IDs in the same catalog, currently
   `llm.thinking-temperature-mismatch`, be included in `pflow guide caching`
   because they affect prompt-cache workflows, or should they be linked to a
   broader LLM/provider guide?

## Design Options to Consider

Option A: Manual guide update only.

- Good: smallest immediate change.
- Bad: drift can recur the next time a warning ID is added.
- Reversible: easy.
- When this is enough: if tests already cover another canonical surface and the
  guide is intentionally high-level rather than exhaustive.

Option B: Manual guide update plus a focused drift test.

- Good: likely best balance. Keeps guide prose human-written but fails tests
  when a catalog ID is missing from the guide or an intentional exclusion list.
- Bad: can make guide wording changes slightly more annoying.
- Reversible: easy.
- Recommended unless code inspection shows a better local pattern.

Option C: Generate the warning section from the catalog.

- Good: strongest drift prevention.
- Bad: may require guide rendering infrastructure; generated docs can be less
  helpful than curated prose if not designed carefully.
- Reversible: medium.
- Consider only if existing guide architecture already supports dynamic
  injection cleanly.

Option D: Add a dedicated warning catalog guide/command.

- Good: separates conceptual caching guide from exhaustive warning reference.
- Bad: larger UX/API surface; possibly unnecessary before users exist.
- Reversible: medium.
- Consider only if exhaustive warning prose makes `pflow guide caching` too
  long/noisy.

## Current Recommendation

Likely best path: **manual guide update plus simple drift protection**, unless
code inspection shows generation is already locally idiomatic.

This keeps the final system simple:

- one live warning catalog,
- guide prose that explains agent actions,
- tests that prevent silent omission,
- no new documentation generation framework unless it naturally fits.

The agent should still verify this recommendation against code. If a generated
table is already easy because of existing guide tooling, present that option to
the user before implementing.

## Desired UX Properties

- An agent who sees any live cache-related warning ID can find it or a clear
  pointer to it through `pflow guide caching`.
- The guide distinguishes the two cache layers:
  - pflow memo cache,
  - provider prompt caching.
- The guide remains action-oriented, not just a raw ID dump.
- Warning IDs remain stable handles; guide text should not hide them entirely
  behind prose.
- MCP/tool docstrings, guide text, and catalog tests should not silently drift.
- If an ID is intentionally omitted from the guide, that omission should be
  explicit in a test or documented exclusion list.

## Test/Verification Expectations

At minimum, after any fix:

```bash
HOME=/private/tmp/pflow-test-home .venv/bin/pflow guide caching
```

should include or clearly reference the live warning IDs relevant to cache
analysis/remediation.

Focused tests to consider:

- Catalog-to-guide drift test.
- Catalog-to-MCP-docstring drift test, if not already present.
- Existing cache warning catalog tests.
- Existing guide rendering tests.

Likely files:

- `tests/test_core/test_cache_analysis_warnings.py`
- `tests/test_core/test_cache_analysis_per_id_coverage.py`
- `tests/test_mcp_server/test_analyze_cache_tool.py`
- Any existing `tests/test_cli` or `tests/test_docs` guide tests.

Run a focused test sweep first, then the broader cache-related sweep from
`scratchpads/stage2-verification/README.md`.

## Non-Goals for This Brief

- Do not start Task 160 structural refactor.
- Do not redesign the entire guide system unless investigation shows the final
  code becomes simpler.
- Do not bundle unrelated ruff/test lint cleanup.
- Do not preserve stale wording because tests happen to expect it; the analyzer
  has no external users yet.

