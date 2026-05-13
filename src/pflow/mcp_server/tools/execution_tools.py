"""Execution tools for the MCP server.

These tools provide workflow execution, validation, saving,
and node testing capabilities.
"""

import asyncio
import logging
from typing import Annotated, Any

from pydantic import Field

from ..server import mcp
from ..services.execution_service import ExecutionService

logger = logging.getLogger(__name__)


@mcp.tool()
async def workflow_execute(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Input parameters as key-value pairs matching the workflow's declared inputs"),
    ] = None,
) -> str:
    """Execute a workflow with natural language output.

    Input Types:
    1. Workflow name: "my-workflow" (from saved library)
    2. File path: "./workflow.pflow.md" (for agents with filesystem access)
    3. Raw markdown content: "# Title\\n## Steps\\n..." (inline .pflow.md content)
    4. Inline IR: {...} (for sandboxed agents or programmatic building)

    Built-in behaviors:
    - Trace always saved to ~/.pflow/debug/workflow-trace-{wf_hash}-{name}-{timestamp}.json
      (wf_hash = first 8 hex chars of md5(workflow_path), enabling O(matches)
      glob lookup by workflow rather than O(N) scan-and-parse).
    - Returns explicit errors with suggestions for fixing

    Before executing:
    1. Call workflow_describe to understand required parameters
    2. Ensure all required inputs are provided
    3. Validate parameters match expected types

    Examples:
        # Execute saved workflow by name
        workflow="my-workflow"
        parameters={"input1": "value1", "input2": 123}

        # Execute workflow from file
        # ⚠️ Use when you have filesystem access (non-sandbox agents)
        workflow="./workflows/my-workflow.pflow.md"
        parameters={...}

        # Execute inline workflow IR
        # ⚠️ Use in sandboxed environments or when building programmatically
        workflow={
            "inputs": {...},
            "nodes": [...],
            "edges": [...],
            "outputs": {...}
        }
        parameters={...}

    Returns:
        Formatted text with execution results.
        Success: one-line completion tag, optional supplementary info (batch
            errors, stderr warnings, LLM cost, validation warnings) when
            present, then ``Workflow output:`` followed by the declared
            output value (JSON-encoded for structured types so agents can
            parse it directly).
            Example: "✓ Workflow completed in 0.5s\n\nWorkflow output:\n\n{\"key\": \"value\"}"
        Error: "❌ Workflow execution failed\n\nError details:\n  • node-id: error message..."
    """
    logger.debug(f"workflow_execute called: workflow type={type(workflow)}")

    def _sync_execute() -> str:
        """Synchronous execution operation."""
        return ExecutionService.execute_workflow(workflow, parameters)

    # Run in thread pool to avoid blocking
    result = await asyncio.to_thread(_sync_execute)

    # Log based on result content
    if result.startswith("✓"):
        logger.info("Workflow execution successful")
    else:
        logger.warning("Workflow execution failed")

    return result


@mcp.tool()
async def workflow_validate(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
) -> str:
    """STATIC validation of workflow structure WITHOUT execution.

    Checks:
    - Schema compliance (required fields, correct structure)
    - Data flow correctness (execution order, no cycles)
    - Template structure (${node.output} references)
    - Node types exist in registry
    - Sub-workflow validation (recursive — checks referenced workflow files for errors)
    - Required input coverage (sub-workflows receive all required inputs)

    Does NOT check:
    - Runtime values
    - API credentials
    - ANY runtime issues

    Examples:
        # Validate saved workflow (returns validation errors if any)
        workflow="my-workflow"

        # Validate workflow file
        # ⚠️ Use when you have filesystem access
        workflow="./workflow.pflow.md"

        # Validate inline workflow IR
        # ⚠️ Use in sandboxed environments
        workflow={
            "inputs": {...},
            "nodes": [...],
            "edges": [...],
            "outputs": {...}
        }

    Returns:
        Formatted text with validation results and suggestions for fixing
        Success: "✓ Workflow is valid"
        Failure: "✗ Static validation failed:\n  • Error 1\n  • Error 2\n\nSuggestions:\n  • Fix 1"
    """
    logger.debug("workflow_validate called")

    def _sync_validate() -> str:
        """Synchronous validation operation."""
        return ExecutionService.validate_workflow(workflow)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_validate)

    # Log based on result content (string now)
    if result.startswith("✓"):
        logger.info("Workflow validation passed")
    else:
        logger.info("Workflow validation failed")

    return result


