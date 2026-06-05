"""Parser + IR-schema coverage for the `loop:` config block (issue #445).

Covers Phase 1 (authoring surface + schema): both authoring forms route to
`node["loop"]`, and the schema catches the `whlie:` typo and bad `max_iterations`.
"""

import pytest

from pflow.core.exceptions import SchemaValidationError
from pflow.core.ir_schema import normalize_ir, validate_ir
from pflow.core.markdown_parser import parse_markdown

_BASE = """# Loop test

A loop workflow.

## Steps

### counter

Counts down.

- type: shell
- command: echo hi
- loop:
    while: ${counter.stdout}
    max_iterations: 5
"""


def _ir(md: str) -> dict:
    return normalize_ir(parse_markdown(md).ir)


def test_inline_loop_routes_to_top_level() -> None:
    node = _ir(_BASE)["nodes"][0]
    assert node["loop"] == {"while": "${counter.stdout}", "max_iterations": 5}
    # loop is a top-level node field, not a param
    assert "loop" not in node.get("params", {})


def test_fenced_yaml_loop_routes_to_top_level() -> None:
    md = """# Loop test

A loop workflow.

## Steps

### counter

Counts.

- type: shell
- command: echo hi

```yaml loop
while: ${counter.stdout}
max_iterations: 3
```
"""
    node = _ir(md)["nodes"][0]
    assert node["loop"] == {"while": "${counter.stdout}", "max_iterations": 3}


def test_valid_loop_passes_schema() -> None:
    validate_ir(_ir(_BASE))  # no raise


def test_whlie_typo_rejected_by_schema() -> None:
    with pytest.raises(SchemaValidationError) as exc:
        validate_ir(_ir(_BASE.replace("while:", "whlie:")))
    # additionalProperties:false is the thing that catches misspelled loop keys.
    assert "whlie" in str(exc.value)


def test_until_loop_passes_schema() -> None:
    ir = _ir(_BASE.replace("while: ${counter.stdout}", "until: ${counter.done}"))
    validate_ir(ir)
    assert ir["nodes"][0]["loop"]["until"] == "${counter.done}"


def test_carry_loop_passes_schema() -> None:
    md = _BASE.replace(
        "while: ${counter.stdout}",
        "carry:\n      state: ${counter.next_state}\n    while: ${counter.more}",
    )
    ir = _ir(md)
    validate_ir(ir)
    assert ir["nodes"][0]["loop"]["carry"] == {"state": "${counter.next_state}"}


def test_non_dict_carry_rejected_by_schema() -> None:
    with pytest.raises(SchemaValidationError):
        validate_ir(_ir(_BASE.replace("while: ${counter.stdout}", "carry: ${counter.x}\n    while: ${counter.more}")))


def test_max_iterations_zero_rejected_by_schema() -> None:
    with pytest.raises(SchemaValidationError):
        validate_ir(_ir(_BASE.replace("max_iterations: 5", "max_iterations: 0")))


def test_max_iterations_template_allowed() -> None:
    ir = _ir(_BASE.replace("max_iterations: 5", "max_iterations: ${max_cycles}"))
    validate_ir(ir)  # template form is valid
    assert ir["nodes"][0]["loop"]["max_iterations"] == "${max_cycles}"


def test_loop_without_max_iterations_allowed() -> None:
    md = """# Loop test

A loop workflow.

## Steps

### counter

Counts.

- type: shell
- command: echo hi
- loop:
    while: ${counter.stdout}
"""
    ir = _ir(md)
    validate_ir(ir)
    assert ir["nodes"][0]["loop"] == {"while": "${counter.stdout}"}
