# Concept Chooser

Generate 15 song concepts through 4 analytical lenses (Heart, Mind, Body, Full Brief), then select the top 4 most songworthy concepts. Each lens sees a different subset of the source analysis, forcing genuinely different creative territory. Every concept must specify a character who wants/fears/needs something — the judge uses this as a hard gate (no character with a want = rejected regardless of quality).

The key creative principle: source material is INSPIRATION, not SUBJECT. Every concept must be about a universal human experience that the source illuminates, using the source's imagery as metaphorical language.

Used as a **sub-workflow** by `lyrics-generator.pflow.md`, called once between analyze-sources and enforce-diversity. Also callable standalone by the Approach 3 agent with flat string inputs.

## Inputs

### analyses

Source analyses. Accepts either format:

* Pipeline: batch results object from analyze-sources (list of sub-workflow outputs, each containing a response with all 6 specialist analyses concatenated)
* Agent: flat combined analysis string (the `02-source-analyses.md` file content)

The code node handles both — batch objects are unwrapped, flat strings pass through directly.

- type: any
- required: true

### brief

The combined source analyses (all 6 specialists, formatted as a single string). Used by the Full lens for cross-cutting concept generation. When calling with flat string inputs, pass the same string as both `analyses` and `brief`.

- type: string
- required: true

### top_n

Number of concepts for the judge to select. Set to 0 to skip the judge entirely and return all 15 concepts (useful when the agent wants to make its own selection from the full pool).

- type: integer
- required: false
- default: 4

## Steps

### build-analysis-subsets

Parse the source analyses into 3 thematic subsets (lenses) for targeted concept generation. Each lens shows the concept generator a different dimension of the source, forcing different creative starting points.

* HEART: Emotional Depth + Voice/Tone/Humor — feelings, personality, warmth
* MIND: Themes/Angles + Narrative Structure — ideas, stories, arcs
* BODY: Sensory Details + Language/Musicality — texture, sound, physicality

- type: code
- inputs:
    raw_analyses: ${analyses}
    brief: ${brief}

```python code
raw_analyses: list | str
brief: str
import re

# Extract analysis text from batch results.
# analyze-sources returns a list of sub-workflow outputs.
# Each item's response is a dict {'analysis': '...'} where the analysis string
# contains all 6 specialist sections concatenated with ## headers.
all_analysis = ""
items = raw_analyses if isinstance(raw_analyses, list) else [raw_analyses]
for a in items:
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
    all_analysis += text + "\n\n"

# Split by ## headers into named sections.
# For multi-source, the same header appears multiple times — we APPEND, not overwrite.
raw_sections = re.split(r'(?=^## )', all_analysis, flags=re.MULTILINE)

sections = {
    'Emotional': [],
    'Sensory': [],
    'Themes': [],
    'Narrative': [],
    'Musicality': [],
    'Voice': []
}

for s in raw_sections:
    s = s.strip()
    if not s:
        continue
    header_line = s.split('\n')[0]
    if 'Emotional' in header_line:
        sections['Emotional'].append(s)
    elif 'Sensory' in header_line:
        sections['Sensory'].append(s)
    elif 'Theme' in header_line or 'Angle' in header_line:
        sections['Themes'].append(s)
    elif 'Narrative' in header_line:
        sections['Narrative'].append(s)
    elif 'Language' in header_line or 'Musicality' in header_line:
        sections['Musicality'].append(s)
    elif 'Voice' in header_line or 'Tone' in header_line or 'Humor' in header_line:
        sections['Voice'].append(s)

# Build 3 subset lenses by joining matched sections
lens_heart = "\n\n---\n\n".join(sections['Emotional'] + sections['Voice'])
lens_mind = "\n\n---\n\n".join(sections['Themes'] + sections['Narrative'])
lens_body = "\n\n---\n\n".join(sections['Sensory'] + sections['Musicality'])

if not lens_heart:
    lens_heart = "No emotional/voice analysis available."
if not lens_mind:
    lens_mind = "No thematic/narrative analysis available."
if not lens_body:
    lens_body = "No sensory/musicality analysis available."

sections_found = [k for k, v in sections.items() if v]

result: dict = {
    "brief": brief,
    "lens_heart": lens_heart,
    "lens_mind": lens_mind,
    "lens_body": lens_body,
    "sections_found": sections_found
}
```

### generate-concepts

Generate concepts from 4 perspectives in parallel: 3 analysis subsets (3 each) + the full brief (6). 15 total. Each lens forces different creative territory by showing only a subset of the source analysis.

- type: llm
- temperature: 0.9
- reasoning_effort: none
- prompt: ${item.prompt}

```yaml batch
items:
  - lens: heart
    prompt: ./generate-concepts-heart.prompt.md
  - lens: mind
    prompt: ./generate-concepts-mind.prompt.md
  - lens: body
    prompt: ./generate-concepts-body.prompt.md
  - lens: full
    prompt: ./generate-concepts-full.prompt.md
parallel: true
```

