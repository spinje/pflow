"""Echo node for testing and debugging workflows."""

import logging
from typing import Any, Optional

from pflow.pocketflow import Node

# Set up logging
logger = logging.getLogger(__name__)


class EchoNode(Node):
    """
    Simple echo node for testing workflows without side effects.

    This node echoes input values to output, making it perfect for:
    - Testing workflow execution
    - Debugging parameter passing
    - Verifying output handling
    - Testing without external dependencies

    Interface:
    - Params: message: str  # Message to echo (default: "Hello, World!")
    - Params: count: int  # Number of times to repeat (default: 1)
    - Params: data: Any  # Any data to pass through unchanged (optional)
    - Writes: shared["echo"]: str  # The echoed message
    - Writes: shared["data"]: Any  # The passed-through data (if provided)
    - Writes: shared["metadata"]: dict  # Information about the echo operation
        - original_message: str  # The original message before transformations
        - count: int  # Number of repetitions
        - modified: bool  # Whether the message was modified
    - Params: prefix: str  # Optional prefix for the message
    - Params: suffix: str  # Optional suffix for the message
    - Params: uppercase: bool  # Convert to uppercase (default: false)
    - Actions: default (always)
    """

    def __init__(self) -> None:
        """Initialize the echo node."""
        super().__init__()

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare echo operation."""
        # Get parameters with defaults
        message = self.params.get("message", "Hello, World!")
        count = self.params.get("count", 1)
        data = self.params.get("data")

        # Get params (these are only in params, not shared)
        prefix = self.params.get("prefix", "")
        suffix = self.params.get("suffix", "")
        uppercase = self.params.get("uppercase", False)

        logger.debug(
            "Preparing echo operation",
            extra={"message": message, "count": count, "has_data": data is not None, "phase": "prep"},
        )

        return {
            "message": message,
            "count": count,
            "data": data,
            "prefix": prefix,
            "suffix": suffix,
            "uppercase": uppercase,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute echo operation."""
        message = prep_res["message"]
        count = prep_res["count"]
        prefix = prep_res["prefix"]
        suffix = prep_res["suffix"]
        uppercase = prep_res["uppercase"]

        # Build the echo message
        full_message = f"{prefix}{message}{suffix}" if (prefix or suffix) else message

        # Repeat if count > 1
        if count > 1:
            full_message = " ".join([full_message] * count)

        # Apply uppercase if requested
        if uppercase:
            full_message = full_message.upper()

        logger.info(
            "Echo operation completed",
            extra={
                "original_length": len(message),
                "final_length": len(full_message),
                "modified": bool(prefix or suffix or uppercase or count > 1),
                "phase": "exec",
            },
        )

        return {
            "echo": full_message,
            "data": prep_res["data"],
            "metadata": {
                "original_message": message,
                "count": count,
                "modified": bool(prefix or suffix or uppercase or count > 1),
            },
        }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
        """Store echo results in shared store."""
        shared["echo"] = exec_res["echo"]
        shared["metadata"] = exec_res["metadata"]

        if exec_res["data"] is not None:
            shared["data"] = exec_res["data"]

        logger.debug(
            "Echo results stored",
            extra={"echo_length": len(exec_res["echo"]), "has_data": exec_res["data"] is not None, "phase": "post"},
        )

        return "default"
