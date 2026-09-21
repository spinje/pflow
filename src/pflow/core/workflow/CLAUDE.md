# Workflow Lifecycle

## Task Navigation

| Task | Owner |
|---|---|
| Save/load storage and metadata | `manager.py::WorkflowManager` |
| Validate and save content, bundle dependencies | `save_service.py::save_workflow_with_options` |
| Change pre-execution validation | `validator.py::WorkflowValidator.validate` |
| Change dependencies or cache declaration rules | `data_flow.py::validate_data_flow`, `_validate_cache_block` |
| Resolve child workflows and external files | `sub_workflow_resolver.py`, `dependency_discovery.py` |
| Change static graph construction or rendering | `graph/CLAUDE.md`; compatibility entry point in `mermaid/CLAUDE.md` |
| Publish skills | `skill_service.py` |
| Change status or workflow discovery | `status.py`, `context.py`, `discovery.py` |

`workflow/__init__.py` has no re-exports. Import from the specific submodule.

## manager.py and save_service.py

Storage is `~/.pflow/workflows/{name}/{name}.pflow.md` with bundled dependencies.
Creates publish a temporary directory with `os.rename`; metadata updates use
`os.replace`. Preserve original markdown body content when changing metadata.

`save_workflow_with_options()` accepts raw markdown and owns content parsing,
normalization, full validation, then bundling/persistence. **Callers must validate
the workflow name** with `validate_workflow_name`; reserved names are owned by
`RESERVED_WORKFLOW_NAMES`. Direct manager operations are persistence primitives,
not a substitute for content validation.

## validator.py

`WorkflowValidator.validate()` is the canonical pipeline/step-order reference.
Structural errors short-circuit semantic checks: those checks assume valid IR
shape, and malformed data causes misleading cascades. Producer bugs in semantic
validators propagate to the outer exception boundary.

Unknown-node-type diagnostics belong to `_validate_node_types`. Template output
registration skips unknown types so it does not report the same error twice.

Child provenance in `_add_child_provenance` is first-write-wins: `setdefault`
preserves the innermost child location as diagnostics unwind through parents.
Warnings also propagate at runtime through
`WorkflowExecutor._propagate_child_parser_warnings`. Both paths must use
`format_child_provenance`, `node_id=d.node_id or step_id`, and the same first-write
semantics so siblings remain distinct while duplicate propagation collapses.

## data_flow.py

`validate_data_flow()` is shared by pre-execution and compiler validation. Cache
structure and prompt-body overlap checks belong in `_validate_cache_block`;
`analyze-cache` consumes that producer through `WorkflowValidator`, rather than
maintaining another validator.

**Pflow vs bash syntax:** `_PFLOW_VAR_RE` uses the runtime variable grammar to
recognize pflow references. Bash expansions such as `${var:-default}` are not
pflow dependencies. Keep positive grammar matching rather than rejecting every
`${...}` shape.

`check_inputs=True` checks undeclared workflow inputs. The compiler passes False
because its `initial_params` can contain values unavailable to this validator;
that difference must not become separate implementations of dependency rules.
