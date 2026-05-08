# Lyrics Generator

Generate original song lyrics inspired by **non-song source material** — articles, YouTube talks, blog posts, personal notes, or any text that isn't already a song.

The pipeline explores **4 creative paths simultaneously**: it analyzes source material through 6 specialist lenses, generates 15 song concepts through 4 analytical lenses (judge picks top 4), enforces diversity (different genre families + 2+2 narrator split), curates a per-concept material palette for each song, then develops each into a complete song through independent parallel pipelines (creative direction → architecture → chorus-first writing → specialist reviews → deliberation-first revision).

Every stage of every path is saved to a numbered output folder for inspection, comparison, and learning across runs.

**Usage:**
```bash
# Single source
pflow workflows/lyrics-generator/lyrics-generator.pflow.md sources='["https://example.com/article"]'

# Multiple mixed sources (fetched in parallel)
pflow workflows/lyrics-generator/lyrics-generator.pflow.md \
  sources='["https://youtube.com/watch?v=...", "https://blog.com/post", "./notes.txt"]'

# Custom output location
pflow workflows/lyrics-generator/lyrics-generator.pflow.md \
  sources='["https://example.com"]' output_base="./experiments"
```

## Inputs

### sources

One or more source materials to draw inspiration from. Each element can be any type supported by the `fetch-source` sub-workflow:

* `"https://youtube.com/watch?v=..."` — YouTube video transcript
* `"https://example.com/article"` — web page content
* `"./path/to/notes.txt"` — local file
* `"Raw text about any topic"` — literal text

Multiple sources produce richer results — the pipeline finds **connections and tensions** between them that wouldn't exist in any single source.

- type: array
- required: true

### output_base

Base directory for numbered output folders. Each run creates a new folder like `0001-20260315-1428/` containing all pipeline stage outputs.

- type: string
- required: false
- default: "./output"

## Steps

### fetch-sources

**Fan-out:** Fetch content from all sources in parallel. Each source is routed through the `fetch-source` sub-workflow, which detects the source type and uses the appropriate fetcher (yt-dlp, Jina Reader, file read, or text passthrough).

* `error_handling: continue` — if one source fails (e.g., YouTube with no transcript), the pipeline continues with the remaining sources rather than aborting

- type: workflow
- workflow: ./fetch-source/fetch-source.pflow.md
- inputs:
    source: ${item}
- batch:
    items: ${sources}
    parallel: true
    error_handling: continue

### analyze-sources

**Fan-out:** Analyze each source through **6 specialist analysts in parallel** via the `analyze-source` sub-workflow. Each source gets 6 dedicated LLM calls (emotional depth, sensory details, themes/angles, narrative/scenes, language/musicality, voice/tone/humor), ensuring every dimension gets deep, focused attention.

This is the last step that sees the raw source material — everything downstream works from these analyses. Anything the specialists miss is lost to the songwriter forever.

* `error_handling: continue` — if one source's analysis fails, the pipeline continues with the others

- type: workflow
- workflow: ./analyze-source/analyze-source.pflow.md
- inputs:
    content: ${item.content}
- batch:
    items: ${fetch-sources.results}
    parallel: true
    error_handling: continue

### validate-sources

Abort the pipeline if no sources were successfully fetched and analyzed. Without source material, the entire pipeline would generate songs from nothing.

- type: code
- inputs:
    fetch_results: ${fetch-sources.results}
    fetch_errors: ${fetch-sources.error_count}
    analyze_results: ${analyze-sources.results}
    analyze_errors: ${analyze-sources.error_count}
    source_count: ${sources}

```python code
fetch_results: list
fetch_errors: int
analyze_results: list
analyze_errors: int
source_count: list

total = len(source_count)
fetched = total - fetch_errors
analyzed = total - analyze_errors

if fetched == 0:
    raise RuntimeError(f"All {total} source(s) failed to fetch. Cannot proceed without source material.")

if analyzed == 0:
    raise RuntimeError(f"All {total} source(s) failed analysis. Fetched {fetched} but none could be analyzed.")

result: str = f"{analyzed}/{total} sources ready"
```

### format-all-analyses

