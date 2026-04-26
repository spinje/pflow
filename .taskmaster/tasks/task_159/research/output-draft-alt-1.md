Here's a mockup of `pflow analyze-cache` output on the lyrics-generator. I've used plausible token counts — actual numbers need a real trace. Structure and content are what we're deciding on.

````
$ pflow analyze-cache workflows/lyrics-generator/lyrics-generator.pflow.md \
    sources='["https://example.com/article"]'

═══════════════════════════════════════════════════════════════════════
 Cache Analysis — lyrics-generator.pflow.md
 1 source · 4 song concepts · ~181 LLM calls
═══════════════════════════════════════════════════════════════════════

 SUMMARY
   Estimated cost vs no-cache baseline (1h TTL):
     First run:          $2.18  →  $0.84    (-61%)
     Rerun (within 1h):  $2.18  →  $0.39    (-82%)

   Two biggest wins available:
     • Declare shared_context in song-creator    -$0.78 per run
     • Reorder score-choruses prompt             -$0.23 per run

   Issues requiring attention: 1 critical, 2 minor (see WARNINGS)

─── PER-CALL CACHE ANALYSIS ────────────────────────────────────────────

 Node                              Calls  Prefix   Tail   Cache  Status
 ─────────────────────────────────────────────────────────────────────
 analyze-sources/emotional             1  3,412    0     100%   ✓
 analyze-sources/sensory               1  3,412    0     100%   ✓
 analyze-sources/* (4 more)            4  3,412    0     100%   ✓
   ↳ All 6 specialists share the same {{content}}. First call
     writes, other 5 read. Pre-warm recommended (+2.3s, -$0.04).

 concept-chooser/generate-heart        1  3,890  842      82%   ✓
 concept-chooser/generate-* (3 more)   3  3,890  ~900     82%   ✓
 concept-chooser/select-concepts       1  4,120    0     100%   ✓

 curate-briefs                         4  2,450  ~380     87%   ✓

 song-creator × 4 parallel paths:

   creative-direction                  4    892    0     100%   ✓
   song-architecture                   4  2,104    0     100%   ✓
   easter-eggs                         4  2,850    0     100%   ✓
   chorus-chooser/generate             32 3,280 ~420      89%   ✓
   chorus-chooser/score              136    87 1,803       4%   ⚠⚠
   chorus-chooser/select-chorus        4  2,980    0     100%   ✓
   write-lyrics                        4  8,440    0     100%   ✓
   reviews/emotional-architecture      4  3,120    0     100%   ✓
   reviews/narrative                   4  2,810    0     100%   ✓
   reviews/imagery                     4  2,640    0     100%   ✓
   reviews/stranger-summary            4    640    0     100%   ✓
   rewrite-emotional                   4 10,200    0     100%   ✓
   reviews/ai-tells                    4  2,810    0     100%   ✓
   reviews/cliche                      4  2,640    0     100%   ✓
   reviews/genre                       4  3,410    0     100%   ✓
   rewrite-craft                       4 11,480    0     100%   ✓
   generate-suno-prompt                4  1,840    0     100%   ✓

 evaluate-songs                        1  8,920    0     100%   ✓

─── SHARED CONTEXT (cross-call reuse) ──────────────────────────────────

 No shared_context declared. Detected high-value opportunities:

 ▸ song-creator subflow (per-path, runs 4× in parallel)

   These outputs are re-pasted into many downstream prompts.
   Each prompt today has its own role header, so the prefixes
   diverge and cross-prompt caching doesn't fire.

   Candidate          Size      Reuses  Would save
   ──────────────────────────────────────────────────
   ${concept}           ~620 tok   12        8,370 tok
   ${concept_brief}   ~3,100 tok    9       27,900 tok
   ${creative-direction.response}
                      ~2,400 tok   11       26,400 tok
   ${song-architecture.response}
                      ~1,900 tok    7       13,300 tok
   ${easter-eggs.response}
                      ~1,200 tok    4        4,800 tok
   ──────────────────────────────────────────────────
   Total redundant input per song path:     80,770 tok
   × 4 parallel paths:                     323,080 tok

   Recommended TTL: 1h  (max reuse gap: 8.4 min)
   Estimated savings if declared:  -$0.78 per run

   Suggested addition to song-creator.pflow.md:

     shared_context:
       - value: ${concept}
       - value: ${concept_brief}
       - value: ${creative-direction.response}
         ttl: 1h
       - value: ${song-architecture.response}
         ttl: 1h
       - value: ${easter-eggs.response}
         ttl: 1h

     # Then on each downstream LLM node:
     # shared_context: [concept, concept_brief, creative-direction,
     #                  song-architecture, easter-eggs]

─── BATCH PRE-WARMING ──────────────────────────────────────────────────

 When N parallel calls share a prefix, firing them simultaneously
 means all N pay cache-write cost (1.25×) instead of 1 write + N-1
 reads (0.1×). Pre-warming fires the first call, waits, then fans
 out. Cost: one call's latency. Savings scale with N.

   analyze-sources         N=6    +2.3s latency   -$0.04
   concept-chooser/gen     N=4    +3.1s latency   -$0.02
   curate-briefs           N=4    +2.1s latency   -$0.01
   chorus-chooser/generate N=8    +3.8s latency   -$0.06
   emotional-reviews       N=4    +2.9s latency   -$0.02
   craft-reviews           N=3    +2.7s latency   -$0.01

   Total pre-warm savings:  -$0.16 per run   (+~18s total latency)

─── WARNINGS ───────────────────────────────────────────────────────────

 ⚠⚠ CRITICAL  song-creator/chorus-chooser: score-choruses
    File:   chorus-chooser.pflow.md (inline prompt @ build-scoring-items)
    Cache:  4% (87 of 1,890 tok)
    Issue:  {{chorus_text}} appears at line 3 of the prompt.
            Scoring rubric (~1,640 tok, stable across all 136 scorings
            of a song path) falls AFTER the dynamic value, so nothing
            caches beyond the opening sentence.
    Fix:    Move "## The Chorus\n{chorus_text}" section to END of
            prompt, after rubric + output format.
            Projected cache ratio post-fix: 87% → -$0.23 per run
    Impact: ~136 calls per song path × 4 paths = 544 calls affected

 ⚠ MINOR  curate-briefs: {{concept_md}} at line 12
    Cache:  87% — already good. Moving the 2 label lines above
            {{concept_md}} down would push this to 94%. Low priority.

 ⚠ MINOR  generate-suno-prompt: prompt contains {{creative_direction}}
    inline. Template is stable within a song path, so this caches
    fine — flagged because the prompt file is unusually short
    (1,840 tok) and won't hit the 1024 minimum on Haiku if you
    ever switch models.

─── NOTES ──────────────────────────────────────────────────────────────

 • Shared context for song-creator is per-invocation (4 separate
   cache entries, one per song path). No cross-path sharing since
   each path has unique concept/brief.
 • 1h TTL costs 2× on write, 0.1× on read. Break-even at 3 reads.
   All declared shared_context items above exceed that threshold.
 • This plan assumes current prompt text. Editing a prompt file
   invalidates the cache for all nodes using it.

 Re-run this analysis after edits with:  pflow analyze-cache --diff
````

## Specific things I want your reaction to

1. **Top summary is "two biggest wins" + dollar amounts.** Is that the right first thing to see, or would you want something else up top?

2. **Per-call table granularity.** I've shown every node. For a 181-call workflow this table is already ~30 rows. Should it collapse clean (100%) nodes by default and expand on a flag?

3. **The shared_context suggestion embeds concrete YAML to paste.** This is the most agent-friendly part IMO — warning + exact fix. Does that feel right, or too prescriptive?

4. **Warnings in a dedicated section vs inline in the per-call table?** I put them both places (⚠ in table, details below). Might be redundant.

5. **"Suggested addition" syntax assumes the shared_context design from last turn.** The mockup is implicitly committing to a design. Is that OK for this exercise, or should I produce a version that's syntax-agnostic (e.g., shows "~$0.78/run savings available via shared context" without showing HOW)?

6. **Missing anything?** Things I considered but didn't include:
   - Per-provider cost breakdown (Anthropic vs Gemini vs OpenAI)
   - Cache-hit projections over time (1st/2nd/3rd run)
   - Graph visualization of what flows where
   - JSON output mode for machine consumption

What lands, what doesn't?