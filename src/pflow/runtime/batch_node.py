"""Batch processing node using PocketFlow's BatchNode pattern.

This module provides PflowBatchNode, which wraps any pflow node to process
multiple items sequentially using isolated shared store contexts per item.

Key Design Decisions:
- **Inherits from BatchNode**: Gains per-item retry logic for free via MRO trick
- **Isolated context per item**: Each item gets `item_shared = dict(shared)` to prevent
  cross-item pollution and prepare for parallel execution in Phase 2
- **Error handling modes**: `fail_fast` (default) stops on first error; `continue`
  processes all items and collects errors separately

Usage:
    The compiler wraps batch-configured nodes with PflowBatchNode:
    ```python
    if batch_config := node_data.get("batch"):
        node = PflowBatchNode(node, node_id, batch_config)
    ```

IR Syntax:
    ```json
    {
      "id": "summarize",
      "type": "llm",
      "batch": {
        "items": "${list_files.files}",
        "as": "file",
        "error_handling": "continue"
      },
      "params": {"prompt": "Summarize: ${file}"}
    }
    ```

Output Structure:
    ```python
    shared["summarize"] = {
        "results": [...],      # Array of results in input order
        "count": 3,            # Total items processed
        "success_count": 2,    # Items without errors
        "error_count": 1,      # Items with errors
        "errors": [...]        # Error details (or None if no errors)
    }
    ```
"""

import logging
from typing import Any

from pocketflow import BatchNode

from pflow.runtime.template_resolver import TemplateResolver

logger = logging.getLogger(__name__)