Combine all per-source analysis results into a single readable string. This serves as input to the concept-chooser's Full lens and to enforce-diversity for context.

- type: code
- inputs:
    validate: ${validate-sources.result}
    analyze_results: ${analyze-sources.results}

```python code
validate: str
analyze_results: list

items = analyze_results if isinstance(analyze_results, list) else [analyze_results]
combined = ""
for i, a in enumerate(items):
    text = ""
    if isinstance(a, dict):
        response = a.get("response", a)
        if isinstance(response, dict):
            text = response.get("analysis", "")
            if not text:
                for k, v in response.items():
                    if isinstance(v, str) and len(v) > 200:
                        text = v
                        break
        if not text and isinstance(response, str):
            text = response
    if not text:
        text = str(a)
    if len(items) > 1:
        combined += f"# Source {i + 1}\n\n{text}\n\n---\n\n"
    else:
        combined += text

result: str = combined
```

### choose-concepts

**Generate-many-pick-best for concepts.** Generates 15 song concepts through 4 analytical lenses (Heart, Mind, Body, Full Brief), each requiring a character who wants/fears/needs something. A judge selects the top 4 using a hard gate (no character with a want = rejected) and scoring on stranger test, replay value, emotional immediacy, and depth over breadth.

The key creative principle: source material is INSPIRATION, not SUBJECT. Every concept is about a universal human experience that the source illuminates, using the source's imagery as metaphorical language.

- type: workflow
- workflow: ./concept-chooser/concept-chooser.pflow.md
- inputs:
    analyses: ${analyze-sources.results}
    brief: ${format-all-analyses.result}

### enforce-diversity

Review all 4 concepts together and assign diversity constraints — different genre families and narrator perspectives — so the pipeline explores genuinely different creative territory rather than 4 variations on the same idea.

**Genre:** Full enforcement — no two songs in the same genre family.
**Narrators:** 2+2 split — 2 concepts keep the most natural narrator, 2 get deliberately non-obvious perspectives that reveal something the obvious narrator can't. Wild card narrators must be people who CARE about someone in the song — not metaphorical devices or observation points.
**Source emphasis:** For multi-source runs, considers whether different concepts should emphasize different sources.

- type: workflow
- workflow: ./enforce-diversity/enforce-diversity.pflow.md
- inputs:
    concepts: ${choose-concepts.selected_concepts}
    analysis: ${format-all-analyses.result}

### prepare-brief-inputs

Split the 6 specialist analyses into individually labeled sections and build per-concept items for the brief generation step. Each analysis is presented separately so the brief-maker can engage with what each specialist uniquely offers.

- type: code
- inputs:
    raw_sources: ${fetch-sources.results}
    analyses_text: ${format-all-analyses.result}
    selected: ${choose-concepts.selected_concepts}
    enriched: ${enforce-diversity.concepts}
    reservations: ${enforce-diversity.reserved_material}