@mcp.tool()
async def plan_workflow(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Input parameters as key-value pairs matching the workflow's declared inputs"),
    ] = None,
) -> dict[str, Any]:
    """Build a workflow execution plan without invoking side effects."""
    logger.debug(f"plan_workflow called: workflow type={type(workflow).__name__}")

    def _sync_plan() -> dict[str, Any]:
        return ExecutionService.plan_workflow(workflow, parameters)

    result = await asyncio.to_thread(_sync_plan)
    logger.info("Workflow plan generated")
    return result


@mcp.tool()
async def workflow_save(
    workflow: Annotated[
        str,
        Field(
            description=(
                "Workflow to save. Can be:\n"
                "  - Raw .pflow.md content (markdown string with newlines)\n"
                "  - Path to .pflow.md file: './my-workflow.pflow.md'"
            )
        ),
    ],
    name: str = Field(..., description="Unique workflow name (format: lowercase-with-hyphens, max 50 chars)"),
    force: bool = Field(False, description="Whether to overwrite existing workflow with same name"),
) -> str:
    """Save workflow to global library for reuse.

    Purpose: Make workflows reusable by name. Save ONLY workflows you'll execute multiple times.
    Don't save: One-off workflows, tests, experiments.

    Validates the workflow before saving. Description is extracted from the
    markdown content (prose after the # title heading).
    Name must be lowercase letters, numbers, and hyphens only (max 50 chars).

    By default, saving fails if a workflow with the same name exists.
    Use force=true to overwrite existing workflows.

    Examples:
        # Save workflow from file
        # ⚠️ Use when you have filesystem access
        workflow="./path/to/my-workflow.pflow.md"
        name="my-workflow"
        force=False

        # Save raw markdown content
        workflow="# My Workflow\\n\\nDescription.\\n\\n## Steps\\n..."
        name="my-workflow"

    Returns:
        Formatted success message with location and execution hint
        "✓ Saved workflow 'name' to library\n  Location: /path/to/workflow.pflow.md\n  ✨ Execute with: pflow name param=<value>"
    """
    logger.debug(f"workflow_save called: name={name}, force={force}")

    def _sync_save() -> str:
        """Synchronous save operation."""
        return ExecutionService.save_workflow(workflow, name, force)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_save)

    logger.info(f"Workflow saved as '{name}' (force={force})")

    return result


@mcp.tool()
async def registry_run(
    node_type: Annotated[str, Field(description="Node type identifier from the registry")],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(description="Node-specific input parameters as key-value pairs"),
    ] = None,
) -> str:
    """Execute a single node with real data to test/discover its output structure and available template variables.

    ⚠️ WARNING: This EXECUTES the node with real side effects.

    Safe to test: HTTP GET, read-file, data transforms
    Ask user first: shell, write-file, HTTP POST/PUT/DELETE, MCP tools, git operations

    ⚠️ Critical use case: Use when node output structure is "Any" or unknown - common with HTTP and MCP nodes.

    WHEN TO USE:
    - AFTER using registry_describe to understand node parameters
    - BEFORE building workflows to discover available template variables
    - For any HTTP/MCP/external nodes where output structure is unclear

    Shows complete flattened output structure with all available template paths
    (like `${result.data.items[0].title}`) for workflow building.

    Examples:
        # Test HTTP GET (shows response structure for API calls)
        node_type="http"
        parameters={"url": "https://api.github.com/repos/owner/repo",
            "method": "GET",
            "headers": {"X-API-Key": "your_api_key", "X-Custom-Header": "value"}
        }

        # Test HTTP POST with JSON body (shows request/response structure)
        node_type="http"
        parameters={"url": "https://api.example.com/endpoint",
            "method": "POST",
            "body": {"key": "value", "data": [1, 2, 3]},
            "auth_token": "your_bearer_token"
        }

        # Test MCP node to discover nested output structure
        node_type="mcp-slack-mcp-server-SLACK_SEND_MESSAGE"
        parameters={"channel": "The channel id",
            "markdown_text": "Your message here"
        }

    Returns:
        Formatted text with output structure and all available template paths
    """
    logger.debug(f"registry_run called: node_type={node_type}")

    def _sync_run() -> str:
        """Synchronous node execution."""
        return ExecutionService.run_registry_node(node_type, parameters)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_run)

    logger.info(f"Node '{node_type}' execution completed, returning formatted output")
    return result


