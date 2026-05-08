# Enforce Diversity

Review song concepts together and assign diversity constraints — different genre families and narrator perspectives — so the songs explore genuinely different creative territory rather than variations on the same idea.

Callable both as a sub-workflow by the pipeline and standalone by the Approach 3 agent.

## Inputs

### concepts

The concepts to assign diversity to. Accepts any format — structured JSON array (from pipeline's concept-chooser) or flat text descriptions (from agent's concept picks). The LLM reads them as text either way.

- type: any
- required: true

### analysis

Source analyses for context. Helps the LLM make informed genre/narrator assignments based on the source material's dimensions.

- type: string
- required: true

## Steps

### assign-diversity

Assign genre families (no duplicates) and narrators (2 natural + 2 wild card) to each concept. Wild card narrators must be people who CARE about someone in the song.

- type: llm
- prompt: ./enforce-diversity.prompt.md
- inputs:
    concepts: ${concepts}
    analysis: ${analysis}

```yaml output_schema
type: object
properties:
  concepts:
    type: array
    items:
      type: object
      properties:
        title:
          type: string
        core_idea:
          type: string
        angle:
          type: string
        why_compelling:
          type: string
        narrator_hint:
          type: string
          description: Who is singing this and their relationship to the material
        narrator_type:
          type: string
          description: natural (obvious choice) or wild_card (intentionally non-obvious)
        genre_family:
          type: string
          description: The genre family this concept should be developed in
        source_emphasis:
          type: string
          description: Which source to emphasize if multiple sources exist, or empty string for single source
        reasoning:
          type: string
          description: Why this narrator and genre combination serves this concept
      required:
        - title
        - core_idea
        - angle
        - why_compelling
        - narrator_hint
        - narrator_type
        - genre_family
        - reasoning
  reserved_material:
    type: array
    description: 0-3 selective reservations of signature source moments, allocated to exactly one concept each. Empty array is valid and common.
    items:
      type: object
      properties:
        moment:
          type: string
          description: The specific phrase, scene, image, or Kill Moment being reserved. Quote or close paraphrase with enough specificity that a curator can recognize it.
        assigned_to:
          type: string
          description: The exact concept title this moment is reserved to.
        reasoning:
          type: string
          description: Why this moment's natural owner is that concept.
      required:
        - moment
        - assigned_to
        - reasoning
required:
  - concepts
```

## Outputs

### concepts

The concepts enriched with diversity assignments (genre_family, narrator_hint, narrator_type, reasoning).

- source: ${assign-diversity.response.concepts}

### reserved_material

Selective cross-concept material reservations (0-3 items). Each reservation names a signature source moment allocated to exactly one concept by title; other concepts' briefs must treat these as Forbidden Territory. Empty array means the enforcer judged no reservation necessary.

- source: ${assign-diversity.response.reserved_material}
