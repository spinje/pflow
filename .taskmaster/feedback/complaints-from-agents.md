- Long execution time - 60 seconds per full run meant slow iteration. Would have been faster to test individual nodes.
- Error messages were helpful but late - The trace file showed exactly what went wrong, but only after the full workflow failed.

- A "dry-run" mode that tests shell commands without actually executing the full workflow
- Platform-aware examples in the instructions showing both GNU and BSD variants
- More discipline - I should have followed my own todo list more strictly and tested incrementally as planned

1. JSON escaping for shell commands - Writing jq inside JSON is painful:
  "command": "jq -R -s 'split(\"\\n\") | map(select(length > 0))'"
1. All those escaped quotes and backslashes are error-prone and hard to read.
2. Boilerplate for simple operations - I needed 3 nodes just to generate a filename:
    - get-current-date → date +%Y-%m-%d
    - generate-filename → sanitize URL with sed
    - determine-output-path → combine them with jq

Would be nice to have template functions like ${date:YYYY-MM-DD} or ${slugify:target_url}.
3. The URL sanitization was verbose:
sed 's|https\\?://||' | sed 's|[^a-zA-Z0-9]|-|g' | sed 's|--*|-|g' | sed 's|^-||' | sed 's|-$||' | cut -c1-100
3. This is a common pattern - turning URLs/strings into safe filenames. Could be a built-in.
4. Batch results structure wasn't immediately obvious - Had to figure out that ${process-images.results} contains objects with .item and .response fields. A quick example in the docs would help. ✅ (fixed)