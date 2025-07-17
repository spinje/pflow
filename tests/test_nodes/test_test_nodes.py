"""Test the test nodes themselves to ensure they work correctly."""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.pflow.nodes.test_node import TestNode
from src.pflow.nodes.test_node_retry import TestNodeRetry
from src.pflow.nodes.test_node_structured import TestNodeStructured


class TestTestNode:
    """Test the basic TestNode functionality."""

    def test_basic_processing(self):
        """Test successful processing with input."""
        node = TestNode()
        shared = {"test_input": "hello world"}

        # Test full lifecycle
        prep_res = node.prep(shared)
        assert prep_res == "hello world"

        exec_res = node.exec(prep_res)
        assert exec_res == "Processed: hello world"

        action = node.post(shared, prep_res, exec_res)
        assert action == "default"
        assert shared["test_output"] == "Processed: hello world"

    def test_default_value_handling(self):
        """Test handling when input is missing."""
        node = TestNode()
        shared = {}  # No test_input

        # Test with run() method
        action = node.run(shared)
        assert action == "default"
        assert shared["test_output"] == "Processed: default value"

    def test_run_method(self):
        """Test using the run() convenience method."""
        node = TestNode()
        shared = {"test_input": "test data"}

        action = node.run(shared)
        assert action == "default"
        assert shared["test_output"] == "Processed: test data"


class TestTestNodeRetry:
    """Test the TestNodeRetry functionality."""

    def test_retry_behavior(self):
        """Test that retry logic works correctly."""
        node = TestNodeRetry()
        shared = {"retry_input": "test data"}

        # The node is designed to fail on first attempts
        action = node.run(shared)

        # After retries, it should succeed
        assert action == "default"
        assert "retry_output" in shared
        assert "Processed with retry support: test data" in shared["retry_output"]

    def test_max_retries_parameter(self):
        """Test that max_retries is properly configured."""
        node = TestNodeRetry()
        assert node.max_retries == 3
        assert node.wait == 0.1

    def test_retry_failed_action(self):
        """Test the retry_failed action path."""
        # This is tricky to test without modifying the node
        # The current implementation always succeeds after 2 retries
        # We'll test the post() method directly
        node = TestNodeRetry()
        shared = {}

        action = node.post(shared, "input", "Failed after retries: test error")
        assert action == "retry_failed"
        assert shared["retry_output"] == "Failed after retries: test error"

    def test_exec_fallback(self):
        """Test the exec_fallback method."""
        node = TestNodeRetry()
        result = node.exec_fallback("test input", RuntimeError("test error"))
        assert result == "Failed after retries: test error"


class TestTestNodeStructured:
    """Test the TestNodeStructured functionality."""

    def test_structured_output_generation(self):
        """Test that structured output is generated correctly."""
        node = TestNodeStructured()
        shared = {"user_id": "user-123"}

        # Test full lifecycle
        prep_res = node.prep(shared)
        assert prep_res == "user-123"

        exec_res = node.exec(prep_res)
        assert isinstance(exec_res, dict)
        assert "user_data" in exec_res
        assert "tags" in exec_res

        action = node.post(shared, prep_res, exec_res)
        assert action == "default"
        assert "user_data" in shared
        assert "tags" in shared

    def test_nested_data_structure(self):
        """Test the nested structure of user_data."""
        node = TestNodeStructured()
        shared = {"user_id": "test-456"}

        action = node.run(shared)
        assert action == "default"

        # Verify user_data structure
        user_data = shared["user_data"]
        assert user_data["id"] == "test-456"
        assert user_data["profile"]["name"] == "Test User"
        assert user_data["profile"]["email"] == "test@example.com"
        assert user_data["profile"]["age"] == 25
        assert user_data["preferences"]["theme"] == "dark"
        assert user_data["preferences"]["notifications"] is True

    def test_list_structure(self):
        """Test the list structure of tags."""
        node = TestNodeStructured()
        shared = {"user_id": "test-789"}

        action = node.run(shared)
        assert action == "default"

        # Verify tags structure
        tags = shared["tags"]
        assert isinstance(tags, list)
        assert len(tags) == 2
        assert tags[0]["name"] == "premium"
        assert tags[0]["color"] == "gold"
        assert tags[1]["name"] == "verified"
        assert tags[1]["color"] == "blue"

    def test_default_user_id(self):
        """Test behavior with no user_id provided."""
        node = TestNodeStructured()
        shared = {}  # No user_id

        action = node.run(shared)
        assert action == "default"
        assert shared["user_data"]["id"] == "test-user-123"
