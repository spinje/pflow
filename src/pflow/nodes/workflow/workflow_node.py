"""A node that executes another workflow as a sub-workflow."""

import json
from pathlib import Path
from typing import Any, Dict

from pflow.registry import Registry
from pflow.runtime import compile_ir_to_flow
from pflow.runtime.template_resolver import TemplateResolver
from pocketflow import BaseNode


class WorkflowNode(BaseNode):
    """Execute another workflow as a sub-workflow.

    This node enables workflow composition by loading and executing
    other workflows with controlled parameter passing and storage isolation.

    Inputs:
        - Any keys defined in param_mapping will be read from shared store

    Outputs:
        - Keys defined in output_mapping will be written to shared store

    Parameters:
        - workflow_ref (str): Path to workflow file (absolute or relative)
        - workflow_ir (dict): Inline workflow definition (alternative to ref)
        - param_mapping (dict): Map parent values to child parameters
        - output_mapping (dict): Map child outputs to parent keys
        - storage_mode (str): "mapped" (default), "scoped", "isolated", or "shared"
        - max_depth (int): Maximum nesting depth (default: 10)
        - error_action (str): Action to return on error (default: "error")

    Actions:
        - default: Workflow executed successfully
        - error: Workflow execution failed (or custom error_action)
    """

    # Class-level constants
    MAX_DEPTH_DEFAULT = 10
    RESERVED_KEY_PREFIX = "_pflow_"

    def prep(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Load and prepare the sub-workflow for execution."""
        # Get parameters with defaults
        workflow_ref = self.params.get("workflow_ref")
        workflow_ir = self.params.get("workflow_ir")
        max_depth = self.params.get("max_depth", self.MAX_DEPTH_DEFAULT)

        # Validate inputs
        if not workflow_ref and not workflow_ir:
            raise ValueError("Either 'workflow_ref' or 'workflow_ir' must be provided")
        if workflow_ref and workflow_ir:
            raise ValueError("Only one of 'workflow_ref' or 'workflow_ir' should be provided")

        # Check nesting depth
        current_depth = shared.get(f"{self.RESERVED_KEY_PREFIX}depth", 0)
        if current_depth >= max_depth:
            raise RecursionError(f"Maximum workflow nesting depth ({max_depth}) exceeded")

        # Track execution stack for circular dependency detection
        execution_stack = shared.get(f"{self.RESERVED_KEY_PREFIX}stack", [])

        # Load workflow
        workflow_path = None
        if workflow_ref:
            # Validate path security
            workflow_path = self._resolve_safe_path(workflow_ref, shared)

            # Check circular dependency
            if str(workflow_path) in execution_stack:
                cycle = " -> ".join(execution_stack + [str(workflow_path)])
                raise ValueError(f"Circular workflow reference detected: {cycle}")

            # Load workflow file
            workflow_ir = self._load_workflow_file(workflow_path)

        # Prepare child parameters
        param_mapping = self.params.get("param_mapping", {})
        child_params = self._resolve_parameter_mappings(param_mapping, shared)

        return {
            "workflow_ir": workflow_ir,
            "workflow_path": str(workflow_path) if workflow_path else "<inline>",
            "child_params": child_params,
            "storage_mode": self.params.get("storage_mode", "mapped"),
            "current_depth": current_depth,
            "execution_stack": execution_stack,
            "parent_shared": shared,  # Pass the parent shared storage
        }

    def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """Compile and execute the sub-workflow."""
        workflow_ir = prep_res["workflow_ir"]
        workflow_path = prep_res["workflow_path"]
        child_params = prep_res["child_params"]
        storage_mode = prep_res["storage_mode"]
        parent_shared = prep_res.get("parent_shared", {})

        # Get registry from node parameters (injected by compiler)
        registry = self.params.get("__registry__")
        if not isinstance(registry, Registry):
            # If no registry available, compilation might fail
            # Let the error propagate with clear message
            registry = None

        try:
            # Compile the sub-workflow
            sub_flow = compile_ir_to_flow(
                workflow_ir,
                registry=registry,  # type: ignore
                initial_params=child_params,
                validate=True,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to compile sub-workflow: {e!s}", "workflow_path": workflow_path}

        # Create appropriate storage for child
        child_storage = self._create_child_storage(
            parent_shared,  # Parent shared storage from prep_res
            storage_mode,
            prep_res,
        )

        try:
            # Execute the sub-workflow
            result = sub_flow.run(child_storage)

            return {"success": True, "result": result, "child_storage": child_storage, "storage_mode": storage_mode}
        except Exception as e:
            return {
                "success": False,
                "error": f"Sub-workflow execution failed: {e!s}",
                "workflow_path": workflow_path,
                "child_storage": child_storage,
            }

    def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any], exec_res: Dict[str, Any]) -> str:
        """Process results and update parent storage."""
        if not exec_res.get("success", False):
            # Handle failure
            error_msg = exec_res.get("error", "Unknown error")
            workflow_path = exec_res.get("workflow_path", "<unknown>")

            # Store error in shared storage
            shared["error"] = f"WorkflowNode failed at {workflow_path}: {error_msg}"

            # Return error action
            error_action = self.params.get("error_action", "error")
            return str(error_action) if error_action else "error"

        # Success - apply output mappings
        output_mapping = self.params.get("output_mapping", {})
        if output_mapping and exec_res.get("storage_mode") != "shared":
            child_storage = exec_res.get("child_storage", {})

            for child_key, parent_key in output_mapping.items():
                # Skip reserved keys
                if parent_key.startswith(self.RESERVED_KEY_PREFIX):
                    continue

                if child_key in child_storage:
                    shared[parent_key] = child_storage[child_key]

        # Return result action or default
        child_result = exec_res.get("result")
        if isinstance(child_result, str):
            return child_result
        return "default"

    def _resolve_safe_path(self, workflow_ref: str, shared: Dict[str, Any]) -> Path:
        """Resolve workflow path."""
        # Convert to Path object
        path = Path(workflow_ref)

        # If relative, resolve from parent workflow location
        if not path.is_absolute():
            parent_file = shared.get(f"{self.RESERVED_KEY_PREFIX}workflow_file")
            if parent_file:
                base_dir = Path(parent_file).parent
                path = base_dir / path
            else:
                # Resolve from current working directory
                path = Path.cwd() / path

        # Return resolved absolute path
        return path.resolve()

    def _load_workflow_file(self, path: Path) -> Dict[str, Any]:
        """Load workflow from file."""
        # Check file exists
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {path}")

        # Load and parse JSON
        try:
            with open(path) as f:
                workflow_ir = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in workflow file: {e}")
        except Exception as e:
            raise OSError(f"Error reading workflow file: {e}")

        # Basic validation
        if not isinstance(workflow_ir, dict):
            raise ValueError("Workflow must be a JSON object")
        if "nodes" not in workflow_ir:
            raise ValueError("Workflow must contain 'nodes' array")

        return workflow_ir

    def _resolve_parameter_mappings(self, param_mapping: Dict[str, Any], shared: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve parameter mappings using template resolution."""
        if not param_mapping:
            return {}

        # Build resolution context
        context = dict(shared)

        # Resolve each parameter
        resolved = {}
        for child_param, parent_value in param_mapping.items():
            if isinstance(parent_value, str) and TemplateResolver.has_templates(parent_value):
                # Resolve template
                try:
                    resolved[child_param] = TemplateResolver.resolve_string(parent_value, context)
                except Exception as e:
                    raise ValueError(f"Failed to resolve parameter '{child_param}': {e}")
            else:
                # Static value
                resolved[child_param] = parent_value

        return resolved

    def _create_child_storage(
        self, parent_shared: Dict[str, Any], storage_mode: str, prep_res: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create storage for child workflow based on isolation mode."""
        # Update depth and stack for child
        child_depth = prep_res["current_depth"] + 1
        child_stack = prep_res["execution_stack"] + [prep_res["workflow_path"]]
        child_storage: Dict[str, Any]

        if storage_mode == "mapped":
            # Only mapped parameters available
            child_storage = prep_res["child_params"].copy()

        elif storage_mode == "isolated":
            # Completely empty storage
            child_storage = {}

        elif storage_mode == "scoped":
            # Filtered view of parent storage
            prefix = self.params.get("scope_prefix", "child_")
            child_storage = {
                k[len(prefix) :]: v
                for k, v in parent_shared.items()
                if k.startswith(prefix) and not k.startswith(self.RESERVED_KEY_PREFIX)
            }
            # Also include mapped parameters
            child_storage.update(prep_res["child_params"])

        elif storage_mode == "shared":
            # Direct reference to parent storage (dangerous!)
            child_storage = parent_shared

        else:
            raise ValueError(f"Invalid storage_mode: {storage_mode}")

        # Always set execution context
        child_storage[f"{self.RESERVED_KEY_PREFIX}depth"] = child_depth
        child_storage[f"{self.RESERVED_KEY_PREFIX}stack"] = child_stack
        child_storage[f"{self.RESERVED_KEY_PREFIX}workflow_file"] = prep_res["workflow_path"]

        # Pass through registry if available
        if "__registry__" in parent_shared:
            child_storage["__registry__"] = parent_shared["__registry__"]

        return child_storage
