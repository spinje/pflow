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

Execute, validate, and plan through `WorkflowRunner`; single-node probes construct
an IR for the same pipeline. Do not load node classes independently in services.
`plan_workflow` uses `format_plan_json` for the CLI dry-run JSON shape.

MCP-specific parameter checks are in
`../utils/validation.py:validate_execution_parameters`. Existing execution/planning/
cache-analysis/probe entry points call them explicitly; a new service method does
not receive them automatically.

When changing a shared formatter, inspect **both CLI and MCP callers**. CLI run
rendering is in `cli/commands/run.py` and `cli/workflow_output.py`, not `cli/main.py`.
Local imports avoid cycles; use shared formatters rather than duplicate wording.

`execution_service.py:_mcp_surfaced_diagnostics` includes warnings and parser/validator
INFO advisories; runtime INFO is not generally surfaced. Preserve those source and
severity conditions when moving diagnostics across boundaries.

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
