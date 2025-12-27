# Scripts Directory

This directory contains utility scripts for development and testing.

## analyze-trace/

Tools for analyzing planner trace files to optimize prompts and debug issues.

### Quick Start
```bash
# Analyze the most recent trace
./scripts/analyze-trace/latest.sh

# Analyze a specific trace
uv run python scripts/analyze-trace/analyze.py ~/.pflow/debug/planner-trace-*.json
```

See [analyze-trace/README.md](analyze-trace/README.md) for detailed documentation.
