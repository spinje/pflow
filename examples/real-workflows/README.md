# Real-World Workflow Examples

Production-ready workflows demonstrating pflow capabilities.

## Webpage to Markdown

Converts any webpage into clean, portable markdown with locally-stored images. Optionally uses vision AI to describe images for accessibility.

### Run

```bash
# Basic usage (no image descriptions)
pflow examples/real-workflows/webpage-to-markdown.json \
  url="https://www.anthropic.com/engineering/claude-code-best-practices" \
  output_dir="./output"

# With vision-powered image descriptions
pflow examples/real-workflows/webpage-to-markdown.json \
  url="https://www.anthropic.com/engineering/claude-code-best-practices" \
  output_dir="./output" \
  describe_images=true
```

### Output

```
./output/
├── article.md          # Clean markdown with local image refs
└── images/
    ├── image1.png
    ├── image2.svg
    └── ...
```

With `describe_images=true`, each image gets a vision-generated description:

```markdown
![Claude Code interface](./images/screenshot.png)

> *A terminal interface showing the Claude Code permission rules menu,
> listing authorized bash commands and tools the AI can execute...*
```

### Features

- Extracts article content (prefers `<article>` tag, falls back to `<body>`)
- Splits at `<h2>` and `<h3>` headings for fine-grained parallelism
- Processes up to 50 sections concurrently
- Filters out ad/tracking images (doubleclick, pixel, tracker, etc.)
- Decodes Next.js optimized image URLs (`/_next/image?url=...`)
- Adds page title as H1 heading
- Downloads images locally and rewrites markdown references
- **Optional**: Vision AI describes images for accessibility/AI consumption

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | yes | - | Webpage URL to convert |
| `output_dir` | string | yes | - | Directory for markdown and images |
| `describe_images` | boolean | no | false | Use vision AI for image descriptions |

### Performance

| Mode | Time | Cost | Use Case |
|------|------|------|----------|
| Basic | ~17s | ~$0.01 | Fast conversion |
| With vision | ~24s | ~$0.02 | AI-readable content |

### Why It's Fast

1. **Shell preprocessing** - Extracts only `<article>` content, reducing tokens by ~90%
2. **Fine-grained splitting** - Splits at h2+h3 level for smaller chunks (~635 tokens avg)
3. **High parallelism** - 50 concurrent LLM calls process all sections simultaneously
4. **Shell-based extraction** - Image URL extraction uses regex, not LLM
5. **Parallel vision** - Image descriptions run 10 concurrent calls

### Use Cases

**For humans**: Clean, offline-readable articles with local images

**For AI agents**: Full context including image descriptions - unlike built-in web scrapers that lose visual information or only provide summaries
