"""Task 170 parity corpus: one template, every surface, validator vs runtime.

Each ``Row`` states, for ONE template on ONE surface, what the validator says and
what the runtime does. The validator side is ``WorkflowRunner().validate(...)``
called directly (``execution/runner.py::validate``). It validates through
``core/validation_utils.validate_with_placeholder_inputs``, the one call
``pflow --validate-only``, ``pflow save`` and ``analyze-cache`` share (#643), so a
row speaks for every validation entry point.

The runtime side has a DIRECT driver per surface, because a runner run cannot
reach a template the validator rejects: ``param`` → ``compile_workflow`` +
``resolve_templates``; ``batch_items`` → ``resolve_batch_items``; loop fields →
``evaluate_loop_condition`` / ``resolve_loop_cap``; ``output_source`` →
``populate_declared_outputs``; ``cache_*`` → markdown text through the chunker and
``_resolve_chunk_value`` (hash render and prepare render are asserted
byte-identical); ``prewarm_system`` → ``engine._resolve_template_string``. The
shared store every direct driver resolves against is seeded by a REAL producer
run, and each driver first asserts the producer's namespace equals the payload
(no empty-store free passes). Rows the validator accepts ALSO run end to end
through ``WorkflowRunner().run`` and must agree with the direct driver.

Row discipline (plan §0.5.1): ``Expect(today, after, flips_in)``. ``today`` is a
plain passing test; when ``after`` is set a second item asserts it under
``xfail(strict=True, raises=AssertionError)`` naming the phase that flips it —
the flipping phase deletes the ``today`` item and the marker. A harness bug
raises something other than ``AssertionError`` and therefore fails loudly
instead of masquerading as an expected failure.

If a row fails, fix the divergence, never the row (from phase 2 on).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from pflow.core.prompt_cache import CacheRenderContext, build_cache_system_blocks
from pflow.execution.result import RunnerConfig
from pflow.execution.runner import WorkflowRunner
from pflow.registry import Registry
from pflow.registry.scanner import scan_for_nodes
from pflow.runtime import WorkflowEngine, compile_workflow
from pflow.runtime.engine.batch_executor import _resolve_and_validate_items, resolve_batch_items
from pflow.runtime.engine.engine import _resolve_template_string
from pflow.runtime.engine.loop_control import evaluate_loop_condition, resolve_loop_cap
from pflow.runtime.engine.plan_node import _render_cache_for_hash
from pflow.runtime.engine.template_resolution import resolve_templates
from pflow.runtime.engine.types import LoopConfig
from pflow.runtime.output_resolver import populate_declared_outputs
from tests.shared.markdown_utils import write_workflow_file

# ---------------------------------------------------------------------------
# Registry: the isolated core registry + the two corpus nodes
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]
_CORPUS_NODES_DIR = _REPO / "tests" / "fixtures" / "template_corpus" / "nodes"


def _scan_corpus_nodes() -> dict[str, dict[str, Any]]:
    """Scan ONLY the fixture dir — scanning ``src/pflow/nodes`` here would import the agent
    backend at collection time, before ``test_agent``'s SDK stub (tests/CLAUDE.md pitfall 17).

    The nodes live outside the pflow package, so they are "user" nodes: the compiler
    imports them from their file path.
    """
    entries = scan_for_nodes([_CORPUS_NODES_DIR])
    return {e["name"]: {**{k: v for k, v in e.items() if k != "name"}, "type": "user"} for e in entries}


_CORPUS_NODES = _scan_corpus_nodes()
if set(_CORPUS_NODES) != {"template-corpus-producer", "template-corpus-sink"}:  # pragma: no cover
    raise RuntimeError(f"corpus node scan found {sorted(_CORPUS_NODES)}")


@pytest.fixture(autouse=True)
def _corpus_registry() -> None:
    """Add the corpus nodes to this test's isolated registry (core nodes come from conftest)."""
    registry = Registry()
    registry.save({**registry.load(include_filtered=True), **copy.deepcopy(_CORPUS_NODES)})


class HarnessError(Exception):
    """A harness precondition failed. Deliberately NOT an ``AssertionError``, so it
    fails an ``xfail(raises=AssertionError)`` item loudly instead of passing as one."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise HarnessError(message)


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ok:
    """Validator: no ERROR diagnostic."""


@dataclass(frozen=True)
class Error:
    """Validator: an ERROR diagnostic whose message contains ``substring``."""

    substring: str


@dataclass(frozen=True)
class Resolves:
    """Runtime: the surface received exactly ``value`` (type-exact)."""

    value: Any


@dataclass(frozen=True)
class Unresolved:
    """Runtime: the surface reported the template unresolved, naming every ref.

    ``forbid`` lists text the report must NOT contain (a mangled reference).
    """

    refs: tuple[str, ...]
    forbid: tuple[str, ...] = ()


@dataclass(frozen=True)
class StaticLiteral:
    """Runtime: the param was routed STATIC — the node received the raw text."""


@dataclass(frozen=True)
class Raises:
    """Runtime: the driver raised ``exc_name`` with ``substring`` in its message."""

    exc_name: str
    substring: str


@dataclass(frozen=True)
class Absent:
    """Runtime: the surface produced nothing (output skipped, cache chunk dropped)."""


Outcome = Ok | Error | Resolves | Unresolved | StaticLiteral | Raises | Absent


@dataclass(frozen=True)
class Expect:
    today: Outcome
    after: Outcome | None = None
    flips_in: str | None = None
    why: str = ""

    def __post_init__(self) -> None:
        if (self.after is None) != (self.flips_in is None):
            raise HarnessError("an `after` needs a `flips_in` phase and vice versa")


DEFAULT_PAYLOAD: Mapping[str, Any] = MappingProxyType({
    "out": {
        "text": "T",
        "num": 3,
        "flag": True,
        "nested": {"k": "K"},
        "items": [{"x": "X0"}, {"x": "X1"}],
        "json_str": '{"a": 1}',
        "maybe": None,
    },
    "out_str": "S",
    "out_list": ["L0", "L1"],
    "out_arr": [{"x": "A0"}, {"x": "A1"}],
    "out_any": {"deep": {"v": 1}},
})


@dataclass(frozen=True)
class Row:
    """One template on one surface. ``consumer`` picks the param/annotation for ``param`` rows."""

    id: str
    surface: str
    template: Any
    validator: Expect
    runtime: Expect
    mutation: str = ""
    payload: Mapping[str, Any] = DEFAULT_PAYLOAD
    declared_inputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)
    mode: str = "strict"
    consumer: str = "sink_any"
    batch_items: Any = "${p.out_arr}"
    extra_params: Mapping[str, Any] = field(default_factory=dict)
    # Add node ``g``: a second producer wired only on ``p``'s error action, so it
    # exists (validator roots resolve) but never runs (runtime root ABSENT).
    ghost: bool = False
    # Add node ``b`` between ``p`` and ``s``: a batch sink over ``${p.out_arr}``
    # (``sink_any: ${item}``), so ``s`` can read ``${b.results…}``.
    upstream_batch: bool = False
    # ``cache_*`` rows: the chunk names the consumer's ``prompt_cache:`` lists.
    prompt_cache: tuple[str, ...] = ()
    # When the end-to-end run observes something other than the direct driver
    # (loop iteration counts, a sub-workflow's echoed output), state it here.
    end_to_end: Outcome | None = None


# ---------------------------------------------------------------------------
# Workflow shape: producer ``p`` → consumer ``s``; the surface decides ``s``
# ---------------------------------------------------------------------------


def _write_payload(tmp_path: Path, payload: Mapping[str, Any]) -> Path:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(dict(payload)), encoding="utf-8")
    return path


def _producer_node(node_id: str, payload_file: Path) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "template-corpus-producer",
        "purpose": "Write the corpus payload.",
        "params": {"payload_file": str(payload_file)},
    }


def _code_params(value: Any, annotation: str, extra_inputs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A ``code`` consumer: ``result`` is the input ``v``; extra inputs are declared ``Any``."""
    extra = dict(extra_inputs or {})
    declarations = "".join(f"{name}: Any\n" for name in extra)
    return {"inputs": {"v": value, **extra}, "code": f"v: {annotation}\n{declarations}result: Any = v"}


def _is_code(row: Row) -> bool:
    return row.consumer.startswith("code")


def _consumer(row: Row, **extra: Any) -> dict[str, Any]:
    """Node ``s`` carrying the template: a ``code`` node (``code[:annotation]``) or the typed sink.

    For a ``code`` consumer ``extra_params`` become extra inputs; for the sink, extra params.
    """
    if _is_code(row):
        _, _, annotation = row.consumer.partition(":")
        return _node("code", _code_params(row.template, annotation or "Any", row.extra_params), **extra)
    return _node("template-corpus-sink", {row.consumer: row.template, **row.extra_params}, **extra)


def _node(node_type: str, params: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"id": "s", "type": node_type, "purpose": "Consume the template.", "params": params, **extra}


def _plain_sink(row: Row, **extra: Any) -> dict[str, Any]:
    """Node ``s`` when the template lives on the node's config, not in a param."""
    return _node("template-corpus-sink", {"sink_any": "${p.out_str}", **row.extra_params}, **extra)


def _write_child(tmp_path: Path) -> Path:
    """A child workflow echoing its input ``v`` as output ``got``."""
    child = {
        "ir_version": "0.1.0",
        "inputs": {"v": {"type": "any", "required": True, "description": "value"}},
        "nodes": [{"id": "c", "type": "code", "purpose": "Echo the input.", "params": _code_params("${v}", "Any")}],
        "edges": [],
        "outputs": {"got": {"source": "${c.result}", "description": "the echoed input"}},
    }
    path = tmp_path / "child.pflow.md"
    write_workflow_file(child, path, title="Corpus Child", description="Echo the input.")
    return path


def _names_child(row: Row) -> bool:
    return row.surface == "sub_workflow" and "{child" in str(row.template)


def _child_input_spec(tmp_path: Path) -> dict[str, Any]:
    return {"type": "string", "required": False, "default": str(_write_child(tmp_path)), "description": "child"}


def _build_sub_workflow(row: Row, tmp_path: Path, ir: dict[str, Any]) -> dict[str, Any]:
    # The child path rides in declared input ``child`` so ``${child}`` can name it.
    if _names_child(row):
        ir.setdefault("inputs", {})["child"] = _child_input_spec(tmp_path)
    return _node("workflow", {"workflow": row.template, "inputs": {"v": "fixed"}})


def _build_loop_carry(row: Row, tmp_path: Path, ir: dict[str, Any]) -> dict[str, Any]:
    extra = dict(row.extra_params)
    declarations = "".join(f"{name}: Any\n" for name in extra)
    code = f"v: Any\n{declarations}result: dict = {{'done': False, 'seen': v, 'lst': ['c0', 'c1']}}"
    loop = {"carry": {"v": row.template}, "until": "${s.result.done}", "max_iterations": 2}
    return _node("code", {"inputs": {"v": "seed", **extra}, "code": code}, loop=loop)


