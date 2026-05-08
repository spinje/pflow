# Baseline Findings — Task 159

> Cases where the system's observed behavior differs from spec or where an
> adversarial input *succeeded* when it should have been rejected. Each entry
> is for Andreas to triage; the baseline captures current behavior either way.

---

## F-01 — Parser silently accepts two `${var}` on one prose line

**Case**: `01-parser-errors/03-two-vars-in-chunk/`

**Spec text** (`task-159.md` § "## Cache Block Parsing"):

> **Exactly one `${var}` per chunk.** Two or more `${var}` in a chunk is a
> syntax error (prose should describe its value, not contain further template
> references).

**Observed behavior**: A cache block containing
`The article ${article} is about ${topic}.` is silently accepted. The parser
splits the line into two valid chunks (`article` and `topic`) — by
construction of the chunking algorithm (`[prose-before-var, ${var}]` pairs),
every chunk has exactly one var. The "two vars in a chunk" error described in
the spec is unreachable from a `.pflow.md` source file.

**Severity guess**: spec-vs-impl mismatch. Either:

- (a) The parser is correct and the spec wording should be updated to clarify
  that the chunker itself enforces one-var-per-chunk by construction.
- (b) The parser should detect *adjacent* `${a}${b}` (no prose between) or
  `${a} <whitespace> ${b}` (intra-line) as a special case and reject — to
  catch authors who *intended* a single chunk.

The current behavior produces small individual chunks that may fall below the
provider min-cache threshold (each split chunk's prose-before-var is whatever
prose preceded that var, so multi-var lines produce small chunks). Authors
hitting this pattern may silently get sub-threshold cache content and a
`cache.below-min-tokens` warning rather than a clear "you wrote two vars in
one chunk" error.

**Mutation contract**: case `03-two-vars-in-chunk/expected-stdout.txt` locks
the current parser-splits-silently behavior. If Task 160 changes chunking and
starts rejecting this pattern, the case fails — surfacing the behavior change
for review.

---
## F-02 — 5 catalog warning IDs need more elaborate fixtures to fire

**Cases**: `04-warning-catalog/06`, `07`, `08`, `12`, `14`, `19`.

The minimal fixtures in this baseline successfully trigger 15 of 20 catalog
warnings. The remaining 5 require more elaborate setups that the implementing
agent for surfaces 06+ (or a future contributor) should extend.

| ID | What's missing |
|---|---|
| `cache.batch-prewarm-recommended` | Needs a batch-prompt with a long static prefix (≥ provider min-cache) before the first `${item.X}` reference, plus savings_ratio ≥ 5%. The current fixture has the prefix but the analyzer still doesn't fire — likely because partial batch-input resolution drops below threshold. Try inline `items: [...]` that's long enough. |
| `cache.dynamic-before-static` | Needs a node prompt where a `${var}` appears near the top and a long stable section follows. The detector likely checks token positions; current fixture may not pass length thresholds. |
| `cache.padding-advisory` | Needs producer + consumer with subset overlap + threshold cleared. Sensitivity floors ($0.005 per advisory, $0.05 cumulative) suppress until savings are large enough. |
| `cache.discrepancy` | Marked TODO. Needs a recorded trace where the analyzer's predicted memo config-hash diverges from the engine's actual `event["cache_key"]`. Easiest reproduction: record run, edit IR, record again, analyze second trace. |
| `cache.consolidate-to-root-recommended` | Needs `${dict.field1}` and `${dict.field2}` in `## Cache` where each sub-path is below provider min but `${dict}` would clear it. Current fixture passes long fields but consolidation suggestion may need the parent value to be available via params resolution. |
| `cache.prompt-body-shadows-cache` | Subtle distinction from `prompt-body-duplicates-cache`. Shadows fires when the prompt body uses an identifier that overlaps WITH cache namespace BUT under different binding. Current fixture triggers `duplicates` instead. Probably needs a node output named `article` in addition to the input named `article`. |

**Mutation contract for the case folders**: each captures the analyzer's
*current* output. If a future change makes any of these IDs start firing on
the existing fixture, the case fails — surfacing the behavior change for
review. So the baseline case is still load-bearing as a regression gate, even
when the target ID isn't yet hit.

