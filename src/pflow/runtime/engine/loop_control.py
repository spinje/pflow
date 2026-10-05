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
from dataclasses import replace
from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import LoopCarryError, LoopConditionError
from pflow.core.templates import TemplateResolver, parse, resolve

from . import instrumentation
from .types import LoopConfig, NodeConfig, TemplateConfig


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


def apply_carry_overrides(template_config: TemplateConfig, carry: dict[str, str]) -> TemplateConfig:
    """Return an effective TemplateConfig for carried loop iterations.

    The compiled TemplateConfig is reused across visits. This helper never
    mutates it: carried keys are moved into the effective ``inputs`` template
    map for the current visit, while non-carried inputs keep their original
    static/template values.
    """
    static_inputs = template_config.static_params.get("inputs", {})
    template_inputs = template_config.template_params.get("inputs", {})
    current_inputs: dict[str, Any] = {}
    if isinstance(static_inputs, dict):
        current_inputs.update(static_inputs)
    if isinstance(template_inputs, dict):
        current_inputs.update(template_inputs)

    effective_inputs = {**current_inputs, **carry}
    return replace(
        template_config,
        template_params={**template_config.template_params, "inputs": effective_inputs},
        static_params={k: v for k, v in template_config.static_params.items() if k != "inputs"},
    )


def is_carry_iteration(config: NodeConfig, shared: dict[str, Any]) -> bool:
    """True when a carried loop node is past round 1 (carry overrides the round-1 seed)."""
    loop_config = config.loop_config
    return loop_config is not None and bool(loop_config.carry) and shared.get("__iteration__", 1) > 1


def carry_effective_config(config: NodeConfig, shared: dict[str, Any]) -> NodeConfig:
    """Return ``config`` with carried inputs overridden for round N>1, else unchanged.

    Owned by the resolution layer (called from ``plan_node``, the single authority for
    template resolution + config hashing — see runtime/CLAUDE.md), so the carry override
    is part of "what inputs does this node resolve this iteration" and config-hash,
    resolution, and execution all observe the same effective inputs — the planner
    included: it walks a resumed loop step at its saved iteration, so carry fires there
    from the seeded previous output exactly as it will at runtime (Task 179).
    """
    if not is_carry_iteration(config, shared):
        return config
    loop_config = config.loop_config
    if loop_config is None:  # unreachable post-is_carry_iteration; narrows for mypy
        return config
    if config.template_config is None:
        raise LoopCarryError(
            f"Loop '{config.node_id}' has carried inputs but no template configuration to resolve them.",
            node_id=config.node_id,
            suggestion="Declare round-1 seed values under the node's `inputs:` mapping.",
        )
    return replace(
        config,
        template_config=apply_carry_overrides(config.template_config, loop_config.carry),
    )


def evaluate_loop_condition(
    condition_template: str, shared: dict[str, Any], node_id: str, *, until: bool = False
) -> bool:
    """Return whether the loop should re-run, given the node's just-completed output.

    Reads ``shared`` at the engine seam where ``shared[node_id]`` holds the fresh
    output. Absent reference → falsy (stop). A resolved ``str`` value raises
    ``LoopConditionError`` rather than being ``bool()``-ed (a non-empty string like
    ``"0\\n"`` or ``"false"`` is truthy — exactly the foot-gun this guards).
    """
    if not parse(condition_template).is_simple:
        # Not a single ${...} reference. The validator rejects this shape at parse time
        # (_make_loop_shape_diagnostic), so this is the backstop for a programmatic IR that
        # bypassed validation — stop rather than loop on garbage.
        #
        # Polarity-agnostic STOP is intentional (does NOT apply the `until` inversion): a
        # malformed TEMPLATE is garbage, distinct from an absent VALUE (handled below, where
        # `until` + absent → continue). Fail-closed for both. This is load-bearing ONLY while
        # the validator keeps rejecting this shape for `until` too — if that ever loosens, a
        # malformed `until:` would stop on pass 1 (the "runs once and exits" bug).
        return False

    resolution = resolve(condition_template, dict(shared))
    value = resolution.value if resolution.ok else None

    if isinstance(value, str):
        preview = value if len(value) <= 60 else value[:57] + "..."
        raise LoopConditionError(
            f"Node '{node_id}' loop condition '{condition_template}' resolved to a string ({preview!r}). "
            f"String truthiness is unsafe — a non-empty string like '0\\n' or 'false' is truthy, "
            f"so the loop would never stop on those values.",
            node_id=node_id,
            suggestion=(
                "Reference a typed output in `while:` or `until:` — a list (drains to empty), "
                "a number (counts to 0), or a boolean. If the source is genuinely a list/number, "
                "declare its output type so it isn't produced as a string."
            ),
        )

    truthy = bool(value)
    return not truthy if until else truthy


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