```python code
raw_sources: list
analyses_text: str
selected: list
enriched: list
reservations: list | None

import re

# Combine raw source content
raw_items = raw_sources if isinstance(raw_sources, list) else [raw_sources]
raw_source = ""
for i, src in enumerate(raw_items):
    content = src.get("content", str(src)) if isinstance(src, dict) else str(src)
    if len(raw_items) > 1:
        raw_source += f"# Source {i + 1}\n\n{content}\n\n---\n\n"
    else:
        raw_source += content

# Split analyses into individual specialist sections
raw_sections = re.split(r'(?=^## )', analyses_text, flags=re.MULTILINE)

sections = {
    'emotional': [],
    'sensory': [],
    'themes': [],
    'narrative': [],
    'musicality': [],
    'voice_tone': []
}

for s in raw_sections:
    s = s.strip()
    if not s:
        continue
    header = s.split('\n')[0]
    if 'Emotional' in header:
        sections['emotional'].append(s)
    elif 'Sensory' in header:
        sections['sensory'].append(s)
    elif 'Theme' in header or 'Angle' in header:
        sections['themes'].append(s)
    elif 'Narrative' in header:
        sections['narrative'].append(s)
    elif 'Language' in header or 'Musicality' in header:
        sections['musicality'].append(s)
    elif 'Voice' in header or 'Tone' in header or 'Humor' in header:
        sections['voice_tone'].append(s)

# Normalize reservations to a list of dicts; empty or missing is valid.
reservations_list = reservations if isinstance(reservations, list) else []

# Build per-concept items
labels = "ABCDEFGHIJ"
per_concept_items = []
for i, c in enumerate(selected):
    label = labels[i] if i < len(labels) else str(i)
    if isinstance(c, dict) and i < len(enriched) and isinstance(enriched[i], dict):
        e = enriched[i]
        title = c.get('title', 'Untitled')
        concept_md = f"## Concept {label}: {title}\n\n"
        concept_md += f"**Emotional core**: {c.get('core_idea', '')}\n\n"
        concept_md += f"**Mode of engagement**: {c.get('mode_of_engagement', '')}\n\n"
        concept_md += f"**Listener pitch**: {c.get('why_compelling', '')}\n\n"
        concept_md += f"**Source imagery**: {c.get('source_imagery', '')}\n\n"
        concept_md += f"**Genre family**: {e.get('genre_family', '')}\n\n"
        concept_md += f"**Narrator**: {e.get('narrator_hint', '')} ({e.get('narrator_type', '')})\n\n"
        concept_md += f"**Reasoning**: {e.get('reasoning', '')}\n\n"

        # Gather reservations owned by OTHER concepts — these are forbidden material for this brief.
        others = [r for r in reservations_list if isinstance(r, dict) and r.get('assigned_to', '').strip() != title.strip()]
        if others:
            others_md = ""
            for r in others:
                moment = r.get('moment', '').strip()
                owner = r.get('assigned_to', '').strip()
                reason = r.get('reasoning', '').strip()
                others_md += f"- **{moment}** — reserved for \"{owner}\". {reason}\n"
        else:
            others_md = "(None — no cross-concept reservations were made for this run.)"

        per_concept_items.append({
            "label": label,
            "title": title,
            "concept_md": concept_md,
            "others_reserved_material": others_md
        })

result: dict = {
    "raw_source": raw_source,
    "analysis_emotional": "\n\n".join(sections['emotional']) or "No emotional analysis available.",
    "analysis_sensory": "\n\n".join(sections['sensory']) or "No sensory analysis available.",
    "analysis_themes": "\n\n".join(sections['themes']) or "No themes analysis available.",
    "analysis_narrative": "\n\n".join(sections['narrative']) or "No narrative analysis available.",
    "analysis_musicality": "\n\n".join(sections['musicality']) or "No musicality analysis available.",
    "analysis_voice_tone": "\n\n".join(sections['voice_tone']) or "No voice/tone analysis available.",
    "items": per_concept_items
}
```

### curate-briefs

Generate a per-concept material palette for each selected concept in parallel. Each brief is tailored to the concept's emotional core, genre, and narrator — providing metaphor mappings, kill moments, the unsaid, contradictions, recognition moments, narrator's blind spot, vocabulary, and scenes.

- type: llm
- temperature: 0.5
- reasoning_effort: medium
- timeout: 300
- prompt: ./curate-concept-brief-single.prompt.md
- inputs:
    concept_md: ${item.concept_md}
    others_reserved_material: ${item.others_reserved_material}
- batch:
    items: ${prepare-brief-inputs.result.items}
    parallel: true

### zip-concepts-with-briefs

Pair each enriched concept with its generated per-concept brief for the song-creator batch.

- type: code
- inputs:
    enriched: ${enforce-diversity.concepts}
    brief_results: ${curate-briefs.results}

```python code
enriched: list
brief_results: list

zipped = []
for i, concept in enumerate(enriched):
    brief_text = ""
    if i < len(brief_results) and isinstance(brief_results[i], dict):
        brief_text = brief_results[i].get("response", "")
    item = {"concept_brief": brief_text}
    if isinstance(concept, dict):
        item.update(concept)
    zipped.append(item)

result: list = zipped
```

### create-songs

**Fan-out:** Develop each concept into a complete song through the `song-creator` sub-workflow. Each concept gets its own per-concept material palette. The song-creator runs: creative direction → architecture → easter eggs → chorus-first writing → two-phase review/rewrite (emotional architecture, then craft polish) → verification → Suno prompt.

