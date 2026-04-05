"""Runtime component for executing workflows as sub-workflows."""

import copy
import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, format_child_provenance
from pflow.core.file_resolver import is_workflow_file_reference
from pflow.core.node import BaseNode
from pflow.registry import Registry
from pflow.runtime import CompilationError, compile_workflow

logger = logging.getLogger(__name__)


class WorkflowExecutor(BaseNode):
    """Runtime executor for nested workflow execution.

    Enables workflow composition by loading and executing other workflows
    with controlled parameter passing and storage isolation.

    Workflow nodes use the same syntax as any other node — non-reserved
    params are passed as child inputs, and child outputs are auto-exposed
    via the namespace system.

    Example .pflow.md syntax:
        ### process_title
        - type: workflow
        - workflow: ./child.pflow.md
        - text: ${document_title}
        - mode: title

    Downstream access: ${process_title.result}

    Parameters:
        - workflow (str): File path (.pflow.md) or saved workflow name
        - workflow_ir (dict): Inline workflow definition (via yaml code block)
        - storage_mode (str): "mapped" (default) or "shared"
        - max_depth (int): Maximum nesting depth (default: 10)
        - error_action (str): Action to return on error (default: "error")

    All other params are passed as child workflow inputs.

    Actions:
        - default: Workflow executed successfully
        - error: Workflow execution failed (or custom error_action)
    """

    MAX_DEPTH_DEFAULT = 10
    RESERVED_KEY_PREFIX = "_pflow_"

    # Params consumed by WorkflowExecutor itself, NOT passed to child
    RESERVED_PARAMS = frozenset({
        "workflow",
        "workflow_ir",
        "storage_mode",
        "max_depth",
        "error_action",
        "__registry__",
        "inputs",  # Framework key consumed by engine's template resolution, not a child input
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
    #   _callback__ |                                    | MCP server always None (NullOutput).
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
        """Load the sub-workflow and prepare child inputs."""
        max_depth = self.params.get("max_depth", self.MAX_DEPTH_DEFAULT)

        # Check nesting depth
        current_depth = shared.get(f"{self.RESERVED_KEY_PREFIX}depth", 0)
        if current_depth >= max_depth:
            raise RecursionError(f"Maximum workflow nesting depth ({max_depth}) exceeded")

        execution_stack = shared.get(f"{self.RESERVED_KEY_PREFIX}stack", [])

        # Cache file/name loaded IR for compile-once: same dict object = same id() = compile cache hit.
        # First batch item loads and caches. Subsequent items reuse the same IR object.
        # For parallel batch, each deep-copied instance starts without cache and loads independently.
        # DON'T cache inline IR — it comes from self.params["workflow_ir"] which may contain
        # per-item resolved templates (e.g., ${item} inside the child IR), producing a different
        # dict per item. Caching would freeze the first item's resolved values.
        cached_ir = getattr(self, "_cached_loaded_ir", None)
        if cached_ir is not None:
            workflow_ir, workflow_path, workflow_source, parser_warnings = cached_ir
        else:
            workflow_ir, workflow_path, workflow_source, parser_warnings = self._load_workflow(shared, execution_stack)
            if workflow_source != "inline":
                self._cached_loaded_ir = (workflow_ir, workflow_path, workflow_source, parser_warnings)
        self._child_parser_warnings = list(parser_warnings)
        self._propagate_child_parser_warnings(shared)

        # Extract child inputs: all non-reserved params
        # Template resolution already handled by engine's _execute_single_node before prep() runs
        child_params = self._extract_child_inputs()

        # Validate child params against declared inputs
        self._validate_child_params(workflow_ir, child_params, workflow_path)

        return {
            "workflow_ir": workflow_ir,
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

        First call compiles and caches. Subsequent calls (batch items) reuse
        the cached CompiledWorkflow. For parallel batch, the batch executor
        pre-warms this cache before deep-copying, so each thread inherits
        the compiled workflow.

        Cache gate:
        - Non-inline workflows (_cached_loaded_ir exists): return cache unconditionally.
          After deepcopy, the IR dict has a new id() but the content is identical.
          _cached_loaded_ir is the signal that the workflow came from a file/name source.
        - Inline workflows (_cached_loaded_ir absent): check id(workflow_ir) match.
          Inline IR may contain parent-resolved templates (e.g., ${item}) that produce
          a different dict per batch item. id() match means the same dict object,
          which means sequential reuse is safe. Different id() means recompile.

        CompilationError always propagates — it means the workflow definition
        is broken, not the data.
        """
        from pflow.runtime.engine.types import CompiledWorkflow

        # Compile-once cache
        cached: Optional[CompiledWorkflow] = getattr(self, "_cached_workflow", None)
        if cached is not None:
            # Non-inline (file/name): always reuse. _cached_loaded_ir is set only for
            # non-inline sources. Content is identical across items — only the dict
            # object identity differs after deepcopy.
            if getattr(self, "_cached_loaded_ir", None) is not None:
                return cached
            # Inline: reuse only if same dict object (id match).
            cached_ir_id: Optional[int] = getattr(self, "_cached_workflow_ir_id", None)
            if cached_ir_id is not None and cached_ir_id == id(workflow_ir):
                return cached

        registry = self.params.get("__registry__")
        if registry is not None and not isinstance(registry, Registry):
            registry = None

        try:
            compiled = compile_workflow(
                copy.deepcopy(workflow_ir),  # Protect against concurrent mutation in parallel batch
                registry=registry or Registry(),
                initial_params=dict(child_params),  # Copy — don't mutate caller's dict
            )
        except CompilationError as e:
            if not e.details:
                e.details = {}
            e.details["sub_workflow_path"] = str(workflow_path)
            raise
        except Exception as e:
            raise CompilationError(
                f"Failed to compile sub-workflow at {workflow_path}: {e!s}",
                phase="sub_workflow_compilation",
                details={"sub_workflow_path": str(workflow_path)},
                suggestion=getattr(e, "suggestion", None),
            ) from e

        # Cache for compile-once
        self._cached_workflow = compiled
        self._cached_workflow_ir_id = id(workflow_ir)
        return compiled

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Compile and execute the sub-workflow."""
        from pflow.runtime.engine import WorkflowEngine

        workflow_ir = prep_res["workflow_ir"]
        workflow_path = prep_res["workflow_path"]
        workflow_source = prep_res.get("workflow_source", "unknown")
        child_params = prep_res["child_params"]
        storage_mode = prep_res["storage_mode"]
        parent_shared = prep_res.get("parent_shared", {})

        # Ensure child workflow can resolve file references relative to its own location
        if workflow_path and workflow_path != "<inline>":
            child_params["_pflow_workflow_file"] = str(Path(workflow_path).resolve())

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

        # Initialize _child_trace_events (will be populated after engine runs)
        self._child_trace_events: list[dict[str, Any]] | None = None

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
        """
        if not getattr(self, "_child_parser_warnings", None):
            return
        from dataclasses import replace

        parser_diagnostics = shared.setdefault("__parser_diagnostics__", [])
        step_id = getattr(self, "node_id", None)
        for d in self._child_parser_warnings:
            if step_id:
                parser_diagnostics.append(
                    replace(d, message=format_child_provenance(step_id, d.message), node_id=step_id)
                )
            else:
                parser_diagnostics.append(d)

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
        child_ir = prep_res.get("workflow_ir", {})
        child_declared_outputs = child_ir.get("outputs", {})

        if child_declared_outputs:
            for output_name in child_declared_outputs:
                if output_name in child_storage:
                    shared[output_name] = child_storage[output_name]
            return

        child_input_keys = set(prep_res.get("child_params", {}).keys())
        for key, value in child_storage.items():
            if key.startswith(("_pflow_", "__")):
                continue
            if key in child_input_keys:
                continue
            shared[key] = value

    @staticmethod
    def _extract_child_error(child_storage: dict[str, Any], workflow_path: str) -> str:
        """Extract a meaningful error message from child storage after sub-workflow failure.

        When a sub-workflow's Flow returns "error" action (not an exception), the actual
        error message is namespaced under the failed node's ID in child_storage.
        """
        failed_node = child_storage.get("__execution__", {}).get("failed_node")
        if failed_node:
            # Check namespaced node error (e.g., node's own post() set shared["error"])
            node_data = child_storage.get(failed_node)
            if isinstance(node_data, dict):
                error = node_data.get("error")
                if error:
                    return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {error}"
            # Check warnings (e.g., routing failures, API warnings)
            warning = child_storage.get("__warnings__", {}).get(failed_node)
            if warning:
                return f"Sub-workflow failed at {workflow_path} (node '{failed_node}'): {warning}"
        return f"Sub-workflow failed at {workflow_path} (returned error action)"

    def _extract_child_inputs(self) -> dict[str, Any]:
        """Extract child workflow inputs from params (everything not reserved)."""
        return {
            key: value
            for key, value in self.params.items()
            if key not in self.RESERVED_PARAMS and not key.startswith("__")
        }

    def _load_workflow(
        self, shared: dict[str, Any], execution_stack: list[str]
    ) -> tuple[dict[str, Any], Optional[Path], str, list[Diagnostic]]:
        """Load the workflow from file, saved name, or inline IR.

        Returns:
            (workflow_ir, workflow_path, workflow_source, parser_warnings)
        """
        from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow

        workflow = self.params.get("workflow")
        workflow_ir = self.params.get("workflow_ir")

        if not workflow and not workflow_ir:
            raise ValueError("WorkflowExecutor requires either 'workflow' or 'workflow_ir' parameter")
        if workflow and workflow_ir:
            raise ValueError("Only one of 'workflow' or 'workflow_ir' should be provided")

        # Determine base_path for relative file resolution
        parent_file = shared.get(f"{self.RESERVED_KEY_PREFIX}workflow_file")
        base_path = Path(parent_file).parent if parent_file else Path.cwd()

        # Use shared resolver
        result = resolve_sub_workflow(self.params, base_path=base_path)

        if result is None:
            # Template references (${...}) return None from resolver — give a clear error
            if isinstance(workflow, str) and "${" in workflow:
                raise ValueError(f"Cannot execute sub-workflow with unresolved template reference: '{workflow}'")
            raise ValueError("WorkflowExecutor requires either 'workflow' or 'workflow_ir' parameter")

        workflow_ir = result.ir
        workflow_path = result.path

        # Cycle detection (executor-specific: uses runtime execution stack)
        if workflow_path:
            self._check_workflow_cycle(workflow_path, execution_stack)

        # Determine source label for tracing
        if isinstance(self.params.get("workflow_ir"), dict):
            workflow_source = "inline"
        elif workflow_path and is_workflow_file_reference(workflow or ""):
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
        """Validate provided params against child workflow's declared inputs."""
        declared_inputs = workflow_ir.get("inputs", {})
        if not declared_inputs:
            return

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
            path_str = workflow_path if workflow_path else "<inline>"
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
