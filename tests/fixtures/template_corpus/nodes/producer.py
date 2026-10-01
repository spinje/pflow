"""Template-corpus fixture nodes (Task 170 parity corpus).

Two nodes, registered only by ``tests/test_integration/test_template_parity.py``:

- ``TemplateCorpusProducer`` writes a declared, nested output structure read from a
  JSON file. The payload travels through a FILE, never a ``payload: dict`` param, so
  upstream data containing ``${...}`` text is never itself template-resolved by the
  producer's own params.
- ``TemplateCorpusSink`` has typed top-level params, the only way the engine's
  simple-template gate (auto-parse, coercion, ``validate_resolved_type``) is reached
  for a ``str`` template — ``code.inputs`` values are nested and bypass it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pflow.core.node import Node

_PRODUCER_KEYS = ("out", "out_str", "out_list", "out_arr", "out_any")
_SINK_KEYS = ("sink", "sink_list", "sink_str", "sink_any", "sink_union")


class TemplateCorpusProducer(Node):
    """
    Write a declared nested structure from a JSON payload file (test fixture).

    Interface:
    - Params: payload_file: str  # Path to a JSON object whose keys are the outputs to write
    - Writes: shared["out"]: dict  # Nested structured output
        - text: str  # A string field
        - num: int  # An integer field
        - flag: bool  # A boolean field
        - nested: dict  # A nested object
          - k: str  # A nested string field
        - items: list[dict]  # A list of objects
          - x: str  # A field of each item
        - json_str: str  # A string that may hold JSON text
        - maybe: any  # A field that may be null
    - Writes: shared["out_str"]: str  # A top-level string output
    - Writes: shared["out_list"]: list  # A list-typed output
    - Writes: shared["out_arr"]: array  # An array-typed output
    - Writes: shared["out_any"]: any  # An untyped output
    - Actions: default
    """

    def __init__(self) -> None:
        super().__init__(max_retries=1, wait=0)

    def prep(self, shared: dict[str, Any]) -> str:
        return str(self.params["payload_file"])

    def exec(self, prep_res: str) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(Path(prep_res).read_text(encoding="utf-8"))
        return payload

    def post(self, shared: dict[str, Any], prep_res: str, exec_res: dict[str, Any]) -> str:
        for key in _PRODUCER_KEYS:
            if key in exec_res:
                shared[key] = exec_res[key]
        return "default"


class TemplateCorpusSink(Node):
    """
    Record the typed params it received (test fixture).

    Interface:
    - Params: sink: dict  # A dict-typed param
    - Params: sink_list: list  # A list-typed param
    - Params: sink_str: str  # A str-typed param
    - Params: sink_any: any  # An untyped param
    - Params: sink_union: str|dict  # A union-typed param
    - Writes: shared["received"]: any  # {param: value} for every sink param that was set
    - Actions: default
    """

    def __init__(self) -> None:
        super().__init__(max_retries=1, wait=0)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {key: self.params[key] for key in _SINK_KEYS if key in self.params}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        shared["received"] = exec_res
        return "default"
