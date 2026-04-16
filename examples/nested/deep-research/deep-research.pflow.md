# Deep Research Analysis

Analyze source documents from multiple perspectives, score quality, and produce a reviewed research report.

## Inputs

### sources

The source documents to analyze.

- type: array
- required: true

### focus

The research focus or question guiding the analysis.

- type: string
- required: true

## Steps

### prepare

Validate and normalize the source documents.

- type: code
- inputs:
    docs: ${sources}
    focus: ${focus}

```python code
docs: list
focus: str

result = [{"text": d, "focus": focus} for d in docs]
```

### analyze-sources

Analyze each prepared document through extraction and scoring.

- type: workflow
- workflow: ./analyze-source.pflow.md
- inputs:
    content: ${item.text}
    focus: ${item.focus}

```yaml batch
items: ${prepare.result}
parallel: true
```

### combine

Merge all source analyses into a unified summary.

- type: code
- inputs:
    analyses: ${analyze-sources.results}

```python code
analyses: list

result = {"summary": "Combined analysis", "source_count": len(analyses)}
```

### reviews

Review the combined analysis from five critical perspectives. Each review runs the same workflow template with a different focus aspect.

- type: workflow
- workflow: ${item.workflow}
- inputs:
    summary: ${combine.result}
    aspect: ${item.aspect}

```yaml batch
items:
  - aspect: accuracy
    workflow: ./review-aspect.pflow.md
  - aspect: completeness
    workflow: ./review-aspect.pflow.md
  - aspect: clarity
    workflow: ./review-aspect.pflow.md
  - aspect: relevance
    workflow: ./review-aspect.pflow.md
  - aspect: depth
    workflow: ./review-aspect.pflow.md
parallel: true
```

### final-report

Compile the analysis and reviews into a final research report.

- type: code
- inputs:
    analyses: ${analyze-sources.results}
    reviews: ${reviews.results}

```python code
analyses: list
reviews: list

result = {"report": "Final research report", "analyses": len(analyses), "reviews": len(reviews)}
```

## Outputs

### report

The final research report combining all analyses and reviews.

- source: ${final-report.result}
