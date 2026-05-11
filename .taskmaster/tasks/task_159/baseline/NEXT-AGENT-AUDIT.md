# Next Agent — Baseline Output Audit

> Read this end-to-end before starting. The construction-mindset agent
> (me) built 63 cases across 8 surfaces. Your job is **not** to build
> more. Your job is to **read what's captured** and judge whether each
> output would actually help an AI agent fix a problem.

## Your mission

Audit the captured `expected-stdout.txt` and `expected-stderr.txt`
files at `.taskmaster/tasks/task_159/baseline/`. Write findings to
`BASELINE-AUDIT.md` in this folder. Do NOT regenerate any expected
files. Do NOT add new cases. Do NOT extend surfaces 06–11.

You are looking at this from the **agent-user** perspective:
"if I (an AI agent) were debugging this workflow and got this output,
would it tell me what's wrong, why, where, and how to fix it?"

## Priority — content correctness over JSON shape

User's directive (verbatim): *"the json is lower priority, the most
important things are that the cases that agents will run into most are
handled good, and that complex outputs, for example from the music
workflow shows up good with every important piece of information
showing up and is correct"*

Three priority tiers:

### Tier 1 — Complex real-world outputs (highest)

The single most load-bearing surface is **case 12 — real-world
lyrics-generator**. Every piece of information in the captured output
should be:

- **correct** (matches what's actually in the workflow)
- **complete** (no information silently dropped)
- **agent-actionable** (an agent can decide what to do from it)
- **dense** (no repetition that buries the signal)

**Cases to audit thoroughly**:
- `12-real-world-lyrics-generator/01-analyze-cache-text/` (already
  spot-audited; see worked examples below)
- `12-real-world-lyrics-generator/03-analyze-cache-song-creator-text/`
- `12-real-world-lyrics-generator/02-analyze-cache-json/` — only enough
  to confirm key info isn't missing vs the text version

For each section in these outputs (Header, Summary, Recommended
actions, Sub-workflow boundaries, Per-call cache report, Sub-workflow
drill-in, Notes), ask: *if I'm fixing a real problem in a 17-file
workflow tree, does this section give me what I need without burying
the signal?*

### Tier 2 — Common-path agent UX

The cases agents will hit *most often* in their workflow lifecycle:

| Lifecycle stage | Cases to audit |
|---|---|
| **Wrote a workflow, ran `pflow run`, got an error** | `01-parser-errors/01,02,04,06,07` (the most-likely typos: empty cache block, multi-block, duplicate id, bad TTL, unresolved var); `02-validator-errors/01,02,03` (out-of-order, undeclared, on-non-llm) |
| **Workflow runs but caching feels off** | `02-validator-errors/06,07,08`; `04-warning-catalog/04,09,17,18` (shared-context-undeclared, below-min-tokens, opaque-prompt, prompt-body-duplicates) |
| **Asked analyze-cache to evaluate a workflow** | `03-analyze-cache-modes/01,03,07` (greenfield-text, steady-state-text, json-error-envelope) |
| **Workflow runs in a batch / fan-out** | `04-warning-catalog/13` (prewarm-no-prefix); `05-advisory-cases/01,02,03` (silent-skip + suppression) |

For each: read the captured output. Does an agent who hits this
specific situation get told **what** is wrong, **why** it matters, **where**
in their file (line number, node id), and **how** to fix it?

### Tier 3 — Lower priority (skim only)

- JSON shape consistency (user explicitly de-prioritized)
- Section ordering across modes (mostly handled by tests already)
- Help text (`09-help-and-guide` — not built)

You may note JSON-shape issues if they jump out, but don't go hunting.

## What "good agent UX" means — concretely

Borrowed from the existing pflow conventions surfaced in the spec and
reviews:

1. **Every error includes 4 elements**: WHAT broke, WHY it matters,
   WHERE (file path + line number + node id), HOW to fix.
2. **Warning IDs in a stable catalog** (e.g. `cache.below-min-tokens`)
   should be present in the rendered output so agents can grep / filter.
3. **No magic strings in agent-facing data** — if a value is "unknown",
   the rendering should say so explicitly with a typed state, not an
   empty string or `<unknown>` literal.
4. **No false confidence** — if a number is heuristic, the rendering
   should say `src=low` or `cacheable=?` rather than presenting a number
   that looks measured.
5. **No mixed signals** — "unavailable" should mean one thing, not
   "unavailable for this view but trace-driven later if you run the
   workflow."
6. **No path noise** — absolute paths should be normalized to relative
   forms where they're meant to be copy-pasted as commands.
7. **No repetition that buries signal** — if the same file path appears
   17 times in a section, fold it into a table or a one-line summary.
8. **Notes that explain silence** — when a warning is suppressed (e.g.
   savings_ratio < 5%, partial trace, below threshold), the rendering
   should say so once, briefly. Silence without explanation is the
   worst class of agent UX.

## Worked examples — what I already noticed

From a 2-minute spot-audit of
`12-real-world-lyrics-generator/01-analyze-cache-text/expected-stdout.txt`:

### Example 1 — Header `model=` empty + "no model resolved" mixed messaging

```
Workflow: 25 LLM nodes, invocation count unavailable (3 dynamic batch nodes)
  (no model resolved — set settings.default_model)
```

Then per-call rows:
```
write-lyrics  model=  tokens= 3684  cacheable= 2763  ratio= 75%  src=low
```

`model=` (empty string) is bad UX. The header says "no model resolved",
implying the workflow lacks `- model:` declarations OR `settings.default_model`.
But the per-call rows just show empty strings — agent can't tell
which case applies. Should be `model=<unresolved>` or
`model=<inherited from parent default>` with typed-state field for
JSON consumers (the `PerNodeThresholdEntry` precedent at commit
`60a2eec8`).

**Severity guess**: medium — affects every workflow that uses pflow's
default-model-via-settings pattern, which is the recommended pattern.

### Example 2 — `ratio= 75%` looks measured but is heuristic

```
write-lyrics  model=  tokens= 3684  cacheable= 2763  ratio= 75%  src=low
```

The 75% ratio is computed from a heuristic (chunk size estimate ÷
prompt size), not from real cache_creation/cache_read tokens. `src=low`
flags this — but the value `75%` itself looks authoritative. An agent
reading it concludes "I have 75% caching." They don't.

This is **F-04 in concrete form**: the analyzer can't measure tokens
of `${node.response}` in greenfield mode, so it estimates and shows
a number that LOOKS measured. Better UX: `ratio= ?` when src=low,
matching the `cacheable= ?` pattern already used for opaque-prompt
rows in this same output:

```
generate-chorus-options  model=<varies>  tokens= 3  cacheable=  ?  ratio=  ?%  src=low  opaque-prompt
```

### Example 3 — 17 cross-workflow renames, full path repeated each time

```
1. Cross-workflow rename — `creative-direction.response` ↔ `creative_direction`
   song-creator → chorus-chooser  (line 97)
   <REPO_ROOT>/.../song-creator.pflow.md → <REPO_ROOT>/.../chorus-chooser.pflow.md: parent passes ...

2. Cross-workflow rename — `song-architecture.response` ↔ `architecture`
   song-creator → chorus-chooser  (line 97)
   <REPO_ROOT>/.../song-creator.pflow.md → <REPO_ROOT>/.../chorus-chooser.pflow.md: parent passes ...

   ... 15 more entries, same pattern ...
```

After entry 4 the agent's eyes glaze. Information density is terrible.
The renames are real findings, but the rendering treats each as equally
worthy of 4 lines including a 200-char-each absolute path.

**Better UX**: a table, OR a per-source-workflow grouping:

```
song-creator → chorus-chooser  (line 97):
    creative-direction.response → creative_direction
    song-architecture.response  → architecture
    concept_brief               → creative_brief
song-creator → review-emotional-architecture  (line 124):
    write-lyrics.response       → lyrics
    creative-direction.response → creative_direction
... etc
```

Same information; one-fourth the lines.

### Example 4 — Sub-workflow drill-in shows absolute paths

```
Sub-workflow opportunities don't surface here — run analyze-cache per child:
  pflow analyze-cache <REPO_ROOT>/.taskmaster/tasks/task_159/baseline/_shared/workflows/lyrics-generator/analyze-source/analyze-source.pflow.md
  pflow analyze-cache <REPO_ROOT>/.../concept-chooser/concept-chooser.pflow.md
  ... 15 paths total, each absolute ...
```

These are paste-ready commands but the absolute paths are 200+ chars
each. An agent working from the workflow's directory wants:

```
cd <to-the-workflow-dir>
pflow analyze-cache analyze-source/analyze-source.pflow.md
pflow analyze-cache concept-chooser/concept-chooser.pflow.md
...
```

### Example 5 — Notes section has 3 near-duplicate lines

```
· Workflow batch fetch-sources in <REPO_ROOT>/.../lyrics-generator.pflow.md
  uses items: ${sources}; sub-workflow rows for these runtime items are not
  in the per-call table. ...

· Workflow batch analyze-sources in <REPO_ROOT>/.../lyrics-generator.pflow.md
  uses items: ${fetch-sources.results}; sub-workflow rows for these runtime
  items are not in the per-call table. ...

· Workflow batch create-songs in <REPO_ROOT>/.../lyrics-generator.pflow.md
  uses items: ${zip-concepts-with-briefs.result}; sub-workflow rows for these
  runtime items are not in the per-call table. ...
```

Same template, three times, each ~250 chars. Should be one note with
the list of affected batches.

### Example 6 — "Cost per run: unavailable" without next-step suggestion

```
Cost per run:                unavailable
...
Cost data unavailable: no model resolved for LLM nodes (set settings.default_model or add per-node `- model:`).
```

The actionable hint IS there, on a separate line. But the
attention-grabbing "unavailable" appears first, in the Summary block,
without explanation. An agent skimming sees `unavailable` and might
miss the Notes-style explanation that follows. UX-wise, the
explanation should sit next to the value:

```
Cost per run:  unavailable (no model resolved — set settings.default_model)
```

### Example 7 — Only 2 recommended actions despite 17 renames + 5 below-min

The "Recommended actions" section has 2 entries:
- Sub-workflow cache undeclared
- Prompt opaque to static analysis

But surface 04 case 09 (`below-min-tokens`) demonstrates that the
analyzer DOES surface below-min-tokens recommendations under
"Recommended actions" elsewhere. Why are they NOT here? The 5 below-min
findings I saw in earlier exploration of this same workflow are
present in `## Per-call cache report` (via the warning column?) but
not promoted to actions. **Investigate**: is this an intentional
suppression (renderer dropping low-priority warnings on workflows
with too many findings?) or a regression?

## Process

1. Read this file end-to-end first.
2. Start `BASELINE-AUDIT.md`: per-finding sections with case path, what's wrong,
   what good UX would look like, severity guess.
3. Audit Tier 1 cases first (lyrics-generator outputs).
4. Audit Tier 2 cases (common-path agent UX).
5. Skim Tier 3 cases (note JSON-shape issues only if they jump out).
6. Stop and ask Andreas if a finding suggests the captured output
   reflects a real bug (not just UX wart) — those need triage before
   you can write up the finding usefully.

## What you'll know when done

You're done when:

- BASELINE-AUDIT.md has 10–30 findings (my over/under).
- The Tier 1 cases (lyrics-generator) have been read line-by-line.
- Tier 2 cases have been read enough to spot the worst issues.
- You've added at least one new dimension I didn't think of (you'll
  see things I won't because I built these).

## What NOT to do

- Don't regenerate `expected-*.txt` files. The captures are the audit
  subject, not a moving target.
- Don't add new cases. The 63 cases are the corpus.
- Don't audit the `## Cache` block content of source workflows; you're
  auditing the **analyzer's output on those workflows**, not the
  workflows themselves.
- Don't try to read every JSON case. They're huge; the user
  de-prioritized them.
- Don't try to fix anything. Findings only.

## Reference

- The construction perspective: `PLAN.md`.
- Real workflow under test: `_shared/workflows/lyrics-generator/`.
- The 7 worked examples above are starting templates — you'll find
  more.