* `error_handling: continue` — if one concept path fails, the others still complete

- type: workflow
- workflow: ./song-creator/song-creator.pflow.md
- inputs:
    concept: ${item}
    concept_brief: ${item.concept_brief}
- batch:
    items: ${zip-concepts-with-briefs.result}
    parallel: true
    error_handling: continue

### prepare-evaluation

Format all finished songs for blind evaluation. Each song is presented with only the Creative Direction Summary (the 5 final decisions — genre, voice, contrast, audience, register) and its easter egg list (for verification). The full creative direction exploration (3-genre deliberation, narrator development, reasoning) is stripped — a listener only experiences the final sonic direction, and the evaluator should judge the same way.

- type: code
- inputs:
    songs: ${create-songs.results}

```python code
songs: list

labels = "ABCDEFGHIJ"
sections = []
for i, song in enumerate(songs):
    label = labels[i] if i < len(labels) else str(i)
    if isinstance(song, dict):
        creative_dir_full = song.get("creative_direction_text", "Not available")
        lyrics = song.get("finished_song", "Not available")
        easter_eggs = song.get("easter_eggs_text", "Not available")

        # Extract only the Creative Direction Summary for unbiased evaluation.
        # The full exploration (3-genre deliberation, narrator development) would
        # bias the evaluator — a listener only experiences the final decisions.
        summary_marker = "## Creative Direction Summary"
        if summary_marker in creative_dir_full:
            creative_dir = creative_dir_full[creative_dir_full.index(summary_marker):]
        else:
            creative_dir = creative_dir_full
    else:
        creative_dir = "Not available"
        lyrics = str(song)
        easter_eggs = "Not available"

    sections.append(
        f"## Song {label}\n\n"
        f"### Creative Direction\n\n{creative_dir}\n\n"
        f"### Lyrics\n\n{lyrics}\n\n"
        f"### Easter Eggs to Verify\n\n{easter_eggs}"
    )

result: str = "\n\n---\n\n".join(sections)
```

### evaluate-songs

Compare all finished songs and rank them with letter grades (A through D). The evaluator grades against "would a stranger put this on repeat?" — not cleverness, not craft sophistication. The bar is real songs people love, not "good for AI-generated."

Genre context is provided (a listener would hear the genre in the music). Easter egg lists are provided for verification. Creative rationale and arc plans are deliberately withheld — if the evaluator needs to read a paragraph explaining why the bridge works, the bridge doesn't work.

- type: llm
- temperature: 0.3
- prompt: ./evaluate-songs.prompt.md

### build-file-list

Construct the complete list of files to save. Formats raw batch results into readable markdown, organizes per-song outputs into labeled subdirectories (song-A/, song-B/, etc.), and generates metadata. Produces 6 shared files + 13 files per song (including concept brief) + evaluation + metadata.

- type: code
- inputs:
    output_base: ${output_base}
    sources_input: ${sources}
    sources_raw: ${fetch-sources.results}
    all_analyses: ${format-all-analyses.result}
    concepts: ${choose-concepts.selected_concepts}
    all_concepts: ${choose-concepts.all_concepts_text}
    concept_selection: ${choose-concepts.selection_text}
    enriched_concepts: ${enforce-diversity.concepts}
    reservations: ${enforce-diversity.reserved_material}
    concept_briefs: ${curate-briefs.results}
    songs: ${create-songs.results}
    evaluation: ${evaluate-songs.response}
    fetch_errors: ${fetch-sources.error_count}
    song_errors: ${create-songs.error_count}

