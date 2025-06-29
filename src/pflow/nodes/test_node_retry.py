"""Test node with retry capabilities."""

import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from typing import Any

from pocketflow import Node


class TestNodeRetry(Node):
    """
    Test node that inherits from Node for retry capabilities.

    This node demonstrates the retry pattern and how nodes
    with built-in retry logic should be structured.

    Interface:
    - Reads: shared["retry_input"]
    - Writes: shared["retry_output"]
    - Params: max_retries (default: 3)
    - Actions: default, retry_failed
    """

    def __init__(self) -> None:
        super().__init__(max_retries=3, wait=0.1)

    def prep(self, shared: dict) -> str:
        """Prepare input with retry context."""
        input_data = shared.get("retry_input", "test data")
        return str(input_data)

    def exec(self, input_data: str) -> str:
        """Process with potential for retry."""
        # Simulate work that might fail
        if hasattr(self, "cur_retry") and self.cur_retry < 2:
            # Simulate failure on first attempts
            raise RuntimeError("Simulated failure for testing")
        return f"Processed with retry support: {input_data}"

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        """Handle final failure after all retries."""
        return f"Failed after retries: {exc}"

    def post(self, shared: dict, prep_res: str, exec_res: str) -> str:
        """Store result and determine action."""
        shared["retry_output"] = exec_res
        if "Failed" in str(exec_res):
            return "retry_failed"
        return "default"
