# Chorus Chooser

Generate chorus options through 13 creative lenses × 2 models (plus unconstrained "from the heart" at the end of each group), score them individually against a rubric (with stranger test in hook_strength), rank by score, and have a judge select the winner + 2 runners-up from the top 8. The judge's most important criterion is the stranger test: would someone hearing only this chorus feel something?

Used as a **sub-workflow** by `song-creator.pflow.md`, called once per song between the easter-eggs and write-lyrics steps.

**The approach:** Each model gets the 13 lenses randomly shuffled into 4 groups of [3,3,3,4]. Each group ends with an unconstrained chorus — the LLM writes "from the heart" after exploring the constrained lenses, benefiting from the creative warm-up. Different models bring different creative voices. The randomized groupings mean different creative cross-pollination each run.

## Inputs

### concept

The core concept for this song, including diversity assignments.

- type: object
- required: true

### creative_direction

Full creative direction response including genre exploration and summary.

- type: string
- required: true

### architecture

Full song architecture including chorus design (Section 5) and musical structure (Section 7).

- type: string
- required: true

### creative_brief

Per-concept material palette curated from source analyses.

- type: string
- required: true

## Steps

### build-grouped-items

Create randomized lens groupings across 2 models. 13 constrained lenses shuffled into 4 groups of [3,3,3,4], each ending with an unconstrained "write from the heart" chorus. Different random groupings per model.

- type: code
- inputs:
    concept_title: ${concept.title}
    concept_core_idea: ${concept.core_idea}
    creative_direction: ${creative_direction}
    architecture: ${architecture}
    creative_brief: ${creative_brief}