```python code
output_base: str
sources_input: list
sources_raw: list
all_analyses: str
concepts: list
all_concepts: str
concept_selection: str
enriched_concepts: list
reservations: list | None
concept_briefs: list
songs: list
evaluation: str
fetch_errors: int
song_errors: int

import os
import glob
import json
from datetime import datetime

# Compute output directory right before saving
existing = sorted(glob.glob(os.path.join(output_base, "[0-9][0-9][0-9][0-9]-*")))
if existing:
    latest_num = int(os.path.basename(existing[-1])[:4])
else:
    latest_num = 0

next_num = f"{latest_num + 1:04d}"
timestamp = datetime.now().strftime("%Y%m%d-%H%M")
output_dir = os.path.join(output_base, f"{next_num}-{timestamp}")

files = []
labels = "ABCDEFGHIJ"

# 01 - Sources raw
raw_md = "# Raw Sources\n\n"
if isinstance(sources_raw, list):
    for i, src in enumerate(sources_raw):
        content = src.get("content", str(src)) if isinstance(src, dict) else str(src)
        raw_md += f"## Source {i + 1}\n\n{content}\n\n---\n\n"
else:
    raw_md += str(sources_raw)
files.append({"path": f"{output_dir}/01-sources-raw.md", "content": raw_md})

# 02 - Source analyses
files.append({"path": f"{output_dir}/02-source-analyses.md", "content": f"# Source Analyses\n\n{all_analyses}"})

# 03 - All concepts from all lenses (15 concepts for inspection)
files.append({"path": f"{output_dir}/03-concepts-all.md", "content": f"# All Concepts (15 from 4 lenses)\n\n{all_concepts}"})

# 04 - Concept selection (judge's ranking and reasoning)
files.append({"path": f"{output_dir}/04-concept-selection.md", "content": f"# Concept Selection\n\n{concept_selection}"})

# 05 - Selected concepts (the 4 picks, structured)
concepts_md = "# Selected Concepts\n\n"
for i, concept in enumerate(concepts):
    label = labels[i] if i < len(labels) else str(i)
    if isinstance(concept, dict):
        concepts_md += f"## Concept {label}: {concept.get('title', 'Untitled')}\n\n"
        concepts_md += f"**Emotional core**: {concept.get('core_idea', '')}\n\n"
        concepts_md += f"**Mode of engagement**: {concept.get('mode_of_engagement', '')}\n\n"
        concepts_md += f"**Listener pitch**: {concept.get('why_compelling', '')}\n\n"
        concepts_md += f"**Source imagery**: {concept.get('source_imagery', '')}\n\n"
        concepts_md += f"**Originating lens**: {concept.get('originating_lens', '')}\n\n---\n\n"
files.append({"path": f"{output_dir}/05-selected-concepts.md", "content": concepts_md})

# 06 - Diversity assignments
diversity_md = "# Diversity Assignments\n\n"
for i, ec in enumerate(enriched_concepts):
    label = labels[i] if i < len(labels) else str(i)
    if isinstance(ec, dict):
        diversity_md += f"## Concept {label}: {ec.get('title', 'Untitled')}\n\n"
        diversity_md += f"**Genre family**: {ec.get('genre_family', '')}\n\n"
        diversity_md += f"**Narrator**: {ec.get('narrator_hint', '')} ({ec.get('narrator_type', '')})\n\n"
        se = ec.get('source_emphasis', '')
        if se:
            diversity_md += f"**Source emphasis**: {se}\n\n"
        diversity_md += f"**Reasoning**: {ec.get('reasoning', '')}\n\n---\n\n"

reservations_list = reservations if isinstance(reservations, list) else []
diversity_md += "## Material Reservations\n\n"
if reservations_list:
    diversity_md += "Signature source moments reserved to a specific concept. Other concepts' briefs treat these as Forbidden Territory.\n\n"
    for r in reservations_list:
        if isinstance(r, dict):
            diversity_md += f"- **{r.get('moment', '').strip()}** — assigned to: {r.get('assigned_to', '').strip()}. {r.get('reasoning', '').strip()}\n"
else:
    diversity_md += "None — the enforcer judged no cross-concept reservations necessary for this run.\n"

files.append({"path": f"{output_dir}/06-diversity-assignments.md", "content": diversity_md})

# Per-song files
for i, song in enumerate(songs):
    label = labels[i] if i < len(labels) else str(i)
    song_dir = f"{output_dir}/song-{label}"

    # Per-concept brief
    if i < len(concept_briefs) and isinstance(concept_briefs[i], dict):
        brief_text = concept_briefs[i].get("response", "")
        files.append({"path": f"{song_dir}/00-concept-brief.md", "content": str(brief_text)})

    if isinstance(song, dict):
        stage_files = [
            ("01-creative-direction.md", "creative_direction_text"),
            ("02-song-architecture.md", "song_architecture_text"),
            ("03-easter-eggs.md", "easter_eggs_text"),
            ("04-chorus-options.md", "chorus_options_text"),
            ("05-chorus-selection.md", "chorus_selection_text"),
            ("06-lyrics-draft.md", "draft_lyrics"),
            ("07-emotional-reviews.md", "emotional_reviews"),
            ("08-emotional-deliberation.md", "emotional_rewrite_deliberation"),
            ("09-craft-reviews.md", "craft_reviews"),
            ("10-craft-deliberation.md", "revision_deliberation"),
            ("11-lyrics-final.md", "finished_song"),
            ("12-suno-prompt.md", "suno_style_prompt"),
        ]
        for filename, key in stage_files:
            content = song.get(key, "")
            files.append({"path": f"{song_dir}/{filename}", "content": str(content)})

# Evaluation
files.append({"path": f"{output_dir}/evaluation.md", "content": evaluation})

# Metadata
metadata = {
    "sources": sources_input,
    "source_count": len(sources_input),
    "concept_count": len(concepts),
    "songs_completed": len(songs) - song_errors,
    "fetch_errors": fetch_errors,
    "song_errors": song_errors,
    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "run_id": output_dir.split("/")[-1],
}
files.append({"path": f"{output_dir}/metadata.json", "content": json.dumps(metadata, indent=2)})

result: dict = {"files": files, "output_dir": output_dir}
```

