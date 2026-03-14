"""Runtime component for executing workflows as sub-workflows."""

import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
from pflow.core.workflow_manager import WorkflowManager
from pflow.pocketflow import BaseNode
from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow
from pflow.runtime.template_resolver import TemplateResolver

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
    })

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Load the sub-workflow and prepare child inputs."""
        max_depth = self.params.get("max_depth", self.MAX_DEPTH_DEFAULT)

        # Check nesting depth
        current_depth = shared.get(f"{self.RESERVED_KEY_PREFIX}depth", 0)
        if current_depth >= max_depth:
            raise RecursionError(f"Maximum workflow nesting depth ({max_depth}) exceeded")

        execution_stack = shared.get(f"{self.RESERVED_KEY_PREFIX}stack", [])

        # Load the workflow (file, saved name, or inline IR)
        workflow_ir, workflow_path, workflow_source = self._load_workflow(shared, execution_stack)

        # Extract child inputs: all non-reserved params
        child_inputs = self._extract_child_inputs()
        child_params = self._resolve_child_inputs(child_inputs, shared)

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

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Compile and execute the sub-workflow."""
        workflow_ir = prep_res["workflow_ir"]
        workflow_path = prep_res["workflow_path"]
        workflow_source = prep_res.get("workflow_source", "unknown")
        child_params = prep_res["child_params"]
        storage_mode = prep_res["storage_mode"]
        parent_shared = prep_res.get("parent_shared", {})

        logger.debug(f"Executing sub-workflow from {workflow_source} (path: {workflow_path})")

        # Get registry (injected by compiler)
        registry = self.params.get("__registry__")
        if registry is not None and not isinstance(registry, Registry):
            registry = None

        try:
            sub_flow = compile_ir_to_flow(
                workflow_ir,
                registry=registry,  # type: ignore[arg-type]
                initial_params=child_params,
                validate=True,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to compile sub-workflow: {e!s}", "workflow_path": workflow_path}

        # Create child storage
        child_storage = self._create_child_storage(parent_shared, storage_mode, prep_res)

        try:
            result = sub_flow.run(child_storage)
            return {"success": True, "result": result, "child_storage": child_storage, "storage_mode": storage_mode}
        except Exception as e:
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

        # Auto-expose child outputs (skip for shared mode — child already wrote to parent)
        if exec_res.get("storage_mode") != "shared":
            child_storage = exec_res.get("child_storage", {})
            child_ir = prep_res.get("workflow_ir", {})
            child_declared_outputs = child_ir.get("outputs", {})

            if child_declared_outputs:
                # Child has ## Outputs — expose only declared outputs
                for output_name in child_declared_outputs:
                    if output_name in child_storage:
                        shared[output_name] = child_storage[output_name]
            else:
                # No declared outputs — expose all non-internal, non-input root keys
                child_input_keys = set(prep_res.get("child_params", {}).keys())
                for key, value in child_storage.items():
                    if key.startswith(("_pflow_", "__")):
                        continue
                    if key in child_input_keys:
                        continue
                    shared[key] = value

        # Return result action
        child_result = exec_res.get("result")
        return child_result if isinstance(child_result, str) else "default"

    @staticmethod
    def _is_file_reference(value: str) -> bool:
        """Determine if a workflow param value is a file path or saved name."""
        return "/" in value or "\\" in value or value.endswith(".pflow.md") or value.startswith(".")

    def _extract_child_inputs(self) -> dict[str, Any]:
        """Extract child workflow inputs from params (everything not reserved)."""
        return {
            key: value
            for key, value in self.params.items()
            if key not in self.RESERVED_PARAMS and not key.startswith("__")
        }

    def _resolve_child_inputs(self, child_inputs: dict[str, Any], shared: dict[str, Any]) -> dict[str, Any]:
        """Resolve template variables in child input values."""
        if not child_inputs:
            return {}

        context = dict(shared)
        resolved = {}
        for param_name, param_value in child_inputs.items():
            if isinstance(param_value, str) and TemplateResolver.has_templates(param_value):
                try:
                    resolved[param_name] = TemplateResolver.resolve_template(param_value, context)
                except Exception as e:
                    raise ValueError(f"Failed to resolve parameter '{param_name}': {e}") from e
            else:
                resolved[param_name] = param_value
        return resolved

    def _load_workflow(
        self, shared: dict[str, Any], execution_stack: list[str]
    ) -> tuple[dict[str, Any], Optional[Path], str]:
        """Load the workflow from file, saved name, or inline IR.

        Returns:
            (workflow_ir, workflow_path, workflow_source)
        """
        workflow = self.params.get("workflow")
        workflow_ir = self.params.get("workflow_ir")

        if not workflow and not workflow_ir:
            raise ValueError("WorkflowExecutor requires either 'workflow' or 'workflow_ir' parameter")
        if workflow and workflow_ir:
            raise ValueError("Only one of 'workflow' or 'workflow_ir' should be provided")

        workflow_path: Optional[Path] = None

        if workflow:
            if self._is_file_reference(workflow):
                logger.debug(f"Loading workflow from file: {workflow}")
                workflow_path = self._resolve_safe_path(workflow, shared)
                if str(workflow_path) in execution_stack:
                    cycle = " -> ".join([*execution_stack, str(workflow_path)])
                    raise ValueError(f"Circular workflow reference detected: {cycle}")
                workflow_ir = self._load_workflow_file(workflow_path)
                workflow_source = f"ref:{workflow}"
            else:
                logger.debug(f"Loading workflow by name: {workflow}")
                workflow_manager = WorkflowManager()
                try:
                    workflow_ir = workflow_manager.load_ir(workflow)
                    workflow_path = Path(workflow_manager.get_path(workflow))
                    if str(workflow_path) in execution_stack:
                        cycle = " -> ".join([*execution_stack, str(workflow_path)])
                        raise ValueError(f"Circular workflow reference detected: {cycle}")
                except Exception as e:
                    raise ValueError(f"Failed to load workflow '{workflow}': {e!s}") from e
                workflow_source = f"name:{workflow}"
        else:
            logger.debug("Using inline workflow definition")
            workflow_source = "inline"

        if workflow_ir is None:
            raise ValueError("WorkflowExecutor requires either 'workflow' or 'workflow_ir' parameter")
        if "nodes" not in workflow_ir:
            raise ValueError("Workflow IR must contain 'nodes' (use '## Steps' section in .pflow.md files)")

        return workflow_ir, workflow_path, workflow_source

    def _resolve_safe_path(self, workflow_ref: str, shared: dict[str, Any]) -> Path:
        """Resolve workflow path, relative to parent workflow or CWD."""
        path = Path(workflow_ref)
        if not path.is_absolute():
            parent_file = shared.get(f"{self.RESERVED_KEY_PREFIX}workflow_file")
            base_dir = Path(parent_file).parent if parent_file else Path.cwd()
            path = base_dir / path
        return path.resolve()

    def _load_workflow_file(self, path: Path) -> dict[str, Any]:
        """Load and parse a .pflow.md workflow file."""
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {path}")

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            raise OSError(f"Error reading workflow file: {e}") from e

        try:
            result = parse_markdown(content)
        except MarkdownParseError as e:
            raise ValueError(f"Invalid workflow file {path}: {e}") from e

        workflow_ir = result.ir
        if "nodes" not in workflow_ir:
            raise ValueError(f"Workflow file {path} must contain a '## Steps' section with at least one node")
        return workflow_ir

    def _validate_child_params(
        self, workflow_ir: dict[str, Any], child_params: dict[str, Any], workflow_path: Any
    ) -> None:
        """Validate provided params against child workflow's declared inputs."""
        declared_inputs = workflow_ir.get("inputs", {})
        if not declared_inputs:
            return

        missing_required = []
        for input_name, input_spec in declared_inputs.items():
            has_default = "default" in input_spec
            if not has_default and input_name not in child_params:
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
        """Create storage for child workflow based on isolation mode."""
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

        if "__registry__" in parent_shared:
            child_storage["__registry__"] = parent_shared["__registry__"]

        return child_storage