```python code
concept_title: str
concept_core_idea: str
creative_direction: str
architecture: str
creative_brief: str

import random

# Extract Creative Direction Summary for scoring context
summary_marker = "## Creative Direction Summary"
if summary_marker in creative_direction:
    cd_summary = creative_direction[creative_direction.index(summary_marker):]
else:
    cd_summary = creative_direction[:500]

# Extract language from creative direction
import re
lang_match = re.search(r'\*\*Language\*\*:\s*(.+)', cd_summary)
song_language = lang_match.group(1).strip() if lang_match else "English"

lenses = {
    "MINIMAL": "The hook phrase must be 2-4 words maximum. Everything else in the chorus serves this tiny, concentrated phrase. Strip to the absolute essence.",
    "REPETITION": "A specific word or phrase repeats strategically to build intensity. The power is in the accumulation. The repeated element must be specific to THIS song, not a generic word.",
    "NARRATIVE": "The chorus tells a micro-story. Something HAPPENS — not a feeling, an event or action. A listener should be able to picture what's occurring.",
    "CONCRETE IMAGE": "The chorus anchors on ONE vivid, concrete image from the source material. The image IS the hook. No abstraction allowed — every line should be something you can see, touch, smell, or hear.",
    "DIRECT ADDRESS": "The chorus speaks directly to a specific person — dead, absent, present, or imagined. The address creates intimacy and urgency. Who is the narrator speaking to?",
    "PARADOX": "The chorus contains a tension or contradiction within itself — two things that shouldn't coexist but do. The paradox should emerge from THIS song's specific situation.",
    "UNDERSTATED": "Power through restraint. This chorus should be SMALLER than the verses — quieter, simpler, more stripped down. The emotion comes from what's held back.",
    "VISCERAL": "Physical, gut-level, body before brain. Every line should land in the stomach before the head. Texture, temperature, weight, motion, impact.",
    "SOUND-FIRST": "Prioritize how the words SOUND over what they literally mean. Phonetic texture, vowel patterns, consonant rhythms, alliteration, assonance. The meaning should emerge from the sound.",
    "QUESTION": "The chorus poses a question that the verses can't fully answer. Each time the chorus returns, the question weighs more because the verses have made the answer harder. The question must be specific to THIS song's situation.",
    "CONFESSION": "The chorus is the truth the narrator has been avoiding saying. The verses build around it, circling the admission. The chorus is where the mask drops — the most brutally honest moment in the song.",
    "IRONIC/SUBVERSIVE": "The surface reading and the real reading are different. The chorus sounds like one thing but means the opposite or something darker. A casual listener hears it one way; an attentive listener discovers the real meaning underneath.",
    "CALLBACK/SOURCE ECHO": "The chorus directly transforms specific language, phrases, or verbal patterns from the source material. Not just inspired by — containing recognizable echoes of the source speaker's actual words, turned into lyrics.",
}

# Reduced to 2 models during development to save cost (~$0.50/run).
# For production quality: add claude-sonnet-4-6 and claude-opus-4-6 alongside gemini-3-flash-preview.
models = ["gemini-3-flash-preview", "gemini-2.5-flash-lite"]

items = []
lens_names = list(lenses.keys())

for model in models:
    shuffled = lens_names.copy()
    random.shuffle(shuffled)
    groups = [shuffled[0:3], shuffled[3:6], shuffled[6:9], shuffled[9:13]]

    for group in groups:
        all_lenses = group + ["UNCONSTRAINED"]
        n = len(all_lenses)

        lens_block = ""
        for i, lens_name in enumerate(all_lenses[:-1], 1):
            lens_block += f"\n**Chorus {i} — {lens_name}**: {lenses[lens_name]}\n"
        lens_block += f"\n**Chorus {n} — FROM THE HEART**: Now forget the frameworks. You've explored {n-1} different approaches. Write one more chorus — the one that feels RIGHT for this song. No constraints. Trust your instinct. Let everything you just wrote inform this, but don't be bound by any of it.\n"

        format_lines = ""
        for i, lens_name in enumerate(all_lenses, 1):
            label = lens_name if lens_name != "UNCONSTRAINED" else "FROM THE HEART"
            format_lines += f"\n===CHORUS {i}: {label}===\n[chorus lyrics]\n"

        prompt = f"""You are an exceptional songwriter. Write {n} completely different choruses for the same song, each through a different creative lens. The final chorus has no constraints — write from the heart after exploring the others.

CRITICAL: Each chorus must be GENUINELY DIFFERENT from the others. After writing each chorus, actively react against it — if your first was minimal, make the next dense. If one was quiet, make another explosive. The lenses are starting points; the differentiation is what matters.

**LANGUAGE: Write all choruses in {song_language}.** This is non-negotiable — the language was chosen because the source material's cultural specificity lives in it.

## Song Context

**Title**: "{concept_title}"
**Core idea**: {concept_core_idea}
**Genre/Direction**: {cd_summary}
**Musical Structure**: {architecture}
**Source Material**: {creative_brief}

## Creative Lenses
{lens_block}
## Rules for EVERY chorus

- The hook must be specific to THIS song — a phrase that could only belong here
- Follow the chorus musical structure targets from the architecture (line count, syllable range, rhyme scheme)
- No clichés, no AI tells
- A generic emotional declaration ("Hold On," "Breaking Free") is a failure regardless of which lens produced it
- **The stranger test**: Someone walks into a room mid-song, hears only the chorus, knows nothing about the source material. They must feel something. If the chorus requires context to land, it fails. Verses can be dense — the chorus must be emotionally immediate.
- **The singback test**: Could a first-time listener join in by the second chorus? Not because it's dumbed down — because the phrase is so rhythmically satisfying it lodges after one hearing.
- **Genre character**: What "memorable" means depends on the genre. A folk refrain accumulates weight through repetition. A punk chorus is a shout-along. A chamber chorus is a haunting phrase that lingers. An electronic chorus is a mantra. Write the chorus this genre demands, not a default pop earworm.

## Output Format

Write ONLY the chorus lyrics in this exact format:
{format_lines}"""

        items.append({
            "prompt": prompt,
            "model": model,
            "lenses": all_lenses,
            "group_size": n
        })

result: dict = {
    "items": items,
    "cd_summary": cd_summary
}
```

### generate-chorus-options

Generate choruses in groups. Each LLM call writes 4-5 choruses in one pass, actively differentiating between them. 8 calls total (2 models × 4 groups), all parallel, no reasoning overhead.

- type: llm
- model: ${item.model}
- temperature: 0.9
- reasoning_effort: none
- prompt: ${item.prompt}

```yaml batch
items: ${build-grouped-items.result.items}
parallel: true
max_concurrent: 50
error_handling: continue
```

### extract-individual-choruses

Parse the 8 grouped outputs into individual choruses tagged with lens and model.

