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
5. No stdin/stdout visibility on success - Workflow shows `✓ convert-to-array (11ms)` but not what went in/out. Had shell bug where URLs went in but `/bin/sh` came out - would be obvious with `--verbose` showing truncated stdin→stdout per node.

---

3. Batch errors could show which items failed

  Current (if some fail):
  ⚠️ process-images (29732ms) - 6/8 items succeeded

  Suggestion: Show failed items
  ⚠️ process-images (29.7s) - 6/8 items succeeded, 2 failed
    Failed items:
      • Item 3: Connection timeout
      • Item 7: Invalid image format

  Or at least:
  ⚠️ process-images (29.7s) - 6/8 items succeeded (view errors: pflow trace show --node process-images)

  4. "Workflow output" could be clearer

  Current:
  Workflow output:

  ./2026-01-09-anthropic-com-engineering-building-effective-agent.md

  Suggestion: Make it more obvious this is the result
  📄 Result:
  ./2026-01-09-anthropic-com-engineering-building-effective-agent.md

  Or if multiple outputs:
  📄 Results:
    • file_path: ./2026-01-09-anthropic-com-engineering-building-effective-agent.md
    • images_processed: 8


    6. Workflow file not found error could be better

  Current:
  ❌ Workflow '/tmp/test-grep-bug.json' not found.

  Use 'pflow workflow list' to see available workflows.
  Or use quotes for natural language: pflow "your request"

  Issue: This appears even when the file path is correct but pflow is running from wrong directory

  Suggestion:
  ❌ Workflow '/tmp/test-grep-bug.json' not found.

  Checked:
    • Absolute path: /tmp/test-grep-bug.json (not found)
    • Relative to cwd: /current/dir/tmp/test-grep-bug.json (not found)

  Did you mean:
    • pflow workflow list - see saved workflows
    • pflow "describe what you want" - natural language