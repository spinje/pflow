Take a webpage URL and turn it into a clean markdown file with images saved locally and referenced by their local path in the markdown file.

The idea is to make web content portable and readable by both humans and AI agents. When you scrape a blog post, you want the full article - NOT a summary, NOT raw HTML soup.

Workflow:

1. Fetch the webpage and pull out just the article content (skip the nav, footer, ads, etc.)

2. Split the article into sections by h2 and h3 headings for fine-grained parallelism

3. Convert each section to markdown in parallel (up to 50 concurrent). Keep the text content exactly as it is, just converted to markdown.

4. Stitch the sections back together, adding the page title as an H1 heading

5. Find all images in the markdown using regex, filter out ads/tracking pixels

6. Download the real content images locally and update the markdown to point to local copies

End result:
A markdown file you can read anywhere, with all the images right there in a folder next to it.