- type: code
- inputs:
    grouped_results: ${generate-chorus-options.results}

```python code
grouped_results: list

import re

choruses = []
for gr in grouped_results:
    response = gr.get("response", "") if isinstance(gr, dict) else str(gr)
    item = gr.get("item", {}) if isinstance(gr, dict) else {}
    model = item.get("model", "unknown")

    parts = re.split(r'===CHORUS \d+:\s*([^=]+)===', response)
    i = 1
    while i < len(parts) - 1:
        lens_name = parts[i].strip()
        lyrics = parts[i + 1].strip()
        if lyrics:
            choruses.append({
                "chorus_text": lyrics,
                "lens": lens_name.lower().replace(" ", "-"),
                "model": model
            })
        i += 2

result: list = choruses
```

### build-scoring-items

Extract per-run scoring context (genre, narrator info) and prepare per-item
data for the parallel scoring batch. The LLM prompt template lives on
`score-choruses` directly so static analysis can detect cache opportunities
(see `pflow guide caching` — Python-assembled prompts).

- type: code
- inputs:
    chorus_list: ${extract-individual-choruses.result}
    cd_summary: ${build-grouped-items.result.cd_summary}

```python code
chorus_list: list
cd_summary: str

import re

# Extract just the genre line from the creative direction summary for blind scoring
genre_match = re.search(r'\*\*Genre\*\*:\s*(.+)', cd_summary)
genre_only = genre_match.group(1).strip() if genre_match else cd_summary[:200]

# Extract narrator + blind-spot / voice-ceiling info for narrator_fidelity scoring.
# We want the scorer to know who the narrator is and what psychological discipline the concept imposes,
# so it can penalize choruses that violate it (e.g., lines where the narrator confesses a blind spot).
voice_match = re.search(r'\*\*Voice\*\*:\s*(.+)', cd_summary)
persona_match = re.search(r'\*\*Persona\*\*:\s*(.+)', cd_summary)
narrator_info = ""
if voice_match:
    narrator_info += f"**Voice**: {voice_match.group(1).strip()}\n"
if persona_match:
    narrator_info += f"**Persona**: {persona_match.group(1).strip()}\n"
if not narrator_info:
    narrator_info = "(narrator info not found in creative direction summary — score narrator_fidelity as 3 by default)"

# Per-item dynamic data only — the prompt scaffold lives on score-choruses.
items = []
for i, ch in enumerate(chorus_list):
    items.append({
        "chorus_index": i,
        "chorus_text": ch.get("chorus_text", ""),
        "lens": ch.get("lens", "unknown"),
        "model": ch.get("model", "unknown"),
    })

result: dict = {
    "items": items,
    "genre_only": genre_only,
    "narrator_info": narrator_info,
}
```

### score-choruses

Score each chorus individually with the 1-5 anchored rubric. All run in parallel. Simple evaluation — low reasoning effort.

The rubric (~1.6k tokens) is the shared prefix across all scoring calls; the
per-item `${item.chorus_text}` lives at the END so provider-level prefix
caching can fire. Run `pflow analyze-cache` to see prewarm savings projection.

- type: llm
- temperature: 0.3
- reasoning_effort: none
- prompt: ./score-chorus.prompt.md

```yaml batch
items: ${build-scoring-items.result.items}
parallel: true
max_concurrent: 50
error_handling: continue
```

### rank-choruses

Sort scored choruses by total score, extract top 8 for the final judge.

- type: code
- inputs:
    score_results: ${score-choruses.results}

