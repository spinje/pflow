# MCP Services

Public request entry points are typed classmethods decorated with
`@ensure_stateless`. Create request-scoped dependencies inside the call; module/class
singletons holding request state can leak data or race between `to_thread` calls.
`base_service.py:ensure_stateless` logs boundaries—it does not enforce this rule.

## Navigation

| Concern | Owner |
|---|---|
| Execute/validate/plan/save workflows, probe nodes, analyze cache | `execution_service.py:ExecutionService` |
| Workflow/component discovery | `discovery_service.py:DiscoveryService` |
| Node descriptions and search | `registry_service.py:RegistryService` |
| Saved workflow listing/descriptions | `workflow_service.py:WorkflowService` |
| Read cached probe fields | `field_service.py:FieldService` |
| Exception rendering and legacy pass-through | `../server.py:PflowMCP`, `_should_render` |

## Execution and diagnostic seams

Execute, validate, and plan through `WorkflowRunner`; the single-node probe is
`execution/probe.py::probe_node` (shared with CLI `pflow probe`), a one-node IR through the same pipeline. Do not load node classes independently in services.
`plan_workflow` uses `format_plan_json` for the CLI dry-run JSON shape.

MCP-specific parameter checks are in
`../utils/validation.py:validate_execution_parameters`. Existing execution/planning/
cache-analysis/probe entry points call them explicitly; a new service method does
not receive them automatically.

`execute_workflow` renders the run's ending through `execution/formatters/run_outcome.py`
(`build_run_outcome` → `render_mcp_text`) — the same document the CLI emits as JSON — and
returns the text on success or a durable pause, raising it as `RuntimeError` on failure.
Never assemble MCP run text here; change the builder or a section function. Local imports
avoid cycles.

The advisory policy — warnings plus parser/validator INFO, runtime INFO left to the
document — lives in `render_mcp_text` for runs and in
`execution_service.py:_mcp_surfaced_diagnostics` for `validate_workflow` and the
`registry_run` probe. Preserve those source and severity conditions when moving diagnostics.

For saved-workflow not-found responses, retain actionable similar-name suggestions;
see `workflow_service.py:describe_workflow` and
`core/suggestion_utils.py:format_did_you_mean`.

Save delegates to `core/workflow/save_service.py:save_workflow_with_options` and
formats its validation errors. Warning/advisory fields on an exception do not
ensure a caller passes or displays them: preserve diagnostic objects explicitly
when changing handoffs rather than assuming the exception type supplies parity.

Durable gate pause is a distinct result, not an execution failure. Keep the
Runner's durability check before exposing a resume token. Other exceptions reach
the parent server boundary; see `../CLAUDE.md` for typed versus legacy handling.
