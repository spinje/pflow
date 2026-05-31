"""Loop condition evaluation for engine re-entry (issue #445).

A ``loop:``-configured node is re-run by the engine until a truthiness condition
over its own typed output goes falsy or an iteration cap is hit. This module owns
the two runtime decisions that drive that re-entry:

- :func:`evaluate_loop_condition` — absent-aware, type-preserving truthiness over
  the ``while:`` source. NEVER uses ``resolve_template`` (which returns the truthy
  literal on an absent reference → infinite loop). A still-``str`` resolved value
  raises :class:`LoopConditionError` (belt half 2 of the typed-output guard).
- :func:`resolve_loop_cap` — resolves ``max_iterations`` (literal already validated
  at compile time, or a ``${template}`` resolved here at loop entry) and bounds it
  to ``[1, MAX_NODE_VISITS]``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pflow.core.exceptions import LoopConditionError
from pflow.runtime.template_resolver import TemplateResolver

from . import instrumentation
from .types import LoopConfig


@contextmanager
def loop_runtime_scope(
    shared: dict[str, Any],
    active: bool,
    *,
    iteration: int | None = None,
    clear_iteration_on_exit: bool,
) -> Iterator[None]:
    """Manage the per-iteration loop bookkeeping around a node execution (issue #445).

    On enter (when ``active``): sets ``${__iteration__}`` (if ``iteration`` given) and
    raises the ``__loop_active__`` depth counter that suppresses inner-node memo reads.
    On exit: decrements the depth, and pops ``__iteration__`` when ``clear_iteration_on_exit``.

    The ``clear_iteration_on_exit`` asymmetry is real: the engine KEEPS ``__iteration__``
    across re-entry (it clears it only when the loop actually ends), so it passes False;
    the planner walks the body once and must not leak ``__iteration__`` to later nodes, so
    it passes True. A no-op when ``not active``.
    """
    if active:
        if iteration is not None:
            shared["__iteration__"] = iteration
        shared["__loop_active__"] = shared.get("__loop_active__", 0) + 1
    try:
        yield
    finally:
        if active:
            depth = shared.get("__loop_active__", 1) - 1
            if depth > 0:
                shared["__loop_active__"] = depth
            else:
                shared.pop("__loop_active__", None)
            if clear_iteration_on_exit:
                shared.pop("__iteration__", None)


def evaluate_loop_condition(while_template: str, shared: dict[str, Any], node_id: str) -> bool:
    """Return whether the loop should re-run, given the node's just-completed output.

    Reads ``shared`` at the engine seam where ``shared[node_id]`` holds the fresh
    output. Absent reference → falsy (stop). A resolved ``str`` value raises
    ``LoopConditionError`` rather than being ``bool()``-ed (a non-empty string like
    ``"0\\n"`` or ``"false"`` is truthy — exactly the foot-gun this guards).
    """
    context = dict(shared)
    var = TemplateResolver.extract_simple_template_var(while_template)
    if var is None:
        # Not a single ${...} reference. The validator rejects this shape at parse time
        # (_make_loop_shape_diagnostic), so this is the backstop for a programmatic IR that
        # bypassed validation — stop rather than loop on garbage.
        return False

    if TemplateResolver.is_coalesce_expression(var):
        value, status = TemplateResolver.resolve_coalesce(var, context)
        if status != "resolved":
            return False
    else:
        if not TemplateResolver.variable_exists(var, context):
            return False
        value = TemplateResolver.resolve_value(var, context)

    if isinstance(value, str):
        preview = value if len(value) <= 60 else value[:57] + "..."
        raise LoopConditionError(
            f"Node '{node_id}' loop condition '{while_template}' resolved to a string ({preview!r}). "
            f"String truthiness is unsafe — a non-empty string like '0\\n' or 'false' is truthy, "
            f"so the loop would never stop on those values.",
            node_id=node_id,
            suggestion=(
                "Reference a typed output in `while:` — a list (drains to empty), a number "
                "(counts to 0), or a boolean. If the source is genuinely a list/number, declare "
                "its output type so it isn't produced as a string."
            ),
        )

    return bool(value)


def resolve_loop_cap(loop_config: LoopConfig, shared: dict[str, Any], node_id: str) -> int:
    """Resolve the iteration cap for a loop, bounded to ``[1, MAX_NODE_VISITS]``.

    - Literal cap: already validated at compile time — returned as-is.
    - Template cap (``max_iterations: ${cap}``): resolved against ``dict(shared)``
      at loop entry and routed through the same coerce + range check as the literal.
    - Neither: defaults to the live ``MAX_NODE_VISITS`` (env-overridable).
    """
    if loop_config.max_iterations is not None:
        return loop_config.max_iterations

    if loop_config.max_iterations_template is not None:
        raw = TemplateResolver.resolve_template(loop_config.max_iterations_template, dict(shared))
        return _coerce_runtime_cap(raw, node_id, loop_config.max_iterations_template)

    return instrumentation.MAX_NODE_VISITS


def _coerce_runtime_cap(raw: Any, node_id: str, template: str) -> int:
    """Coerce a runtime-resolved ``max_iterations`` value to a bounded positive int."""
    if isinstance(raw, bool):
        value = int(raw)
    elif isinstance(raw, int):
        value = raw
    elif isinstance(raw, float):
        value = int(raw)
    elif isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise LoopConditionError(
                f"Node '{node_id}' loop `max_iterations` template '{template}' resolved to {raw!r}, "
                f"which is not a positive integer.",
                node_id=node_id,
                suggestion="Ensure the referenced value is a positive integer (the iteration cap).",
            ) from exc
    else:
        raise LoopConditionError(
            f"Node '{node_id}' loop `max_iterations` template '{template}' resolved to "
            f"{type(raw).__name__} ({raw!r}), which is not a positive integer.",
            node_id=node_id,
            suggestion="Ensure the referenced value is a positive integer (the iteration cap).",
        )

    if value < 1:
        raise LoopConditionError(
            f"Node '{node_id}' loop `max_iterations` resolved to {value}; it must be >= 1.",
            node_id=node_id,
            suggestion="Provide a positive integer cap.",
        )
    if value > instrumentation.MAX_NODE_VISITS:
        raise LoopConditionError(
            f"Node '{node_id}' loop `max_iterations` resolved to {value}, exceeding the hard visit "
            f"cap of {instrumentation.MAX_NODE_VISITS}.",
            node_id=node_id,
            suggestion=(
                f"Lower max_iterations to <= {instrumentation.MAX_NODE_VISITS}, or raise the cap via "
                "the PFLOW_MAX_NODE_VISITS environment variable."
            ),
        )
    return value
