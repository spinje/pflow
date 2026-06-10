"""Render Mermaid for every buildable example into a directory, for before/after
diffing around the is_decision rule change.

Usage: uv run python scratchpads/transform-role/mermaid_corpus.py /tmp/mermaid-before
"""

from __future__ import annotations

import sys
from pathlib import Path

from pflow.core.workflow.graph import render_mermaid
from pflow.execution.graph_service import resolve_validate_build

EXCLUDED_DIRS = {"invalid", "legacy", "real-workflows"}


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = [
        f for f in sorted(Path("examples").rglob("*.pflow.md"))
        if not (set(f.parts) & EXCLUDED_DIRS)
    ]
    ok = 0
    for f in files:
        try:
            graph = resolve_validate_build(str(f), max_depth=5)
        except Exception:  # noqa: BLE001 — sweep tool
            continue
        name = str(f.relative_to("examples")).replace("/", "__").replace(".pflow.md", ".mmd")
        (out / name).write_text(render_mermaid(graph))
        ok += 1
    print(f"rendered {ok}/{len(files)} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1])
