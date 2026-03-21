# Batch File Reference Test

Test that a batch config can be loaded from an external YAML file.

Note: batch is specified inline here because the IR schema expects batch
to be an object after parsing. File references for batch are resolved
at compile time, not parse time. To test batch file refs, use the
automated tests in test_file_resolver.py.

## Steps

### review

Run batch reviews with inline config.

- type: llm
- prompt: ${item.prompt}

```yaml batch
items:
  - focus: quality
    prompt: Check this text for quality issues.
  - focus: style
    prompt: Check this text for style issues.
parallel: true
```
