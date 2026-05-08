# Analyze Source

Six specialist analysts examine a single source in parallel, each focused on a different dimension of songwriting potential. Splitting the analysis ensures each dimension gets full, dedicated attention — a single analyzer trying to extract everything at once goes less deep in each area.

Used as a **sub-workflow** by `lyrics-generator.pflow.md`, batched across multiple sources in parallel.

**Specialists:**
1. **Emotional Depth** — emotions, arcs, human stories, psychological dynamics, the unsaid
2. **Sensory Details & Vocabulary** — concrete details, unusual words, physical actions, objects, settings
3. **Themes & Angles** — deeper ideas, unique perspectives, tensions, paradoxes, tone
4. **Narrative & Scenes** — story beats, self-contained scenes, turning points, narrative structure
5. **Language & Musicality** — natural rhythms, singable phrases, phonetic patterns, potential hooks
6. **Voice & Tone** — the speaker's personality, humor, warmth, register shifts, rhetorical style

## Inputs

### content

The raw source content to analyze. Passed directly from the fetch-source sub-workflow — intentionally NOT cleaned, as raw transcripts contain rhythmic patterns, verbal tics, and "errors" that produce valuable songwriting material.

- type: string
- required: true

## Steps

### analyze

Six specialist analysts run in parallel, each examining the source through a single focused lens. Each specialist is explicitly told that other specialists handle the other dimensions — this gives them permission to go deep in their domain without trying to cover everything.

This is the last step that sees the raw source material — everything downstream works from these analyses. Anything the specialists miss is lost to the songwriter forever.

- type: llm
- prompt: ${item.prompt}

```yaml batch
items:
  - focus: emotional
    prompt: ./analyze-emotional.prompt.md
  - focus: details
    prompt: ./analyze-sensory.prompt.md
  - focus: angles
    prompt: ./analyze-themes.prompt.md
  - focus: narrative
    prompt: ./analyze-narrative.prompt.md
  - focus: musicality
    prompt: ./analyze-musicality.prompt.md
  - focus: voice-tone
    prompt: ./analyze-voice-tone.prompt.md
parallel: true
```

### format

Combine the six specialist analyses into a single structured document with clear sections. This combined output is what the synthesizer and concept generator see downstream.

- type: code
- inputs:
    results: ${analyze.results}

```python code
results: list

labels = {
    "emotional": "Emotional Depth",
    "details": "Sensory Details & Unusual Vocabulary",
    "angles": "Themes, Angles & Tensions",
    "narrative": "Narrative Structure & Scenes",
    "musicality": "Language & Musicality",
    "voice-tone": "Voice, Tone & Humor"
}

sections = []
for r in results:
    if isinstance(r, dict):
        item = r.get("item", {})
        focus = item.get("focus", "unknown") if isinstance(item, dict) else "unknown"
        label = labels.get(focus, focus)
        response = r.get("response", str(r))
        sections.append(f"## {label}\n\n{response}")
    else:
        sections.append(str(r))

result: str = "\n\n---\n\n".join(sections)
```

## Outputs

### analysis

Combined analysis from all six specialists, formatted as a single markdown document with clear section headers.

- source: ${format.result}
