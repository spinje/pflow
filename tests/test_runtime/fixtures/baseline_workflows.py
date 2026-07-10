"""Single source of truth for the Task 159 B3 regression baseline workflows.

Both ``scripts/generate_config_hash_baseline.py`` (regen) and
``tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match``
(verify) import this module. Without this consolidation, the script's
``WORKFLOWS`` table and the test's ``_BASELINE_INPUTS`` dict could drift —
regen would produce hashes that the test cannot reproduce, surfacing as a
spurious DD#19 regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FixtureWorkflow:
    """One workflow in the baseline.

    rel_path: project-relative path (e.g. ``examples/core/minimal.pflow.md``).
    shapes: tags listed in the fixture's ``_coverage`` block for auditability.
    inputs: workflow-input dict needed for ``compile_workflow`` to succeed.
    """

    rel_path: str
    shapes: tuple[str, ...]
    inputs: dict[str, Any] = field(default_factory=dict)


BASELINE_WORKFLOWS: tuple[FixtureWorkflow, ...] = (
    FixtureWorkflow(
        rel_path="examples/core/minimal.pflow.md",
        shapes=("plain", "single-node", "static-params-only"),
    ),
    FixtureWorkflow(
        rel_path="examples/core/simple-pipeline.pflow.md",
        shapes=("plain", "multi-step", "static-params-only", "non-llm-types"),
    ),
    FixtureWorkflow(
        rel_path="examples/core/template-variables.pflow.md",
        shapes=("template-params", "multiple-required-inputs"),
        inputs={
            "input_file": "in.txt",
            "file_encoding": "utf-8",
            "api_token": "tok",
            "api_endpoint": "https://x",
            "backup_dir": "./backups",
            "backup_name": "b.txt",
            "output_dir": "./output",
            "output_file": "o.txt",
            "timestamp": "unknown",
            "recipient_email": "r@x",
        },
    ),
    FixtureWorkflow(
        rel_path="examples/core/conditional-branching.pflow.md",
        shapes=("branching", "code-node", "next-routing"),
    ),
    FixtureWorkflow(
        rel_path="examples/real-workflows/git-worktree-task-creator/workflow.pflow.md",
        shapes=("cache-false", "llm-node", "shell-templates"),
        inputs={"task_description": "implement caching"},
    ),
    FixtureWorkflow(
        rel_path="examples/batch-test.pflow.md",
        shapes=("batch", "batch-sequential", "batch-default-config"),
    ),
    FixtureWorkflow(
        rel_path="examples/batch-test-parallel.pflow.md",
        shapes=("batch", "batch-parallel", "batch-max-concurrent"),
    ),
    FixtureWorkflow(
        rel_path="examples/test_llm_templates.pflow.md",
        shapes=("llm-node", "template-params", "llm-defaults"),
        inputs={"topic": "caching"},
    ),
    FixtureWorkflow(
        rel_path="examples/bundling/parent-with-sub.pflow.md",
        shapes=("workflow-node", "sub-workflow"),
        inputs={"input": "x"},
    ),
)
