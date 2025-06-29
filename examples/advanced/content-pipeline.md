# Content Pipeline Example

## Purpose
This advanced example demonstrates a complete content generation pipeline inspired by the pocketflow-workflow pattern. It shows:
- Multi-stage content creation with research, writing, and review
- Revision loops for quality control
- Complex data flow through shared store
- Integration of multiple AI models and tools

## Use Case
Automated content creation for:
- Technical tutorials and guides
- Documentation generation
- Blog post creation
- Educational material development

## Visual Flow
```
┌─────────┐    ┌─────────┐    ┌──────────────┐    ┌─────────────┐
│research │───►│ outline │───►│expand_sections│───►│add_examples │
└─────────┘    └─────────┘    └──────┬───────┘    └──────┬──────┘
                                     ▲                     │
                                     │                     ▼
                              (needs_revision)      ┌──────────────┐
                                     │              │review_technical│
                                     └──────────────┤              │
                                                   └──────┬───────┘
                                                         │
                                                    (approved)
                                                         ▼
                                                  ┌──────────────┐
                                                  │format_output │
                                                  └──────┬───────┘
                                                         │
                                                         ▼
                                                  ┌─────────────┐
                                                  │ save_draft  │
                                                  └─────────────┘
```

## Template Variables
**Configuration Variables**:
- `$topic`: Main subject of the content
- `$audience`: Target reader level
- `$difficulty`: Content complexity
- `$writing_style`: Tone and style
- `$programming_language`: For code examples
- `$author`: Content creator
- `$tags`: Categorization

**Data Flow Variables** (set by nodes):
- `$research_summary`: Compiled research findings
- `$outline`: Structured content outline
- `$key_concepts`: Extracted main ideas
- `$full_content`: Expanded article text
- `$date`: Generation timestamp

## Node Pipeline (Inspired by pocketflow-workflow)

### 1. research
Gathers authoritative information from specified domains about the topic.

### 2. outline
Creates structured outline based on research, similar to pocketflow-workflow's OutlineGenerator.

### 3. expand_sections
Transforms outline into full content, maintaining coherent flow between sections.

### 4. add_examples
Generates relevant code examples and practical demonstrations.

### 5. review_technical
Quality control step that can trigger revisions if issues found.

### 6. format_output
Final formatting with TOC, syntax highlighting, and metadata.

### 7. save_draft
Persists the generated content with backup.

## Revision Loop
The `review_technical → expand_sections` edge with action "needs_revision" creates a quality loop, ensuring content meets standards before proceeding.

## Pattern Application from pocketflow-workflow
This example adapts the three-phase approach from pocketflow-workflow:
1. **Planning Phase**: Research and outline generation
2. **Content Phase**: Expansion and example addition
3. **Polish Phase**: Review and formatting

Each phase builds on the previous, with data flowing through the shared store.

## How to Run
```python
from pflow.core import validate_ir
import json

with open('content-pipeline.json') as f:
    ir = json.load(f)
    validate_ir(ir)

# Runtime parameters:
params = {
    "topic": "Python Async Programming",
    "audience": "intermediate developers",
    "difficulty": "medium",
    "writing_style": "conversational but technical",
    "programming_language": "python",
    "author": "AI Assistant",
    "tags": ["python", "async", "tutorial"]
}
```

## Extending This Workflow
1. **Multiple formats**: Add nodes for video scripts, slides
2. **Localization**: Translate to multiple languages
3. **SEO optimization**: Add keyword analysis and optimization
4. **Publishing**: Direct integration with CMS or blog platforms

## Key Insights
- Sequential processing ensures each stage has required context
- Revision loops maintain quality without manual intervention
- Template variables enable reuse for any topic
- Shared store manages complex data flow between stages