def _build_output_source(row: Row, tmp_path: Path, ir: dict[str, Any]) -> dict[str, Any]:
    ir["outputs"] = {"o": {"source": row.template, "description": "the corpus output"}}
    return _plain_sink(row)


def build_ir(row: Row, tmp_path: Path, *, producer_only: bool = False) -> dict[str, Any]:
    """The row's workflow: ``p`` [→ ``b``] → ``s``, plus ghost ``g`` when asked.

    ``producer_only`` stops before ``s`` (and declares no inputs): the seed run.
    """
    payload_file = _write_payload(tmp_path, row.payload)
    ir: dict[str, Any] = {"ir_version": "0.1.0", "nodes": [_producer_node("p", payload_file)], "edges": []}
    if row.mode != "strict":
        ir["template_resolution_mode"] = row.mode
    upstream = "p"
    if row.upstream_batch:
        batch = {"items": "${p.out_arr}", "as": "item"}
        ir["nodes"].append({**_node("template-corpus-sink", {"sink_any": "${item}"}, batch=batch), "id": "b"})
        ir["edges"].append({"from": "p", "to": "b"})
        upstream = "b"
    if producer_only:
        return ir
    if row.declared_inputs:
        ir["inputs"] = {name: dict(spec) for name, spec in row.declared_inputs.items()}
    ir["nodes"].append(SURFACES[row.surface].build(row, tmp_path, ir))
    ir["edges"].append({"from": upstream, "to": "s"})
    if row.ghost:
        ir["nodes"].insert(1, _producer_node("g", payload_file))
        ir["edges"] += [{"from": "p", "to": "g", "action": "error"}, {"from": "g", "to": "s"}]
    return ir


# ---------------------------------------------------------------------------
# Direct drivers — reach what the validator rejects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeObservation:
    kind: str  # resolves | unresolved | static | raises | absent
    value: Any = None
    message: str = ""
    exc_name: str = ""


def _resolved(value: Any) -> RuntimeObservation:
    return RuntimeObservation("resolves", value)


def _input_values(row: Row, tmp_path: Path) -> dict[str, Any]:
    """Declared inputs as the runner seeds them: the given param, else the default."""
    declared = dict(row.declared_inputs)
    if _names_child(row):
        declared["child"] = _child_input_spec(tmp_path)
    return {
        name: row.params[name] if name in row.params else spec["default"]
        for name, spec in declared.items()
        if name in row.params or "default" in spec
    }


def seed_shared(row: Row, tmp_path: Path) -> dict[str, Any]:
    """Run the producer for real; require its namespace to equal the payload.

    The seed workflow declares no inputs (an input it never uses would fail
    validation); the row's input values are layered on at the root, where the
    runner puts them.
    """
    result = WorkflowRunner().run(build_ir(row, tmp_path, producer_only=True), {}, RunnerConfig())
    require(result.success, f"producer seed run failed: {[d.message for d in result.diagnostics]}")
    shared = dict(result.shared_after)
    require(shared["p"] == dict(row.payload), "producer namespace must equal the payload")
    shared.update(_input_values(row, tmp_path))
    return shared


def validator_errors(workflow: str | dict[str, Any], params: Mapping[str, Any]) -> list[str]:
    result = WorkflowRunner().validate(workflow, dict(params))
    return [d.message for d in result.errors]


def _compile(row: Row, ir: dict[str, Any]) -> Any:
    return compile_workflow(ir, Registry(), initial_params=dict(row.params))


def _resolve_param(row: Row, config: Any, shared: dict[str, Any], key: str) -> RuntimeObservation:
    """``resolve_templates`` for node ``s``; the observation is ``merged[key]`` (``["v"]`` of ``inputs``).

    Strict mode raises ``ValueError``: carrying ``_pflow_template_diagnostic`` means
    unresolved, lacking it means a type error.
    """
    template_config = config.template_config
    if template_config is None or key not in template_config.template_params:
        return RuntimeObservation("static")
    try:
        merged, _, errors = resolve_templates(template_config, shared, "s")
    except ValueError as exc:
        if getattr(exc, "_pflow_template_diagnostic", None) is not None:
            return RuntimeObservation("unresolved", message=str(exc))
        return RuntimeObservation("raises", message=str(exc), exc_name=type(exc).__name__)
    if errors:
        return RuntimeObservation("unresolved", message=" | ".join(str(e["message"]) for e in errors))
    return _resolved(merged[key]["v"] if key == "inputs" else merged[key])


def _param_key(row: Row) -> str:
    return "inputs" if _is_code(row) or row.surface == "sub_inputs" else row.consumer


