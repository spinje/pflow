"""Compiler coverage for the `loop:` config block (issue #445).

Covers Phase 2: `LoopConfig` construction, literal `max_iterations` validation
(>= 1, <= MAX_NODE_VISITS, non-int rejection), template deferral, and
batch/loop mutual exclusion.
"""

import pytest

from pflow.core.exceptions import CompilationError
from pflow.registry import Registry
from pflow.runtime.compilation.compiler import _build_loop_config, compile_workflow
from pflow.runtime.engine import instrumentation
from pflow.runtime.engine.types import LoopConfig


def _node(loop, *, batch=None):
    n = {"id": "n", "type": "shell", "params": {"command": "echo hi"}, "loop": loop}
    if batch is not None:
        n["batch"] = batch
    return n


def test_literal_max_iterations() -> None:
    lc = _build_loop_config(_node({"while": "${n.stdout}", "max_iterations": 5}), False)
    assert lc == LoopConfig(while_template="${n.stdout}", max_iterations=5, max_iterations_template=None)


def test_template_max_iterations_deferred() -> None:
    lc = _build_loop_config(_node({"while": "${n.x}", "max_iterations": "${cap}"}), False)
    assert lc is not None and lc.max_iterations is None and lc.max_iterations_template == "${cap}"


def test_no_max_iterations_defaults_none() -> None:
    lc = _build_loop_config(_node({"while": "${n.x}"}), False)
    assert lc is not None and lc.max_iterations is None and lc.max_iterations_template is None


def test_batch_and_loop_mutually_exclusive() -> None:
    with pytest.raises(CompilationError, match="mutually exclusive"):
        _build_loop_config(_node({"while": "${n.x}"}, batch={"items": [1]}), True)


def test_missing_while_rejected() -> None:
    with pytest.raises(CompilationError, match="missing a `while:`"):
        _build_loop_config(_node({"max_iterations": 3}), False)


def test_max_iterations_zero_rejected() -> None:
    with pytest.raises(CompilationError, match=">= 1"):
        _build_loop_config(_node({"while": "${n.x}", "max_iterations": 0}), False)


def test_max_iterations_over_cap_rejected() -> None:
    over = instrumentation.MAX_NODE_VISITS + 1
    with pytest.raises(CompilationError, match="exceeds the hard visit cap"):
        _build_loop_config(_node({"while": "${n.x}", "max_iterations": over}), False)


def test_max_iterations_garbage_rejected() -> None:
    with pytest.raises(CompilationError, match="positive integer"):
        _build_loop_config(_node({"while": "${n.x}", "max_iterations": "abc"}), False)


def test_over_cap_respects_lowered_env(monkeypatch) -> None:
    monkeypatch.setattr(instrumentation, "MAX_NODE_VISITS", 3)
    with pytest.raises(CompilationError, match="exceeds the hard visit cap"):
        _build_loop_config(_node({"while": "${n.x}", "max_iterations": 4}), False)
    # 3 is exactly the cap — allowed
    assert _build_loop_config(_node({"while": "${n.x}", "max_iterations": 3}), False).max_iterations == 3


def test_compile_workflow_builds_loop_config() -> None:
    ir = {
        "ir_version": "0.1.0",
        "nodes": [_node({"while": "${n.stdout}", "max_iterations": 5})],
        "edges": [],
    }
    compiled = compile_workflow(ir, Registry())
    assert compiled.node_configs["n"].loop_config == LoopConfig(
        while_template="${n.stdout}", max_iterations=5, max_iterations_template=None
    )


def test_compile_workflow_rejects_batch_plus_loop() -> None:
    # batch+loop is now caught by the shared data_flow validation (which runs during
    # compile via _validate_data_flow_at_compile_time), BEFORE the _build_loop_config
    # backstop is reached — so compilation fails at the validation phase. The specific
    # "mutually exclusive" message is asserted by the _build_loop_config unit test above
    # and by test_loop_validation::test_batch_and_loop_rejected_on_validate_path.
    ir = {
        "ir_version": "0.1.0",
        "nodes": [_node({"while": "${n.x}"}, batch={"items": [1, 2]})],
        "edges": [],
    }
    with pytest.raises(CompilationError):
        compile_workflow(ir, Registry())
