"""Test node with structured outputs for testing structure parsing."""

import sys
from pathlib import Path

# Add pocketflow to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


from pocketflow import Node


class StructuredExampleNode(Node):
    """
    Test node that produces structured output data.

    This node demonstrates nested data structures in outputs
    for testing the structure parsing functionality.

    Interface:
    - Reads: shared["user_id"]: str  # User ID to fetch data for
    - Writes: shared["user_data"]: dict  # User information
        - id: str  # User ID
        - profile: dict  # User profile information
          - name: str  # Full name
          - email: str  # Email address
          - age: int  # Age in years
        - preferences: dict  # User preferences
          - theme: str  # UI theme preference
          - notifications: bool  # Email notifications enabled
    - Writes: shared["tags"]: list  # User tags
        - name: str  # Tag name
        - color: str  # Tag color
    - Actions: default
    """

    def prep(self, shared: dict) -> str:
        """Get user ID from shared store."""
        return str(shared.get("user_id", "test-user-123"))

    def exec(self, user_id: str) -> dict:
        """Generate structured test data."""
        return {
            "user_data": {
                "id": user_id,
                "profile": {"name": "Test User", "email": "test@example.com", "age": 25},
                "preferences": {"theme": "dark", "notifications": True},
            },
            "tags": [{"name": "premium", "color": "gold"}, {"name": "verified", "color": "blue"}],
        }

    def post(self, shared: dict, prep_res: str, exec_res: dict) -> str:
        """Store structured data in shared store."""
        shared["user_data"] = exec_res["user_data"]
        shared["tags"] = exec_res["tags"]
        return "default"
