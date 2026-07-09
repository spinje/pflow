# Scripts Directory

This directory contains utility scripts for development and testing.

## Claude/Codex asset synchronization

`sync_claude_assets.py` keeps generated Codex skills and subagents aligned with their
Claude sources. It automatically discovers every command in `.claude/commands/`. Run
`make sync-claude-assets` after changing a generated source; `make check` runs the
non-mutating `--check` mode in CI.

All generated asset bodies are platform-neutral. The sync tool changes only the
frontmatter required by the destination format.
