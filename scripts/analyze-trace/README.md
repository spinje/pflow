# Trace analysis tools

This directory contains helpers for analyzing `workflow-trace-*.json` files saved in `~/.pflow/debug/`.

## What these scripts do

- Inspect per-node LLM prompts, responses, token usage, and duration
- Summarize a single workflow trace into readable markdown
- Compare two workflow traces to see what changed between runs

## Files

```text
scripts/analyze-trace/
├── README.md
├── analyze.py
├── compare.py
├── latest.sh
└── compare-latest.sh
```

## Usage

Generate a workflow trace:

```bash
uv run pflow my-workflow
```

Analyze the latest trace:

```bash
./scripts/analyze-trace/latest.sh
```

Analyze a specific trace:

```bash
uv run python scripts/analyze-trace/analyze.py ~/.pflow/debug/workflow-trace-20250815-120310.json
```

Compare the two most recent traces:

```bash
./scripts/analyze-trace/compare-latest.sh
```

Compare two specific traces:

```bash
uv run python scripts/analyze-trace/compare.py trace1.json trace2.json
```

## Output

The analyzer writes markdown files under `scripts/analyze-trace/output/`, including:

- A top-level `README.md` with summary metrics
- One markdown file per captured LLM call
- Comparison reports for two-trace diffs

## Notes

- Use `--no-trace` only when you explicitly want to skip trace capture.
- The analyzer still tolerates some older trace shapes, but current usage is workflow-trace based.
