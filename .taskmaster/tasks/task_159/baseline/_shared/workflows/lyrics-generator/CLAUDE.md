# Lyrics Generator Pipeline

## Usage

```bash
# Single source
pflow workflows/lyrics-generator/lyrics-generator.pflow.md sources='["https://example.com/article"]'

# Multiple mixed sources
pflow workflows/lyrics-generator/lyrics-generator.pflow.md sources='["https://youtube.com/watch?v=...", "https://blog.com/post", "./notes.txt", "raw text here"]'
```

Each run produces a numbered output folder (`output/0001-20260315-1428/`) with every pipeline stage saved as a separate file.

## Pipeline Architecture

```
sources[] → batch fetch-source (parallel, sub-workflow)
               ├─ YouTube: yt-dlp → on-error → Klavis MCP fallback
               ├─ Webpage: Jina Reader (r.jina.ai)
               ├─ File: read from disk
               └─ Raw text: passthrough
          → validate sources (fail-fast if zero fetched)
          → batch analyze-source (parallel, sub-workflow)
               └─ 6 specialists per source:
                    emotional, sensory/vocabulary, themes/angles, narrative/scenes, musicality, voice/tone/humor
          → format all analyses (code, combine into single string)
          → concept-chooser (sub-workflow)
               ├─ parse analyses into 3 lenses (Heart/Mind/Body)
               ├─ generate 15 concepts (3+3+3+6 from 4 lenses, parallel, temp 0.9)
               │    └─ each concept requires character + want (who is singing, what they desire/fear)
               ├─ judge selects top 4 (temp 0.3, character/want hard gate)
               └─ structure for downstream compatibility
          → enforce diversity (assign genre families + narrator 2+2 split)
               └─ wild card narrators must be people who CARE about someone in the song
          → curate per-concept briefs (batch LLM, 4 parallel)
               └─ each brief tailored to concept's emotional core, genre, narrator:
                    source imagery, metaphor mappings, kill moments, the unsaid,
                    contradictions, recognition moments, narrator's blind spot,
                    vocabulary with jargon transformations, human scenes
          → batch song-creator (parallel, sub-workflow, one per concept)
               ├─ creative direction (6 decisions incl. language)
               ├─ song architecture (narrative arc + musical structure)
               ├─ easter eggs (meaning-over-structure, constraint self-audit)
               ├─ chorus-chooser (sub-sub-workflow)
               │    ├─ generate ~34 chorus options (13 creative lenses × 2 models, grouped)
               │    ├─ score each individually (1-5 rubric, 6 dimensions, blind stranger test)
               │    ├─ rank by score, top 8 to judge
               │    └─ judge picks winner + 2 runners-up (stranger test is top criterion)
               ├─ write lyrics (Suno format, palette instructions, max 2 images/verse, builds around chorus)
               ├─ Phase 1: emotional architecture + legibility reviews (4 parallel, sub-workflows)
               │    └─ emotional-architecture (Kill Moments, Unsaid, Blind Spot) + narrative + imagery
               │       + stranger-summary (context-free legibility check — lyrics only)
               ├─ Phase 1: emotional/legibility rewrite (structural — move sections, fix Blind Spot confessions, add setup for unintroduced characters or unnamed conflicts)
               ├─ Phase 2: craft reviews (3 parallel, sub-workflows)
               │    └─ AI tells + clichés + genre authenticity
               ├─ Phase 2: craft rewrite (line-level — clichés, syllables, rhyme, Suno tags)
               └─ generate suno prompt (GMIV style prompt)
          → prepare evaluation (Creative Direction Summary only, no deliberation bias)
          → evaluate songs (calibrated, letter grades A-D, stranger replay test)
          → save all outputs (60 files per run)
```

Cost: ~$1.80 per run. Time: ~380 seconds. LLMs: Gemini Flash (default), Gemini Flash Lite (chorus generation). Temperature: 0.9 creative / 0.3 analytical / 0.5 mixed / 0.4 revision. Reasoning effort: none for creative generation, low for chorus scoring, medium for brief curation and craft rewrite, high for emotional rewrite. 4 songs produced per run.

