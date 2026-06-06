"""Golden file tests for mermaid visualization output.

These tests compare the output of generate_mermaid() against committed golden
files to catch any unintended changes during refactoring.  The golden files
were generated via the CLI and represent the expected byte-exact output.

To regenerate a golden file after an intentional change:

    uv run pflow visualize <workflow> [flags] -o tests/test_core/golden_mermaid/<name>.mmd
"""

from pathlib import Path

import pytest

from pflow.core.workflow.mermaid import generate_mermaid
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.workflow_resolver import resolve_workflow

GOLDEN_DIR = Path(__file__).parent / "golden_mermaid"
EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


def _generate_from_file(
    workflow_path: Path,
    *,
    depth: int = 5,
    direction: str = "LR",
    descriptions: bool = False,
) -> str:
    """Resolve a workflow file and generate mermaid output."""
    resolved = resolve_workflow(str(workflow_path))
    base_path = Path(resolved.file_path).parent if resolved.file_path else None
    return generate_mermaid(
        resolved.ir,
        resolve_child=resolve_sub_workflow,
        base_path=base_path,
        max_depth=depth,
        direction=direction,
        descriptions=descriptions,
    )


@pytest.mark.parametrize(
    "workflow_rel,golden_name,direction",
    [
        ("core/conditional-branching.pflow.md", "conditional-branching.mmd", "LR"),
        ("nested/document-processor.pflow.md", "document-processor.mmd", "LR"),
        ("batch-test-parallel.pflow.md", "batch-parallel.mmd", "LR"),
        ("core/error-handling.pflow.md", "error-handling.mmd", "LR"),
        ("real-workflows/generate-changelog/workflow.pflow.md", "generate-changelog.mmd", "LR"),
        ("nested/deep-research/deep-research.pflow.md", "deep-research-TD.mmd", "TD"),
        ("nested/deep-research/deep-research.pflow.md", "deep-research-LR.mmd", "LR"),
        # Loop rendering: `loop:` on a sub-workflow node (multinode body) renders the
        # loop badge on the subgraph title — the only golden exercising loop visibility.
        ("core/stateful-loop-tournament.pflow.md", "stateful-loop-tournament.mmd", "LR"),
    ],
)
def test_golden_example_workflow(workflow_rel: str, golden_name: str, direction: str) -> None:
    """Example workflow mermaid output matches golden file."""
    workflow_path = EXAMPLES_DIR / workflow_rel
    golden_path = GOLDEN_DIR / golden_name

    assert workflow_path.exists(), f"Workflow not found: {workflow_path}"
    assert golden_path.exists(), f"Golden file not found: {golden_path}"

    actual = _generate_from_file(workflow_path, direction=direction)
    expected = golden_path.read_text(encoding="utf-8")

    assert actual == expected, (
        f"Mermaid output differs from golden file {golden_name}.\n"
        f"To update: uv run pflow visualize {workflow_path} --depth 5 "
        f"--direction {direction} -o {golden_path}"
    )