def should_reenter(
    config: NodeConfig,
    shared: dict[str, Any],
    node_id: str,
    loop_counts: dict[str, int],
    loop_caps: dict[str, int],
) -> bool:
    """Decide whether a ``loop:`` node re-enters after a clean run (issue #445).

    The one re-entry decision, three callers: the engine walk (after each iteration),
    the engine's resume AFTER a loop step's completed iteration (Task 179 — an answered
    escalation, or a kill before the decision: ``WorkflowEngine._prepare_resume``), and
    the dry-run planner's view of that resume (its ``loop_stopped`` / cap advisory land
    in the planner's scratch store only). A non-loop node never re-enters. Known resume
    edge: a ``max_iterations: ${template}`` referencing this node's OWN output resolves
    against the resumed iteration's output, not iteration 1's.

    Order is load-bearing: a falsy condition is a CLEAN drain (``loop_stopped:
    "condition"``); a truthy condition that has reached the cap is a
    non-degrading advisory (``loop_stopped: "max_iterations"`` + INFO). The cap
    counts the loop's OWN iterations and is always ``<= MAX_NODE_VISITS``, so it
    stops before the hard visit guard would raise.

    The cap is resolved ONCE per loop and memoized in ``loop_caps`` — a
    ``max_iterations: ${template}`` that resolves to different values across
    iterations uses its first-iteration value (a loop's cap is fixed by design).
    """
    loop_config = config.loop_config
    if loop_config is None:
        return False

    if loop_config.until_template is not None:
        should_continue = evaluate_loop_condition(loop_config.until_template, shared, node_id, until=True)
    elif loop_config.while_template is not None:
        should_continue = evaluate_loop_condition(loop_config.while_template, shared, node_id)
    else:
        raise LoopConditionError(
            f"Node '{node_id}' loop has neither `while:` nor `until:` configured.",
            node_id=node_id,
            suggestion="Declare exactly one loop condition: `while: ${node.output}` or `until: ${node.output}`.",
        )
    if not should_continue:
        mark_loop_stopped(shared, node_id, "condition")
        return False

    cap = loop_caps.get(node_id)
    if cap is None:
        cap = resolve_loop_cap(loop_config, shared, node_id)
        loop_caps[node_id] = cap

    if loop_counts[node_id] >= cap:
        mark_loop_stopped(shared, node_id, "max_iterations")
        emit_loop_cap_advisory(shared, node_id, cap, until=loop_config.until_template is not None)
        return False

    return True


def mark_loop_stopped(shared: dict[str, Any], node_id: str, reason: str) -> None:
    """Stamp ``loop_stopped`` on the loop node's output so JSON/MCP/CLI can read why it ended."""
    node_output = shared.get(node_id)
    if isinstance(node_output, dict):
        node_output["loop_stopped"] = reason


def emit_loop_cap_advisory(shared: dict[str, Any], node_id: str, cap: int, *, until: bool = False) -> None:
    """Emit a non-degrading INFO advisory when a loop stops because it hit its cap.

    Mirrors the empty-input batch advisory (``batch_executor._push_batch_warnings``):
    an ``INFO`` Diagnostic written to ``__warnings__`` surfaces in reports / CLI /
    JSON without flipping the workflow to DEGRADED.

    The wording is polarity-aware (``until``): a ``while:`` loop caps with its
    condition still *truthy* (it never went falsy); an ``until:`` loop caps with
    its condition still *falsy* (it never went truthy). Hard-coding the ``while``
    phrasing for an ``until`` loop would tell the agent to make the source "go
    falsy" — the exact polarity confusion ``until:`` exists to prevent.

    Overwrite precedence (deliberate): this writes ``__warnings__[node_id]``
    unconditionally. It is reached only on the non-error re-entry path, and the
    failure-path writers (``mark_node_failed``) plus batch's advisory writers
    (batch is mutually exclusive with loop) never coexist with it. The one
    non-error writer that CAN coexist is an ``llm`` loop body emitting its own
    INFO/WARNING advisory on the same capping iteration; in that case the cap
    advisory intentionally WINS (it explains *why the loop stopped* — the more
    important signal). Per-iteration ``clear_node_failure`` already pops stale
    warnings on re-entry, so only the final iteration's advisory is at stake.
    """
    keyword = "until" if until else "while"
    still_state = "falsy" if until else "truthy"
    target_state = "truthy" if until else "falsy"
    shared.setdefault("__warnings__", {})[node_id] = Diagnostic(
        severity=Severity.INFO,
        title="Loop reached max_iterations",
        message=(
            f"Loop node '{node_id}' stopped after reaching its max_iterations cap ({cap}) "
            f"with its `{keyword}:` condition still {still_state}."
        ),
        suggestions=[
            "Expected when capping a stop-on-condition loop. If the loop should have drained "
            f"naturally, raise max_iterations or check that the `{keyword}:` source eventually goes {target_state}.",
        ],
        node_id=node_id,
        source="runtime",
        id="loop.max-iterations-reached",
    )
