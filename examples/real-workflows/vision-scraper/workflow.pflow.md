# Vision Scraper

Convert a webpage to clean markdown with AI-powered image analysis.
Uses Jina Reader for initial conversion and Gemini vision for image descriptions.

## Inputs

### target_url

Webpage URL to convert to markdown. Supports any publicly accessible URL.

- type: string
- required: true

### output_file

Output file path. Use 'auto' to generate from URL with date prefix.

- type: string
- required: false
- default: "auto"

### describe_images

Use vision AI to extract content from images found in the page.

- type: boolean
- required: false
- default: true

## Steps

### compute-filename

Generate output filename from URL with date prefix, or use provided output_file.

- type: shell
- env:
    OUTPUT_FILE: ${output_file}
    TARGET_URL: ${target_url}

```shell command
if [ "$OUTPUT_FILE" != 'auto' ]; then
  printf '%s' "$OUTPUT_FILE"
else
  name=$(printf '%s' "$TARGET_URL" | sed 's|[?#].*||; s|/$||; s|.*/||; s|\\.[^.]*$||')
  [ -z "$name" ] && name='article'
  printf '%s' "./$(date +%Y-%m-%d)-$name.md"
fi
```

### fetch

Fetch markdown via Jina Reader. We use Jina over direct fetching because
it handles SPAs and paywalled content better.

- type: http
- url: https://r.jina.ai/${target_url}

### extract-images

Extract image URLs from the fetched markdown. Returns empty array if
describe_images is false to skip the analysis step.

- type: shell
- stdin: ${fetch.response}
- env:
    DESCRIBE_IMAGES: ${describe_images}

```shell command
case "$DESCRIBE_IMAGES" in
  *[Ff]alse*) echo '[]' ;;
  *) grep 'Image [0-9]' | grep -o 'https://[^)]*' | \
     jq -Rs 'split("\n") | map(select(. != ""))' ;;
esac
```

### analyze

Analyze each image with vision AI to extract content. Uses Gemini's
vision capabilities for cost-effective batch processing.

- type: llm
- model: gemini/gemini-3-flash-preview
- images: ${item}

```yaml batch
items: ${extract-images.stdout}
parallel: true
max_concurrent: 40
error_handling: continue
```

````markdown prompt
Extract the information from this image. No analysis or summary - just the content.

* Diagram/flowchart: mermaid code only (```mermaid block)
* Chart/graph: data values and labels
* Screenshot: visible text and UI elements
* Decorative: say 'decorative'

Be direct. No commentary.
````

### format-analyses

Format image analyses as numbered markdown sections for appending to the article.

- type: shell
- stdin: ${analyze.results}

```shell command
jq -r 'to_entries | map("### Image " + (.key + 1 | tostring) + "\n" + .value.response + "\n") | join("\n")'
```

### save-article

Save the article markdown to disk at the computed filename.

- type: write-file
- file_path: ${compute-filename.stdout}
- content: ${fetch.response}

### append-analyses

Append image analysis sections to the saved article file.

- type: shell
- stdin: ${format-analyses.stdout}
- env:
    ARTICLE_FILE: ${compute-filename.stdout}

```shell command
echo '' >> "$ARTICLE_FILE" && \
echo '---' >> "$ARTICLE_FILE" && \
echo '' >> "$ARTICLE_FILE" && \
echo '## Image Details' >> "$ARTICLE_FILE" && \
echo '' >> "$ARTICLE_FILE" && \
cat >> "$ARTICLE_FILE" && \
echo "$ARTICLE_FILE"
```

## Outputs

### file_path

Path to the saved markdown file with article content and image analyses.

- source: ${compute-filename.stdout}
