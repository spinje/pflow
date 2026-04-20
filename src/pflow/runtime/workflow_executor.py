"""Runtime component for executing workflows as sub-workflows."""

import copy
import logging
from pathlib import Path
from typing import Any, ClassVar, Optional

from pflow.core.diagnostic import Diagnostic, format_child_provenance
from pflow.core.exceptions import (
    MarkdownParseError,
    PflowError,
    WorkflowNotFoundError,
)
from pflow.core.file_resolver import is_workflow_file_reference
from pflow.core.ir_schema import normalize_ir, validate_ir
from pflow.core.node import BaseNode
from pflow.registry import Registry
from pflow.runtime import CompilationError, compile_workflow

# Exceptions from prep() that should dispatch through error_action rather than
# propagate. These are "per-child" failures — bad input shape, unresolvable ref,
# missing file — where one bad item shouldn't kill a batch of otherwise-valid
# items. CompilationError deliberately NOT included: a broken workflow
# definition is not recoverable by error routing.
_PREP_RECOVERABLE = (
    ValueError,
    RecursionError,
    FileNotFoundError,
    MarkdownParseError,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)


class WorkflowExecutor(BaseNode):
    """Runtime executor for nested workflow execution.

    Enables workflow composition by loading and executing other workflows
    with controlled parameter passing and storage isolation.

    Child inputs are passed via the ``inputs`` dict on the workflow node.
    Child outputs are auto-exposed via the namespace system.

    Example .pflow.md syntax:
        ### process_title
        - type: workflow
        - workflow: ./child.pflow.md
        - inputs:
            text: ${document_title}
            mode: title

    Downstream access: ``${process_title.result}``

    Parameters:
        - workflow (str): File path (.pflow.md) or saved workflow name
        - inputs (dict): Values to pass to the child's declared ``## Inputs``
        - storage_mode (str): "mapped" (default) or "shared"
        - max_depth (int): Maximum nesting depth (default: 10)
        - error_action (str): Action to return on error (default: "error")

    Actions:
        - default: Workflow executed successfully
        - error: Workflow execution failed (or custom error_action)
    """

    MAX_DEPTH_DEFAULT = 10
    RESERVED_KEY_PREFIX = "_pflow_"

    # Closed top-level schema for workflow nodes. The validator (Step 7) reads
    # this attribute to reject unknown top-level fields at parse time, matching
    # the closure Step 7 applies to every other node via Interface docstrings.
    # Framework-internal keys (``__registry__`` etc.) are compiler-injected into
    # params and never user-authored, so they don't need to appear here.
    ALLOWED_PARAMS: ClassVar[frozenset[str]] = frozenset({
        "workflow",
        "inputs",
        "error_action",
        "storage_mode",
        "max_depth",
    })

    # Cross-cutting infrastructure keys propagated from parent to child storage.
    # These are accumulators/resources that must flow through workflow boundaries,
    # NOT execution-scoped state (__execution__, __cache_hits__, __template_errors__).
    #
    # Propagation copies REFERENCES (not deep copies) — parent and child share the
    # same objects. Missing keys are silently skipped; all consumers use .get() with
    # defaults, so missing keys cause graceful degradation, never crashes.
    #
    # Key           | Producer                          | If missing
    # --------------|-----------------------------------|----------------------------------
    # __registry__  | compiler.py inject_special_params  | Child can't compile sub-workflows.
    #               | (into node params) AND propagated  | NOTE: dual path — WorkflowExecutor
    #               | via shared store for grandchildren  | reads from self.params (direct),
    #               |                                    | shared store copy is for grandchild
    #               |                                    | propagation only.
    # __progress__  | runner._initialize_shared_store()  | No progress display (silent).
    #   _callback__ |                                    | MCP server always None.
    # __mcp_pool__  | runner._initialize_shared_store()  | No connection reuse — each MCP call
    #               |                                    | creates a fresh connection.
    # __warnings__  | runner._initialize_shared_store()  | Self-healing: consumers create {} if
    #               |                                    | missing. NOTE: parent and child share
    #               |                                    | the SAME dict — child warnings appear
    #               |                                    | in parent's status determination.
    # __memo...__   | runner._initialize_shared_store()  | Memoization skipped (no caching).
    #               |                                    |
    # _trace_       | runner._compile_and_execute()      | No child trace collector created;
    #   collector   |                                    | sub-workflow events not captured.
    #               |                                    | NOTE: propagated for truthiness check
    #               |                                    | only — child creates its OWN collector
    #               |                                    | in exec(), not reusing parent's.
    #
    # NOT propagated (per-workflow, children get their own):
    #   __execution__       — node completion/failure tracking
    #   __cache_hits__      — per-workflow cache hit display
    #   __template_errors__ — per-workflow template error accumulation
    _PROPAGATED_KEYS = (
        "__registry__",
        "__progress_callback__",
        "__mcp_pool__",
        "__warnings__",
        "__parser_diagnostics__",
        "__memoization_cache__",
        "_trace_collector",
    )

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Load the sub-workflow and prepare child inputs.

        Per-child recoverable failures (bad input shape, unresolvable ref,
        missing file, circular ref, max-depth) are captured into a
        ``_prep_error`` marker so exec()/post() can dispatch them through
        ``error_action`` instead of raising. This keeps the semantic
        "any failure in this node routes via error_action" uniform across
        prep and exec — matching what the feature docstring promises.
        CompilationError is NOT caught: a broken child definition is not
        routable by error_action.
        """
        try:
            return self._prep_unsafe(shared)
        except _PREP_RECOVERABLE as e:
            # workflow_path: raw ref when present (helps the error message
            # even if resolution failed), "<unresolved>" otherwise.
            ref = self.params.get("workflow")
            path = ref if isinstance(ref, str) and ref else "<unresolved>"
            return {
                "_prep_error": str(e),
                "workflow_path": path,
            }

    def _prep_unsafe(self, shared: dict[str, Any]) -> dict[str, Any]:
        """The real prep body; raises on failure. Wrapped by prep()."""
        max_depth = self.params.get("max_depth", self.MAX_DEPTH_DEFAULT)

        # Check nesting depth
        current_depth = shared.get(f"{self.RESERVED_KEY_PREFIX}depth", 0)
        if current_depth >= max_depth:
            raise RecursionError(f"Maximum workflow nesting depth ({max_depth}) exceeded")

        execution_stack = shared.get(f"{self.RESERVED_KEY_PREFIX}stack", [])

        # IR load cache, keyed by raw workflow ref string (`self.params["workflow"]`).
        # Heterogeneous batches (`${item.workflow}` → different per-item refs) naturally
        # get different keys, so each item loads its own child IR. Homogeneous batches
        # (same ref across items) hit the cache and reuse the IR.
        raw_ref = self.params.get("workflow")
        if not isinstance(raw_ref, str) or not raw_ref:
            workflow_ir, workflow_path, workflow_source, parser_warnings = self._load_workflow(shared, execution_stack)
        else:
            cache = getattr(self, "_loaded_ir_cache", None)
            if cache is None:
                cache = {}
                self._loaded_ir_cache = cache
            entry = cache.get(raw_ref)
            if entry is not None:
                workflow_ir, workflow_path, workflow_source, parser_warnings = entry
            else:
                workflow_ir, workflow_path, workflow_source, parser_warnings = self._load_workflow(
                    shared, execution_stack
                )
                cache[raw_ref] = (workflow_ir, workflow_path, workflow_source, parser_warnings)
        self._child_parser_warnings = list(parser_warnings)
        self._propagate_child_parser_warnings(shared)

        # Extract child inputs from the ``inputs:`` dict param.
        # Template resolution already handled by engine's _execute_single_node before prep() runs.
        child_params = self._extract_child_inputs()

        # Validate child params against declared inputs
        self._validate_child_params(workflow_ir, child_params, workflow_path)

        return {
            "child_ir": workflow_ir,
            "workflow_path": str(workflow_path) if workflow_path else "<inline>",
            "workflow_source": workflow_source,
            "child_params": child_params,
            "storage_mode": self.params.get("storage_mode", "mapped"),
            "current_depth": current_depth,
            "execution_stack": execution_stack,
            "parent_shared": shared,
        }

    def _compile_sub_workflow(
        self,
        workflow_ir: dict[str, Any],
        workflow_path: str,
        child_params: dict[str, Any],
    ) -> Any:
        """Compile the sub-workflow with compile-once caching.

        Cache keyed by ``workflow_path`` (resolved file/name string).
        Heterogeneous batches where ``${item.workflow}`` varies per iteration
        naturally produce different cache keys per item, so each child compiles
        exactly once. Homogeneous batches hit the cache on item 2 onward.

        If the child has no on-disk path (saved name not backed by a file —
        an edge case), it is compiled without caching. Compilation is cheap
        relative to execution; skipping the cache for this rare case keeps
        the cache-key logic single-source-of-truth.

        CompilationError always propagates — it means the workflow definition
        is broken, not the data.
        """
        cache = getattr(self, "_compiled_workflow_cache", None)
        if cache is None:
            cache = {}
            self._compiled_workflow_cache = cache

        cacheable = bool(workflow_path) and workflow_path != "<inline>"
        if cacheable:
            cached = cache.get(workflow_path)
            if cached is not None:
                return cached

        registry = self.params.get("__registry__")
        if registry is not None and not isinstance(registry, Registry):
            registry = None

        compiled = self._validate_and_compile_child(workflow_ir, workflow_path, registry, child_params, cacheable)
        if cacheable:
            cache[workflow_path] = compiled
        return compiled

    @staticmethod
    def _validate_and_compile_child(
        workflow_ir: dict[str, Any],
        workflow_path: str,
        registry: Optional[Registry],
        child_params: dict[str, Any],
        cacheable: bool,
    ) -> Any:
        """Validate the child IR and compile it, wrapping errors with sub-workflow path.

        Template-referenced children (``workflow: ${var}``) skip parent-time
        ``validate_ir`` because the resolver returns None for ``${...}``. Running it
        here closes the bypass so every path to ``compile_workflow`` goes through
        schema validation — keeping S1 vocabulary enforcement uniform.
        ``normalize_ir`` mirrors the parent validator path (fills in
        ``ir_version``/``edges`` often omitted by programmatic and
        resolved-at-runtime IRs).
        """
        try:
            params = dict(child_params)  # Copy — don't mutate caller's dict
            if cacheable:
                params["_pflow_workflow_file"] = str(Path(workflow_path).resolve())
            normalize_ir(workflow_ir)
            validate_ir(workflow_ir)
            return compile_workflow(
                copy.deepcopy(workflow_ir),  # Protect against concurrent mutation in parallel batch
                registry=registry or Registry(),
                initial_params=params,
            )
        except CompilationError as e:
            if not e.details:
                e.details = {}
            e.details["sub_workflow_path"] = str(workflow_path)
            raise
        except PflowError as e:
            # Self-describing errors (e.g. SchemaValidationError from validate_ir)
            # already carry structured context — similar_names, available_fields,
            # suggestions_list — consumed by the unified renderer. Pass their
            # diagnostics through verbatim; CompilationError.to_diagnostics will
            # merge sub_workflow_path into each diagnostic's context.
            raise CompilationError(
                f"Failed to compile sub-workflow at {workflow_path}: {e!s}",
                phase="sub_workflow_compilation",
                details={"sub_workflow_path": str(workflow_path)},
                wrapped_diagnostics=e.to_diagnostics(),
            ) from e
        except Exception as e:
            raise CompilationError(
                f"Failed to compile sub-workflow at {workflow_path}: {e!s}",
                phase="sub_workflow_compilation",
                details={"sub_workflow_path": str(workflow_path)},
                suggestion=getattr(e, "suggestion", None),
            ) from e

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Compile and execute the sub-workflow."""
        from pflow.runtime.engine import WorkflowEngine

        # Reset per-run trace state BEFORE any early return. Sequential batch
        # reuses the same WorkflowExecutor instance across items; without this
        # unconditional reset, a prep-error item inherits the previous item's
        # child trace events (batch_executor reads `node._child_trace_events`
        # via getattr at _execute_batch_item). Parallel batch is unaffected
        # because workers deep-copy the node.
        self._child_trace_events: list[dict[str, Any]] | None = None

        # Prep captured a recoverable failure — surface it through the same
        # success=False dict shape exec's own failure paths use. post() then
        # dispatches error_action uniformly.
        if "_prep_error" in prep_res:
            return {
                "success": False,
                "error": prep_res["_prep_error"],
                "workflow_path": prep_res.get("workflow_path", "<unresolved>"),
                # No child workflow ever ran — compile/execute was short-circuited
                # by the prep failure. post()'s _expose_child_outputs() is skipped
                # on success=False so this empty dict is never consumed, but
                # keeping the key present preserves shape-compatibility with
                # exec's other failure return sites.
                "child_storage": {},
            }

        workflow_ir = prep_res["child_ir"]
        workflow_path = prep_res["workflow_path"]
        workflow_source = prep_res.get("workflow_source", "unknown")
        child_params = prep_res["child_params"]
        storage_mode = prep_res["storage_mode"]
        parent_shared = prep_res.get("parent_shared", {})

        logger.debug(f"Executing sub-workflow from {workflow_source} (path: {workflow_path})")

        # Create child trace collector for sub-workflow visibility
        parent_trace = parent_shared.get("_trace_collector")
        child_trace = None
        if parent_trace:
            from pflow.runtime.workflow_trace import WorkflowTraceCollector

            child_trace = WorkflowTraceCollector(workflow_name=str(workflow_path or "sub-workflow"))
            child_trace.enable_llm_interception = False

        # Compile (with compile-once caching)
        compiled = self._compile_sub_workflow(workflow_ir, workflow_path, child_params)

        # Create child storage
        child_storage = self._create_child_storage(parent_shared, storage_mode, prep_res)

        # Seed structural defaults (for inputs NOT provided by this item), then per-item values.
        # Only seed resolved_defaults keys absent from child_params — resolved_defaults may
        # contain coerced values from the first item's compilation (compile-once cache), and
        # those per-item coerced values must NOT leak to subsequent items.
        #
        # KNOWN LIMITATION (see #188): Per-item type coercion is lost. The old model ran
        # prepare_inputs() per item (via per-item recompilation), which coerced "7" → 7 for
        # int-typed inputs. The new compile-once model skips per-item coercion — child_params
        # contain raw values from template resolution (typically strings from CLI args).
        # This matters for sub-workflow inputs with declared numeric types. Most inputs are
        # strings in practice, and template resolution preserves upstream types.
        for k, v in compiled.resolved_defaults.items():
            if k not in child_params:
                child_storage[k] = v
        child_storage.update(child_params)

        engine = WorkflowEngine(trace_collector=child_trace)

        try:
            result = engine.run(compiled, child_storage)

            # Store child trace events for parent engine to embed in trace
            if child_trace and child_trace.events:
                self._child_trace_events = child_trace.events

            # Detect sub-workflow failure via action string
            if isinstance(result, str) and result.startswith("error"):
                error_msg = self._extract_child_error(child_storage, workflow_path)
                return {
                    "success": False,
                    "error": error_msg,
                    "workflow_path": workflow_path,
                    "child_storage": child_storage,
                }

            return {"success": True, "result": result, "child_storage": child_storage, "storage_mode": storage_mode}
        except Exception as e:
            if child_trace and child_trace.events:
                self._child_trace_events = child_trace.events
            return {
                "success": False,
                "error": f"Sub-workflow execution failed: {e!s}",
                "workflow_path": workflow_path,
                "child_storage": child_storage,
            }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Auto-expose child outputs and update parent storage."""
        if not exec_res.get("success", False):
            error_msg = exec_res.get("error", "Unknown error")
            workflow_path = exec_res.get("workflow_path", "<unknown>")
            shared["error"] = f"WorkflowExecutor failed at {workflow_path}: {error_msg}"
            error_action = self.params.get("error_action", "error")
            return str(error_action) if error_action else "error"

        self._expose_child_outputs(shared, prep_res, exec_res)

        # Return result action — "end" from inner workflow means normal
        # termination, map to "default" so it doesn't leak to parent engine
        child_result = exec_res.get("result")
        if not isinstance(child_result, str) or child_result == "end":
            return "default"
        return child_result

    def _propagate_child_parser_warnings(self, shared: dict[str, Any]) -> None:
        """Append parser diagnostics from the child workflow to the parent shared store.

        Adds the parent step's node_id as provenance so that:
        - Sibling children with identical parser warnings don't collapse during dedup
          (dedup identity includes node_id)
        - Display shows which step produced each warning
        - Structured JSON consumers see ``context['sub_workflow_step']`` (always)
          and ``context['sub_workflow_path']`` (when the child workflow was loaded
          by file path or registered name) — matching the validator path's
          ``_add_child_provenance`` policy so the two propagation paths produce
          equivalent diagnostics that deduplicate naturally.
        """
        if not getattr(self, "_child_parser_warnings", None):
            return
        from dataclasses import replace

        parser_diagnostics = shared.setdefault("__parser_diagnostics__", [])
        step_id = getattr(self, "node_id", None)
        workflow_ref = self.params.get("workflow")
        for d in self._child_parser_warnings:
            if not step_id:
                parser_diagnostics.append(d)
                continue
            new_context = dict(d.context or {})
            new_context.setdefault("sub_workflow_step", step_id)
            if isinstance(workflow_ref, str) and workflow_ref:
                new_context.setdefault("sub_workflow_path", workflow_ref)
            parser_diagnostics.append(
                replace(
                    d,
                    message=format_child_provenance(step_id, d.message),
                    node_id=d.node_id or step_id,
                    context=new_context,
                )
            )

    @staticmethod
    def is_exposable_child_key(key: object, child_input_keys: set[str]) -> bool:
        """Whether a child_storage key should be exposed to the parent's namespace.

        Shared predicate between runtime `_expose_child_outputs` and the dry-run
        planner's `_mirror_child_shared` (in `execution/plan.py`). Centralizing
        the rule here prevents drift: adding a new reserved prefix means
        updating one function, both consumers inherit. Non-string keys are
        skipped defensively — Python dicts use string keys in practice, but
        a non-string key from a rogue node would otherwise crash `startswith`.
        """
        if not isinstance(key, str):
            return False
        if key.startswith(("_pflow_", "__")):
            return False
        return key not in child_input_keys

    @staticmethod
    def _expose_child_outputs(
        shared: dict[str, Any],
        prep_res: dict[str, Any],
        exec_res: dict[str, Any],
    ) -> None:
        """Expose child workflow outputs unless child storage was shared directly."""
        if exec_res.get("storage_mode") == "shared":
            return

        child_storage = exec_res.get("child_storage", {})
        child_ir = prep_res.get("child_ir", {})
        child_declared_outputs = child_ir.get("outputs", {})

        if child_declared_outputs:
            for output_name in child_declared_outputs:
                if output_name in child_storage:
                    shared[output_name] = child_storage[output_name]
            return

        child_input_keys = set(prep_res.get("child_params", {}).keys())
        for key, value in child_storage.items():
            if WorkflowExecutor.is_exposable_child_key(key, child_input_keys):
                shared[key] = value

    @staticmethod
    def _extract_child_error(child_storage: dict[str, Any], workflow_path: str) -> str:
        """Extract a meaningful error message from child storage after sub-workflow failure.

        When a sub-workflow's Flow returns "error" action (not an exception), the actual
        error message is namespaced under the failed node's ID in child_storage.
        """
        from pflow.runtime.node_state import get_node_failure, get_node_output

        failed_node = child_storage.get("__execution__", {}).get("failed_node")
        if failed_node:
            failure = get_node_failure(child_storage, failed_node)
            if failure and failure.get("error"):
                return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {failure['error']}"
            node_data = get_node_output(child_storage, failed_node)
            if isinstance(node_data, dict):
                error = node_data.get("error")
                if error:
                    return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {error}"
            warning = child_storage.get("__warnings__", {}).get(failed_node)
            if warning:
                return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {warning}"
        return f"Sub-workflow failed at {workflow_path} (returned error action)"

    def _extract_child_inputs(self) -> dict[str, Any]:
        """Extract child workflow inputs from the ``inputs`` dict param.

        Raises ``ValueError`` if ``inputs:`` is set but not a dict — catches
        the "template resolved to the wrong shape" case that parse-time can't
        check (e.g. ``inputs: ${item}`` where ``item`` resolves to a list).
        ``None`` and missing keys are treated as no-inputs-provided.
        """
        inputs = self.params.get("inputs")
        if inputs is None:
            return {}
        if isinstance(inputs, dict):
            return dict(inputs)
        type_name = type(inputs).__name__
        raise ValueError(f"Workflow node's 'inputs:' resolved to {type_name}, expected dict of child inputs.")

    def _load_workflow(
        self, shared: dict[str, Any], execution_stack: list[str]
    ) -> tuple[dict[str, Any], Optional[Path], str, list[Diagnostic]]:
        """Load the workflow from file path or saved name.

        Returns:
            (workflow_ir, workflow_path, workflow_source, parser_warnings)
        """
        from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow

        workflow = self.params.get("workflow")

        if not workflow:
            raise ValueError("WorkflowExecutor requires a 'workflow' parameter (file path or saved name)")

        # Determine base_path for relative file resolution
        parent_file = shared.get(f"{self.RESERVED_KEY_PREFIX}workflow_file")
        base_path = Path(parent_file).parent if parent_file else Path.cwd()

        # Use shared resolver
        result = resolve_sub_workflow(self.params, base_path=base_path)

        if result is None:
            # Template references (${...}) return None from resolver — give a clear error
            if isinstance(workflow, str) and "${" in workflow:
                raise ValueError(f"Cannot execute sub-workflow with unresolved template reference: '{workflow}'")
            raise ValueError("WorkflowExecutor requires a 'workflow' parameter (file path or saved name)")

        workflow_ir = result.ir
        workflow_path = result.path

        # Cycle detection (executor-specific: uses runtime execution stack)
        if workflow_path:
            self._check_workflow_cycle(workflow_path, execution_stack)

        # Determine source label for tracing
        if workflow_path and is_workflow_file_reference(workflow or ""):
            workflow_source = f"ref:{workflow}"
        else:
            workflow_source = f"name:{workflow}"

        if "nodes" not in workflow_ir:
            raise ValueError("Workflow IR must contain 'nodes' (use '## Steps' section in .pflow.md files)")

        return workflow_ir, workflow_path, workflow_source, list(result.warnings)

    @staticmethod
    def _check_workflow_cycle(workflow_path: Path, execution_stack: list[str]) -> None:
        """Raise if loading ``workflow_path`` would create a cycle."""
        if str(workflow_path) in execution_stack:
            cycle = " -> ".join([*execution_stack, str(workflow_path)])
            raise ValueError(f"Circular workflow reference detected: {cycle}")

    def _validate_child_params(
        self, workflow_ir: dict[str, Any], child_params: dict[str, Any], workflow_path: Any
    ) -> None:
        """Validate provided params against child workflow's declared inputs.

        Checks both directions at runtime as defense-in-depth against programmatic
        callers that bypass the parse-time validator:
          * Missing required inputs → ``ValueError``.
          * Undeclared extras inside ``inputs:`` dict → ``ValueError``.

        Runs even when the child declares no inputs — in that case the
        missing-required loop is a natural no-op but the extras loop correctly
        rejects any provided keys (set(child_params) - set() = set(child_params)).
        Previously this method early-returned on empty declarations, which
        reopened the silent-drop class of bug for programmatic callers against
        children with no ``## Inputs`` section.
        """
        # ``or {}`` defends against programmatic callers that set inputs=None
        # explicitly. The schema (Step 1) rejects ``inputs: null`` from user-
        # authored IR cleanly, but bypass callers (MCP server, direct Python
        # API, tests constructing executors) skip validation — this is the
        # runtime defense-in-depth boundary that catches the leak.
        declared_inputs = workflow_ir.get("inputs") or {}
        path_str = workflow_path if workflow_path else "<unknown>"

        # Missing-required direction (pre-existing).
        missing_required = []
        for input_name, input_spec in declared_inputs.items():
            is_required = input_spec.get("required", True)
            has_default = "default" in input_spec
            if is_required and not has_default and input_name not in child_params:
                desc = input_spec.get("description", "")
                input_type = input_spec.get("type", "any")
                missing_required.append(
                    f"  - {input_name} ({input_type}): {desc}" if desc else f"  - {input_name} ({input_type})"
                )

        if missing_required:
            provided = list(child_params.keys()) if child_params else []
            msg_parts = [
                f"Child workflow '{path_str}' is missing required inputs:",
                *missing_required,
            ]
            if provided:
                msg_parts.append(f"You provided: {', '.join(provided)}")
            else:
                msg_parts.append("You provided no inputs.")
            all_input_names = list(declared_inputs.keys())
            msg_parts.append(f"Available inputs: {', '.join(all_input_names)}")
            raise ValueError("\n".join(msg_parts))

        # Undeclared-extras direction (symmetric to missing-required).
        extras = sorted(set(child_params.keys()) - set(declared_inputs.keys()))
        if extras:
            declared_names = sorted(declared_inputs.keys())
            msg_parts = [
                f"Child workflow '{path_str}' was passed undeclared input(s): {', '.join(extras)}.",
                f"The child declares: {', '.join(declared_names) if declared_names else '(none)'}.",
                "Either declare these inputs in the child's ## Inputs section, "
                "or remove them from this workflow node's inputs: dict.",
            ]
            raise ValueError("\n".join(msg_parts))

    def _create_child_storage(
        self, parent_shared: dict[str, Any], storage_mode: str, prep_res: dict[str, Any]
    ) -> dict[str, Any]:
        """Create storage for child workflow based on isolation mode.

        In "mapped" mode, child gets a fresh dict with only passed params.
        In "shared" mode, child uses parent storage directly (propagation is
        redundant but harmless — just re-assigns references to themselves).

        Propagated keys are SAME object references, not copies. This is
        intentional: __warnings__ accumulates across the full tree,
        __memoization_cache__ is a shared SQLite instance, etc.
        See _PROPAGATED_KEYS for the full contract.
        """
        child_depth = prep_res["current_depth"] + 1
        child_stack = [*prep_res["execution_stack"], prep_res["workflow_path"]]
        child_storage: dict[str, Any]

        if storage_mode == "mapped":
            child_storage = prep_res["child_params"].copy()
        elif storage_mode == "shared":
            child_storage = parent_shared
        else:
            raise ValueError(f"Invalid storage_mode: '{storage_mode}'. Use 'mapped' (default) or 'shared'.")

        # Always set execution context
        child_storage[f"{self.RESERVED_KEY_PREFIX}depth"] = child_depth
        child_storage[f"{self.RESERVED_KEY_PREFIX}stack"] = child_stack
        child_storage[f"{self.RESERVED_KEY_PREFIX}workflow_file"] = prep_res["workflow_path"]

        for key in self._PROPAGATED_KEYS:
            if key in parent_shared:
                child_storage[key] = parent_shared[key]

        return child_storage
