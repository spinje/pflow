# Analyze Source

Analyze a single source document by extracting key sections and scoring them.

## Inputs

### content

The source document text to analyze.

- type: string
- required: true

### focus

The analysis focus area.

- type: string

## Steps

### extract

Extract key sections from the source content.

- type: llm
- prompt: Extract the key sections from this document, focusing on ${focus}: ${content}

### score

Score the extracted sections for quality.

- type: workflow
- workflow: ./score-section.pflow.md
- inputs:
    text: ${extract.response}
    criteria: ${focus}

### compile

Compile the extraction and scores into a structured analysis.

- type: code
- inputs:
    sections: ${extract.response}
    scores: ${score.score}

```python code
sections: str
scores: dict

result = {"sections": sections, "scores": scores, "compiled": True}
```

## Outputs

### analysis

The structured analysis with sections and scores.

- source: ${compile.result}

### quality_score

The quality score from the scoring sub-workflow.

- source: ${score.score}
