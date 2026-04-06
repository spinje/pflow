"""Golden file tests for mermaid visualization output.

These tests compare the output of generate_mermaid() against committed golden
files to catch any unintended changes during refactoring.  The golden files
were generated via the CLI and represent the expected byte-exact output.

To regenerate a golden file after an intentional change:

    uv run pflow visualize <workflow> [flags] -o tests/test_core/golden_mermaid/<name>.mmd

The lyrics-generator tests require an external repo and are skipped in CI.
"""

from pathlib import Path

import pytest

from pflow.core.workflow.mermaid import generate_mermaid
from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow
from pflow.execution.workflow_resolver import resolve_workflow

GOLDEN_DIR = Path(__file__).parent / "golden_mermaid"

LYRICS_GENERATOR = Path("/Users/andfal/projects/music-generation/workflows/lyrics-generator/lyrics-generator.pflow.md")


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


# ---------------------------------------------------------------------------
# In-repo workflows (always available)
# ---------------------------------------------------------------------------

EXAMPLES_DIR = Path(__file__).parent.parent.parent / "examples"


@pytest.mark.parametrize(
    "workflow_rel,golden_name,direction",
    [
        ("core/conditional-branching.pflow.md", "conditional-branching.mmd", "LR"),
        ("nested/document-processor.pflow.md", "document-processor.mmd", "LR"),
        ("batch-test-parallel.pflow.md", "batch-parallel.mmd", "LR"),
        ("core/error-handling.pflow.md", "error-handling.mmd", "LR"),
        ("real-workflows/generate-changelog/workflow.pflow.md", "generate-changelog.mmd", "LR"),
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


# ---------------------------------------------------------------------------
# Lyrics-generator (external repo — skipped when unavailable)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not LYRICS_GENERATOR.exists(), reason="lyrics-generator repo not available")
@pytest.mark.parametrize(
    "golden_name,direction",
    [
        ("lyrics-generator-TD.mmd", "TD"),
        ("lyrics-generator-LR.mmd", "LR"),
    ],
)
def test_golden_lyrics_generator(golden_name: str, direction: str) -> None:
    """Lyrics-generator mermaid output matches golden file."""
    golden_path = GOLDEN_DIR / golden_name
    assert golden_path.exists(), f"Golden file not found: {golden_path}"

    actual = _generate_from_file(
        LYRICS_GENERATOR,
        direction=direction,
    )
    expected = golden_path.read_text(encoding="utf-8")

    assert actual == expected, (
        f"Mermaid output differs from golden file {golden_name}.\n"
        f"To update: uv run pflow visualize {LYRICS_GENERATOR} --depth 5 "
        f"--direction {direction} -o {golden_path}"
    )
