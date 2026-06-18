# tests/test_cli/CLAUDE.md

CLI-specific test notes. General test guidance (markers, fixtures, CliRunner limits, subprocess/e2e patterns, LLM mock) lives in `tests/CLAUDE.md`.

- **Don't use real saved workflow names as CliRunner args** — a kebab-case or `key=value` arg can trip `is_likely_workflow_name` and trigger a real direct-execution attempt instead of the path you meant to test.
- Use `runner.isolated_filesystem()` for tests that touch the filesystem.
