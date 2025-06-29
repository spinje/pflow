"""Test node for scanner validation."""

import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from pocketflow import BaseNode


class TestNode(BaseNode):
    """
    Example node for testing scanner functionality.

    This node demonstrates proper docstring format that will be
    extracted by the scanner. It includes multiple lines and
    special characters to test edge cases.

    Interface:
    - Reads: shared["test_input"]
    - Writes: shared["test_output"]
    - Actions: default, error
    """

    def prep(self, shared):
        """Prepare by reading input from shared store."""
        return shared.get("test_input", "default value")

    def exec(self, input_data):
        """Process the input (pure computation)."""
        return f"Processed: {input_data}"

    def post(self, shared, prep_res, exec_res):
        """Store result in shared store."""
        shared["test_output"] = exec_res
        # Return default action
        return "default"


class NotANode:
    """Regular class that should not be detected as a node."""

    def some_method(self):
        """This is not a node."""
        pass


class NoDocstringNode(BaseNode):
    # This node has no docstring to test edge case
    pass


class NamedNode(BaseNode):
    """Node with explicit name attribute."""

    name = "custom-name"

    def exec(self, prep_res):
        return "Named node executed"