@mcp.tool()
async def read_fields(
    execution_id: Annotated[
        str, Field(description="Execution ID from previous registry_run call (format: exec-TIMESTAMP-RANDOM)")
    ],
    field_paths: Annotated[
        list[str], Field(description="Field paths to retrieve like ['result[0].title', 'result[0].id']")
    ],
) -> str:
    """Read specific field values from a cached node execution.

    This tool retrieves only the requested fields from a previous registry_run execution,
    enabling efficient data access without re-executing the node.

    WHEN TO USE:
    - AFTER calling registry_run to see structure
    - When you need actual data values (not just structure)
    - To selectively retrieve specific fields without fetching everything

    The execution_id comes from the registry_run output (displayed after execution).
    Field paths use the same syntax shown in registry_run structure output.

    Examples:
        # Single field retrieval
        execution_id="exec-1705234567-a1b2c3d4"
        field_paths=["result[0].title"]

        # Multiple fields at once (more efficient than separate calls)
        execution_id="exec-1705234567-a1b2c3d4"
        field_paths=["result[0].title", "result[0].id", "result[0].state"]

        # Nested field access
        execution_id="exec-1705234567-a1b2c3d4"
        field_paths=["result.data.items[0].author.login"]

    Returns:
        Formatted text showing each field path and its value.
        Fields not found return None.
    """
    logger.debug(f"read_fields called: execution_id={execution_id}, field_count={len(field_paths)}")

    def _sync_read_fields() -> str:
        """Synchronous field reading operation."""
        from ..services.field_service import FieldService

        return FieldService.read_fields(execution_id, field_paths)

    # Run in thread pool
    result = await asyncio.to_thread(_sync_read_fields)

    logger.info(f"Retrieved {len(field_paths)} fields from execution {execution_id}")
    return result


