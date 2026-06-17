"""Generator for the committed React-Flow contract fixtures the web tests consume.

Why this exists: every web test builds its contract payloads BY HAND, which is
exactly the synthetic-fixture trap (tests/CLAUDE.md gotcha #19) — a hand-built
fixture can encode a bug-compatible shape and stay green while the real
renderer's output breaks the frontend. The literal-batch invisibility bug
(2026-06-11, CRITICAL) lived precisely in that blind spot: the Python contract
and the frontend composition were each "right by themselves".

These fixtures are REAL renderer output for three representative workflows
(branching/error/end · dynamic batch + loop + nesting · literal batches +
truncation + IO), committed under ``web/src/test/fixtures/contracts/`` where
``web/src/graph/lossless.test.ts`` feeds them through ``buildFlow``'s
no-information-loss invariant. Drift detection mirrors the cache_analysis
pattern: ``tests/test_core/test_react_flow_contract_fixtures.py`` fails when
the committed JSON no longer matches the live renderer (the failure message
carries the regen command).

Regenerate: ``uv run python -m tests.fixtures.react_flow_contracts._generate``
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_DIR = REPO_ROOT / "web" / "src" / "test" / "fixtures" / "contracts"

# name -> repo-relative workflow path. Chosen for structural variety, not count:
# every feature the frontend composes over (decision/error/end, dynamic batch of
# sub-workflows, loops, literal batches of sub-workflows incl. >4-item
# truncation, nested IO wrappers) appears in at least one.
WORKFLOWS: dict[str, str] = {
    "conditional-branching": "examples/core/conditional-branching.pflow.md",
    "run-cycle": "examples/agent-orchestration/parallel-planner-review/run-cycle/run-cycle.pflow.md",
    "deep-research": "examples/nested/deep-research/deep-research.pflow.md",
    # prompt-cache edges (input_name="prompt_cache") — pins them in the Python
    # drift guard AND enrolls them in the frontend lossless real-contract sweep.
    "prompt-caching-multi-chunk": "examples/core/prompt-caching-multi-chunk.pflow.md",
}

# Matches the `pflow ui` server's depth (graph_service default path).
MAX_DEPTH = 5


def _relativize_source_files(data: Any) -> Any:
    """Rewrite every ``source.file`` absolute path to REPO_ROOT-relative, in place.

    The contract carries ABSOLUTE source paths (``build.py`` stores ``str(source_file)``
    verbatim, resolved for child refs), so a committed fixture would otherwise bake in
    the generating machine's checkout root — the comparison then fails on every OTHER
    machine (CI at ``/home/runner/work/...`` vs a dev clone). The path VALUE is
    environment noise, not contract shape: the web consumer (``lossless.test.ts``)
    never reads ``source.file``, and the live server keys its source pane on the node,
    not this string. Normalizing here — the one function feeding both the fixture
    writer and the drift comparison — makes both sides machine-independent.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "file" and isinstance(value, str):
                # ValueError = path outside the repo (shouldn't happen for in-repo fixtures) — leave it
                with contextlib.suppress(ValueError):
                    data[key] = Path(value).resolve().relative_to(REPO_ROOT).as_posix()
            else:
                _relativize_source_files(value)
    elif isinstance(data, list):
        for item in data:
            _relativize_source_files(item)
    return data


def render_contract(name: str) -> dict[str, Any]:
    """The live renderer's contract for one fixture workflow, as plain JSON data."""
    from pflow.core.workflow.graph import render_react_flow
    from pflow.execution.graph_service import resolve_validate_build
    from pflow.registry import Registry

    graph = resolve_validate_build(str(REPO_ROOT / WORKFLOWS[name]), max_depth=MAX_DEPTH)
    # Mirror the `pflow ui` server exactly: it injects the registry's declared
    # output types (ui/server.py). The fixture workflows use core kinds only,
    # whose interfaces live in this repo's docstrings — deterministic across
    # environments (the renderer filters to kinds present in the graph).
    kind_types = Registry().output_types_by_kind()
    rf = render_react_flow(graph, kind_output_types=kind_types)
    # Round-trip through dumps/loads so the committed file and the comparison
    # both see pure JSON types (tuples -> lists), exactly what the wire carries.
    data = json.loads(json.dumps(asdict(rf), default=str))
    # Strip the absolute checkout root from source paths so the fixture is portable.
    return _relativize_source_files(data)  # type: ignore[no-any-return]


def main() -> None:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    for name in WORKFLOWS:
        path = CONTRACT_DIR / f"{name}.json"
        path.write_text(json.dumps(render_contract(name), indent=2) + "\n")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
