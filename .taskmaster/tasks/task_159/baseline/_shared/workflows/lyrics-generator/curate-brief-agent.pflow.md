# Curate Concept Brief (Agent)

Generate a per-concept material palette from source analyses and a concept description. Standalone wrapper around the pipeline's brief curation prompt, designed for the Approach 3 agent. Takes flat string inputs instead of the pipeline's batch result objects.

The tool re-reads the full analyses through the lens of a specific concept, so the agent doesn't need to re-read the 344-line analysis file per song. Returns a comprehensive palette: metaphor mappings, Kill Moments, The Unsaid, Narrator's Blind Spot, vocabulary, scenes.

## Inputs

### concept_md

Concept description — title, emotional core, genre family, narrator, and any other creative context. This becomes the "The Song" section the brief is curated around.

- type: string
- required: true

### analysis

Combined source analyses from the analyze-source workflow. Contains 6 specialist sections separated by `## ` headers (Emotional, Sensory, Themes, Narrative, Musicality, Voice/Tone).

- type: string
- required: true

### raw_source

Raw source transcript from the fetch-source workflow.

- type: string
- required: true

## Steps

### prepare-brief-inputs

Split the flat combined analysis string into 6 individually labeled sections for the brief prompt. Each analysis section is identified by keywords in its `## ` header. Also passes the raw source through for the prompt's "Raw Source Material" section.

- type: code
- inputs:
    analysis: ${analysis}
    raw_source: ${raw_source}

```python code
analysis: str
raw_source: str

import re

raw_sections = re.split(r'(?=^## )', analysis, flags=re.MULTILINE)

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

result: dict = {
    "analysis_emotional": "\n\n".join(sections['emotional']) or "No emotional analysis available.",
    "analysis_sensory": "\n\n".join(sections['sensory']) or "No sensory analysis available.",
    "analysis_themes": "\n\n".join(sections['themes']) or "No themes analysis available.",
    "analysis_narrative": "\n\n".join(sections['narrative']) or "No narrative analysis available.",
    "analysis_musicality": "\n\n".join(sections['musicality']) or "No musicality analysis available.",
    "analysis_voice_tone": "\n\n".join(sections['voice_tone']) or "No voice/tone analysis available.",
    "raw_source": raw_source
}
```

### curate-brief

Generate the material palette using the pipeline's battle-tested 97-line prompt. The prompt covers every angle: source imagery, metaphor mappings, Kill Moments, The Unsaid, contradictions, recognition moments, Narrator's Blind Spot, vocabulary with jargon transformations, and scenes.

- type: llm
- temperature: 0.5
- reasoning_effort: medium
- timeout: 180
- prompt: ./curate-concept-brief-single.prompt.md
- inputs:
    concept_md: ${concept_md}

## Outputs

### brief

The curated material palette for one song concept.

- source: ${curate-brief.response}