def _drive_param(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    return _resolve_param(row, _compile(row, ir).node_configs["s"], shared, _param_key(row))


def _drive_batch_param(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    """Resolve the param once per item, with the item context the batch executor builds."""
    config = _compile(row, ir).node_configs["s"]
    items = resolve_batch_items(row.batch_items, shared)
    require(isinstance(items, list), f"batch items did not resolve: {items!r}")
    values = []
    for index, item in enumerate(items):
        observed = _resolve_param(row, config, {**shared, "item": item, "__index__": index}, _param_key(row))
        if observed.kind != "resolves":
            return observed
        values.append(observed.value)
    return _resolved(values)


def _drive_batch_items(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    """The executor's own items step: ``None`` raises "resolved to None" (the unresolved report)."""
    config = _compile(row, ir).node_configs["s"]
    try:
        return _resolved(_resolve_and_validate_items(config.batch_config, shared, "s"))  # type: ignore[arg-type]
    except ValueError as exc:
        return RuntimeObservation("unresolved", message=str(exc))


def _drive_loop_condition(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    _compile(row, ir)
    return _resolved(evaluate_loop_condition(row.template, shared, "s", until=row.surface == "loop_until"))


def _drive_loop_cap(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    _compile(row, ir)
    return _resolved(resolve_loop_cap(LoopConfig(max_iterations_template=row.template), shared, "s"))


def _drive_loop_carry(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    """The bare engine (no validator in front): a carry needs the loop to actually re-enter."""
    compiled = _compile(row, ir)
    store: dict[str, Any] = {**row.params, **compiled.resolved_defaults}
    WorkflowEngine().run(compiled, store)
    return _resolved(store["s"]["result"]["seen"])


def _drive_output(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    _compile(row, ir)
    store = dict(shared)
    populate_declared_outputs(store, ir)
    return _resolved(store["o"]) if "o" in store else RuntimeObservation("absent")


CHILD = "<the child workflow path>"


def _drive_sub_workflow(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    observed = _resolve_param(row, _compile(row, ir).node_configs["s"], shared, "workflow")
    if observed.kind == "resolves" and observed.value == shared.get("child"):
        return _resolved(CHILD)
    return observed


def _drive_prewarm(row: Row, ir: dict[str, Any], shared: dict[str, Any]) -> RuntimeObservation:
    """``None`` means the warm-up silently drops the user's ``system`` prompt: Absent, no report."""
    value = _resolve_template_string(row.template, shared)
    return RuntimeObservation("absent") if value is None else _resolved(value)


def drive_runtime(row: Row, tmp_path: Path) -> RuntimeObservation:
    """The row's DIRECT runtime driver; any exception it raises is the observation."""
    if row.surface == "cache":
        return drive_cache(row, tmp_path)
    shared = seed_shared(row, tmp_path)
    try:
        return SURFACES[row.surface].drive(row, build_ir(row, tmp_path), shared)
    except HarnessError:
        raise
    except Exception as exc:
        return RuntimeObservation("raises", message=str(exc), exc_name=type(exc).__name__)


# ---------------------------------------------------------------------------
# End to end — what ``WorkflowRunner().run`` delivers, per surface
# ---------------------------------------------------------------------------


def _iterations(result: Any) -> int:
    """How many times ``s`` ran (one trace node event per loop pass)."""
    return sum(1 for event in result.trace.events if event.get("node_id") == "s")


def _observe_consumer(row: Row, result: Any) -> Any:
    received = result.shared_after["s"]
    return received["result"] if _is_code(row) else received["received"][row.consumer]


def _observe_batch(row: Row, result: Any) -> Any:
    items = result.shared_after["s"]["results"]
    if row.surface == "batch_items":
        return [item["received"]["sink_any"] for item in items]
    return [item["result"] if _is_code(row) else item["received"][row.consumer] for item in items]


def run_end_to_end(row: Row, ir: dict[str, Any]) -> RuntimeObservation:
    result = WorkflowRunner().run(ir, dict(row.params), RunnerConfig())
    if not result.success:
        return RuntimeObservation("raises", message=" | ".join(d.message for d in result.errors), exc_name="run-failed")
    if row.surface == "output_source" and "o" not in result.shared_after:
        return RuntimeObservation("absent")
    return _resolved(SURFACES[row.surface].observe(row, result))


# ---------------------------------------------------------------------------
# The surface table — one entry per template-bearing surface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    build: Callable[[Row, Path, dict[str, Any]], dict[str, Any]]  # node ``s`` (may add to the IR)
    drive: Callable[[Row, dict[str, Any], dict[str, Any]], RuntimeObservation]  # (row, ir, seeded shared)
    observe: Callable[[Row, Any], Any]  # the end-to-end value from an ExecutionResult


SURFACES: Mapping[str, Surface] = MappingProxyType({
    "param": Surface(lambda row, _t, _ir: _consumer(row), _drive_param, _observe_consumer),
    "batch_items": Surface(
        lambda row, _t, _ir: _node(
            "template-corpus-sink", {"sink_any": "${item}"}, batch={"items": row.template, "as": "item"}
        ),
        _drive_batch_items,
        _observe_batch,
    ),
    "batch_param": Surface(
        lambda row, _t, _ir: _consumer(row, batch={"items": row.batch_items, "as": "item"}),
        _drive_batch_param,
        _observe_batch,
    ),
    "loop_while": Surface(
        lambda row, _t, _ir: _plain_sink(row, loop={"while": row.template, "max_iterations": 2}),
        _drive_loop_condition,
        lambda _row, result: _iterations(result),
    ),
    "loop_until": Surface(
        lambda row, _t, _ir: _plain_sink(row, loop={"until": row.template, "max_iterations": 2}),
        _drive_loop_condition,
        lambda _row, result: _iterations(result),
    ),
    # ``while:`` is always truthy, so the run iterates until the cap stops it.
    "loop_max": Surface(
        lambda row, _t, _ir: _plain_sink(row, loop={"while": "${p.out.flag}", "max_iterations": row.template}),
        _drive_loop_cap,
        lambda _row, result: _iterations(result),
    ),
    "loop_carry": Surface(
        _build_loop_carry, _drive_loop_carry, lambda _row, result: result.shared_after["s"]["result"]["seen"]
    ),
    "output_source": Surface(_build_output_source, _drive_output, lambda _row, result: result.shared_after["o"]),
    "sub_inputs": Surface(
        lambda row, tmp_path, _ir: _node(
            "workflow", {"workflow": str(_write_child(tmp_path)), "inputs": {"v": row.template}}
        ),
        _drive_param,
        lambda _row, result: result.shared_after["s"]["got"],
    ),
    "sub_workflow": Surface(
        _build_sub_workflow, _drive_sub_workflow, lambda _row, result: result.shared_after["s"]["got"]
    ),
    # The engine's batch warm-up resolves an llm node's ``system`` with this helper;
    # end to end, the same text is a plain ``sink_str`` param.
    "prewarm_system": Surface(
        lambda row, _t, _ir: _node("template-corpus-sink", {"sink_str": row.template}),
        _drive_prewarm,
        lambda _row, result: result.shared_after["s"]["received"]["sink_str"],
    ),
})


# ---------------------------------------------------------------------------
# ``## Cache`` rows: markdown text (dict IR skips the chunker)
# ---------------------------------------------------------------------------

_CACHE_MODEL = "anthropic/claude-haiku-4-5"


def _markdown_inputs(row: Row) -> str:
    if not row.declared_inputs:
        return ""
    sections = []
    for name, spec in row.declared_inputs.items():
        lines = [f"### {name}", "", str(spec.get("description", name)), "", f"- type: {spec['type']}"]
        lines.append(f"- required: {str(spec.get('required', True)).lower()}")
        if "default" in spec:
            lines.append(f"- default: {json.dumps(spec['default'])}")
        sections.append("\n".join(lines))
    return "## Inputs\n\n" + "\n\n".join(sections) + "\n\n"


def write_cache_workflow(row: Row, tmp_path: Path) -> Path:
    """The row's ``## Cache`` block (``row.template`` verbatim) over producer ``p`` → llm ``s``."""
    payload_file = _write_payload(tmp_path, row.payload)
    names = json.dumps(list(row.prompt_cache))
    # A ghost ``g`` is a declared step the direct driver never runs (its seed is
    # the producer alone), so its root is ABSENT at render time.
    ghost = (
        "### g\n\nA producer the render never sees run.\n\n"
        f"- type: template-corpus-producer\n- payload_file: {json.dumps(str(payload_file))}\n\n"
        if row.ghost
        else ""
    )
    text = (
        "# Corpus cache\n\nOne cache block over the corpus producer.\n\n"
        f"{_markdown_inputs(row)}"
        "## Cache\n\nThe block under test.\n\n"
        f"```cache\n{row.template}\n```\n\n"
        "## Steps\n\n"
        "### p\n\nWrite the corpus payload.\n\n"
        f"- type: template-corpus-producer\n- payload_file: {json.dumps(str(payload_file))}\n\n"
        f"{ghost}"
        "### s\n\nRead the cached chunks.\n\n"
        f"- type: llm\n- model: {_CACHE_MODEL}\n- prompt_cache: {names}\n\n"
        "```prompt\nSay hi.\n```\n"
    )
    path = tmp_path / "cache.pflow.md"
    path.write_text(text, encoding="utf-8")
    return path


def drive_cache(row: Row, tmp_path: Path) -> RuntimeObservation:
    """Chunk the markdown for real, then render hash-side and prepare-side.

    ``Resolves`` carries the rendered ``prose_before + value`` texts in
    ``prompt_cache:`` order; the two render sites must agree byte for byte.
    """
    from pflow.execution.workflow_resolver import resolve_workflow
    from pflow.runtime.engine.engine import build_prompt_cache_dict

    shared = seed_shared(row, tmp_path)
    try:
        ir = resolve_workflow(str(write_cache_workflow(row, tmp_path))).ir
        compiled = compile_workflow(ir, Registry(), initial_params=dict(row.params))
    except Exception as exc:
        return RuntimeObservation("raises", message=str(exc), exc_name=type(exc).__name__)
    chunk_names = {chunk.name for chunk in compiled.cache_block.items} if compiled.cache_block else set()
    require(set(row.prompt_cache) <= chunk_names, f"prompt_cache {row.prompt_cache} names a non-chunk: {chunk_names}")
    shared["__pflow_prompt_cache__"] = MappingProxyType(build_prompt_cache_dict(compiled, shared))
    hash_render = _render_cache_for_hash(compiled.node_configs["s"], shared)
    cache_ctx: CacheRenderContext = shared["__pflow_prompt_cache__"]["s"]
    blocks, _ = build_cache_system_blocks(user_system=None, cache_ctx=cache_ctx, shared=shared, model=_CACHE_MODEL)
    hash_texts = tuple(chunk["prose"] + chunk["value"] for chunk in hash_render or [])
    prep_texts = tuple(block["text"] for block in blocks or [])
    require(hash_texts == prep_texts, f"hash render {hash_texts} != prepare render {prep_texts}")
    return RuntimeObservation("resolves", hash_texts) if hash_texts else RuntimeObservation("absent")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def assert_validator(expected: Outcome, errors: list[str]) -> None:
    if isinstance(expected, Ok):
        assert errors == [], f"expected no validator ERROR, got {errors}"
    elif isinstance(expected, Error):
        assert any(expected.substring in message for message in errors), (
            f"expected a validator ERROR containing {expected.substring!r}, got {errors}"
        )
    else:  # pragma: no cover
        raise HarnessError(f"not a validator outcome: {expected!r}")


def _same(a: Any, b: Any) -> bool:
    """Type-exact equality (1 != True, '{}' != {})."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def assert_runtime(expected: Outcome, observed: RuntimeObservation) -> None:
    if isinstance(expected, Resolves):
        assert observed.kind == "resolves" and _same(observed.value, expected.value), (
            f"expected Resolves({expected.value!r}), observed {observed}"
        )
    elif isinstance(expected, StaticLiteral):
        assert observed.kind == "static", f"expected a STATIC param, observed {observed}"
    elif isinstance(expected, Unresolved):
        assert observed.kind == "unresolved", f"expected Unresolved{expected.refs}, observed {observed}"
        missing = [ref for ref in expected.refs if ref not in observed.message]
        assert not missing, f"unresolved report must name {missing}: {observed.message}"
        mangled = [text for text in expected.forbid if text in observed.message]
        assert not mangled, f"unresolved report must not contain {mangled}: {observed.message}"
    elif isinstance(expected, Raises):
        assert observed.kind == "raises" and observed.exc_name == expected.exc_name, (
            f"expected Raises({expected.exc_name}), observed {observed}"
        )
        assert expected.substring in observed.message, (
            f"expected {expected.substring!r} in the {expected.exc_name} message: {observed.message}"
        )
    elif isinstance(expected, Absent):
        assert observed.kind == "absent", f"expected Absent, observed {observed}"
    else:  # pragma: no cover
        raise HarnessError(f"not a runtime outcome: {expected!r}")


def assert_end_to_end(row: Row, expected: Outcome, tmp_path: Path) -> None:
    """A validator-clean row must behave the same through ``WorkflowRunner().run``."""
    observed = run_end_to_end(row, build_ir(row, tmp_path))
    if isinstance(expected, Resolves):
        assert observed.kind == "resolves" and _same(observed.value, expected.value), (
            f"end to end: expected {expected.value!r}, observed {observed}"
        )
    elif isinstance(expected, StaticLiteral):
        assert observed.kind == "resolves" and observed.value == row.template, (
            f"end to end: the node must receive the literal text {row.template!r}, observed {observed}"
        )
    elif isinstance(expected, Unresolved):
        assert observed.kind == "raises", f"end to end: expected a failed run, observed {observed}"
        missing = [ref for ref in expected.refs if ref not in observed.message]
        assert not missing, f"end to end: the run error must name {missing}: {observed.message}"
    elif isinstance(expected, Raises):
        assert observed.kind == "raises" and expected.substring in observed.message, (
            f"end to end: expected a failed run containing {expected.substring!r}, observed {observed}"
        )
    elif isinstance(expected, Absent):
        assert observed.kind == "absent", f"end to end: expected nothing written, observed {observed}"


# ---------------------------------------------------------------------------
# Row vocabulary
# ---------------------------------------------------------------------------

P = DEFAULT_PAYLOAD
IDX = MappingProxyType({"idx": {"type": "number", "required": False, "default": 0, "description": "An index."}})
IDX_STR = MappingProxyType({
    "idx": {"type": "string", "required": False, "default": "abc", "description": "A bad index."}
})
# Uses ``idx`` outside the dynamic index, so unused-input accounting stays quiet
# and the row isolates the behavior under test.
USE_IDX = MappingProxyType({"sink_str": "i=${idx}"})
ARR_INPUT = MappingProxyType({
    "arr": {"type": "array", "required": False, "default": [{"x": "a0"}], "description": "A list input."}
})
B_INPUT = MappingProxyType({"b": {"type": "string", "required": False, "default": "B", "description": "A string."}})
BAR_INPUT = MappingProxyType({"bar": {"type": "string", "required": False, "default": "B", "description": "A string."}})
TOPIC_INPUT = MappingProxyType({
    "topic": {"type": "string", "required": False, "default": "cats", "description": "A topic."}
})
CAP_INPUT = MappingProxyType({"cap": {"type": "number", "required": False, "default": 2, "description": "A cap."}})
I_INPUT = MappingProxyType({"i": {"type": "number", "required": False, "default": 1, "description": "An index."}})


def with_payload(**overrides: Any) -> Mapping[str, Any]:
    return MappingProxyType({**P, **overrides})


def now(outcome: Outcome) -> Expect:
    """No change planned: ``outcome`` holds today and after every phase."""
    return Expect(outcome)


def flips(today: Outcome, after: Outcome, phase: str, why: str) -> Expect:
    return Expect(today, after, phase, why)


MALFORMED = "Malformed template"  # the ONE Issue pass keeps today's message shape (plan §0.3)
# An Expression in cache prose (dict IR only); an Issue there is MALFORMED (Dev-7 ruling)


# ---------------------------------------------------------------------------
# 1b. Surface parity rows
# ---------------------------------------------------------------------------

PARAM_ROWS: tuple[Row, ...] = (
    # -- plain references, every consumer type -------------------------------
    Row(
        "param_bare_ref_dict",
        "param",
        "${p.out}",
        now(Ok()),
        now(Resolves(dict(P["out"]))),
        consumer="sink",
        mutation="a simple template stops preserving its type",
    ),
    Row("param_nested_field", "param", "${p.out.nested.k}", now(Ok()), now(Resolves("K")), consumer="sink_str"),
    Row("param_index_out_arr", "param", "${p.out_arr[0].x}", now(Ok()), now(Resolves("A0"))),
    Row(
        "param_json_str_autoparse_dict",
        "param",
        "${p.out.json_str}",
        now(Ok()),
        now(Resolves({"a": 1})),
        consumer="sink",
        mutation="the dict-typed engine gate stops auto-parsing a JSON string",
    ),
    Row(
        "param_json_str_stays_str",
        "param",
        "${p.out.json_str}",
        now(Ok()),
        now(Resolves('{"a": 1}')),
        consumer="sink_str",
    ),
    Row(
        "param_json_traversal",
        "param",
        "${p.out.json_str.a}",
        now(Ok()),
        now(Resolves(1)),
        mutation="traversal stops auto-parsing a JSON-container string",
    ),
    Row(
        "param_dict_into_str_serialized",
        "param",
        "${p.out.nested}",
        now(Ok()),
        now(Resolves('{"k": "K"}')),
        consumer="sink_str",
    ),
    Row("param_int_into_str_kept", "param", "${p.out.num}", now(Ok()), now(Resolves(3)), consumer="sink_str"),
    Row("param_union_dict", "param", "${p.out.nested}", now(Ok()), now(Resolves({"k": "K"})), consumer="sink_union"),
    Row(
        "param_union_json_str_not_parsed",
        "param",
        "${p.out.json_str}",
        now(Ok()),
        now(Resolves('{"a": 1}')),
        consumer="sink_union",
    ),
    Row("param_any_deep", "param", "${p.out_any.deep.v}", now(Ok()), now(Resolves(1))),
    Row(
        "param_code_input",
        "param",
        "${p.out.items}",
        now(Ok()),
        now(Resolves([{"x": "X0"}, {"x": "X1"}])),
        consumer="code",
    ),
    Row(
        "param_complex_stringifies",
        "param",
        "n=${p.out.num} f=${p.out.flag} m=${p.out.maybe}",
        now(Ok()),
        now(Resolves("n=3 f=True m=")),
        mutation="complex interpolation stops using _convert_to_string",
    ),
    Row(
        "param_nested_structure",
        "param",
        {"a": ["${p.out.num}", "t=${p.out.text}"], "b": "${p.out.json_str}"},
        now(Ok()),
        now(Resolves({"a": [3, "t=T"], "b": {"a": 1}})),
        mutation="resolve_nested stops auto-parsing a simple template's JSON string",
    ),
    Row(
        "param_missing_field", "param", "${p.nope}", now(Error("does not output 'nope'")), now(Unresolved(("p.nope",)))
    ),
    # -- `??` ------------------------------------------------------------------
    Row(
        "coalesce_literal_fallback",
        "param",
        '${p.out.nope ?? "fb"}',
        now(Ok()),
        now(Resolves("fb")),
        mutation="Pass 5 field-checks `??` operands",
    ),
    Row("coalesce_root_absent", "param", '${g.out.text ?? "fb"}', now(Ok()), now(Resolves("fb")), ghost=True),
    Row(
        "coalesce_field_absent_441",
        "param",
        "${p.out.nope ?? p.out.text}",
        now(Ok()),
        now(Resolves("T")),
        mutation="`??` stops falling through on an absent field (#441)",
    ),
    Row(
        "coalesce_all_absent",
        "param",
        "${g.out.text ?? g.out.num}",
        now(Ok()),
        now(Unresolved(("g.out.text", "g.out.num"))),
        ghost=True,
    ),
    Row(
        "coalesce_found_none_returned",
        "param",
        '${p.out.maybe ?? "fb"}',
        now(Ok()),
        now(Resolves(None)),
        mutation="derive `found` from `value is not None`",
    ),
    Row(
        "coalesce_root_typo_still_errors",
        "param",
        '${gone.x ?? "fb"}',
        now(Error("non-existent node 'gone'")),
        now(Resolves("fb")),
    ),
    # -- escapes and #630 (delta 1) --------------------------------------------
    Row(
        "escape_only",
        "param",
        "$${x}",
        now(Ok()),
        now(Resolves("${x}")),
        mutation="has_templates stops routing escape-only values (#620)",
    ),
    Row(
        "escape_and_ref_same_param_630",
        "param",
        "${p.out_str} $${p.out_str}",
        now(Ok()),
        # Today's report names no reference at all — the generic #630 message.
        # Flipped in phase 2 — delta 1 (#630): strict mode consumes the resolver's unresolved set
        now(Resolves("S ${p.out_str}")),
    ),
    Row(
        "upstream_text_names_referenced_var_630",
        "param",
        "${p.out_str} ${b}",
        now(Ok()),
        # Flipped in phase 2 — delta 1 (#630): a resolved value's `${b}` text is not an unresolved reference
        now(Resolves("has ${b} B")),
        declared_inputs=B_INPUT,
        payload=with_payload(out_str="has ${b}"),
    ),
    Row(
        "upstream_text_unrelated_var",
        "param",
        "v=${p.out_str}",
        now(Ok()),
        now(Resolves("v=has ${b} text")),
        payload=with_payload(out_str="has ${b} text"),
    ),
    # -- the four TestContainsUnresolvedTemplate cases (that class dies in phase 2)
    Row(
        "permissive_missing_field_recorded",
        "param",
        "${p.nope}",
        now(Error("does not output 'nope'")),
        now(Unresolved(("p.nope",))),
        mode="permissive",
    ),
    Row("cut_fully_resolved", "param", "Hi ${p.out_str}", now(Ok()), now(Resolves("Hi S"))),
    Row(
        "cut_simple_unresolved",
        "param",
        "${p.nope}",
        now(Error("does not output 'nope'")),
        now(Unresolved(("p.nope",))),
    ),
    Row(
        "cut_partially_resolved_complex",
        "param",
        "prefix ${p.out_str} and ${p.nope}",
        now(Error("does not output 'nope'")),
        now(Unresolved(("p.nope",))),
    ),
    Row(
        "cut_resolved_data_contains_template_text",
        "param",
        "${p.out_str}",
        now(Ok()),
        now(Resolves("${OLD_VAR}")),
        payload=with_payload(out_str="${OLD_VAR}"),
    ),
    # -- converse-silent class (delta 2: validator OK → static literal today) ---
    Row(
        "silent_digit_field",
        "param",
        "${p.out_str.0}",
        # Flipped in 4b — delta 2: strict grammar wins — an Issue is a validator ERROR
        now(Error(MALFORMED)),
        now(StaticLiteral()),
        consumer="sink_str",
        mutation="drop a shape from the Issue pass",
    ),
    Row(
        "silent_trailing_dot",
        "param",
        "${p.out.}",
        # Flipped in 4b — delta 2: strict grammar wins
        now(Error(MALFORMED)),
        now(StaticLiteral()),
        consumer="sink_str",
    ),
    Row(
        "silent_empty_segment",
        "param",
        "${p..out}",
        # Flipped in 4b — delta 2: strict grammar wins
        now(Error(MALFORMED)),
        now(StaticLiteral()),
        consumer="sink_str",
    ),
    Row(
        "empty_segment_with_field_errors_for_wrong_reason",
        "param",
        "${p..out.x}",
        # Flipped in 4b — delta 2: the Issue pass names the real cause
        now(Error(MALFORMED)),
        now(StaticLiteral()),
    ),
    Row(
        "silent_coalesce_inner_index",
        "param",
        "${p.out_arr[${idx ?? 0}]}",
        # Flipped in 4b — delta 2: a `??` inner index is an Issue
        now(Error(MALFORMED)),
        # Flipped in 4a — an Issue-only value is static; the rewrite pre-pass died
        now(StaticLiteral()),
        declared_inputs=IDX,
        extra_params=USE_IDX,
        mutation="skip the `[${` nested count",
    ),
    Row(
        "silent_root_typo_under_dynamic_index",
        "param",
        '${lsit[${idx}].x ?? "default"}',
        # Flipped in 4b — delta 2/6: the outer root of a dynamic index is root-checked
        now(Error("lsit")),
        now(Resolves("default")),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row("multi_index_rejected_both_layers", "param", "${p.out.m[0][1]}", now(Error(MALFORMED)), now(StaticLiteral())),
    # -- loud-today Issue shapes (the `issues` channel keeps them loud) --------
    Row(
        "loud_issue_dict_sibling",
        "param",
        {"x": "${p.out.items.0}", "y": "${p.out.text}"},
        # Flipped in 4b — the Issue pass names the real cause
        now(Error(MALFORMED)),
        now(Unresolved(("${p.out.items.0}",))),
    ),
    # -- validator-only divergences -------------------------------------------
    Row(
        "coalesce_literal_containing_template_text",
        "param",
        '${g.out ?? "${b}"}',
        # Flipped in 4b — `${b}` inside a literal is literal text
        now(Ok()),
        now(Resolves("${b}")),
        ghost=True,
    ),
    Row(
        "list_input_index_262",
        "param",
        "${arr[0]}",
        # Flipped in 4b — #262: Pass 5 consumes parse_path segments
        now(Ok()),
        now(Resolves({"x": "a0"})),
        declared_inputs=ARR_INPUT,
    ),
    Row(
        "list_input_index_typo_partner",
        "param",
        "${arrr[0]}",
        now(Error("arrr")),
        now(Unresolved(("arrr[0]",))),
        declared_inputs=ARR_INPUT,
        extra_params={"sink_list": "${arr}"},
    ),
    Row(
        "nested_list_index_over_rejection_r9",
        "param",
        "${p.out.items[0].x}",
        # Flipped in 4b — R9: a list field's structure is its element structure
        now(Ok()),
        now(Resolves("X0")),
        mutation="Pass 5 looks up the literal key `items[0]`",
    ),
    Row(
        "nested_list_index_typo_partner",
        "param",
        "${p.out.items[0].nope}",
        now(Error("does not output")),
        now(Unresolved(("p.out.items[0].nope",))),
    ),
    Row(
        "list_typed_output_index_over_rejection_r9",
        "param",
        "${p.out_list[0]}",
        # Flipped in 4b — R9: `list` indexes like `array`
        now(Ok()),
        now(Resolves("L0")),
    ),
    Row(
        "list_typed_output_typo_partner",
        "param",
        "${p.out_lsit[0]}",
        now(Error("does not output 'out_lsit[0]'")),
        now(Unresolved(("p.out_lsit[0]",))),
    ),
    # -- delta 4, validator half ------------------------------------------------
    Row(
        "escape_hides_input_use_delta4",
        "param",
        "$${FOO:-${bar}}",
        # Flipped in 4b — delta 4: an input used only inside an escape is unused — the escape is literal
        now(Error("never used as template variable: bar")),
        now(Resolves("${FOO:-${bar}}")),  # flipped in 4a — delta 4: the escape consumes through `}`
        declared_inputs=BAR_INPUT,
    ),
    Row(
        "escape_hides_input_use_partner",
        "param",
        "$${FOO:-${bar}}",
        now(Ok()),
        now(Resolves("${FOO:-${bar}}")),  # flipped in 4a — delta 4: the escape consumes through `}`
        declared_inputs=BAR_INPUT,
        extra_params={"sink_str": "${bar}"},
    ),
)

BATCH_ROWS: tuple[Row, ...] = (
    Row("batch_items_node_list", "batch_items", "${p.out_arr}", now(Ok()), now(Resolves([{"x": "A0"}, {"x": "A1"}]))),
    Row(
        "batch_items_nested_list_field",
        "batch_items",
        "${p.out.items}",
        now(Ok()),
        now(Resolves([{"x": "X0"}, {"x": "X1"}])),
    ),
    Row(
        "batch_items_list_input",
        "batch_items",
        "${arr}",
        now(Ok()),
        now(Resolves([{"x": "a0"}])),
        declared_inputs=ARR_INPUT,
    ),
    Row(
        "batch_items_json_string_autoparse",
        "batch_items",
        "${p.out_str}",
        now(Ok()),
        now(Resolves(["j0", "j1"])),
        payload=with_payload(out_str='["j0", "j1"]'),
    ),
    Row(
        "batch_items_missing_field",
        "batch_items",
        "${p.nope}",
        now(Error("does not output 'nope'")),
        now(Unresolved(("${p.nope}",))),
    ),
    Row(
        "batch_items_coalesce_root_typo",
        "batch_items",
        "${typo.x ?? p.out_list}",
        # Flipped in 4b — coalesce roots in `batch.items` are root-checked (surface parity)
        now(Error("typo")),
        now(Resolves(["L0", "L1"])),
        mutation="drop `batch.items` from template_surfaces.iter_node_surfaces",
    ),
    Row("batch_items_inline_list", "batch_items", ["${p.out_str}", "lit"], now(Ok()), now(Resolves(["S", "lit"]))),
    Row(
        "batch_items_inline_unresolved_element_r12",
        "batch_items",
        ["${g.out_str}", "lit"],
        now(Ok()),
        now(Resolves(["${g.out_str}", "lit"])),
        ghost=True,
    ),
    Row(
        "batch_items_inline_malformed_element_520",
        "batch_items",
        ["${data.result[0]", "lit"],
        # Flipped in 4b — #520 first half: the Issue pass covers `batch.items`
        now(Error(MALFORMED)),
        now(Resolves(["${data.result[0]", "lit"])),
    ),
    Row("batch_item_alias", "batch_param", "${item}", now(Ok()), now(Resolves([{"x": "A0"}, {"x": "A1"}]))),
    Row("batch_item_dotted", "batch_param", "${item.x}", now(Ok()), now(Resolves(["A0", "A1"]))),
    Row("batch_item_missing_field", "batch_param", "${item.nope}", now(Ok()), now(Unresolved(("item.nope",)))),
    Row(
        "batch_dynamic_index_on_node_output",
        "batch_param",
        "${p.out_arr[${__index__}].x}",
        now(Ok()),
        now(Resolves(["A0", "A1"])),
    ),
    Row(
        "batch_results_dotted_item_d5a1af8c",
        "batch_param",
        "${item.received.sink_any.x}",
        now(Ok()),
        now(Resolves(["A0", "A1"])),
        upstream_batch=True,
        batch_items="${b.results}",
    ),
    Row(
        "batch_item_coalesce_pass8_over_rejection",
        "batch_param",
        '${item.nope ?? "none"}',
        # Flipped in 4b — Pass 8 stops field-checking `??` operands
        now(Ok()),
        now(Resolves(["none", "none"])),
        upstream_batch=True,
        batch_items="${b.results}",
        mutation="Pass 8 field-checks `??` operands",
    ),
    Row(
        "batch_item_pass8_partner",
        "batch_param",
        "${item.nope}",
        now(Error("not available on batch items")),
        now(Unresolved(("item.nope",))),
        upstream_batch=True,
        batch_items="${b.results}",
    ),
    Row(
        "batch_item_field_inside_dynamic_index_pass8",
        "batch_param",
        "${p.out_arr[${item.nope}]}",
        # Pass 8 reads the dependency view: the inner `item.nope` is an item-field read.
        now(Error("${item.nope} references field 'nope' which is not available on batch items")),
        now(Unresolved(("item.nope",))),
        upstream_batch=True,
        batch_items="${b.results}",
        mutation="Pass 8 collects value-position operands only (loses dynamic-index inner refs)",
    ),
    Row("batch_results_index", "param", "${b.results[0].item.x}", now(Ok()), now(Resolves("A0")), upstream_batch=True),
    Row(
        "batch_results_index_missing_field",
        "param",
        "${b.results[0].nope}",
        now(Error("does not output 'results[0]'")),
        now(Unresolved(("b.results[0].nope",))),
        upstream_batch=True,
    ),
)

LOOP_ROWS: tuple[Row, ...] = (
    Row("loop_while_bool", "loop_while", "${p.out.flag}", now(Ok()), now(Resolves(True)), end_to_end=Resolves(2)),
    Row("loop_while_list", "loop_while", "${p.out_list}", now(Ok()), now(Resolves(True)), end_to_end=Resolves(2)),
    Row(
        "loop_while_string_rejected",
        "loop_while",
        "${p.out.text}",
        now(Error("String truthiness")),
        now(Raises("LoopConditionError", "resolved to a string")),
    ),
    Row(
        "loop_while_missing_field_stops",
        "loop_while",
        "${p.nope}",
        now(Error("does not output 'nope'")),
        now(Resolves(False)),
    ),
    Row(
        "loop_while_complex_shape",
        "loop_while",
        "flag=${p.out.flag}",
        now(Error("does not match")),
        now(Resolves(False)),
    ),
    Row("loop_until_bool", "loop_until", "${p.out.flag}", now(Ok()), now(Resolves(False)), end_to_end=Resolves(1)),
    Row(
        "loop_until_coalesce",
        "loop_until",
        "${p.nope ?? p.out.flag}",
        now(Ok()),
        now(Resolves(False)),
        end_to_end=Resolves(1),
    ),
    Row(
        "loop_max_input",
        "loop_max",
        "${cap}",
        now(Ok()),
        now(Resolves(2)),
        declared_inputs=CAP_INPUT,
        end_to_end=Resolves(2),
    ),
    Row("loop_max_node_output", "loop_max", "${p.out.num}", now(Ok()), now(Resolves(3)), end_to_end=Resolves(3)),
    Row(
        "loop_max_non_int",
        "loop_max",
        "${p.out.text}",
        now(Ok()),
        now(Raises("LoopConditionError", "not a positive integer")),
    ),
    Row(
        "loop_max_missing_field",
        "loop_max",
        "${p.nope}",
        now(Error("does not output 'nope'")),
        now(Raises("LoopConditionError", "resolved to '${p.nope}'")),
    ),
    Row("loop_carry_self_output", "loop_carry", "${s.result.done}", now(Ok()), now(Resolves(False))),
    Row("loop_carry_self_index", "loop_carry", "${s.result.lst[1]}", now(Ok()), now(Resolves("c1"))),
    Row(
        "loop_carry_missing_field",
        "loop_carry",
        "${s.result.nope}",
        now(Ok()),
        now(Raises("LoopCarryError", "did not produce output 'result.nope'")),
    ),
    Row(
        "loop_carry_issue_shape",
        "loop_carry",
        "${s.result.0}",
        # Flipped in 4b — the Issue pass covers carry values
        now(Error(MALFORMED)),
        now(Raises("CompilationError", "Data flow validation failed")),
    ),
    Row(
        "loop_carry_other_node",
        "loop_carry",
        "${p.out_str}",
        now(Error("carry values must reference this loop node's own latest output")),
        now(Raises("CompilationError", "Data flow validation failed")),
    ),
)

OUTPUT_ROWS: tuple[Row, ...] = (
    Row("output_template", "output_source", "${p.out_str}", now(Ok()), now(Resolves("S"))),
    Row("output_plain", "output_source", "p.out_str", now(Ok()), now(Resolves("S"))),
    Row("output_plain_coalesce", "output_source", "p.out_str ?? p.nope", now(Ok()), now(Resolves("S"))),
    Row(
        "output_dollar_prefix_r4",
        "output_source",
        "$p.out_str",
        now(Error("non-existent source '$p'")),
        # Flipped in 4a (R4 moved from 4b by orchestrator ruling) — the runtime-only `$node.x` form is removed
        now(Raises("OutputResolutionError", "o")),
        mutation="restore _normalize_source's `$` branch",
    ),
    Row(
        "output_dollar_prefix_typo_partner",
        "output_source",
        "$typo.x",
        now(Error("non-existent source '$typo'")),
        now(Raises("OutputResolutionError", "typo.x")),
    ),
    Row(
        "output_prose_wrap_recorded_drift",
        "output_source",
        "prefix ${p.out_str}",
        now(Ok()),
        now(Resolves("${prefix S}")),
    ),
    Row("output_literal_only_stays_valid", "output_source", '${"v1"}', now(Ok()), now(Resolves("v1"))),
    Row(
        "output_escape_only_r3",
        "output_source",
        "$${p.out_str}",
        # Flipped in 4b — R3: truthful message for a source with no Expression
        now(Error("output source has no template expression")),
        now(Resolves("${S}")),
    ),
    Row(
        "output_issue_shape_loud",
        "output_source",
        "${p.out.items.0}",
        # Flipped in 4b — the Issue pass covers output sources
        now(Error(MALFORMED)),
        now(Raises("OutputResolutionError", "Unresolved template in output 'o'")),
    ),
    Row(
        "output_plain_issue_shape_stays_loud",
        "output_source",
        "p.out_str.0",
        now(Ok()),
        now(Raises("OutputResolutionError", "Unresolved template in output 'o'")),
    ),
    Row(
        "output_missing_field",
        "output_source",
        "${p.nope}",
        now(Ok()),
        now(Raises("OutputResolutionError", "${p.nope}")),
    ),
    Row(
        "output_all_absent_coalesce_skipped",
        "output_source",
        "${g.out_str ?? g.out.text}",
        now(Ok()),
        now(Absent()),
        ghost=True,
    ),
    Row(
        "output_absent_root_errors",
        "output_source",
        "${g.out_str}",
        now(Ok()),
        now(Raises("OutputResolutionError", "${g.out_str}")),
        ghost=True,
    ),
    Row("output_json_string_not_parsed", "output_source", "${p.out.json_str}", now(Ok()), now(Resolves('{"a": 1}'))),
    Row(
        "output_only_input_use_flagged_unused",
        "output_source",
        "${idx}",
        # Flipped in 4b — an input returned only through an output source is used (the runtime resolves it)
        now(Ok()),
        now(Resolves(0)),
        declared_inputs=IDX,
        mutation="leave output sources out of unused-input accounting",
    ),
    Row(
        "output_only_input_use_partner",
        "output_source",
        "${idx}",
        now(Error("never used as template variable: other")),
        now(Resolves(0)),
        declared_inputs=MappingProxyType({
            **IDX,
            "other": {"type": "string", "required": False, "default": "o", "description": "Unused."},
        }),
    ),
)

SUB_WORKFLOW_ROWS: tuple[Row, ...] = (
    Row("sub_inputs_ref", "sub_inputs", "${p.out_str}", now(Ok()), now(Resolves("S"))),
    Row("sub_inputs_dict", "sub_inputs", "${p.out}", now(Ok()), now(Resolves(dict(P["out"])))),
    Row("sub_inputs_escape_only", "sub_inputs", "$${p.out_str}", now(Ok()), now(Resolves("${p.out_str}"))),
    Row(
        "sub_inputs_missing_field",
        "sub_inputs",
        "${p.nope}",
        now(Error("does not output 'nope'")),
        now(Unresolved(("p.nope",))),
    ),
    Row(
        "sub_workflow_templated_path",
        "sub_workflow",
        "${child}",
        now(Ok()),
        now(Resolves(CHILD)),
        end_to_end=Resolves("fixed"),
    ),
    Row(
        "sub_workflow_escape_only_r6",
        "sub_workflow",
        "$${x}",
        # Flipped in 4b — R6: an escape-only child ref is checked on its unescaped text
        now(Error("${x}")),
        now(Resolves("${x}")),
        end_to_end=Raises("run-failed", "unresolved template reference: '${x}'"),
    ),
)

PREWARM_ROWS: tuple[Row, ...] = (
    Row("prewarm_system_resolves", "prewarm_system", "You are ${p.out_str}", now(Ok()), now(Resolves("You are S"))),
    Row(
        "prewarm_system_escape_dropped",
        "prewarm_system",
        "Use $${x} literally",
        now(Ok()),
        # Flipped in phase 2 — delta 1: the warm-up stops re-scanning its resolved `system`
        now(Resolves("Use ${x} literally")),
        end_to_end=Resolves("Use ${x} literally"),
    ),
    Row(
        "prewarm_system_missing_field",
        "prewarm_system",
        "You are ${p.nope}",
        now(Error("does not output 'nope'")),
        now(Absent()),
    ),
)

CACHE_ROWS: tuple[Row, ...] = (
    Row(
        "cache_var_ref",
        "cache",
        "Base: ${p.out_str}",
        now(Ok()),
        now(Resolves(("Base: S",))),
        prompt_cache=("p.out_str",),
    ),
    Row(
        "cache_var_dict_deterministic",
        "cache",
        "Base: ${p.out.nested}",
        now(Ok()),
        now(Resolves(('Base: {"k":"K"}',))),
        prompt_cache=("p.out.nested",),
    ),
    Row(
        "cache_two_chunks_input",
        "cache",
        "Base: ${p.out_str}\nTopic: ${topic}",
        now(Ok()),
        now(Resolves(("Base: S", "\nTopic: cats"))),
        prompt_cache=("p.out_str", "topic"),
        declared_inputs=TOPIC_INPUT,
    ),
    Row(
        "cache_var_json_string_kept",
        "cache",
        "Base: ${p.out.json_str}",
        now(Ok()),
        now(Resolves(('Base: {"a": 1}',))),
        prompt_cache=("p.out.json_str",),
    ),
    Row(
        "cache_var_field_typo_absent",
        "cache",
        "Base: ${p.out_stt}",
        now(Ok()),
        now(Absent()),
        prompt_cache=("p.out_stt",),
    ),
    Row(
        "cache_var_root_typo",
        "cache",
        "Base: ${plan.stdot}",
        now(Error("'plan' is not a declared input")),
        now(Raises("CompilationError", "Data flow validation failed")),
        prompt_cache=("plan.stdot",),
    ),
    Row(
        "cache_var_absent_root",
        "cache",
        "Base: ${g.out_str}",
        now(Ok()),
        now(Absent()),
        prompt_cache=("g.out_str",),
        ghost=True,
    ),
    Row(
        "cache_var_issue_shape",
        "cache",
        "Base: ${p.out.items.0}",
        # Flipped in 4b — the Issue pass covers cache vars. Re-derived in 4c (R2): the Issue is
        # prose, so the block has no chunk and parsing names it (was: the chunk silently ABSENT)
        now(Error(MALFORMED)),
        now(Raises("MarkdownParseError", MALFORMED)),
        prompt_cache=("p.out.items.0",),
    ),
    Row(
        "cache_var_coalesce_dotless_r5",
        "cache",
        'Base: ${topic ?? "x"}',
        flips(
            Error("is not a declared input"),
            Error("coalesce is not supported"),
            "4c",
            "R5: a `??` chunk var is rejected explicitly at parse",
        ),
        flips(
            Raises("CompilationError", "Data flow validation failed"),
            Raises("MarkdownParseError", "coalesce is not supported"),
            "4c",
            "R5",
        ),
        prompt_cache=('topic ?? "x"',),
        declared_inputs=TOPIC_INPUT,
    ),
    Row(
        "cache_var_coalesce_absent_first_root_r5",
        "cache",
        "Base: ${g.out_str ?? p.out_str}",
        flips(Ok(), Error("coalesce is not supported"), "4c", "R5: loud beats the silent drop"),
        flips(Absent(), Raises("MarkdownParseError", "coalesce is not supported"), "4c", "R5"),
        prompt_cache=("g.out_str ?? p.out_str",),
        ghost=True,
    ),
    Row(
        "cache_var_coalesce_present_root_r5",
        "cache",
        "Base: ${p.nope ?? p.out_str}",
        flips(Ok(), Error("coalesce is not supported"), "4c", "R5 also rejects the chain that renders today"),
        flips(Resolves(("Base: S",)), Raises("MarkdownParseError", "coalesce is not supported"), "4c", "R5"),
        prompt_cache=("p.nope ?? p.out_str",),
    ),
    Row(
        "cache_prose_escape_declared_delta5",
        "cache",
        "Cost $${topic} then ${p.out_str}",
        # Flipped in 4c — delta 5 (ADR-0015): `$${` is honoured in cache prose and unescaped at
        # render. Validator re-derived: the escape no longer reads `topic`, so the declared input
        # is (correctly) unused (was Ok via the bogus `topic` chunk)
        now(Error("never used as template variable: topic")),
        now(Resolves(("Cost ${topic} then S",))),
        prompt_cache=("p.out_str",),
        declared_inputs=TOPIC_INPUT,
    ),
    Row(
        "cache_prose_escape_undeclared_delta5",
        "cache",
        "Home $${HOME} then ${p.out_str}",
        # Flipped in 4c — delta 5: the escaped span is not a chunk
        now(Ok()),
        now(Resolves(("Home ${HOME} then S",))),
        prompt_cache=("p.out_str",),
    ),
    Row(
        "cache_prose_empty_braces_r2",
        "cache",
        "Empty ${} then ${p.out_str}",
        # Flipped early in 4b (row said 4c) — R2: the Issue pass covers cache prose; an Issue there
        # carries the standard malformed message (orchestrator Dev-7 ruling)
        now(Error(MALFORMED)),
        now(Resolves(("Empty ${} then S",))),
        prompt_cache=("p.out_str",),
    ),
    Row(
        "cache_prose_unclosed_r2",
        "cache",
        "Unclosed ${a then ${p.out_str}",
        # Flipped in 4c (R2) and re-derived: the Issue runs to its first `}` (the 4a span ruling),
        # so it swallows `${p.out_str}` and the block has no chunk — parsing names the Issue with
        # the standard malformed message (Dev-7 ruling). Phase 1's `after` assumed the Issue stops
        # before the next `${`.
        now(Error(MALFORMED)),
        now(Raises("MarkdownParseError", MALFORMED)),
        prompt_cache=("p.out_str",),
    ),
    Row(
        "cache_var_dynamic_index",
        "cache",
        "Base: ${p.out_arr[${i}].x}",
        # Flipped in 4c — chunk names are sliced from Expression spans. Runtime re-derived: `i`
        # takes its declared default 1 (phase 1's `after` said A0)
        now(Ok()),
        now(Resolves(("Base: A1",))),
        prompt_cache=("p.out_arr[${i}].x",),
        declared_inputs=I_INPUT,
    ),
)

SURFACE_ROWS: tuple[Row, ...] = (
    PARAM_ROWS + BATCH_ROWS + LOOP_ROWS + OUTPUT_ROWS + SUB_WORKFLOW_ROWS + PREWARM_ROWS + CACHE_ROWS
)


# ---------------------------------------------------------------------------
# 1d. Dynamic-index characterization (delta 3 per consumer; delta 6 validator)
# ---------------------------------------------------------------------------

DYNAMIC_ROWS: tuple[Row, ...] = (
    Row(
        "dyn_resolves",
        "param",
        "${p.out_arr[${idx}].x}",
        now(Ok()),
        now(Resolves("A0")),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_shape_json_string_element",
        "param",
        "${p.out_arr[${idx}]}",
        # Flipped early in 4a (row said 4b) — delta 6: the type pass reads `extract_variables`,
        # which now yields the outer reference, not the index key
        now(Ok()),
        # Flipped in 4a — delta 3: a dynamic-index template is simple, so the dict gate auto-parses
        now(Resolves({"a": 1})),
        consumer="sink",
        declared_inputs=IDX,
        extra_params=USE_IDX,
        payload=with_payload(out_arr=['{"a": 1}']),
        mutation="is_simple_template runs on the original text",
    ),
    Row(
        "dyn_strict_outer_field_missing",
        "param",
        "${p.out_arr[${idx}].nope}",
        now(Ok()),
        # Flipped in phase 2 — delta 1/3: the rewritten reference is in the unresolved set
        now(Unresolved(("p.out_arr[",))),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_permissive_outer_field_missing",
        "param",
        "${p.out_arr[${idx}].nope}",
        now(Ok()),
        # Flipped in phase 2 — delta 1/3: permissive mode records the rewritten reference as a template error
        now(Unresolved(("p.out_arr[",))),
        declared_inputs=IDX,
        extra_params=USE_IDX,
        mode="permissive",
        # Permissive: the recorded error is a warning — the run completes with the literal
        # (the author's reference since 4a; the rewritten `p.out_arr[0].nope` before).
        end_to_end=Resolves("${p.out_arr[${idx}].nope}"),
    ),
    Row(
        "dyn_strict_out_of_range",
        "param",
        "${p.out_arr[${idx}].x}",
        now(Ok()),
        # Flipped in phase 2 — delta 1/3: the rewritten reference is in the unresolved set
        now(Unresolved(("p.out_arr[",))),
        declared_inputs=IDX,
        extra_params=USE_IDX,
        params={"idx": 5},
    ),
    Row(
        "dyn_inner_absent_names_inner",
        "param",
        "${p.out_arr[${g.out.num}].x}",
        now(Ok()),
        now(Unresolved(("g.out.num",))),
        ghost=True,
    ),
    Row(
        "dyn_inner_undeclared_input",
        "param",
        "${p.out_arr[${nope}].x}",
        # Flipped in 4b — delta 6: inner references are root-checked
        now(Error("nope")),
        now(Unresolved(("nope",))),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_non_int_inner_names_outer",
        "param",
        "${p.out_arr[${idx}].x}",
        now(Ok()),
        # Flipped in 4a — delta 3: any inner failure makes the whole reference unresolved
        now(Unresolved(("p.out_arr[${idx}].x",))),
        declared_inputs=IDX_STR,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_batch_item_inner_renderer",
        "batch_param",
        "${p.out_arr[${item.i}].x}",
        now(Ok()),
        # Flipped early in phase 2 (row said 4a; §1 puts OOB in 2) — delta 3 + the field-segment
        # renderer must not tear the inner reference: an out-of-range int index is the rewritten
        # reference, now in the unresolved set.
        now(Unresolved(("p.out_arr[${item.i}].x",), forbid=("'i}]'",))),
        batch_items="${p.out.items}",
        payload=with_payload(out={**P["out"], "items": [{"i": 5}]}),
    ),
    Row(
        "dyn_coalesce_non_int_inner",
        "param",
        '${p.out_arr[${idx}].x ?? "fb"}',
        now(Ok()),
        now(Resolves("fb")),  # flipped in 4a — delta 3: `??` falls through
        declared_inputs=IDX_STR,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_coalesce_int_inner_missing_outer",
        "param",
        '${p.out_arr[${idx}].nope ?? "fb"}',
        now(Ok()),
        now(Resolves("fb")),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_optional_input_absent_root",
        "param",
        "${g.out_arr[${idx}].x}",
        now(Ok()),
        # Flipped early in phase 2 (row said 4a) — delta 3: Optional inputs get None. Injection
        # reads the OUTER root (plan §0.2), so the present inner index no longer blocks it.
        now(Resolves(None)),
        consumer="code:Optional[str]",
        ghost=True,
        declared_inputs=IDX,
        extra_params={"i": "${idx}"},
    ),
    Row(
        "dyn_declared_output_outer_missing",
        "output_source",
        "${p.out_arr[${idx}].nope}",
        now(Ok()),
        # Flipped in phase 2 — ledger: a non-coalesce unresolved declared output is an error (handback Q1 ruling)
        now(Raises("OutputResolutionError", "p.out_arr[")),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_declared_output_non_int",
        "output_source",
        "${p.out_arr[${idx}].x}",
        now(Ok()),
        # Flipped in 4a — ledger: a non-coalesce unresolved declared output is an error
        now(Raises("OutputResolutionError", "p.out_arr[${idx}].x")),
        declared_inputs=IDX_STR,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_loop_while_r1",
        "loop_while",
        "${p.out_arr[${idx}]}",
        # Flipped in 4a — R1: a dynamic-index simple template is a loop shape, and loop control resolves it
        now(Ok()),
        now(Resolves(True)),
        declared_inputs=IDX,
        extra_params=USE_IDX,
        # Validator-clean since 4a, so it runs end to end: truthy every pass → the cap (2) stops it.
        end_to_end=Resolves(2),
    ),
    Row(
        "dyn_loop_while_typo_partner",
        "loop_while",
        "${typo[${idx}]}",
        now(Error("typo")),
        now(Resolves(False)),
        declared_inputs=IDX,
        extra_params=USE_IDX,
    ),
    Row(
        "dyn_loop_carry_r1",
        "loop_carry",
        "${s.result.lst[${i}]}",
        # Flipped in 4a — R1: a dynamic-index carry is a self reference
        now(Ok()),
        now(Resolves("c1")),
        declared_inputs=I_INPUT,
        extra_params={"iu": "${i}"},
    ),
    Row(
        "dyn_type_pass_code_annotation_delta6",
        "param",
        "${p.out_arr[${idx}]}",
        # Flipped early in 4a (row said 4b) — delta 6: a dynamic-index simple template is not 'complex'
        now(Ok()),
        now(Resolves({"x": "A0"})),
        consumer="code:dict",
        declared_inputs=IDX,
        extra_params={"i": "${idx}"},
    ),
    Row(
        "dyn_type_pass_mismatch_partner",
        "param",
        "${p.out.items[${idx}]}",
        now(Error("expects int")),
        now(Resolves({"x": "X0"})),
        consumer="code:int",
        declared_inputs=IDX,
        extra_params={"i": "${idx}"},
    ),
    Row(
        "dyn_unused_input_only_inside_index",
        "param",
        "${p.out_arr[${idx}].x}",
        # Flipped in 4b — delta 6: inner references count for unused-input accounting
        now(Ok()),
        now(Resolves("A0")),
        declared_inputs=IDX,
        mutation="drop inner refs from unused-input accounting",
    ),
    Row(
        "dyn_unused_input_partner",
        "param",
        "${p.out_arr[${idx}].x}",
        now(Error("never used as template variable: other")),
        now(Resolves("A0")),
        extra_params=USE_IDX,
        declared_inputs=MappingProxyType({
            **IDX,
            "other": {"type": "string", "required": False, "default": "o", "description": "Unused."},
        }),
    ),
)


# ---------------------------------------------------------------------------
# Parametrized row tests
# ---------------------------------------------------------------------------


def _row_items(rows: tuple[Row, ...], side: str) -> list[Any]:
    """Two items per side when ``after`` is set: ``today`` passes, ``after`` xfails strictly."""
    items: list[Any] = []
    for row in rows:
        expect: Expect = getattr(row, side)
        items.append(pytest.param(row, expect.today, "today", id=f"{row.id}-today"))
        if expect.after is not None:
            items.append(
                pytest.param(
                    row,
                    expect.after,
                    "after",
                    id=f"{row.id}-after-{expect.flips_in}",
                    marks=pytest.mark.xfail(
                        strict=True, raises=AssertionError, reason=f"{expect.flips_in}: {expect.why}"
                    ),
                )
            )
    return items


def _validate_row(row: Row, tmp_path: Path) -> list[str]:
    require(set(row.params) <= set(row.declared_inputs), "row params must be declared inputs")
    if row.surface == "cache":
        return validator_errors(str(write_cache_workflow(row, tmp_path)), row.params)
    return validator_errors(build_ir(row, tmp_path), row.params)


def _check_validator(row: Row, expected: Outcome, tmp_path: Path) -> None:
    assert_validator(expected, _validate_row(row, tmp_path))


def _check_runtime(row: Row, expected: Outcome, epoch: str, tmp_path: Path) -> None:
    (direct := tmp_path / "direct").mkdir()
    assert_runtime(expected, drive_runtime(row, direct))
    # A validator-clean row must behave the same end to end. Run only for the
    # `today` epoch: an `after` item flips alone, before the validator may.
    if epoch == "today" and isinstance(row.validator.today, Ok) and row.surface != "cache":
        (e2e := tmp_path / "e2e").mkdir()
        assert_end_to_end(row, row.end_to_end or expected, e2e)


class TestSurfaceParity:
    """1b: every surface x the template shapes that drifted (plan §2 phase 1)."""

    @pytest.mark.parametrize(("row", "expected", "epoch"), _row_items(SURFACE_ROWS, "validator"))
    def test_validator(self, row: Row, expected: Outcome, epoch: str, tmp_path: Path) -> None:
        _check_validator(row, expected, tmp_path)

    @pytest.mark.parametrize(("row", "expected", "epoch"), _row_items(SURFACE_ROWS, "runtime"))
    def test_runtime(self, row: Row, expected: Outcome, epoch: str, tmp_path: Path) -> None:
        _check_runtime(row, expected, epoch, tmp_path)


class TestDynamicIndexConsumers:
    """1d: every dynamic-index consumer, measured before delta 3 lands."""

    @pytest.mark.parametrize(("row", "expected", "epoch"), _row_items(DYNAMIC_ROWS, "validator"))
    def test_validator(self, row: Row, expected: Outcome, epoch: str, tmp_path: Path) -> None:
        _check_validator(row, expected, tmp_path)

    @pytest.mark.parametrize(("row", "expected", "epoch"), _row_items(DYNAMIC_ROWS, "runtime"))
    def test_runtime(self, row: Row, expected: Outcome, epoch: str, tmp_path: Path) -> None:
        _check_runtime(row, expected, epoch, tmp_path)


def test_row_ids_are_unique() -> None:
    ids = [row.id for row in SURFACE_ROWS + DYNAMIC_ROWS]
    assert len(ids) == len(set(ids)), sorted(i for i in ids if ids.count(i) > 1)


def _run(ir: dict[str, Any], params: Mapping[str, Any] | None = None) -> Any:
    return WorkflowRunner().run(ir, dict(params or {}), RunnerConfig())


def _code_node(node_id: str, value: Any, *, annotation: str = "Any") -> dict[str, Any]:
    return {"id": node_id, "type": "code", "purpose": "Echo an input.", "params": _code_params(value, annotation)}


# ---------------------------------------------------------------------------
# 1b (runner-only rows) — shapes a direct driver cannot express
# ---------------------------------------------------------------------------


def _parallel_prewarm_ir(tmp_path: Path) -> dict[str, Any]:
    """Parallel sub-workflow batch, `continue` mode, item[0] lacking the field."""
    row = Row(
        "r10",
        "sub_inputs",
        "${item.x}",
        now(Ok()),
        now(Ok()),
        payload=with_payload(out_arr=[{"y": "no-x"}, {"x": "A1"}]),
    )
    ir = build_ir(row, tmp_path)
    ir["nodes"][1]["batch"] = {"items": "${p.out_arr}", "as": "item", "parallel": True, "error_handling": "continue"}
    return ir


class TestRunnerOnlyRows:
    def test_r10_parallel_prewarm_bad_first_item(self, tmp_path: Path) -> None:
        """R10 (flipped in 4a): item[0]'s strict template miss skips the pre-warm, so the
        per-item loop applies ``error_handling: continue`` — before, it failed the WHOLE run.

        Mutation: let the pre-warm template failure propagate → the run fails.
        """
        ir = _parallel_prewarm_ir(tmp_path)
        assert validator_errors(ir, {}) == []
        result = _run(ir)
        assert result.status.value == "degraded"
        assert [r["got"] for r in result.shared_after["s"]["results"]] == ["A1"]

    def test_r10_sequential_partner_degrades(self, tmp_path: Path) -> None:
        """The sequential path already applies `continue` per item — the behavior R10 aligns to."""
        ir = _parallel_prewarm_ir(tmp_path)
        ir["nodes"][1]["batch"]["parallel"] = False
        result = _run(ir)
        assert result.status.value == "degraded"
        assert [r["got"] for r in result.shared_after["s"]["results"]] == ["A1"]


def _llm_model_ir(tmp_path: Path, model: str) -> dict[str, Any]:
    ir = build_ir(Row("r6", "param", "${p.out_str}", now(Ok()), now(Ok())), tmp_path)
    ir["nodes"][1] = {
        "id": "s",
        "type": "llm",
        "purpose": "Consume a model id.",
        "params": {"prompt": "Say ${p.out_str}", "model": model},
    }
    return ir


class TestDeferralSitesEscapeOnly:
    """R6: a static check that defers on ``has_templates`` skips escape-only values today.

    The model check's finding is a WARNING (an uncatalogued model may be a fine-tune),
    so these rows read warnings, not only errors.
    """

    @staticmethod
    def _model_warnings(tmp_path: Path, model: str) -> list[str]:
        result = WorkflowRunner().validate(_llm_model_ir(tmp_path, model), {})
        assert result.errors == [], [d.message for d in result.errors]
        return [d.message for d in result.warnings]

    def test_uncatalogued_model_partner_warns(self, tmp_path: Path) -> None:
        warnings = self._model_warnings(tmp_path, "anthropic/claude-nope-9")
        assert any("'anthropic/claude-nope-9' is not in the LiteLLM catalog" in w for w in warnings), warnings

    def test_escape_only_model_is_checked_on_its_unescaped_text(self, tmp_path: Path) -> None:
        """Flipped in 4b — R6: an escape-only value is statically checked on its unescaped text."""
        warnings = self._model_warnings(tmp_path, "anthropic/claude-nope-$${x}")
        assert any("'anthropic/claude-nope-${x}' is not in the LiteLLM catalog" in w for w in warnings), warnings


# ---------------------------------------------------------------------------
# 1c. Historical fixtures — only the cross-layer halves not pinned elsewhere
#
# Already pinned (not duplicated here): #441 test_branch_convergence.py
# (missing-field coalesce tests), #460 test_node_wrapper_json_parsing.py and
# test_code_annotation_validation.py, d5a1af8c test_workflow_data_flow.py,
# 4516cd72 validator half test_malformed.py, #620 test_template_escape.py.
# ---------------------------------------------------------------------------


class TestHistoricalFixtures:
    def test_4516cd72_nested_index_coalesce_resolves(self, tmp_path: Path) -> None:
        """4516cd72 runtime half: ``${a[${i}] ?? b[${i}]}`` validates AND resolves the fallback."""
        row = Row(
            "4516cd72",
            "param",
            "${g.out_list[${idx}] ?? p.out_list[${idx}]}",
            now(Ok()),
            now(Ok()),
            ghost=True,
            declared_inputs=IDX,
            extra_params=USE_IDX,
            payload=with_payload(out_list=["x"]),
        )
        assert validator_errors(build_ir(row, tmp_path), {}) == []
        assert_end_to_end(row, Resolves("x"), tmp_path)

    def test_266_escape_not_flagged_as_template(self, tmp_path: Path) -> None:
        """#266: an escaped ``$${var}`` beside a real reference is neither validated as an
        input reference nor resolved — the node receives the literal ``${var}``."""
        row = Row("266", "param", "${p.out_str} and $${var}", now(Ok()), now(Ok()))
        assert validator_errors(build_ir(row, tmp_path), {}) == []
        assert_end_to_end(row, Resolves("S and ${var}"), tmp_path)

    def test_6b7faf8f_batch_over_workflow_node_results_index(self, tmp_path: Path) -> None:
        """6b7faf8f: ``${w.results[0].got}`` over a batched workflow node validates and resolves."""
        row = Row("6b7faf8f", "sub_inputs", "${item.x}", now(Ok()), now(Ok()))
        ir = build_ir(row, tmp_path)
        ir["nodes"][1]["batch"] = {"items": "${p.out_arr}", "as": "item"}
        ir["nodes"].append(_code_node("t", "${s.results[0].got}"))
        ir["edges"].append({"from": "s", "to": "t"})
        assert validator_errors(ir, {}) == []
        result = _run(ir)
        assert result.success, [d.message for d in result.errors]
        assert result.shared_after["t"]["result"] == "A0"

    def test_643_child_output_typo_in_output_source_is_an_under_check(self, tmp_path: Path) -> None:
        """#643 / PR #664 sibling gap, pinned: output sources are root-checked only, so a
        typo'd child output passes validation and fails loudly at run. (Params ARE
        field-checked against the child's outputs — the partner assertion.)"""
        row = Row("643", "sub_inputs", "${p.out_str}", now(Ok()), now(Ok()))
        ir = build_ir(row, tmp_path)
        ir["outputs"] = {"out": {"source": "${s.gto}", "description": "a typo'd child output"}}
        assert validator_errors(ir, {}) == []
        result = _run(ir)
        assert not result.success
        assert any("Unresolved" in d.message and "${s.gto}" in d.message for d in result.errors), [
            d.message for d in result.errors
        ]

        ir["nodes"].append(_code_node("t", "${s.gto}"))
        ir["edges"].append({"from": "s", "to": "t"})
        assert any("does not output 'gto'" in e for e in validator_errors(ir, {}))

    def _issue_630_ir(self, tmp_path: Path, value: str, payload_out_str: str) -> dict[str, Any]:
        row = Row(
            "630",
            "param",
            value,
            now(Ok()),
            now(Ok()),
            consumer="code",
            declared_inputs=B_INPUT,
            payload=with_payload(out_str=payload_out_str),
        )
        return build_ir(row, tmp_path)

    def test_630_escape_beside_same_reference_after(self, tmp_path: Path) -> None:
        """#630 repro 1 (``echo "${greeting} | $${greeting}"``) through a code node.

        Delta 1 (#630): the resolver's unresolved set is the judge.
        """
        result = _run(self._issue_630_ir(tmp_path, "${b} | $${b}", "S"))
        assert result.success, [d.message for d in result.errors]
        assert result.shared_after["s"]["result"] == "B | ${b}"

    def test_630_upstream_value_containing_reference_text_after(self, tmp_path: Path) -> None:
        """#630 repro 2 (``echo "${src.stdout} ${b}"`` with ``${b}`` in the upstream value).

        Delta 1 (#630): a resolved value's text is never re-scanned.
        """
        result = _run(self._issue_630_ir(tmp_path, "${p.out_str} ${b}", "src says ${b}"))
        assert result.success, [d.message for d in result.errors]
        assert result.shared_after["s"]["result"] == "src says ${b} B"


def test_example_nested_index_runs_unchanged() -> None:
    """1d: the committed dynamic-index example keeps its output through every phase."""
    example = _REPO / "examples" / "test-nested-index.pflow.md"
    result = WorkflowRunner().run(str(example), {}, RunnerConfig())
    assert result.success, [d.message for d in result.errors]
    stdouts = [r["stdout"].strip() for r in result.shared_after["correlate-batch"]["results"]]
    assert stdouts == [
        "First user: Processing user alice (index 0) with score 85 (VIP)",
        "Second user: Processing user bob (index 1) with score 92 (Regular)",
        "Third user: Processing user charlie (index 2) with score 78 (New)",
    ]


# ---------------------------------------------------------------------------
# 1e. Raw user-typed paths (`-o`, `read-fields`, MCP `read_fields`)
#
# These are NOT templates: the raw reader splits lexically and admits keys the
# template grammar rejects. Both readers must agree wherever the grammar accepts.
# ---------------------------------------------------------------------------

_RAW_RESULT = {"@type": "T", "dc:title": "D", "my key": "K", "0": "zero"}
RAW_PATHS: tuple[tuple[str, Any], ...] = (
    ("result.@type", "T"),
    ("result.dc:title", "D"),
    ("result.my key", "K"),
    ("result.0", "zero"),
    ("batch.results[0].result", "R"),
)
_RAW_CONTEXT: Mapping[str, Any] = MappingProxyType({"result": _RAW_RESULT, "batch": {"results": [{"result": "R"}]}})


class TestRawPaths:
    @pytest.mark.parametrize(("path", "value"), RAW_PATHS)
    def test_walk_pair(self, path: str, value: Any) -> None:
        from pflow.core.templates import TemplateResolver

        context = dict(_RAW_CONTEXT)
        assert TemplateResolver.variable_exists(path, context) is True
        assert TemplateResolver.resolve_value(path, context) == value

    def test_walk_pair_miss(self) -> None:
        from pflow.core.templates import TemplateResolver

        assert TemplateResolver.variable_exists("result.nope", dict(_RAW_CONTEXT)) is False
        assert TemplateResolver.resolve_value("result.nope", dict(_RAW_CONTEXT)) is None

    def test_template_reader_agrees_where_grammar_accepts(self) -> None:
        from pflow.core.templates import TemplateResolver

        grammar_paths = [path for path, _ in RAW_PATHS if TemplateResolver.is_simple_template("${" + path + "}")]
        assert grammar_paths == ["batch.results[0].result"]
        for path in grammar_paths:
            assert TemplateResolver.resolve_template(
                "${" + path + "}", dict(_RAW_CONTEXT)
            ) == TemplateResolver.resolve_value(path, dict(_RAW_CONTEXT))

    @pytest.fixture
    def raw_workflow(self, tmp_path: Path) -> Path:
        """Declared output ``result`` = the raw dict; node ``batch`` = a batch whose results carry ``result``."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "c",
                    "type": "code",
                    "purpose": "Raw keys.",
                    "params": {"code": f"result: dict = {_RAW_RESULT!r}"},
                },
                {
                    "id": "batch",
                    "type": "code",
                    "purpose": "One batch item.",
                    "params": {"inputs": {"v": "${item}"}, "code": "v: Any\nresult: Any = 'R'"},
                    "batch": {"items": ["one"], "as": "item"},
                },
            ],
            "edges": [{"from": "c", "to": "batch"}],
            "outputs": {"result": {"source": "${c.result}", "description": "The raw-keyed dict."}},
        }
        path = tmp_path / "raw.pflow.md"
        write_workflow_file(ir, path)
        return path

    @pytest.mark.parametrize(("path", "value"), RAW_PATHS)
    def test_cli_output_key(self, raw_workflow: Path, path: str, value: Any) -> None:
        from click.testing import CliRunner

        from pflow.cli.main import main

        result = CliRunner(mix_stderr=False).invoke(main, ["-o", path, str(raw_workflow)])
        assert result.exit_code == 0, result.stderr
        assert result.stdout.strip().splitlines()[-1] == value
        assert "not found" not in result.stderr

    @pytest.mark.parametrize(("path", "value"), RAW_PATHS)
    def test_read_fields(self, path: str, value: Any) -> None:
        from click.testing import CliRunner

        from pflow.cli.commands.read_fields import read_fields
        from pflow.core.execution_cache import ExecutionCache

        cache = ExecutionCache()
        execution_id = cache.generate_execution_id()
        cache.store(execution_id=execution_id, node_type="corpus", params={}, outputs=dict(_RAW_CONTEXT))
        result = CliRunner().invoke(read_fields, [execution_id, path])
        assert result.exit_code == 0, result.output
        assert f"{path}: {value}" in result.output
