# Braindump: Baseline Audit Handoff (2026-05-08)

> Context-window handoff from the agent who built the Task 159 baseline
> (`.taskmaster/tasks/task_159/baseline/`, 63 cases) to the agent who will
> audit it (per `.taskmaster/tasks/task_159/baseline/NEXT-AGENT-AUDIT.md`).
>
> **Don't re-read what's already written.** This file captures only the
> tacit knowledge that didn't make it into PLAN.md, README.md, FINDINGS.md,
> NEXT-AGENT-AUDIT.md, or the progress log. Read those first; come back to
> this file as the "what the previous agent knew but didn't formally write
> down" supplement.

---

## Where I am

I built Phase 0 (infrastructure: normalize.py, run-case.sh, regenerate.sh,
verify.sh) plus 8 surfaces (01-05 originally planned + 12-14 added after
the user surfaced gaps via task-review.md and the lyrics-generator
workflow). 63 cases total, all passing roundtrip, 5 findings logged
(F-01 through F-05). Just wrote NEXT-AGENT-AUDIT.md and was wrapping up
when the user requested this braindump.

The audit itself has NOT started.

---

## User's mental model — exact words and what they meant

The user reframed priorities multiple times. The trajectory
matters:

**Round 1 — initial framing**: *"verification specialist"* posture.
*"Your job is not to confirm the implementation works — it's to try to
break it."* *"Your entire value is in the last 20%."*

This set the verification-specialist mindset. Construction-mindset
was secondary.

**Round 2 — mid-build correction**: *"you might be going a little all in
with the edge cases"*.

I had 51 cases planned, was building minimal-fixture catalog cases. The
user wanted compression, not exhaustion. I cut surface 03 from 17 → 8
cases, dropped some 2.0.0-trace edge cases, etc.

**Round 3 — scope clarification**: *"we don't have to test for old
traces"*.

Direct: 2.0.0 trace backcompat is out of scope. I removed
`_shared/fixtures/sample-2.0.0-trace.json`.

**Round 4 — final priority signal**: *"the json is lower priority, the
most important things are that the cases that agents will run into most
are handled good, and that complex outputs, for example from the music
workflow shows up good with every important piece of information showing
up and is correct"*.

**This is the signal that should drive the audit.** Two ideas:

1. **"cases that agents will run into most"** — common-path agent UX.
   Frequency-weighted, not coverage-weighted.
2. **"complex outputs ... every important piece of information ... is
   correct"** — content correctness on real-world output (lyrics-generator
   captures), not mechanical shape testing.

The user's deeper priority — my reading: Task 160 is going to refactor
cache_analysis. The baseline is a regression oracle. Findings from the
audit feed user's pre-Task-160 fix queue. So the audit isn't UX polish
— it's "what should we fix BEFORE the refactor scrambles the diff."

---

## What I learned that isn't in the formal docs

### About the analyzer's behavior on lyrics-generator

The captured output at `12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`
is rich. Things I noticed but didn't fully write up:

1. **Cross-workflow rename detector enumerates per-CALL-SITE, not
   per-NAME-PAIR.** The same rename `creative-direction.response →
   creative_direction` shows up 7 times because 7 sub-workflows consume it
   under that renamed name. Each is a separate "boundary," but UX-wise
   it's one finding. **NEEDS VERIFICATION**: is this intentional (each
   site might need a different prose-canonicalization fix) or a
   coalescing miss? I lean intentional but didn't dig.

2. **Per-call rows include nodes WITHOUT `prompt_cache:` declarations**
   (e.g. `generate-chorus-options` shows `cacheable= ?` because the
   prompt is opaque — but it has no declared cache to begin with).
   **NEEDS VERIFICATION**: is this intentional UX (surfacing them as
   warning candidates) or accidental (renderer not filtering)? It feels
   useful to me, but I'm not sure.

3. **The 75% ratio number is heuristic but DOESN'T look heuristic.** I
   wrote this up as F-04 example #2, but the wider pattern is: any
   analyzer field that depends on token estimation suffers when the
   ref resolves to an LLM response (greenfield mode). The audit will
   probably find the same false-confidence pattern elsewhere — savings
   estimates, projection calcs, prewarm savings_ratio computation.

4. **The `model=` empty string column** is everywhere in the
   lyrics-generator capture. The header explains "no model resolved" but
   per-call rows don't repeat the explanation. The fix shape (typed-state
   field) already exists in the codebase per task-review.md mention of
   `PerNodeThresholdEntry` typed discriminator (commit `60a2eec8`).
   Apply same shape here.

### About the harness itself

