# Real-World Workflow Examples

Production-ready workflows demonstrating pflow capabilities.

## Webpage to Markdown

Converts any webpage into clean, portable markdown with locally-stored images. Works for both humans and AI agents.

### Files

- `webpage-to-markdown-parallel.json` - Parallel HTML-to-markdown converter
- `prompts-to-reproduce/` - Natural language prompts used to create this workflow

### Run

```bash
pflow examples/real-workflows/webpage-to-markdown-parallel.json \
  url="https://www.anthropic.com/engineering/claude-code-best-practices" \
  output_dir="./output"
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

### Features

- Extracts article content (prefers `<article>` tag, falls back to `<body>`)
- Splits at `<h2>` and `<h3>` headings for fine-grained parallelism
- Processes up to 50 sections concurrently
- Filters out ad/tracking images (doubleclick, pixel, tracker, etc.)
- Decodes Next.js optimized image URLs (`/_next/image?url=...`)
- Adds page title as H1 heading
- Downloads images locally and rewrites markdown references

### Performance

Tested across different blog platforms:

| Article | Time | Sections | Size | Images | Cost |
|---------|------|----------|------|--------|------|
| [Claude Code: Best practices for agentic coding](https://www.anthropic.com/engineering/claude-code-best-practices) | 17.9s | 38 | 29KB | 7 | $0.017 |
| [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | 18.9s | 19 | 20KB | 8 | $0.009 |
| [Code Mode: the better way to use MCP](https://blog.cloudflare.com/code-mode/) | 16.8s | 17 | 20KB | 4 | $0.011 |

### Why It's Fast

1. **Shell preprocessing** - Extracts only `<article>` content, reducing tokens by ~90%
2. **Fine-grained splitting** - Splits at h2+h3 level for smaller chunks (~635 tokens avg)
3. **High parallelism** - 50 concurrent LLM calls process all sections simultaneously
4. **Shell-based extraction** - Image URL extraction uses regex, not LLM

## Future Improvements

- [ ] Add an llm step to filter out ads and tracking images more accurately than using shell regex
