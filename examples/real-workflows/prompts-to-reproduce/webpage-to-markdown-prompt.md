# Webpage to Markdown Converter

## Goal

Convert any webpage into clean, portable markdown with locally-stored images. The output should be viewable by both humans (as a document) and AI agents (with full context including images).

## Inputs

- `url` - The webpage URL to convert
- `output_dir` - Directory to save the markdown file and images

## Requirements

### 1. Fetch the webpage HTML

Retrieve the raw HTML from the given URL.

### 2. Extract article content

Extract the main article content, preferring semantic HTML:
- First try to find `<article>` tag content
- Fall back to `<body>` content if no article tag exists

This filters out navigation, footers, and scripts that aren't part of the main content.

### 3. Extract page title

Extract the page title from either:
- The first `<h1>` tag in the content
- The `<title>` tag as fallback

### 4. Split into sections for parallel processing

Split the extracted HTML on `<h2>` and `<h3>` headings to create fine-grained sections. Each section should:
- Start with an h2 or h3 tag (except the first section which contains intro content)
- Be at least 100 characters (skip trivial fragments)
- Be processable independently

Splitting at h3 level (not just h2) creates smaller chunks that:
- Process faster individually
- Allow higher parallelism utilization
- Average ~635 tokens per section instead of ~2,800

### 5. Convert HTML to markdown (parallel)

For each section, use an LLM to convert HTML to clean markdown:
- Ignore scripts, CSS, navigation, ads, and non-content elements
- Preserve all image references using markdown syntax `![alt](url)`
- Keep original image URLs exactly as they appear
- Process all sections in parallel (up to 50 concurrent)

### 6. Stitch sections together

Combine the converted markdown sections back into a single document:
- Add the extracted title as an H1 heading at the top
- Preserve the original section order

### 7. Extract image URLs (shell-based)

Use regex to extract all image URLs from the markdown:
- Match markdown image syntax `![alt](url)`
- Filter out ad/tracking URLs (doubleclick, pixel, tracker, analytics, beacon, ads)
- Return as a JSON array

Using shell/regex instead of LLM for extraction is:
- Faster (no API call)
- Cheaper (no tokens)
- More reliable (deterministic)

### 8. Download images and update references

For each image URL:
- If it's a Next.js optimized URL (`/_next/image?url=...`), decode the actual image URL
- Download the image to `{output_dir}/images/`
- Update the markdown to reference the local path `./images/filename.ext`

### 9. Save the final markdown

Write the processed markdown (with local image references) to `{output_dir}/article.md`.

## Output

- `{output_dir}/article.md` - Clean markdown with local image references
- `{output_dir}/images/` - Downloaded content images

## Performance Characteristics

- **Fine-grained parallelism**: Splitting at h2+h3 level creates more sections for better parallel utilization
- **High concurrency**: Up to 50 sections processed simultaneously
- **Shell preprocessing**: Extracts article content before LLM, reducing tokens by ~90%
- **Shell-based extraction**: Image URL extraction uses regex, not LLM
- **Typical performance**: ~17-19s, ~$0.01-0.02 per article
