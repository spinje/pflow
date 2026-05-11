#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
TRACE="$BASELINE_HOME/discrepancy-trace.json"

uv run python - <<'PY'
import json
import os
from pathlib import Path

from pflow.runtime.cache import MemoizationCache

# The analyzer only predicts memo keys when a memo database exists. The
# database does not need entries; plan_node still computes the miss key.
MemoizationCache()

workflow_path = str(Path(os.environ["BASELINE_CASE_DIR"]) / "workflow.pflow.md")
trace = {
    "format_version": "2.2.0",
    "execution_id": "baseline-discrepancy",
    "workflow_name": "workflow",
    "workflow_path": workflow_path,
    "start_time": "2026-05-11T10:00:00",
    "end_time": "2026-05-11T10:00:01",
    "duration_ms": 1000,
    "final_status": "success",
    "nodes_executed": 1,
    "nodes_failed": 0,
    "failed_node_ids": [],
    "llm_summary": {
        "total_calls": 1,
        "total_input_tokens": 1800,
        "total_output_tokens": 24,
        "total_tokens": 1824,
        "models_used": ["anthropic/claude-sonnet-4-5"],
        "total_cost_usd": 0.0058,
        "pricing_available": True,
    },
    "nodes": [
        {
            "node_id": "gen",
            "node_type": "LLMNode",
            "duration_ms": 900,
            "success": True,
            "timestamp": "2026-05-11T10:00:01",
            "node_params": {"model": "anthropic/claude-sonnet-4-5", "max_tokens": 80},
            "template_resolutions": {},
            "node_output": {"response": "Generated answer."},
            "mutations": {},
            "llm_prompt": "Generate a deterministic answer from the stable prompt.",
            "llm_response": "Generated answer.",
            "llm_call": {
                "model": "anthropic/claude-sonnet-4-5",
                "input_tokens": 1800,
                "output_tokens": 24,
                "total_tokens": 1824,
                "cache_creation_input_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_age_sec": 10,
                "cache_chunks_skipped": [],
                "cache_key": "actual-key-from-trace",
                "cost_usd": 0.0058,
            },
        }
    ],
}
Path(os.environ["BASELINE_HOME"], "discrepancy-trace.json").write_text(json.dumps(trace, indent=2))
PY

uv run pflow analyze-cache "$BASELINE_CASE_DIR/workflow.pflow.md" --from-trace "$TRACE"