class PflowBatchNode(BatchNode):
    """Batch node using PocketFlow's prep/exec/post lifecycle with isolated contexts.

    This class wraps any pflow node to process multiple items. Each item gets an
    isolated shallow copy of the shared store, ensuring items don't pollute each
    other while preserving references to mutable tracking objects like `__llm_calls__`.

    The MRO trick `super(BatchNode, self)._exec(item)` gives us per-item retry logic
    from Node._exec() for free:
        MRO: PflowBatchNode → BatchNode → Node → BaseNode → object

    Attributes:
        inner_node: The wrapped node to execute for each item
        node_id: Node identifier for namespacing outputs
        items_template: Template string to resolve items array (e.g., "${node.files}")
        item_alias: Variable name for current item in templates (default: "item")
        error_handling: Error mode - "fail_fast" or "continue"
    """

    def __init__(self, inner_node: Any, node_id: str, batch_config: dict[str, Any]):
        """Initialize batch node wrapper.

        Args:
            inner_node: The wrapped pflow node (already wrapped with Template/Namespace)
            node_id: Unique identifier for this node (used for namespacing results)
            batch_config: Batch configuration dict with keys:
                - items (required): Template reference to items array
                - as (optional): Variable name for current item (default: "item")
                - error_handling (optional): "fail_fast" or "continue" (default: "fail_fast")
        """
        super().__init__()  # Initialize params, successors from BaseNode
        self.inner_node = inner_node
        self.node_id = node_id
        self.items_template = batch_config["items"]
        self.item_alias = batch_config.get("as", "item")
        self.error_handling = batch_config.get("error_handling", "fail_fast")

        # Instance state for current batch execution
        self._shared: dict[str, Any] = {}
        self._errors: list[dict[str, Any]] = []

    def set_params(self, params: dict[str, Any]) -> None:
        """Forward params to inner node chain.

        This is critical: params must reach the TemplateAwareNodeWrapper
        so template variables like ${item} can be properly resolved at runtime.
        """
        super().set_params(params)  # Store on self for any direct access
        if hasattr(self.inner_node, "set_params"):
            self.inner_node.set_params(params)

    def prep(self, shared: dict[str, Any]) -> list[Any]:
        """Resolve items template and return items list.

        BatchNode will iterate over the returned list, calling exec() for each item.

        Args:
            shared: The workflow's shared store

        Returns:
            List of items to process

        Raises:
            ValueError: If items template doesn't resolve to a list
        """
        # Store shared reference for use in exec()
        self._shared = shared

        # Extract variable path from template: "${x.y}" -> "x.y"
        var_path = self.items_template.strip()[2:-1]

        # Resolve items from shared store
        items = TemplateResolver.resolve_value(var_path, shared)

        if items is None:
            raise ValueError(
                f"Batch items template '{self.items_template}' resolved to None. "
                f"Ensure the referenced node output exists."
            )

        if not isinstance(items, list):
            raise ValueError(
                f"Batch items must be an array, got {type(items).__name__}. "
                f"Template '{self.items_template}' resolved to: {items!r}"
            )

        logger.debug(
            f"Batch node '{self.node_id}' processing {len(items)} items",
            extra={"node_id": self.node_id, "item_count": len(items)},
        )

        return items

    def _extract_error(self, result: Any) -> str | None:
        """Extract error message from result dict if present.

        Nodes signal errors in two ways:
        1. Exceptions (caught by retry logic, then re-raised or handled by exec_fallback)
        2. Error key in result dict (e.g., {"error": "Error: Could not read file..."})

        Args:
            result: The result from exec() - typically a dict containing node outputs

        Returns:
            Error message string if error detected, None otherwise
        """
        if not isinstance(result, dict):
            return None
        error = result.get("error")
        if error:
            return str(error)
        return None

    def _exec(self, items: list[Any]) -> list[Any]:
        """Override to support error_handling: continue and detect errors in results.

        This override provides two layers of error detection:
        1. Exceptions raised during exec() - caught in try/except
        2. Error key in result dict - checked after successful exec()

        The MRO trick `super(BatchNode, self)._exec(item)` skips BatchNode._exec
        and calls Node._exec directly, giving us per-item retry logic.

        Args:
            items: List of items from prep()

        Returns:
            List of results in the same order as input items
        """
        self._errors = []
        results = []

        for i, item in enumerate(items):
            try:
                # super(BatchNode, self)._exec gives us per-item retry logic from Node._exec!
                # MRO: PflowBatchNode → BatchNode → Node → BaseNode
                # This calls Node._exec(item) which includes retry loop
                result = super(BatchNode, self)._exec(item)

                # Check if result indicates an error (node wrote to error key)
                error_msg = self._extract_error(result)
                if error_msg:
                    if self.error_handling == "fail_fast":
                        raise RuntimeError(f"Item {i} failed: {error_msg}")
                    self._errors.append({"index": i, "item": item, "error": error_msg})

                results.append(result)

            except Exception as e:
                if self.error_handling == "fail_fast":
                    raise
                self._errors.append({"index": i, "item": item, "error": str(e)})
                results.append(None)

        return results

    def exec(self, item: Any) -> dict[str, Any]:
        """Process a single item with isolated context.

        Called by Node._exec() with retry logic (via the MRO trick in _exec).

        This method:
        1. Creates isolated shallow copy of shared store
        2. Initializes empty namespace for this node
        3. Injects item alias at root level for template resolution
        4. Executes inner node with isolated context
        5. Captures and returns the node's namespace output

        Args:
            item: Single item from the items array

        Returns:
            Dict containing the inner node's outputs (entire namespace)
        """
        # Create isolated context - shallow copy shares mutable objects like __llm_calls__
        item_shared = dict(self._shared)

        # Initialize empty namespace for this node in the isolated context
        item_shared[self.node_id] = {}

        # Inject item alias at root level for template resolution
        # This makes ${item} or ${file} (custom alias) available
        item_shared[self.item_alias] = item

        # Execute inner node with isolated context
        # Inner node writes to item_shared[self.node_id] via NamespacedNodeWrapper
        self.inner_node._run(item_shared)

        # Capture result from inner node's namespace
        result = item_shared.get(self.node_id)
        if result is None:
            return {}
        if not isinstance(result, dict):
            return {"value": result}
        return result

    def post(self, shared: dict[str, Any], prep_res: list, exec_res: list) -> str:
        """Aggregate results into shared store.

        Counts successes by excluding:
        - None results (from exceptions with continue mode)
        - Results with error key (from nodes that wrote errors)

        Args:
            shared: The workflow's shared store
            prep_res: Items list from prep() (unused here but part of PocketFlow interface)
            exec_res: List of results from _exec()

        Returns:
            Action string ("default") for flow control
        """
        # Count successes: non-None results without error keys
        success_count = sum(
            1 for r in exec_res if r is not None and not self._extract_error(r)
        )

        # Write aggregated results to shared store
        shared[self.node_id] = {
            "results": exec_res,
            "count": len(exec_res),
            "success_count": success_count,
            "error_count": len(self._errors),
            "errors": self._errors if self._errors else None,
        }

        logger.debug(
            f"Batch node '{self.node_id}' completed: {success_count}/{len(exec_res)} successful",
            extra={
                "node_id": self.node_id,
                "success_count": success_count,
                "error_count": len(self._errors),
            },
        )

        return "default"