@mcp.tool()
async def analyze_cache(
    workflow: Annotated[
        str | dict[str, Any],
        Field(description="Workflow name from library, path to workflow file, or workflow IR object"),
    ],
    parameters: Annotated[
        dict[str, Any] | None,
        Field(
            description="Input parameters as key-value pairs (optional per DD#35 — analysis falls back gracefully when input substitution can't fully resolve a prompt)"
        ),
    ] = None,
) -> dict[str, Any]:
    """Analyze a workflow's prompt-cache plan; emit recommendations + discrepancies.

    Returns the same JSON shape as ``pflow analyze-cache --format=json``.

    **Schema versioning**: top-level ``format_version`` (string, e.g. ``"4.0"``)
    is the FIRST key. Consumers dispatch on
    ``format_version.startswith(MAJOR + ".")``. Additive 4.x minor fields don't
    bump; semantic shifts in field meaning bump minor; field-shape removal bumps
    major. Full version history in ``pflow.core.cache_analysis.__init__``.

    Top-level keys: ``format_version``, ``workflow_path``, ``analyzed_at``,
    ``estimate_confidence``, ``estimate_confidence_coverage``, ``trace_path``,
    ``summary``, ``blocking_errors``, ``other_blocking_errors``,
    ``recommended_actions``, ``suggested_blocks``, ``per_call``,
    ``cross_workflow``, ``warnings``, ``notes``.

    **Cost-field shape**: ``summary`` carries five atomic cost primitives,
    each with ONE meaning (independent of greenfield/trace context):

      - ``actually_paid_usd`` (number | null): trace-driven recorded cost;
        ``null`` for greenfield. Includes provider-side implicit caching
        (Gemini) and any other discount the trace recorded.
      - ``actually_paid_tier`` (string): ``"trace"`` / ``"trace_partial"``
        / ``"unavailable"``.
      - ``no_cache_hypothetical_usd`` (number | null): pure no-cache
        recompute baseline.
      - ``first_run_with_cache_hypothetical_usd`` (number | null):
        first-run projection that honors declared ``prompt_cache:``.
      - ``rerun_within_ttl_hypothetical_usd`` (number | null): all-cacheable-
        at-read-rate projection.
      - ``total_llm_nodes_estimated`` (number): LLM node rows in the analyzed
        workflow graph.
      - ``total_llm_invocations_estimated`` (number | null): static estimate
        of runtime LLM calls after batch fanout; ``null`` when any batch size
        is dynamic.
      - ``dynamic_batch_node_count`` (number): batch LLM nodes whose fanout
        count could not be estimated statically.
      - ``ir_default_model`` (string | null): IR-resolved default model for
        the analysis run. Compare with ``observed_models_in_trace`` to detect
        settings/default-model divergence in trace mode.
      - ``projection_exclusions`` (array): LLM rows excluded from absolute
        hypothetical projections, with ``workflow_path``, ``node_path``,
        ``reason``, and optional ``actual_cost_usd``. When non-empty, actual
        trace cost and projection cost cover different cohorts. Reasons include
        ``heterogeneous_model``, ``unresolved_model``, ``unpriced_model``, and
        ``missing_output_tokens``.
      - ``suggested_run_command`` (string | null): paste-ready ``pflow run``
        command derived from ``workflow_path`` + declared inputs (placeholder
        values like ``article=<value>``). ``null`` for inline IR or
        ``ir-hash:`` lookup keys. Surfaced on unavailable-cost branches so
        agents see the exact command that lights up cost figures.

    Sub-workflow rollup entries carry the same four primitives at child
    scope.

    Delta objects include ``unavailable_reason`` and ``excluded_nodes``.
    ``actual_vs_no_cache_delta`` is unavailable when trace coverage is
    ``"none"`` or when no priced rows remain to compare against (every row
    in the cohort was excluded — heterogeneous batch, unpriced model, etc.).
    When projection exclusions exist but at least one priced row survives,
    the delta is computed on the priced subset and ``excluded_nodes`` lists
    the node paths whose cost was subtracted from total paid before the
    comparison; ``compared_to`` becomes ``"actually_paid_priced_cohort_usd"``
    so JSON consumers can distinguish whole-cohort deltas from priced-subset
    deltas.

    **Validator finding parity**: ``analyze_cache`` runs the same 10-step
    ``WorkflowValidator`` pipeline as ``pflow run``, ``--validate-only``, and
    ``pflow save``. ERROR findings split by cache-domain across
    ``blocking_errors[]`` (cache-related — id startswith ``cache.``,
    ``llm.thinking-temperature-mismatch``, or context.path under
    ``cache.``/``prompt_cache``) and ``other_blocking_errors[]`` (everything
    else: schema errors, unknown node types, etc.). Both lists are ranked and
    deduplicated, with ``message`` and ``suggestions`` preserved. All ERRORs
    also appear in ``warnings[]`` with ``severity: "error"``.

    ``len(blocking_errors)`` matches ``summary.blocking_errors`` (the cache-
    focused headline count). ``other_blocking_errors[]`` is surfaced for
    awareness so agents can see env-config issues without conflating them
    with caching work.

    New ERROR finding categories agents may now see in addition to the cache
    catalog: IR schema errors, stdin/stdout cardinality violations, forward
    references, execution-order cycles, unresolvable template variables,
    unknown node types, unknown node parameters, and sub-workflow input
    contract violations. These non-cache categories surface in
    ``other_blocking_errors[]``.

    WARNING-severity findings: only cache-domain warnings flow into
    ``recommended_actions[]``. Memoization-cache lint warnings and other
    non-cache advisory findings remain in raw ``warnings[]`` but are filtered
    out of provider prompt-cache recommendations.

    **Sub-workflow provenance**: child-workflow findings have their message
    prefixed with ``In step '<parent_step_id>' sub-workflow:`` per nesting
    level. The leaf workflow path is in each diagnostic's
    ``context.affected_workflow``. The ``node_id`` is the deepest nested node
    id, or the parent step id for un-IDed validators bubbled up through
    ``_add_child_provenance``.

    ``blocking_errors``, ``other_blocking_errors``, and ``recommended_actions``
    are renderer-derived views over ``warnings``; cross-workflow alignment
    IDs are filtered into ``cross_workflow.*`` only.
    ``cross_workflow.{rename, prose, value_flow}`` arrays are derived from
    ``warnings`` by ``Diagnostic.id``.

    For ``cache.sub-workflow-cache-undeclared``, agents should read
    ``context.case`` (``actionable`` / ``model_switch`` / ``refactor`` /
    ``unmeasurable``), ``context.inputs[]`` (per incoming value with
    ``child_cache_ref`` as the child ``## Cache`` entry to add,
    ``child_input_name`` as the boundary input name, ``parent_cache_ref``,
    ``parent_value_expr``, ``tokens_estimated``, and ``consumer_node_ids``),
    ``context.body_block`` (text-ready guidance), and ``context.savings_usd``.
    Older per-input top-level fields such as ``child_input_name`` and
    ``below_threshold_clause`` are no longer emitted.

    **``warnings[].id`` shape**: either one of these cache catalog entries or
    ``None`` for un-IDed validator findings. Use ``severity`` for
    blocking-vs-advisory dispatch; use cache catalog membership for
    cache-vs-other dispatch.
      - cache.order-mismatch
      - cache.unused-chunk
      - cache.shared-context-undeclared
      - cache.sub-workflow-cache-undeclared
      - cache.prompt-cache-incomplete
      - cache.batch-prewarm-recommended
      - cache.dynamic-before-static
      - cache.padding-advisory
      - cache.below-min-tokens
      - cache.cross-workflow-prose-mismatch
      - cache.cross-workflow-rename-detected
      - cache.discrepancy
      - cache.invalid-on-non-llm
      - cache.unsupported-provider-ttl
      - cache.prewarm-no-prefix
      - cache.consolidate-to-root-recommended
      - cache.heterogeneous-models-fragment-cache
      - cache.first-call-write-penalty
      - cache.system-prompts-fragment-cache
      - cache.opaque-prompt
      - cache.prompt-body-duplicates-cache
      - cache.prompt-body-shadows-cache
      - llm.thinking-temperature-mismatch

    **Cost-degradation tri-state** (per the F2 contract): when some node
    models lack pricing data, ``summary.partial_cost_usd`` becomes ``true``,
    ``summary.unavailable_models`` lists the missing model strings, and
    cost fields may be ``null``. Confidence label tracks token-source
    fidelity, NOT dollar fidelity.

    **per_call[].data_source** carries the four-value tier: ``trace`` /
    ``memo`` / ``estimator`` / ``heuristic`` (highest-fidelity first).

    **per_call[].cacheable_data_source** is INDEPENDENT from ``data_source``
    and tracks the cacheable-tokens metric specifically. Values: ``trace``
    / ``memo`` / ``parameters`` / ``batch_prefix`` /
    ``cross_workflow_projection`` / ``unavailable``. The
    two labels may legitimately diverge — e.g., trace fires for input but
    cacheable falls through to memo when ``cache_creation+cache_read==0``.
    ``batch_prefix`` covers the static-prefix projection on batch nodes
    (repeated bytes before the first ``${alias.X}`` ref multiplied by
    observed call count) — a heuristic projection for undeclared rows;
    ``cross_workflow_projection`` covers parent-declared values sent into
    a child workflow that has not declared the receiving input in its own
    ``## Cache``. The text renderer surfaces footer notes flagging both
    projection tiers.

    **per_call[].did_not_execute_in_trace** (boolean): True when the IR
    declares the LLM node but the loaded trace did not record an execution
    for it. Distinguishes "static analysis row" from "trace evidence row";
    agents should treat fields like ``cost_usd`` as projections (not
    actuals) when this is True. Note: under
    ``trace_coverage="complete"``, this can still be True for nodes that
    were conditional dispatches not taken for the run's inputs — the trace
    is complete but the workflow had branches that didn't fire.

    **summary.trace_unexecuted_llm_rows** (array): structured list of
    ``{workflow_path, node_path}`` for every static row with
    ``did_not_execute_in_trace=True``. Populated under both ``"truncated"``
    AND ``"complete"`` trace_coverage — the latter case represents
    conditional-dispatch nodes (e.g., classify→one-of-N branches) where
    the unreached branches surface here for header annotation
    (``"X of Y LLM nodes executed; Z not reached for these inputs"``).

    **summary.evidence_scope** (string): ``"static_analysis"`` /
    ``"complete_trace"`` / ``"truncated_trace_executed_subset"``. Indicates
    how broadly the trace covers the IR. Under
    ``"truncated_trace_executed_subset"``, cost-projection findings (e.g.
    ``cache.first-call-write-penalty``) are suppressed because the cohort is
    incomplete; IR-derived findings (cross-workflow renames,
    shared-context-undeclared, etc.) flow regardless of trace coverage
    because they describe workflow structure, not execution evidence.

    **summary.trace_coverage** (string): ``"none"`` / ``"complete"`` /
    ``"truncated"``. The static-vs-execution coverage discriminator.
    ``"truncated"`` requires the trace's ``final_status`` to be ``"failed"``
    AND some static rows to be unexecuted — workflow died mid-run. A
    successful run that skipped conditional branches (one of N classify
    paths) classifies as ``"complete"`` regardless of unexecuted rows;
    those rows surface in ``trace_unexecuted_llm_rows`` for header
    annotation but don't trigger suppression.

    **summary.actual_vs_no_cache_delta.unavailable_reason** (string when
    ``kind=="unavailable"``): ``"no_trace"`` (trace_coverage is ``"none"``)
    or ``"projection_exclusions"`` (cohort filtered by unpriced models /
    missing tokens). Truncated traces compute this delta over the executed
    subset when pricing is otherwise available.

    **per_node_thresholds[node_id]** in ``suggested_blocks[]`` carries
    ``model: string | null`` and ``model_state: "resolved" |
    "heterogeneous" | "unknown"``. Dispatch on ``model_state`` rather than
    sentinel strings — JSON output uses ``null`` for the heterogeneous /
    unknown cases (the magic-string ``"<varies>"`` / ``"<unknown>"``
    appears only in rendered text).

    **Empty-array contract**: ``cross_workflow.rename_detections``,
    ``prose_mismatches``, ``value_flow_opportunities`` are always present
    as ``[]`` (not absent, not ``null``) when no findings exist.

    Per DD#36, analytical findings are advisory: ERROR-severity findings
    surface in ``warnings[]`` but do NOT raise from this tool. Pre-existing
    parse / validation errors that prevent IR construction DO raise (same
    shape ``workflow_validate`` would surface).

    Examples:
        # Variant 1: saved library workflow
        workflow="my-workflow"

        # Variant 2: file path
        workflow="./path/to/workflow.pflow.md"

        # Variant 3: raw IR dict (for inline analysis)
        workflow={"nodes": [...], "edges": [...]}

        # With parameters (optional)
        workflow="my-workflow"
        parameters={"input_key": "value"}

    Returns:
        JSON dict matching the CLI's ``--format=json`` output shape.
    """
    logger.debug(f"analyze_cache called: workflow type={type(workflow).__name__}")

    def _sync_analyze() -> dict[str, Any]:
        return ExecutionService.analyze_cache(workflow, parameters)

    result = await asyncio.to_thread(_sync_analyze)
    logger.info("Cache analysis complete")
    return result


# Export all execution tools
__all__ = [
    "analyze_cache",
    "plan_workflow",
    "read_fields",
    "registry_run",
    "workflow_execute",
    "workflow_save",
    "workflow_validate",
]
