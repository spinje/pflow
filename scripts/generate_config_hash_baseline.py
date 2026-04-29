"""Generate the golden_config_hashes.json regression baseline (Task 159 B3).

Hashes every node in a curated set of workflows via compile_workflow ->
compute_node_config -> compute_config_hash. The committed fixture is the
load-bearing regression gate: workflows that DO NOT use prompt_cache:/##Cache
must produce byte-identical hashes pre- and post-Task-159 B3 patches. Drift
indicates a silent stale-cache regression class (DD#19).

Usage:
    uv run python scripts/generate_config_hash_baseline.py

Regenerate ONLY after a human-reviewed intentional change to compute_node_config
or its inputs. Silent regeneration encodes the bug as expected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "test_runtime" / "fixtures" / "golden_config_hashes.json"

# Make the shared baseline module importable when running as a script.
sys.path.insert(0, str(REPO_ROOT))
from tests.test_runtime.fixtures.baseline_workflows import (  # noqa: E402
    BASELINE_WORKFLOWS,
    FixtureWorkflow,
)


def compute_hashes_for_workflow(workflow: FixtureWorkflow, registry: Any) -> dict[str, str]:
    """Compile a workflow and return {node_id: config_hash}."""
    from pflow.runtime.compilation.compiler import compile_workflow
    from pflow.runtime.engine.instrumentation import compute_config_hash, compute_node_config

    abs_path = REPO_ROOT / workflow.rel_path
    if not abs_path.exists():
        raise FileNotFoundError(f"Fixture workflow missing: {abs_path}")
    ir_dict = _parse_to_ir(abs_path)
    initial = {**workflow.inputs, "_pflow_workflow_file": str(abs_path)}
    compiled = compile_workflow(ir_dict, registry, initial_params=initial)
    hashes: dict[str, str] = {}
    for node_id, config in compiled.node_configs.items():
        node_config = compute_node_config(
            config.node_type_name,
            config.template_config.static_params if config.template_config else {},
            config.template_config.template_params if config.template_config else {},
            config.batch_config,
        )
        hashes[node_id] = compute_config_hash(node_config)
    return hashes


def _parse_to_ir(workflow_path: Path) -> dict[str, Any]:
    """Parse markdown and return the IR dict."""
    from pflow.core.markdown_parser import parse_markdown

    text = workflow_path.read_text(encoding="utf-8")
    return parse_markdown(text).ir


def _build_meta() -> dict[str, Any]:
    return {
        "purpose": (
            "Task 159 B3 regression baseline. Workflows WITHOUT prompt_cache:/## Cache must "
            "produce byte-identical hashes pre- and post-Task-159 B3 patches. Drift indicates "
            "a silent stale-cache regression (DD#19)."
        ),
        "regen_command": "uv run python scripts/generate_config_hash_baseline.py",
        "warning": (
            "DO NOT regenerate without human review of the change. Silent regeneration "
            "encodes the bug as expected."
        ),
    }


def _build_coverage() -> dict[str, list[str]]:
    return {wf.rel_path: list(wf.shapes) for wf in BASELINE_WORKFLOWS}


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from pflow.registry.registry import Registry

    registry = Registry()
    output: dict[str, Any] = {"_meta": _build_meta(), "_coverage": _build_coverage()}
    for wf in BASELINE_WORKFLOWS:
        output[wf.rel_path] = compute_hashes_for_workflow(wf, registry)
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    total_nodes = sum(len(v) for k, v in output.items() if not k.startswith("_"))
    print(
        f"Wrote {FIXTURE_PATH.relative_to(REPO_ROOT)}: "
        f"{len(BASELINE_WORKFLOWS)} workflows, {total_nodes} nodes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