---

## F-03 — `pflow guide <workflow>` auto-detect misses `caching` topic on cache-using workflows

**Case**: `12-real-world-lyrics-generator/04-guide-auto-detect/`

**Observed**: running `pflow guide ./lyrics-generator/lyrics-generator.pflow.md`
on a workflow tree where 8 nodes across the tree use `prompt_cache:` and
sub-workflow song-creator declares a 5-chunk `## Cache` block. The
auto-detected topics are: `Batch`, `Code`, `File`, `LLM`, `Sub-Workflows`,
`To Uppercase`. **`Caching` is NOT detected.**

**Verified directly on song-creator.pflow.md** (the file that DOES declare
`## Cache`): same omission. Auto-detect doesn't fire on the `## Cache`
keyword inside the workflow body.

**Spec implication**: per Task 159, agents are supposed to learn about
caching by `pflow guide caching`. The auto-detect surface (which the CLI
help promotes as "auto-detects relevant topics") doesn't connect agents to
that topic when their workflow uses it heavily.

**Suggested fix**: extend the workflow scanner in `pflow guide`'s
auto-detect path to look for `## Cache` blocks AND `prompt_cache:`
keywords AND walk into sub-workflow files. The `caching` topic should
surface for any workflow tree that contains those signals.

**Severity guess**: medium — affects every agent who uses `pflow guide
<workflow>` to onboard themselves to a cache-using project.

---

## F-04 — `cache.below-min-tokens` false-positive on greenfield analysis when chunks resolve to LLM responses

**Cases**: `12-real-world-lyrics-generator/01-analyze-cache-text/` (5
warnings on real lyrics-generator), `14-pitfall-19-defenses/01-dotted-path-chunk/`
(synthetic reproduction).

**Observed**: an LLM node with `prompt_cache: [upstream-llm.response]`
gets `cache.below-min-tokens` warnings on greenfield analysis (no run
history). The analyzer computes the chunk's token count from the literal
`${upstream-llm.response}` template string (~5 tokens), not from the
actual response content (which would be hundreds or thousands of tokens
once the upstream node runs).

On the real lyrics-generator, this produces 5 below-min-tokens warnings
that an agent reading the analyzer output would interpret as "my caching
won't fire." But once the workflow runs once and memo cache is populated,
re-running analyze-cache shows the real numbers and the warning
disappears.

**Why this is bad agent UX**: agents inspecting their workflow before
running it get told caching is broken. They invest time consolidating
chunks or adding padding. After the first run, the report tells them
those chunks were always large enough — the changes were unnecessary.

**Suggested fix**: when a chunk's `${var}` resolves through a node-output
path (not an input path), the analyzer should label its size as
`unavailable` rather than estimate from the literal template string.
Honest-unmeasurable convention applies (DD established pattern).
Alternatively: emit `cache.below-min-tokens` only when token data has at
least Tier-2 (memo) confidence, suppressing on Tier-3/4 alone.

**Severity guess**: medium — wastes agent time on first-encounter
workflows and undermines trust in the analyzer's other findings.

---

## F-05 — `pflow visualize` validates before rendering, blocking on unrelated unknown-node-types

**Case**: `12-real-world-lyrics-generator/05-visualize-mermaid/`
(originally targeted parent; redirected to song-creator after this finding).

**Observed**: running `pflow visualize` on the lyrics-generator parent
fails with:

```
Error: Validation Error
In step 'fetch-sources' sub-workflow: Unknown node type: 'mcp-klavis-youtube-get_youtube_video_transcript'
```

The mermaid graph generator can't render workflows whose sub-workflows
contain MCP node types that the current environment hasn't registered.
But mermaid rendering is read-only and topology-only — it doesn't need
nodes to be valid to draw boxes.

**Suggested fix**: bypass full validation in `pflow visualize`. Walk the
graph topologically and render unknown node types as opaque shapes (with
a warning footnote). Pflow already has a `classDef mcp` style class —
unknown MCP nodes can render in that style without validation.

**Severity guess**: low — workaround is "visualize the sub-workflow that
uses LLM only." But it's an avoidable obstacle when an agent wants to see
the full architecture of a workflow tree they're working on.
