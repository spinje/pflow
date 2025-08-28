"""Template-aware node wrapper for transparent template resolution.

This module provides a wrapper that intercepts node execution to resolve
template variables in parameters. It's the runtime proxy that enables
pflow's "Plan Once, Run Forever" philosophy.
"""

import logging
from typing import Any, Optional

from .template_resolver import TemplateResolver

logger = logging.getLogger(__name__)


class TemplateAwareNodeWrapper:
    """Wraps nodes to provide transparent template resolution.

    This wrapper intercepts the node's _run() method to resolve template
    variables just before execution. It maintains complete transparency
    to the rest of the system - the wrapper behaves exactly like the
    wrapped node except for template resolution.

    This is the runtime proxy that enables "Plan Once, Run Forever".
    """

    def __init__(self, inner_node: Any, node_id: str, initial_params: Optional[dict[str, Any]] = None):
        """Initialize the wrapper.

        Args:
            inner_node: The actual node being wrapped
            node_id: Node identifier from IR (for debugging/tracking)
            initial_params: Parameters extracted by planner from natural language
                          These have higher priority than shared store values
        """
        self.inner_node = inner_node
        self.node_id = node_id  # Node ID for debugging purposes only
        self.initial_params = initial_params or {}  # From planner extraction
        self.template_params: dict[str, Any] = {}  # Params containing templates
        self.static_params: dict[str, Any] = {}  # Params without templates

    def set_params(self, params: dict[str, Any]) -> None:
        """Separate template params from static params.

        Called by PocketFlow when setting node parameters. We separate
        parameters containing templates from static ones for efficient
        resolution later.

        Args:
            params: Parameters to set on the node
        """
        self.template_params.clear()
        self.static_params.clear()

        for key, value in params.items():
            if TemplateResolver.has_templates(value):
                self.template_params[key] = value
                logger.debug(
                    f"Node '{self.node_id}' param '{key}' contains templates",
                    extra={"node_id": self.node_id, "param": key},
                )
            else:
                self.static_params[key] = value

        # Set only static params on inner node for now
        self.inner_node.set_params(self.static_params)

        logger.debug(
            f"Node '{self.node_id}' params categorized",
            extra={
                "node_id": self.node_id,
                "template_param_count": len(self.template_params),
                "static_param_count": len(self.static_params),
            },
        )

    def _run(self, shared: dict[str, Any]) -> Any:
        """Execute with template resolution.

        This is the key interception point. We resolve templates just
        before execution, using both the shared store (runtime data)
        and initial parameters (from planner).

        Args:
            shared: The shared store containing runtime data

        Returns:
            Result from the inner node's execution
        """
        # Skip resolution if no templates
        if not self.template_params:
            return self.inner_node._run(shared)

        logger.debug(
            f"Resolving {len(self.template_params)} template parameters for node '{self.node_id}'",
            extra={"node_id": self.node_id},
        )

        # Build resolution context: shared store + planner parameters
        # Planner parameters have higher priority (come second in update)
        context = dict(shared)  # Start with shared store data
        context.update(self.initial_params)  # Planner parameters override

        # Debug: Log context keys when we have template params
        if self.template_params and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Template resolution context for node '{self.node_id}' has keys: {list(context.keys())[:20]}",
                extra={"node_id": self.node_id, "initial_params_keys": list(self.initial_params.keys())},
            )

        # Resolve all template parameters
        resolved_params = {}
        for key, template in self.template_params.items():
            # Check if this is actually a template string or just a value
            if isinstance(template, str) and "${" in template:
                # It's a template string that needs resolution
                # Check if it's a simple variable reference like "${limit}"
                import re

                simple_var_match = re.match(r"^\$\{([^}]+)\}$", template)
                if simple_var_match:
                    # It's a simple variable reference, try to preserve type
                    var_name = simple_var_match.group(1)
                    resolved_value = TemplateResolver.resolve_value(var_name, context)
                    if resolved_value is not None:
                        # Use the resolved value with its original type preserved
                        resolved_params[key] = resolved_value
                    else:
                        # Variable not found, keep template as-is
                        resolved_params[key] = template
                        resolved_value = template
                else:
                    # Complex template with text around it, must be string
                    resolved_value = TemplateResolver.resolve_string(template, context)
                    resolved_params[key] = resolved_value
            else:
                # No template variables present, preserve original type!
                resolved_params[key] = template
                resolved_value = template

            if resolved_value != template:
                logger.debug(
                    f"Resolved param '{key}': '{template}' -> '{resolved_value}'",
                    extra={"node_id": self.node_id, "param": key},
                )
            else:
                # Check if it's actually an error or just no template variables
                if "$" in template:
                    logger.warning(
                        f"Template in param '{key}' could not be fully resolved: '{template}'",
                        extra={"node_id": self.node_id, "param": key},
                    )
                else:
                    # No template variables, this is fine
                    logger.debug(
                        f"Param '{key}' has no template variables: '{template}'",
                        extra={"node_id": self.node_id, "param": key},
                    )

        # Temporarily update inner node params with resolved values
        original_params = self.inner_node.params
        merged_params = {**self.static_params, **resolved_params}
        self.inner_node.params = merged_params

        try:
            # Execute with resolved params
            result = self.inner_node._run(shared)
            return result
        finally:
            # Restore original params (though node copy will be discarded)
            # This is defensive programming in case the node is reused
            self.inner_node.params = original_params

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to inner node.

        This makes the wrapper transparent - any attribute access
        not handled by the wrapper goes to the inner node.

        Args:
            name: Attribute name to access

        Returns:
            Attribute value from inner node
        """
        # Prevent infinite recursion during copy operations
        if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Get inner_node without triggering __getattr__ again
        inner = object.__getattribute__(self, "inner_node")
        return getattr(inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Handle attribute setting to maintain proxy transparency.

        We need to distinguish between wrapper's own attributes and
        attributes that should be set on the inner node.

        Args:
            name: Attribute name to set
            value: Value to set
        """
        # Define proxy's own attributes
        wrapper_attrs = {"inner_node", "node_id", "initial_params", "template_params", "static_params"}

        if name in wrapper_attrs:
            # Set on wrapper itself
            super().__setattr__(name, value)
        else:
            # Delegate to inner node
            setattr(self.inner_node, name, value)

    def __repr__(self) -> str:
        """String representation for debugging."""
        inner_repr = repr(self.inner_node)
        return f"TemplateAwareNodeWrapper({inner_repr}, node_id='{self.node_id}')"

    # Delegate PocketFlow operators
    def __rshift__(self, other: Any) -> Any:
        """Delegate >> operator to inner node."""
        return self.inner_node >> other

    def __sub__(self, action: str) -> Any:
        """Delegate - operator to inner node."""
        return self.inner_node - action
