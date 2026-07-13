"""Regression tests across markdown parsing, compilation, and AgentNode prep."""

from __future__ import annotations

from pathlib import Path

import pytest

from pflow.core.markdown_parser import parse_markdown
from pflow.registry import Registry
from pflow.runtime import compile_workflow


@pytest.fixture
def agent_registry(tmp_path: Path) -> Registry:
    registry = Registry(tmp_path / "registry.json")
    registry.save({
        "agent": {
            "module": "pflow.nodes.agent",
            "class_name": "AgentNode",
            "type": "core",
            "interface": {
                "params": [
                    {"name": "backend", "type": "str"},
                    {"name": "prompt", "type": "str"},
                    {"name": "cwd", "type": "str"},
                    {"name": "use_api_key", "type": "bool"},
                ],
                "outputs": [],
            },
        }
    })
    return registry


@pytest.mark.parametrize("backend", ["claude", "codex"])
def test_fenced_prompt_survives_parser_compiler_and_backend_validation(
    backend: str,
    agent_registry: Registry,
    tmp_path: Path,
) -> None:
    source = f"""# Fenced Agent Prompt

## Steps

### ask

Exercise the unified agent node.

- type: agent
- backend: {backend}
- cwd: {tmp_path}
- use_api_key: false

```prompt
Return the exact text: compiler metadata survived.
```
"""

    parsed = parse_markdown(source)
    parsed_node = parsed.ir["nodes"][0]
    assert parsed_node["_source_lines"]["prompt"] == 15

    compiled = compile_workflow(parsed.ir, registry=agent_registry)

    assert compiled.start_node.params["_prompt_source_line"] == 15
    prepared = compiled.start_node.prep({})
    assert prepared["backend"] == backend
    assert prepared["prompt"] == "Return the exact text: compiler metadata survived."
    assert prepared["use_api_key"] is False
