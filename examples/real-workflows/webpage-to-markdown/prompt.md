Take a webpage URL and turn it into clean markdown with all image content extracted and described.

The idea is to make web content fully accessible to AI agents. When you scrape a blog post, diagrams and charts are just image URLs - the actual information in them is lost. This workflow fixes that.

Workflow:

1. Fetch the webpage as markdown using Jina Reader (https://r.jina.ai/URL) - it's free and handles the HTML conversion

2. Extract image URLs from the markdown using grep

3. For each image, use vision AI to extract the content:
   - Diagrams/flowcharts → mermaid code
   - Charts → data values and labels
   - Screenshots → visible text and UI elements
   - Decorative or ad images → skip

This step is about extracting information from this image in a condensed but complete format. No analysis or summary is needed.

4. Append an "Image Details" section to the markdown with all the extracted content

5. Save to file - auto-generate filename from URL with today's date prefix (e.g., `2026-01-05-article-name-from-url.md`), or use custom path if provided

End result:
A markdown file where nothing is lost - diagrams become mermaid code you can render, charts become data you can use, screenshots become text you can search.