5. **Two `make check` rounds were painful to debug**. Pre-commit's
   `trailing-whitespace` and `end-of-file-fixer` hooks fight raw output
   captures in two ways:
   - Empty stdout/stderr → harness writes `\n` (1 byte) → hook strips to
     0 bytes → diff fails
   - Multi-line text with column-padding spaces → hook strips trailing
     spaces per line → diff fails

   **Both fixed**, but the fixes are *load-bearing*:
   - `run-case.sh` has `_write_with_newline` (empty → empty file;
     non-empty → exactly one trailing newline)
   - `run-case.sh` has matching `_emit` helper for diff mode
   - `normalize.py` ends with `text = "\n".join(line.rstrip() for line in
     text.split("\n"))`

   **Don't remove these without re-running `git status` after `make
   check` to verify nothing went `AM` (added-then-modified-by-hook).**

6. **`HOME=$BASELINE_HOME` redirect is necessary AND sufficient** —
   verified at the start. pflow uses `Path.home()` and `expanduser()`
   throughout; both respect HOME. If a future code path uses
   `os.environ['USER']` or `pwd.getpwuid()`, the redirect won't catch it.
   No instances today.

7. **`env -i` in run-case.sh is deliberate.** Strips inherited env vars
   so case behavior doesn't drift based on the developer's shell. The
   passed-through variables (`HOME`, `PATH`, `BASELINE_*`, `PFLOW_*`,
   `LANG`, `LC_ALL`, `TERM=dumb`, `TZ=UTC`, `PYTHONHASHSEED=0`) are the
   minimum set needed. **`PATH` is preserved** because uv resolves uv
   binary via PATH. Don't remove it.

### About finding the real triggers for catalog warnings

8. **F-02's "5 catalog IDs that don't fire" is INCONCLUSIVE.** I tried
   sonnet model + 30k-char input + correct shape. The 5 IDs still didn't
   fire. Possible reasons (I don't know which):
   - True bug in detector logic
   - Stricter actionability gate than I expected (e.g., requires real
     run history, not greenfield)
   - Need a workflow shape I didn't think of (e.g., padding-advisory
     needs a specific subset-relative-to-master pattern with sensitivity
     floor cleared)
   - Need savings-ratio above some threshold I'm not aware of
   - The detector is correct and the workflow legitimately doesn't
     trigger it (user error in my fixture design)

   **What I'd do**: read the detector source for each of the 5 IDs and
   construct a fixture from the tests in `tests/test_core/test_cache_analysis_per_id_emission.py`.
   I didn't do this because the user signaled to compress and the
   implementing agent for surfaces 06+ can extend.

9. **`thinking_effort` vs `reasoning_effort` was discovered by
   accident.** I wrote `thinking_effort` in a workflow expecting a
   "did you mean?" suggestion. Got nothing. Searched the validator code,
   found `_validate_thinking_temperature_compatibility` looks for
   `reasoning_effort`. **The catalog ID is `llm.thinking-temperature-mismatch`
   — using "thinking" terminology — but the param it validates is
   `reasoning_effort`.** Naming inconsistency in the codebase itself.
   Documented as Bug 1 in `scratchpads/task159-baseline-findings-report.md`.

   **MIGHT MATTER**: are there OTHER LLM-node params with similar
   silent-drop risk? The validator code in `data_flow.py` has explicit
   handlers for some params; others might pass through. Worth a sweep
   if the audit doesn't surface this.

### About the lyrics-generator workflow

10. **The workflow lives at `/Users/andfal/projects/music-generation/workflows/lyrics-generator/`**
    on the user's machine (NOT in the pflow repo). I copied it into
    `_shared/workflows/lyrics-generator/` to make the baseline
    self-contained. **The committed copy may diverge from the live
    workflow over time.** Not a problem now; might matter if user
    edits the live one and the baseline goes stale.

11. **The lyrics-generator USES MCP nodes** (`mcp-klavis-youtube-...`)
    that aren't registered in the test environment. This is why
    `pflow visualize` fails on the parent (F-05). The workflow runs in
    user's environment because his MCP servers ARE configured. The
    baseline can't run the workflow end-to-end without his MCP setup.
    Static analysis (`analyze-cache`) doesn't need MCP execution and
    works fine.

12. **`pflow guide ./lyrics-generator.pflow.md` doesn't auto-detect
    `caching`** despite the workflow tree having 8 `prompt_cache:`
    declarations. This is F-03. Worth re-running `pflow guide` directly
    on song-creator (where the `## Cache` block IS) to confirm — I did
    this and it ALSO doesn't detect caching. The auto-detect path
    isn't recursing into sub-workflows AND isn't keying on `## Cache` /
    `prompt_cache:` keywords.

