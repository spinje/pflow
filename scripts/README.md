# Scripts Directory

This directory contains utility scripts for development and testing.

## analyze-trace/

Tools for analyzing workflow trace files to debug runs and inspect LLM usage.

### Quick Start
```bash
# Analyze the most recent trace
./scripts/analyze-trace/latest.sh

# Analyze a specific trace
uv run python scripts/analyze-trace/analyze.py ~/.pflow/debug/workflow-trace-*.json
```

See [analyze-trace/README.md](analyze-trace/README.md) for detailed documentation.
