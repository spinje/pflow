#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"

TRACE="$BASELINE_HOME/partial-trace.json"
python3 - <<'PY'
import json
import os
from pathlib import Path

src = Path(os.environ["BASELINE_DIR"]) / "_shared/fixtures/live-gemini-translation.trace.json"
data = json.loads(src.read_text())
first = data["nodes"][0]
data["workflow_name"] = "workflow"
data["workflow_path"] = str(Path(os.environ["BASELINE_CASE_DIR"]) / "workflow.pflow.md")
data["nodes"] = [
    first,
    {
        "node_id": "blocker",
        "node_type": "ShellNode",
        "duration_ms": 41.0,
        "success": False,
        "timestamp": "2026-05-08T21:51:28.230000",
        "node_params": {"command": "exit 1", "cache": False},
        "template_resolutions": {},
        "node_output": {
            "stdout": "",
            "stderr": "",
            "exit_code": 1,
            "error": "Command failed with exit code 1",
        },
        "mutations": {},
    },
]
data["nodes_executed"] = 2
data["nodes_failed"] = 1
data["final_status"] = "failed"
data["failed_node_ids"] = ["blocker"]

call = first["llm_call"]
summary = data.get("llm_summary", {})
summary["total_calls"] = 1
summary["total_input_tokens"] = call["input_tokens"]
summary["total_output_tokens"] = call["output_tokens"]
summary["total_tokens"] = call["total_tokens"]
summary["total_cost_usd"] = call["cost_usd"]
summary["models_used"] = [call["model"]]
summary["pricing_available"] = True

Path(os.environ["BASELINE_HOME"], "partial-trace.json").write_text(json.dumps(data, indent=2))
PY

uv run pflow analyze-cache \
  "$BASELINE_CASE_DIR/workflow.pflow.md" \
  --from-trace "$TRACE" \
  context="ignored-by-trace-mode"