### format-concepts

Combine all 15 concepts into one document labeled by lens, for the judge to evaluate.

- type: code
- inputs:
    results: ${generate-concepts.results}

```python code
results: list

lens_labels = {
    "heart": "HEART Lens (Emotional + Voice/Tone)",
    "mind": "MIND Lens (Themes + Narrative)",
    "body": "BODY Lens (Sensory + Musicality)",
    "full": "FULL Brief (Cross-cutting)"
}

all_concepts = ""
for r in results:
    if isinstance(r, dict):
        item = r.get("item", {})
        lens = item.get("lens", "unknown") if isinstance(item, dict) else "unknown"
        label = lens_labels.get(lens, lens)
        response = r.get("response", str(r))
        all_concepts += f"### {label}\n\n{response}\n\n---\n\n"

result: str = all_concepts
```

### route-judge

Check whether to run the judge or skip it. When `top_n=0`, the agent wants all 15 concepts without judge filtering. When `top_n > 0` (pipeline default: 4), the judge selects the top picks.

- type: code
- inputs:
    top_n: ${top_n}

```python code
top_n: int

result: str = "routing"
if top_n == 0:
    next: str = "skip-judge"
else:
    next: str = "select-concepts"
```

### select-concepts

A veteran judge evaluates all 15 concepts and picks the top 4 most songworthy. Uses a hard gate: concepts without a character who wants/fears/needs something are rejected regardless of quality. Scores on stranger test, replay test, pitch test, emotional immediacy, and depth over breadth.

- type: llm
- temperature: 0.3
- next: structure-selected-concepts
- prompt: ./select-concepts.prompt.md

### structure-selected-concepts

Parse the judge's picks into structured JSON that enforce-diversity expects. Maps new concept fields to the existing schema while preserving supplementary data.

- type: code
- next: end
- inputs:
    judge_response: ${select-concepts.response}

```python code
judge_response: str
import re

concepts = []

# Parse ===PICK N=== blocks
picks = re.split(r'===PICK \d+===', judge_response)
for pick in picks:
    if '===END PICK===' not in pick:
        continue

    pick_text = pick[:pick.index('===END PICK===')]

    def extract(field):
        match = re.search(rf'{field}:\s*(.+?)(?:\n|$)', pick_text)
        return match.group(1).strip() if match else ""

    title = extract('TITLE')
    emotional_core = extract('EMOTIONAL_CORE')
    mode = extract('MODE')
    listener_pitch = extract('LISTENER_PITCH')
    source_imagery = extract('SOURCE_IMAGERY')
    lens = extract('LENS')

    if title:
        concepts.append({
            # Fields that downstream prompts reference (concept.title, concept.core_idea, concept.angle)
            "title": title,
            "core_idea": emotional_core,
            "angle": f"{mode} — {source_imagery}" if source_imagery else mode,
            "why_compelling": listener_pitch,
            # Supplementary fields for inspection and diversity enforcement
            "emotional_core": emotional_core,
            "mode_of_engagement": mode,
            "listener_pitch": listener_pitch,
            "source_imagery": source_imagery,
            "originating_lens": lens
        })

# Extract the ranking text (everything before the first ===PICK)
first_pick = judge_response.find('===PICK')
judge_reasoning = judge_response[:first_pick].strip() if first_pick > 0 else judge_response

# Fallback: if parsing found fewer than 4, warn but proceed
warnings = []
if len(concepts) < 4:
    warnings.append(f"Only parsed {len(concepts)} concepts from judge output (expected 4)")

result: dict = {
    "concepts": concepts,
    "judge_reasoning": judge_reasoning,
    "parse_warnings": warnings
}
```

### skip-judge

Fallback outputs when the judge is skipped (`top_n=0`). Provides empty/placeholder values so the workflow's coalesced outputs resolve cleanly.

- type: code
- next: end

```python code
result: dict = {
    "message": "Judge skipped (top_n=0). All 15 concepts returned in all_concepts_text.",
    "concepts": [],
    "parse_warnings": []
}
```

## Outputs

### selected_concepts

The top concepts selected by the judge (when `top_n > 0`), or an empty list (when `top_n=0` and the agent makes its own selection from `all_concepts_text`).

- source: ${structure-selected-concepts.result.concepts ?? skip-judge.result.concepts}

### all_concepts_text

All 15 concepts organized by lens — saved for inspection and learning across runs. When `top_n=0`, this is the primary output.

- source: ${format-concepts.result}

### selection_text

The judge's full ranking and reasoning (when `top_n > 0`), or a skip message (when `top_n=0`).

- source: ${select-concepts.response ?? skip-judge.result.message}

### parse_warnings

Any warnings from parsing the judge's output, or empty list when judge is skipped.

- source: ${structure-selected-concepts.result.parse_warnings ?? skip-judge.result.parse_warnings}
