"""Cache analysis package — Tier 2 + Tier 3 verification per Task 159 DD#36.

Surfaces:

- ``analyze(workflow, parameters)`` — full analysis (CLI ``pflow analyze-cache`` +
  MCP ``analyze_cache`` tool).
- ``summarize(workflow, parameters)`` — one-line dry-run nudge.
- ``CacheAnalysis`` — structured result.
- ``JSON_FORMAT_VERSION`` — version string emitted by ``render_json`` so JSON
  consumers can version-gate (consumer rule: ``startswith(MAJOR + ".")``).

Version history (``JSON_FORMAT_VERSION``):

- ``"1.0"`` — initial shape (Task 159 Segment 4).
- ``"1.1"`` — semantic shift on ``per_call[].cacheable_tokens_estimated``
  (was always 0 in greenfield; now projected from detected shared context
  when memo data exists). Field shapes unchanged.
- ``"2.0"`` — Stage 0 data-model redesign: ``recommended_actions`` and
  ``cross_workflow.*`` collapsed to derived projections from ``warnings``
  (single source of truth). ``per_call[].warnings`` field dropped.
- ``"2.1"`` — Stage C.1 minor-additive: ``per_call[].model_is_heterogeneous``;
  ``summary.heterogeneous_model_node_*``. Track A: ``per_call[].cost_usd``,
  ``per_call[].cost_data_source``; ``cacheable_data_source`` gains
  ``"parameters"`` value.
- ``"4.0"`` — atomic cost primitives: replaced ``current_cost_per_run_usd`` /
  ``optimized_cost_per_run_usd`` / ``rerun_cost_per_run_usd`` with
  ``actually_paid_usd`` / ``no_cache_hypothetical_usd`` /
  ``first_run_with_cache_hypothetical_usd`` /
  ``rerun_within_ttl_hypothetical_usd`` and matching ``CostDelta`` fields.
  Each field carries ONE meaning; tier discriminators (``actually_paid_tier``,
  ``cost_data_source``) are independent of value presence.
- ``"4.1"`` — F-04 fix: ``per_call[].cacheable_data_source`` enum narrowed
  from 5 values to 4 — ``"estimator"`` is no longer emitted. Pre-fix, the
  declared-subset Tier 3 heuristic at ``token_estimation.py:174-176`` would
  fabricate a ``len(prompt) * 75 // 400`` token count when memo/parameters
  couldn't resolve chunks; the value carried the ``"estimator"`` source
  label. Post-fix, that path returns ``(None, "unavailable")`` per the
  honest-unmeasurable contract. Field shape unchanged; only the value
  enum narrows. No production code branched on ``"estimator"`` for this
  field.
- ``"4.1"`` — UX 8 fix (additive, same minor): ``summary.suggested_run_command``
  added (``string | null``). Paste-ready ``pflow run`` command derived from
  ``workflow_path`` + declared inputs, surfaced on unavailable-cost branches
  in text output. ``null`` for inline IR / ``ir-hash:`` lookup keys.
- ``"4.1"`` — trace-mode model disclosure (additive, same minor):
  ``summary.ir_default_model`` added (``string | null``). Captures the
  IR-resolved default model so text/JSON consumers can compare declared
  settings with ``summary.observed_models_in_trace``.

Consumer rule: gate on ``format_version.startswith("4.")`` for the current
shape. Additive 4.x minor fields don't bump; semantic shifts in field meaning
bump minor; field-shape removal bumps major.
"""

from __future__ import annotations

from typing import Final

from .analyze import CacheAnalysis, analyze
from .render_json import render_json
from .render_text import render_text
from .summarize import summarize, summarize_from_analysis

JSON_FORMAT_VERSION: Final[str] = "4.1"
"""Version string emitted as the first key by ``render_json``.

Consumer rule: ``startswith(JSON_FORMAT_VERSION.split(".")[0] + ".")``.
"""

__all__ = [
    "JSON_FORMAT_VERSION",
    "CacheAnalysis",
    "analyze",
    "render_json",
    "render_text",
    "summarize",
    "summarize_from_analysis",
]
