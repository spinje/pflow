# Trace Analysis Tools

This directory contains tools for analyzing pflow planner trace files to help improve prompts and debug issues.

## Overview

When you run pflow with the `--trace` flag, it creates detailed JSON trace files in `~/.pflow/debug/`. These tools help you:

- 📊 **Analyze token usage** - See how many tokens each prompt/response uses
- 💰 **Estimate costs** - Understand the cost implications of your prompts
- 📝 **Review prompts** - Read prompts in a clean, formatted way
- 🔍 **Compare traces** - See what changed between runs
- 🎯 **Improve efficiency** - Identify opportunities to reduce token usage

## Directory Structure

```
scripts/analyze-trace/
├── README.md          # This file
├── analyze.py         # Main analyzer - splits traces into individual files
├── compare.py         # Compare two traces to see differences
├── latest.sh          # Quick script to analyze the most recent trace
└── output/            # Generated analysis files go here
    └── pflow-trace-*/  # One directory per analyzed trace
        ├── README.md                      # Index with summary statistics
        ├── 01-WorkflowDiscoveryNode.md   # Individual node analysis
        ├── 02-ComponentBrowsingNode.md   # Each LLM call gets its own file
        └── ...
```

## Usage

### 1. Generate a Trace

First, run pflow with the `--trace` flag to generate a trace file:

```bash
# Always saves trace on success or failure
uv run pflow --trace "create a workflow that generates a changelog"

# Trace files are saved to ~/.pflow/debug/pflow-trace-*.json
```

### 2. Analyze a Trace

#### Option A: Analyze the Most Recent Trace

```bash
# Quick way - analyzes the latest trace and opens in VS Code (if available)
./scripts/analyze-trace/latest.sh
```

#### Option B: Analyze a Specific Trace

```bash
# Analyze a specific trace file
uv run python scripts/analyze-trace/analyze.py ~/.pflow/debug/pflow-trace-20250815-120310.json

# Or specify a custom output directory
uv run python scripts/analyze-trace/analyze.py trace.json my-analysis/
```

### 3. Review the Analysis

The analyzer creates a directory with:

- **README.md** - Overview with summary statistics, token counts, costs, and execution flow
- **Individual node files** - One markdown file per LLM call with:
  - Token usage breakdown (prompt vs response)
  - Cost estimates
  - Full prompt text
  - Complete response
  - Analysis notes section

Example output structure:
```
output/pflow-trace-20250815-120310/
├── README.md                      # Summary with stats and navigation
├── 01-WorkflowDiscoveryNode.md   # First LLM call
├── 02-ComponentBrowsingNode.md   # Second LLM call
├── 03-ParameterDiscoveryNode.md  # Third LLM call
└── ...
```

### 4. Compare Two Traces

Compare traces to see what changed between runs:

```bash
# Compare two trace files
uv run python scripts/analyze-trace/compare.py trace1.json trace2.json

# This shows:
# - Prompt differences (with diffs)
# - Response changes
# - Performance metrics comparison
# - Success/failure status changes
```

## Understanding the Output

### Token Usage Table

Each node file includes a token breakdown:

```markdown
## 📊 Token Usage

| Type | Count | Percentage |
|------|-------|------------|
| **Prompt** | 1,675 | 86.1% |
| **Response** | 271 | 13.9% |
| **Total** | 1,946 | 100% |

**Estimated Cost:** $0.009090
```

### Summary Statistics

The README.md index shows aggregate metrics:

```markdown
## 📊 Summary Statistics

- **Total LLM Calls:** 8
- **Total Duration:** 35.2s
- **Total Tokens:** 7,536
  - Prompt Tokens: 5,813
  - Response Tokens: 1,723
- **Estimated Total Cost:** $0.0433
```

### Execution Flow

See the sequence of nodes and their resource usage:

```markdown
## 🔄 Execution Flow

| # | Node | Duration | Tokens | File |
|---|------|----------|--------|------|
| 1 | WorkflowDiscovery | 5.3s | 587 | [01-WorkflowDiscoveryNode.md](./01-WorkflowDiscoveryNode.md) |
| 2 | ComponentBrowsing | 8.1s | 627 | [02-ComponentBrowsingNode.md](./02-ComponentBrowsingNode.md) |
...
```

## Workflow for Prompt Improvement

1. **Baseline** - Run your workflow with `--trace` to establish baseline metrics
2. **Analyze** - Use `latest.sh` to quickly analyze the trace
3. **Identify Issues** - Look for:
   - High token usage in specific nodes
   - Redundant information in prompts
   - Inefficient response formats
   - Failed validations or retries
4. **Modify Prompts** - Edit the prompts in `src/pflow/planning/prompts/`
5. **Test Changes** - Run the same workflow again with `--trace`
6. **Compare** - Use `compare.py` to see the differences
7. **Iterate** - Repeat until satisfied with token usage and accuracy

## Tips for Reducing Token Usage

1. **Remove redundant context** - Only include necessary information in prompts
2. **Use concise instructions** - Be clear but brief
3. **Optimize response formats** - Request only the fields you need
4. **Cache common patterns** - Reuse successful prompt structures
5. **Eliminate examples** - Only include examples when absolutely necessary

## Token Counting

The analyzer provides token estimates using a simple heuristic (1 token ≈ 4 characters). For more accurate counts, you could enhance the analyzer with tiktoken:

```python
# Install: pip install tiktoken
import tiktoken
encoding = tiktoken.encoding_for_model("gpt-4")
tokens = len(encoding.encode(text))
```

## Cost Estimates

Default cost estimates are based on common pricing:
- Input tokens: $3 per 1M tokens
- Output tokens: $15 per 1M tokens

Adjust these in `analyze.py` if using different models or pricing tiers.

## Troubleshooting

### No trace files found
- Make sure you're running pflow with the `--trace` flag
- Check that traces are being saved to `~/.pflow/debug/`

### Large trace files
- The analyzer handles large traces well
- Individual node files make it easy to focus on specific parts

### VS Code doesn't open
- The `latest.sh` script will show the output directory path
- You can manually open the directory in any text editor

## Future Enhancements

Potential improvements to these tools:

- **Batch analysis** - Analyze multiple traces at once
- **Trend analysis** - Track token usage over time
- **Prompt templates** - Extract successful prompts as templates
- **A/B testing** - Compare different prompt strategies
- **Regression detection** - Alert when prompts degrade
- **Cost tracking** - Monitor spending across all runs

## Continue working

This feature was implemented with Claude Code with session id: `e040e5f0-9389-424a-b369-b4fddaea9594`

If the user want to work on this feature, you should suggest they run the following command: `claude -r e040e5f0-9389-424a-b369-b4fddaea9594`