## File Structure

```
lyrics-generator.pflow.md             # Main orchestrator
curate-concept-brief-single.prompt.md # Per-concept material palette prompt
enforce-diversity.prompt.md
evaluate-songs.prompt.md
concept-chooser/                      # Concept generation + lens-based selection
  concept-chooser.pflow.md            # 15 concepts from 4 lenses, judge picks 4 (5 nodes)
  generate-concepts-heart.prompt.md
  generate-concepts-mind.prompt.md
  generate-concepts-body.prompt.md
  generate-concepts-full.prompt.md
  select-concepts.prompt.md
song-creator/
  song-creator.pflow.md              # Per-concept creative pipeline
  creative-direction.prompt.md
  song-architecture.prompt.md
  easter-eggs.prompt.md
  write-lyrics.prompt.md
  specialist-reviews-*.prompt.md     # 7 review prompts (emotional-architecture, narrative, imagery, stranger-summary, ai-tells, cliche, genre)
  rewrite-emotional.prompt.md        # Phase 1: structural/emotional rewrite
  rewrite-craft.prompt.md            # Phase 2: line-level craft polish
  generate-suno-prompt.prompt.md
  reviews/                           # 7 standalone review sub-workflows (callable by pipeline AND agents)
    review-emotional-architecture.pflow.md
    review-narrative.pflow.md
    review-imagery.pflow.md
    review-stranger-summary.pflow.md # Context-free: takes only lyrics, returns CLEAR/PARTIAL/OPAQUE verdict
    review-ai-tells.pflow.md
    review-cliche.pflow.md
    review-genre.pflow.md
  chorus-chooser/
    chorus-chooser.pflow.md           # Chorus generation + scoring + selection (8 nodes)
    select-chorus.prompt.md
analyze-source/
  analyze-source.pflow.md            # 6 specialist analysts
  analyze-*.prompt.md                # 6 analyst prompts
fetch-source/
  fetch-source.pflow.md             # Source fetching with type detection
```

All LLM prompts are external `.prompt.md` files named after the node using them. Workflow files are clean architecture; prompt files are the actual LLM instructions.

## Output Structure

```
output/NNNN-YYYYMMDD-HHMM/
  01-sources-raw.md
  02-source-analyses.md
  03-concepts-all.md              # All 15 concepts from 4 lenses
  04-concept-selection.md         # Judge's ranking and reasoning
  05-selected-concepts.md         # The 4 picks
  06-diversity-assignments.md
  song-A/
    00-concept-brief.md             # Per-concept material palette
    01-creative-direction.md
    02-song-architecture.md
    03-easter-eggs.md
    04-chorus-options.md            # All ~34 choruses ranked with scores
    05-chorus-selection.md          # Judge's reasoning and picks
    06-lyrics-draft.md
    07-emotional-reviews.md         # Phase 1: emotional architecture + narrative + imagery + stranger-summary
    08-emotional-deliberation.md    # Phase 1: structural rewrite reasoning
    09-craft-reviews.md             # Phase 2: AI tells + clichés + genre
    10-craft-deliberation.md        # Phase 2: line-level polish reasoning
    11-lyrics-final.md
    13-suno-prompt.md               # Suno AI style prompt (GMIV format)
  song-B/  (same structure)
  song-C/  (same structure)
  song-D/  (same structure)
  evaluation.md
  metadata.json
```

## Conventions

- **New source types** go in `fetch-source/fetch-source.pflow.md` — add a branch in `classify`, add a fetch node, add to the `??` coalesce chain
- **New review types** — create a sub-workflow in `reviews/` with the same pattern as existing ones (inputs → single LLM node → output)
- **pflow descriptions** use `*` for bullets, `-` is reserved for parameters
- **pflow `- inputs:`** works on LLM nodes — maps variable names to external prompt template variables
- **Review prompt variables** use generic names (`${lyrics}`, `${creative_direction}`, `${song_architecture}`, `${concept_brief}`) — not node-specific names — so they work in both the pipeline and standalone

