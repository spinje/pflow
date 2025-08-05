"""Tests for registry_helper utility.

Testing strategy:
- Test pure data extraction functions
- Test edge cases (missing nodes, empty registry)
- No mocking needed - these are pure functions
- Use fixture data from conftest.py
"""

from pflow.planning.utils.registry_helper import get_node_inputs, get_node_interface, get_node_outputs


class TestGetNodeInterface:
    """Test get_node_interface function."""

    def test_returns_interface_for_existing_node(self, test_registry_data):
        """Test that interface is returned for existing node type."""
        interface = get_node_interface("read-file", test_registry_data)

        assert interface == {
            "inputs": [{"key": "file_path", "type": "str", "description": "Path to file"}],
            "outputs": [{"key": "content", "type": "str", "description": "File contents"}],
            "params": [],
        }

    def test_returns_empty_dict_for_missing_node(self, test_registry_data):
        """Test that empty dict is returned for non-existent node type."""
        interface = get_node_interface("non-existent-node", test_registry_data)

        assert interface == {}

    def test_returns_empty_dict_for_empty_registry(self):
        """Test handling of empty registry."""
        interface = get_node_interface("any-node", {})

        assert interface == {}

    def test_handles_node_without_interface_key(self):
        """Test handling of node entry without interface key."""
        registry_data = {
            "broken-node": {
                "module": "pflow.nodes.broken",
                "class_name": "BrokenNode",
                # No 'interface' key
            }
        }

        interface = get_node_interface("broken-node", registry_data)

        assert interface == {}

    def test_preserves_interface_structure(self, test_registry_data):
        """Test that complex interface structure is preserved."""
        # Add a node with complex interface
        test_registry_data["complex-node"] = {
            "interface": {
                "inputs": [
                    {"key": "data", "type": "dict", "description": "Input data"},
                    {"key": "config", "type": "str", "optional": True},
                ],
                "outputs": [
                    {"key": "result", "type": "Any"},
                    {"key": "metadata", "type": "dict"},
                ],
                "params": [
                    {"key": "mode", "type": "str", "default": "fast"},
                    {"key": "timeout", "type": "int", "default": 30},
                ],
                "custom_field": "preserved",
            }
        }

        interface = get_node_interface("complex-node", test_registry_data)

        assert interface["custom_field"] == "preserved"
        assert len(interface["inputs"]) == 2
        assert interface["inputs"][1]["optional"] is True


class TestGetNodeOutputs:
    """Test get_node_outputs function."""

    def test_returns_outputs_for_existing_node(self, test_registry_data):
        """Test that outputs list is returned for existing node."""
        outputs = get_node_outputs("read-file", test_registry_data)

        assert outputs == [{"key": "content", "type": "str", "description": "File contents"}]

    def test_returns_empty_list_for_missing_node(self, test_registry_data):
        """Test that empty list is returned for non-existent node."""
        outputs = get_node_outputs("missing-node", test_registry_data)

        assert outputs == []

    def test_returns_empty_list_when_no_outputs_key(self):
        """Test handling of interface without outputs key."""
        registry_data = {
            "no-output-node": {
                "interface": {
                    "inputs": [{"key": "data", "type": "str"}],
                    "params": [],
                    # No 'outputs' key
                }
            }
        }

        outputs = get_node_outputs("no-output-node", registry_data)

        assert outputs == []

    def test_returns_multiple_outputs(self, test_registry_data):
        """Test node with multiple outputs."""
        outputs = get_node_outputs("llm", test_registry_data)

        assert len(outputs) == 1
        assert outputs[0]["key"] == "response"

    def test_preserves_output_metadata(self):
        """Test that all output metadata is preserved."""
        registry_data = {
            "detailed-node": {
                "interface": {
                    "outputs": [
                        {
                            "key": "result",
                            "type": "dict",
                            "description": "Processing result",
                            "schema": {"type": "object"},
                            "optional": False,
                        }
                    ]
                }
            }
        }

        outputs = get_node_outputs("detailed-node", registry_data)

        assert outputs[0]["schema"] == {"type": "object"}
        assert outputs[0]["optional"] is False


class TestGetNodeInputs:
    """Test get_node_inputs function."""

    def test_returns_inputs_for_existing_node(self, test_registry_data):
        """Test that inputs list is returned for existing node."""
        inputs = get_node_inputs("read-file", test_registry_data)

        assert inputs == [{"key": "file_path", "type": "str", "description": "Path to file"}]

    def test_returns_empty_list_for_missing_node(self, test_registry_data):
        """Test that empty list is returned for non-existent node."""
        inputs = get_node_inputs("missing-node", test_registry_data)

        assert inputs == []

    def test_returns_empty_list_when_no_inputs_key(self):
        """Test handling of interface without inputs key."""
        registry_data = {
            "no-input-node": {
                "interface": {
                    "outputs": [{"key": "data", "type": "str"}],
                    "params": [],
                    # No 'inputs' key
                }
            }
        }

        inputs = get_node_inputs("no-input-node", registry_data)

        assert inputs == []

    def test_returns_multiple_inputs(self):
        """Test node with multiple inputs."""
        registry_data = {
            "multi-input-node": {
                "interface": {
                    "inputs": [
                        {"key": "text", "type": "str", "description": "Input text"},
                        {"key": "config", "type": "dict", "description": "Configuration"},
                        {"key": "max_length", "type": "int", "optional": True},
                    ]
                }
            }
        }

        inputs = get_node_inputs("multi-input-node", registry_data)

        assert len(inputs) == 3
        assert inputs[0]["key"] == "text"
        assert inputs[1]["key"] == "config"
        assert inputs[2]["key"] == "max_length"
        assert inputs[2]["optional"] is True


class TestIntegration:
    """Test integration between helper functions."""

    def test_consistent_behavior_across_helpers(self, test_registry_data):
        """Test that all helpers work consistently with same data."""
        node_type = "read-file"

        interface = get_node_interface(node_type, test_registry_data)
        outputs = get_node_outputs(node_type, test_registry_data)
        inputs = get_node_inputs(node_type, test_registry_data)

        # Verify consistency
        assert outputs == interface.get("outputs", [])
        assert inputs == interface.get("inputs", [])

    def test_all_helpers_handle_missing_node_consistently(self, test_registry_data):
        """Test that all helpers return consistent empty values for missing node."""
        node_type = "non-existent"

        interface = get_node_interface(node_type, test_registry_data)
        outputs = get_node_outputs(node_type, test_registry_data)
        inputs = get_node_inputs(node_type, test_registry_data)

        assert interface == {}
        assert outputs == []
        assert inputs == []