```python code
score_results: list

import re

scored = []

for i, sr in enumerate(score_results):
    response = sr.get("response", "") if isinstance(sr, dict) else ""
    item = sr.get("item", {}) if isinstance(sr, dict) else {}

    chorus_text = item.get("chorus_text", "")
    lens = item.get("lens", "unknown")
    model = item.get("model", "unknown")

    response_text = response if isinstance(response, str) else str(response)

    scores = {}
    for dim in ['hook_strength', 'genre_fit', 'singback', 'meaning_evolution', 'song_craft', 'emotional_payoff', 'narrator_fidelity']:
        match = re.search(rf'{dim}:\s*(\d)', response_text)
        scores[dim] = int(match.group(1)) if match else 0

    total_match = re.search(r'TOTAL:\s*(\d+)', response_text)
    total = int(total_match.group(1)) if total_match else sum(scores.values())

    scored.append({
        "chorus": chorus_text,
        "score": total,
        "lens": lens,
        "model": model,
        "scores": scores,
        "rank": 0
    })

scored.sort(key=lambda x: x["score"], reverse=True)

for i, s in enumerate(scored):
    s["rank"] = i + 1

# Top 8 for the judge (blind to lens/model)
top_text = ""
for i, s in enumerate(scored[:8]):
    top_text += f"### Option {i+1} (Score: {s['score']}/35)\n\n{s['chorus']}\n\n---\n\n"

# All choruses formatted for saving
all_text = ""
for s in scored:
    score_line = " | ".join([f"{k}: {s['scores'].get(k, '?')}" for k in ['hook_strength', 'genre_fit', 'singback', 'meaning_evolution', 'song_craft', 'emotional_payoff', 'narrator_fidelity']])
    all_text += f"### Rank {s['rank']} — {s['score']}/35 (lens: {s['lens']}, model: {s['model']})\n\n{s['chorus']}\n\n{score_line}\n\n---\n\n"

# Store top 8 indexed by option number for the judge's pick mapping
top_map = {}
for i, s in enumerate(scored[:8]):
    top_map[str(i + 1)] = s["chorus"]

result: dict = {
    "top_formatted": top_text,
    "all_formatted": all_text,
    "top_map": top_map,
    "total_generated": len(scored)
}
```

### select-chorus

Final judge evaluates top 8 choruses with full reasoning, then provides a Chorus Integration Guide for the songwriter. Blind to which lens/model produced each option.

- type: llm
- temperature: 0.3
- prompt: ./select-chorus.prompt.md

### extract-winners

Map the judge's option number picks back to actual chorus texts. Falls back to score-based ranking if parsing fails.

- type: code
- inputs:
    judge_response: ${select-chorus.response}
    top_map: ${rank-choruses.result.top_map}

```python code
judge_response: str
top_map: dict

import re

winner_match = re.search(r'WINNER:\s*(\d)', judge_response)
runner1_match = re.search(r'RUNNER_UP_1:\s*(\d)', judge_response)
runner2_match = re.search(r'RUNNER_UP_2:\s*(\d)', judge_response)

# Map option numbers to chorus texts, fallback to score-based order
winner_num = winner_match.group(1) if winner_match else "1"
runner1_num = runner1_match.group(1) if runner1_match else "2"
runner2_num = runner2_match.group(1) if runner2_match else "3"

winning = top_map.get(winner_num, top_map.get("1", ""))
runner1 = top_map.get(runner1_num, top_map.get("2", ""))
runner2 = top_map.get(runner2_num, top_map.get("3", ""))

# Extract the Chorus Integration Guide from the judge's response
chorus_guide = ""
guide_match = re.search(r'===CHORUS GUIDE===(.*?)===END CHORUS GUIDE===', judge_response, re.DOTALL)
if guide_match:
    chorus_guide = guide_match.group(1).strip()

result: dict = {
    "winning_chorus": winning,
    "runner_up_choruses": runner1 + "\n\n---\n\n" + runner2 if runner2 else runner1,
    "chorus_guide": chorus_guide,
    "judge_picks": f"Winner: Option {winner_num}, Runner-up 1: Option {runner1_num}, Runner-up 2: Option {runner2_num}"
}
```

## Outputs

### winning_chorus

The judge's top pick — the chorus the songwriter should build the song around.

- source: ${extract-winners.result.winning_chorus}

### runner_up_choruses

The judge's #2 and #3 picks — reference material for the songwriter.

- source: ${extract-winners.result.runner_up_choruses}

### all_scored_text

All choruses ranked by score with lens/model metadata — saved for inspection and learning.

- source: ${rank-choruses.result.all_formatted}

### selection_text

The final judge's reasoning for the top 3 selection.

- source: ${select-chorus.response}

### chorus_guide

The judge's Chorus Integration Guide — meaning evolution, genre character, and what the songwriter must protect when building around the winning chorus.

- source: ${extract-winners.result.chorus_guide}

### total_generated

How many choruses were generated and scored.

- source: ${rank-choruses.result.total_generated}
