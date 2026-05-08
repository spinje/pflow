# Fetch Source

Universal source content fetcher. Takes a single source — YouTube URL, web URL, local file path, or raw text — detects its type, and returns clean text content.

Used as a **sub-workflow** by `lyrics-generator.pflow.md`, batched across multiple sources in parallel.

**Fallback chain for YouTube:**
1. **yt-dlp** (~4s) — fast local extraction of subtitles/auto-captions
2. **Klavis YouTube MCP** (~70s) — slower API-based fallback, may have transcripts yt-dlp can't access

## Inputs

### source

A single source to fetch content from.

* `"https://youtube.com/watch?v=..."` — extracts transcript via yt-dlp
* `"https://example.com/article"` — fetches as markdown via [Jina Reader](https://r.jina.ai)
* `"./path/to/file.txt"` — reads local file
* `"Any raw text here"` — passed through unchanged

- type: string
- required: true

## Steps

### classify

Route to the correct fetcher based on the source format. Detection order: YouTube URL → web URL → existing file path → raw text.

- type: code
- inputs:
    source: ${source}

```python code
source: str

import re
import os

if re.search(r'(youtube\.com|youtu\.be)', source):
    result: str = "youtube"
    next: str = "fetch-youtube"
elif source.startswith("http://") or source.startswith("https://"):
    result: str = "webpage"
    next: str = "fetch-webpage"
elif os.path.isfile(source):
    result: str = "file"
    next: str = "read-file"
elif os.path.sep in source or source.endswith(('.md', '.txt', '.csv', '.json', '.html')):
    raise FileNotFoundError(f"Source looks like a file path but does not exist: {source}")
else:
    result: str = "text"
    next: str = "pass-text"
```

### fetch-youtube

Primary YouTube path. Uses `yt-dlp` to download subtitles (manual or auto-generated), strips VTT formatting (timestamps, headers, duplicates), and outputs clean transcript text with the video title as a heading.

If no subtitles exist, exits with error → triggers `fetch-youtube-mcp` via `on-error`.

- type: shell
- on-error: fetch-youtube-mcp
- next: end

```shell command
TMP=$(mktemp -d)
yt-dlp --write-sub --write-auto-sub --sub-lang en --skip-download --sub-format vtt -o "$TMP/yt" "${source}" >/dev/null 2>&1
TITLE=$(yt-dlp --get-title "${source}" 2>/dev/null)
if [ -f "$TMP/yt.en.vtt" ]; then
  echo "# $TITLE"
  echo ""
  sed '/^$/d; /^WEBVTT/d; /^Kind:/d; /^Language:/d; /^[0-9][0-9]:[0-9][0-9]/d; /^NOTE/d; /^align:/d; /^position:/d; s/<[^>]*>//g; s/^[[:space:]]*//' "$TMP/yt.en.vtt" | awk '!seen[$0]++'
  rm -rf "$TMP"
else
  rm -rf "$TMP"
  echo "No subtitles found for: $TITLE" >&2
  exit 1
fi
```

### fetch-youtube-mcp

YouTube fallback via the **Klavis YouTube MCP**. Slower (~70s) but accesses YouTube's API directly, which may return transcripts unavailable through yt-dlp's scraping approach.

* `timeout: 120` is required — default 30s is not enough for this MCP server

- type: mcp-klavis-youtube-get_youtube_video_transcript
- url: ${source}
- timeout: 120
- next: end

### fetch-webpage

Fetches any web URL as clean markdown via [Jina Reader](https://r.jina.ai). Returns the page title, source URL, and full content with images stripped.

*Does **not** work for YouTube* — returns page chrome instead of transcript.

- type: shell
- next: end

```shell command
curl -sL "https://r.jina.ai/${source}"
```

### read-file

Read content directly from a local file path.

- type: shell
- next: end

```shell command
cat "${source}"
```

### pass-text

Pass raw text through unchanged. This is the catch-all — anything that isn't a URL or existing file is treated as literal text input.

- type: shell
- next: end

```shell command
printf '%s' "${source}"
```

## Outputs

### content

The fetched source as plain text — YouTube transcript, webpage markdown, file contents, or raw text passed through.

- source: ${fetch-youtube.stdout ?? fetch-youtube-mcp.result ?? fetch-webpage.stdout ?? read-file.stdout ?? pass-text.stdout}

### source_type

The detected source type: `youtube`, `webpage`, `file`, or `text`.

- source: ${classify.result}