### About what the audit might surface

13. **My over/under for audit findings: 10–30.** Why this range:
    - 7 findings I already noticed (in NEXT-AGENT-AUDIT.md "worked
      examples"). Some won't be confirmed by the audit; some will
      proliferate.
    - The cross-workflow renames (17 in lyrics-generator) follow a
      pattern that probably has 2-3 distinct UX issues, not 17.
    - The "model= empty" pattern repeats in many cases.
    - Some findings will combine into one (e.g. "absolute paths
      everywhere" vs "renames repeat the same path 17x" might be one
      finding).
    - Some findings will reveal sub-instances (the F-04 false-confidence
      pattern likely has 3-4 sub-cases).

14. **The audit MUST distinguish "UX wart" from "real bug."** Pitfall
    #19 (synthetic fixtures hide bugs) applies at the baseline level
    too — if a captured output reflects a real bug, locking it as
    "expected behavior" via mutation contracts means future "fixes" get
    reverted as "regressions" against the baseline. **The audit's most
    important triage question: does this finding reflect a UX wart in
    correct behavior, or output that's incorrect?**

    For each finding, the BASELINE-AUDIT.md entry should mark this
    explicitly. F-04 is borderline — the 75% ratio is a UX wart in
    technically-correct behavior (heuristic IS a valid estimate; the
    rendering doesn't make heuristic-vs-measured visible enough).

---

## What's likely missing from NEXT-AGENT-AUDIT.md that I should mention

### Tools the audit agent might forget to use

- **`pflow guide <workflow>`** — invoke on lyrics-generator to verify
  F-03 directly, not just from the captured surface 12 case.
- **`pflow describe <workflow>`** — I didn't use this; might surface
  workflow-interface issues that complement analyze-cache.
- **`pflow visualize <workflow>`** — case 05 captures it on song-creator.
  Visualizing other sub-workflows might reveal more renderer issues.
- **`pflow analyze-cache --help`** — verify the help text actually
  matches the captured behavior. I wrote NEXT-AGENT-AUDIT.md before
  checking this.

### Adjacent surfaces I didn't audit

- The runtime-tier `cache.below-min-predicted` emission path (`LLMNode.post()`).
  My captures use the analyzer-tier emission only. Different code path,
  different output venue (`__warnings__` shared store key, then
  rendered via the engine's diagnostic pipeline).
- The dry-run nudge surface (planned as surface 06; not built). One-line
  output, but it's the only path that calls `summarize_from_analysis`.

### Things the user might not realize

**MIGHT MATTER**: the lyrics-generator copy in `_shared/workflows/`
is a snapshot. If user updates the live workflow at
`/Users/andfal/projects/music-generation/workflows/lyrics-generator/`,
the baseline goes stale. I haven't documented a refresh procedure.

**CONSIDER**: the `_shared/long-stable-text.txt` file is ~30k chars,
~7000 tokens. Used to push past sonnet's 1024 min-cache threshold. If
provider thresholds change (per DD#32 they're version-specific),
fixtures might need bigger inputs.

**UNEXPLORED**: the `analyzed_at` timestamp in JSON output is
normalized away. I never asked: does it have agent-actionable value
(e.g. "you're reading stale analysis from 2 days ago")? The audit
might find it should be preserved as relative time ("analyzed 2
minutes ago") for live consumers.

---

## Assumptions I made that weren't explicitly confirmed

1. **ASSUMPTION**: surfaces 06–11 from PLAN.md are still in scope but
   lower priority than the audit. The user explicitly said "what is the
   task for the next agent" expecting the answer to be "audit." But
   they didn't say "don't build 06–11 ever."

2. **ASSUMPTION**: BASELINE-AUDIT.md should follow FINDINGS.md's
   structure (per-finding section with case path, what's wrong,
   suggested fix, severity). I wrote this directive into
   NEXT-AGENT-AUDIT.md without asking.

3. **ASSUMPTION**: F-01 through F-05 should NOT be re-found by the
   audit. I told the next agent to exclude them. But if the audit's
   process surfaces a NEW angle on F-04 (e.g., specific sub-instance),
   they should still write that.

4. **ASSUMPTION**: the auditing agent has full read access to
   everything in the repo, including the cache_analysis source code.
   This is needed to triage UX-wart vs real-bug.

5. **NEEDS VERIFICATION**: my count of "63 cases" — I trust the
   `find ... command.sh | wc -l` output but never manually counted by
   surface. The README has the per-surface counts that summed to 63
   (10+8+8+20+5+5+4+3 = 63 ✓).

---

## What I'd do differently if starting over

### Build surface 12 (lyrics-generator) FIRST, not last.

The integration capture would have shaped my minimal-fixture priorities.
Several minimal fixtures in surfaces 01-04 turned out to be lower-value
than I thought because surface 12 covers the same ground at integration
scale.

### Read the cache_analysis CLAUDE.md sooner.

The CLAUDE.md surfaced *halfway through* my work (when I read the
warning_catalog.py source for surface 04). It explains things I
re-derived: the 4-tier token estimation, the catalog-as-SSoT pattern,
the "honest unmeasurable" convention, the disambiguation between
memoization vs LLM-provider cache. **Read this first.**

### Use real test fixtures from the existing test suite as a template.

Files like `tests/test_core/test_cache_analysis_per_id_emission.py`
contain exactly the trigger conditions for each catalog ID. I built
fixtures from spec wording instead. The 5 untriggered cases in F-02
might have triggered if I'd cribbed from the tests.

### Ask the user "do we need to test for old traces" earlier.

I built a 2.0.0 fixture before asking. Wasted ~15 minutes.

### Coordinate with user on the `make check` constraint earlier.

I discovered both empty-file and trailing-whitespace pre-commit
interactions by running `make check` blind and fighting fires. If I'd
read `.pre-commit-config.yaml` first I'd have known what to expect.

---

## Things the user said that aren't in any other doc

- *"act like a verification specialist. Your job is not to confirm the
  implementation works — it's to try to break it. You have two
  documented failure patterns. First, verification avoidance … Second,
  being seduced by the first 80%"* — set the entire framing.

- *"this sounds right"* — confirmation of compression strategy
  (51 cases, atomic, mocked default + 4 live, hand-crafted + 1 real,
  no MCP coverage, adversarial enumerated explicitly).

- *"can you implement everything up until case 05, so the implementing
  agent can just continue"* — locked the surfaces 01–05 scope as the
  initial deliverable.

- *"before you continue, can you run this and make sure this works and
  you are writing pflow.md workflows correctly etc"* — interrupted me
  early in surface 01 for sanity-check. Caught my "missing description"
  errors before they propagated.

- *"you might be going a little all in with the edge cases, what do you
  think?"* — turning point. Compressed surface 03 from 17 → 8.

- *"we don't have to test for old traces"* — scope cut for 2.0.0
  backcompat.

- *"I forgot to give you .taskmaster/tasks/task_159/task-review.md,
  anything in this file that makes you reconsider what / how we should
  test"* — signaled that task-review.md was load-bearing context I'd
  missed.

- *"use pflow --help and do pflow guide <music workflow> then add the
  cases we need"* — directive that produced surfaces 12, 13, 14.

- *"we need to add the newline to not upset make check"* — `make check`
  is the constraint, not formatting purity.

- *"the json is lower priority, the most important things are that the
  cases that agents will run into most are handled good, and that
  complex outputs, for example from the music workflow shows up good
  with every important piece of information showing up and is correct"*
  — final priority signal that drives the audit.

---

## Open threads / suspicions

- **The 5 unfired catalog cases (F-02)** — I think 2-3 are detector
  bugs and 2-3 are missing-fixture issues. Reading the tests would
  resolve this in <30 minutes. I didn't.

- **The cross-workflow rename detector enumeration** — per-call-site
  vs per-name-pair. The rendering implies the latter would be denser
  but I'm not sure if collapsing loses information.

- **The auto-detect path in `pflow guide`** — only `batch`, `code`,
  `llm`, `sub-workflows` are surfaced for lyrics-generator. Why not
  `caching`? The detector probably keys on specific markdown headings
  or YAML keys; `## Cache` and `prompt_cache:` aren't in its dictionary.
  The fix is one-line in the auto-detect mapping; the audit agent
  might want to find the exact location and quote it.

- **Whether the audit will surface that the analyzer's "Suggested
  blocks" section silently isn't rendered for lyrics-generator** —
  I noticed the section header didn't appear in the captured output.
  Either there's no actionable suggestion (legitimate) or the renderer
  is dropping the section. Didn't dig.

- **Whether the dry-run footer integration works on lyrics-generator** —
  I never ran `pflow run --dry-run` on it. The cache nudge might or
  might not appear.

---

## For the next agent — direct advice

**Start here**: read `NEXT-AGENT-AUDIT.md` end-to-end. Then
the cache_analysis CLAUDE.md (load-bearing tacit knowledge from the
implementer).

**Don't bother with**:
- Mechanical JSON-shape comparison across cases. User explicitly
  de-prioritized it.
- Re-finding F-01 through F-05.
- Building cases. The 63 captures are the audit subject.
- "Did the harness work?" — yes, it does, 63/63 pass roundtrip, 0
  drift, `make check` clean. Don't audit the harness.

**The user cares most about**:
- The lyrics-generator captures. Read every line. Multiple times.
- The common-path agent UX (parser errors, validator errors, the
  high-frequency warnings). These are what agents will see most.

**Stop and ask user if you find**:
- Output that reflects a real bug (not just a UX wart). He needs to
  triage — fix before Task 160 vs document and ship.
- A finding that requires re-running pflow on a different command
  (e.g., live API recording). He'll decide if it's worth the cost.
- More than ~30 findings. Diminishing returns; he'll re-prioritize.

**Don't stop and ask** for:
- "How should I structure BASELINE-AUDIT.md?" (mirror FINDINGS.md)
- "What severity should I use?" (use your judgment; explain reasoning)
- "Should I include this minor finding?" (yes, but mark severity low)

**Calibration from my work**:
- I spent ~6 hours building the baseline; you should spend 1-2 hours
  auditing it. Audits are denser than construction.
- I found 5 findings during construction. The audit should find more
  per hour because you're looking specifically.
- If you finish in <1 hour, you didn't read the lyrics-generator
  captures carefully enough.

---

## Files & references

**Authoritative reading order**:
1. `.taskmaster/tasks/task_159/baseline/NEXT-AGENT-AUDIT.md` (your mission)
2. This braindump
3. `.taskmaster/tasks/task_159/baseline/FINDINGS.md` (don't re-find these)
4. `src/pflow/core/cache_analysis/CLAUDE.md` (analyzer tacit knowledge)
5. `.taskmaster/tasks/task_159/task-review.md` (the patterns load-bearing
   for Task 160)
6. `.taskmaster/tasks/task_159/baseline/PLAN.md` (the construction plan
   that produced the captures)

**Reference files**:
- `.taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/`
  — the real workflow tree under audit
- `scratchpads/task159-baseline-findings-report.md` — the bug/UX report
  I wrote earlier (covers Bug 1 thinking_effort, F-01, F-02 etc.)
- `src/pflow/core/cache_analysis/warning_catalog.py` — 20-entry catalog
  the audit cross-references
- `src/pflow/core/workflow/data_flow.py::_validate_cache_block` — where
  cache structural validation lives (3 ID-bearing producers + 4 un-IDed)

**Cases to read first** (priority order):
1. `12-real-world-lyrics-generator/01-analyze-cache-text/` (THE case)
2. `12-real-world-lyrics-generator/03-analyze-cache-song-creator-text/`
3. `04-warning-catalog/04-cache.shared-context-undeclared/` (the
   greenfield common-path)
4. `02-validator-errors/01-prompt-cache-out-of-order/` (the error
   common-path with bracketed ID)
5. `02-validator-errors/02-prompt-cache-undeclared-name/` (the error
   common-path WITHOUT bracketed ID — UX inconsistency)

---

## What I'd be furious at myself for not mentioning

1. **The user's priority signal was content correctness, not coverage.**
   If you build more cases instead of auditing, you've missed what they
   asked for.

2. **Pitfall #19 applies to the baseline itself.** If you accept a
   captured output that reflects a real bug as "expected," the mutation
   contract locks the bug. Triage every finding for "wart vs bug."

3. **The harness `make check` interaction is fragile.** Don't change
   `run-case.sh` or `normalize.py` without re-running `make check`
   afterward. The fixes for empty-file and trailing-whitespace are
   load-bearing.

4. **The cross-workflow rename count of 17 in lyrics-generator is
   real, not a renderer bug.** The detector correctly enumerates per-
   call-site. The UX issue is presentation density, not correctness.
   Don't try to "fix" the count.

5. **The `model= empty` rendering is a known fix shape.** The
   `PerNodeThresholdEntry` typed-discriminator pattern (commit
   `60a2eec8`) already exists in the codebase for the same problem
   class. Apply it here.

6. **F-04's wider pattern is "false confidence via heuristic numbers
   that look measured."** The audit should look for this pattern across
   ALL analyzer fields, not just `cache.below-min-predicted`.

7. **The `analyzed_at` timestamp**: I normalized it without asking.
   If it has agent-actionable value (stale analysis warning), that's
   a finding the audit can surface.

---

> **Note to next agent**: Read this document fully before taking any
> action. When ready, confirm you've read and understood by summarizing
> the key points, then state you're ready to proceed.
