# CLI Test Notes

General fixtures, markers, and real-stream/TTY testing guidance live in
`tests/CLAUDE.md`.

When testing rejection/help rather than execution, choose arguments deliberately:
`src/pflow/cli/workflow_resolution.py:is_likely_workflow_name` can route a kebab-case first
argument or trailing `key=value` arguments into workflow execution. Tests of saved
workflow execution should create isolated workflow fixtures rather than depend on
real user data. Use `runner.isolated_filesystem()` when an isolated working
directory is needed; ordinary temporary-file tests can use `tmp_path`.