### save-outputs

Save every file from the build-file-list to disk. This includes shared pipeline stages (sources, analyses, brief, concepts, diversity assignments), per-song subdirectories with all creative pipeline stages, the evaluation, and metadata.

- type: write-file
- file_path: ${item.path}
- content: ${item.content}
- batch:
    items: ${build-file-list.result.files}
    parallel: true

### build-report

Generate a concise summary report of the run — what was created, where it lives, and what each song is about. This is the workflow's terminal output.

- type: code
- inputs:
    output_dir: ${build-file-list.result.output_dir}
    enriched_concepts: ${enforce-diversity.concepts}
    songs: ${create-songs.results}
    song_errors: ${create-songs.error_count}
    file_list: ${build-file-list.result.files}

```python code
output_dir: str
enriched_concepts: list
songs: list
song_errors: int
file_list: list

labels = "ABCDEFGHIJ"
run_id = output_dir.split("/")[-1]
total_files = len(file_list)
total_songs = len(songs) - song_errors

lines = []
lines.append(f"Run {run_id}")
lines.append(f"{total_songs} songs, {total_files} files saved to {output_dir}/")
lines.append("")

for i, ec in enumerate(enriched_concepts):
    label = labels[i] if i < len(labels) else str(i)
    if not isinstance(ec, dict):
        continue

    title = ec.get("title", "Untitled")
    genre = ec.get("genre_family", "")
    narrator = ec.get("narrator_hint", "")
    narrator_type = ec.get("narrator_type", "")
    pitch = ec.get("why_compelling", "")
    type_tag = f" [{narrator_type}]" if narrator_type else ""

    # Extract hook (first non-empty line of winning chorus)
    hook = ""
    suno_prompt = ""
    if i < len(songs) and isinstance(songs[i], dict):
        chorus = songs[i].get("winning_chorus", "")
        if chorus:
            for line in chorus.split("\n"):
                line = line.strip()
                if line and not line.startswith("[") and not line.startswith("==="):
                    hook = line
                    break
        suno_prompt = songs[i].get("suno_style_prompt", "").strip()

    lines.append(f"Song {label}: \"{title}\" — {genre}")
    lines.append(f"  Narrator: {narrator}{type_tag}")
    if hook:
        lines.append(f"  Hook: \"{hook}\"")
    if suno_prompt:
        lines.append(f"  Style: {suno_prompt}")
    if pitch:
        lines.append(f"  Pitch: {pitch}")
    lines.append("")

if song_errors > 0:
    lines.append(f"⚠ {song_errors} song(s) failed")

result: str = "\n".join(lines)
```

## Outputs

### report

Summary of the run — songs created, genres, and output location.

- source: ${build-report.result}
