"""Tests for Pydantic IR models.

Testing strategy:
- Test validation rules (pattern matching, required fields)
- Test alias handling for EdgeIR
- Test to_dict conversion
- Test edge cases and error handling
"""

import pytest
from pydantic import ValidationError

from pflow.planning.ir_models import EdgeIR, FlowIR, NodeIR


class TestNodeIR:
    """Test NodeIR model validation."""

    def test_valid_node_creation(self, tmp_path):
        """Test creating a valid NodeIR."""
        test_file = tmp_path / "test.txt"
        node = NodeIR(
            id="test-node",
            type="read-file",
            purpose="Read test file content for validation",
            params={"path": str(test_file)},
        )

        assert node.id == "test-node"
        assert node.type == "read-file"
        assert node.params == {"path": str(test_file)}

    def test_minimal_node_creation(self):
        """Test creating node with minimal required fields."""
        node = NodeIR(id="n1", type="test-node", purpose="Test node with minimal required fields")

        assert node.id == "n1"
        assert node.type == "test-node"
        assert node.params == {}  # Default empty dict

    def test_id_pattern_validation(self):
        """Test that id must match pattern."""
        # Valid IDs
        valid_ids = ["node1", "test-node", "test_node", "Node123", "a", "A-B_C"]
        for valid_id in valid_ids:
            node = NodeIR(id=valid_id, type="test", purpose="Validate ID pattern matching rules")
            assert node.id == valid_id

        # Invalid IDs
        invalid_ids = ["test node", "test@node", "test.node", "test/node", "", "test!"]
        for invalid_id in invalid_ids:
            with pytest.raises(ValidationError) as exc_info:
                NodeIR(id=invalid_id, type="test", purpose="Test invalid ID pattern validation")
            assert "id" in str(exc_info.value)

    def test_missing_required_fields(self):
        """Test that missing required fields raise validation errors."""
        # Missing id
        with pytest.raises(ValidationError) as exc_info:
            NodeIR(type="test-node", purpose="Test node missing id field")  # type: ignore[call-arg]
        assert "id" in str(exc_info.value)

        # Missing type
        with pytest.raises(ValidationError) as exc_info:
            NodeIR(id="n1", purpose="Test node missing type field")  # type: ignore[call-arg]
        assert "type" in str(exc_info.value)

        # Missing purpose
        with pytest.raises(ValidationError) as exc_info:
            NodeIR(id="n1", type="test-node")  # type: ignore[call-arg]
        assert "purpose" in str(exc_info.value)

    def test_params_can_be_complex(self):
        """Test that params can contain complex nested structures."""
        complex_params = {
            "string": "value",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": {"deeply": "value"}},
            "mixed": [{"a": 1}, {"b": 2}],
        }

        node = NodeIR(
            id="complex", type="test", purpose="Test complex nested parameter structures", params=complex_params
        )
        assert node.params == complex_params


class TestEdgeIR:
    """Test EdgeIR model validation and alias handling."""

    def test_valid_edge_creation_with_aliases(self):
        """Test creating edge using field aliases."""
        # Using aliases "from" and "to"
        edge = EdgeIR(**{"from": "node1", "to": "node2", "action": "success"})

        assert edge.from_node == "node1"
        assert edge.to_node == "node2"
        assert edge.action == "success"

    def test_valid_edge_creation_with_dict(self):
        """Test creating edge using dict with aliases."""
        # EdgeIR requires aliases in the input
        edge_data = {"from": "node1", "to": "node2", "action": "failed"}
        edge = EdgeIR(**edge_data)

        assert edge.from_node == "node1"
        assert edge.to_node == "node2"
        assert edge.action == "failed"

    def test_default_action(self):
        """Test that action defaults to 'default'."""
        edge = EdgeIR(**{"from": "n1", "to": "n2"})

        assert edge.action == "default"

    def test_missing_required_fields(self):
        """Test that missing required fields raise validation errors."""
        # Missing from
        with pytest.raises(ValidationError) as exc_info:
            EdgeIR(**{"to": "n2"})
        assert "from" in str(exc_info.value).lower()

        # Missing to
        with pytest.raises(ValidationError) as exc_info:
            EdgeIR(**{"from": "n1"})
        assert "to" in str(exc_info.value).lower()

    def test_alias_serialization(self):
        """Test that model_dump uses aliases."""
        edge = EdgeIR(**{"from": "n1", "to": "n2", "action": "custom"})
        dumped = edge.model_dump(by_alias=True)

        assert dumped == {"from": "n1", "to": "n2", "action": "custom"}

    def test_edge_with_empty_strings(self):
        """Test that empty strings are allowed for edge fields."""
        # Empty strings should be valid (though not practical)
        edge = EdgeIR(**{"from": "", "to": "", "action": ""})
        assert edge.from_node == ""
        assert edge.to_node == ""
        assert edge.action == ""


class TestFlowIR:
    """Test FlowIR model validation."""

    def test_valid_flow_creation(self):
        """Test creating a valid FlowIR."""
        nodes = [
            NodeIR(id="n1", type="read-file", purpose="Read input file for processing", params={"path": "input.txt"}),
            NodeIR(id="n2", type="write-file", purpose="Write processed output to file", params={"path": "output.txt"}),
        ]
        edges = [EdgeIR(**{"from": "n1", "to": "n2"})]

        flow = FlowIR(nodes=nodes, edges=edges, start_node="n1")

        assert flow.ir_version == "0.1.0"
        assert len(flow.nodes) == 2
        assert len(flow.edges) == 1
        assert flow.start_node == "n1"

    def test_minimal_flow_creation(self):
        """Test creating flow with minimal required fields."""
        nodes = [NodeIR(id="single", type="test", purpose="Single node for minimal flow test")]
        flow = FlowIR(nodes=nodes)

        assert flow.ir_version == "0.1.0"  # Default
        assert len(flow.nodes) == 1
        assert flow.edges == []  # Default empty list
        assert flow.start_node is None  # Optional

    def test_empty_nodes_validation(self):
        """Test that nodes list cannot be empty."""
        with pytest.raises(ValidationError) as exc_info:
            FlowIR(nodes=[])
        assert "at least 1 item" in str(exc_info.value).lower()

    def test_version_pattern_validation(self):
        """Test that ir_version must match semantic version pattern."""
        # Valid versions
        valid_versions = ["0.1.0", "1.0.0", "2.5.10", "999.999.999"]
        for version in valid_versions:
            flow = FlowIR(
                ir_version=version, nodes=[NodeIR(id="n", type="t", purpose="Test semantic version validation")]
            )
            assert flow.ir_version == version

        # Invalid versions
        invalid_versions = ["1.0", "1", "v1.0.0", "1.0.0-beta", "1.0.a"]
        for version in invalid_versions:
            with pytest.raises(ValidationError) as exc_info:
                FlowIR(
                    ir_version=version,
                    nodes=[NodeIR(id="n", type="t", purpose="Test invalid version pattern rejection")],
                )
            assert "ir_version" in str(exc_info.value)

    def test_task21_fields(self):
        """Test Task 21 fields: inputs and outputs."""
        inputs = {"file_path": {"type": "str", "description": "Input file"}}
        outputs = {"result": {"type": "dict", "description": "Processing result"}}

        flow = FlowIR(
            nodes=[NodeIR(id="n1", type="process", purpose="Process input data with specified parameters")],
            inputs=inputs,
            outputs=outputs,
        )

        assert flow.inputs == inputs
        assert flow.outputs == outputs

    def test_to_dict_method(self):
        """Test model_dump conversion for validation."""
        nodes = [
            NodeIR(
                id="read", type="read-file", purpose="Read file from templated input path", params={"path": "${input}"}
            ),
            NodeIR(id="write", type="write-file", purpose="Write data to output destination"),
        ]
        edges = [EdgeIR(**{"from": "read", "to": "write", "action": "success"})]

        flow = FlowIR(
            ir_version="1.0.0",
            nodes=nodes,
            edges=edges,
            start_node="read",
            inputs={"input": {"type": "str"}},
        )

        result = flow.model_dump(by_alias=True, exclude_none=True)

        # Check structure
        assert result["ir_version"] == "1.0.0"
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1
        assert result["start_node"] == "read"
        assert result["inputs"] == {"input": {"type": "str"}}

        # Check aliases are used
        assert result["edges"][0]["from"] == "read"
        assert result["edges"][0]["to"] == "write"
        assert "from_node" not in result["edges"][0]
        assert "to_node" not in result["edges"][0]

        # Check None values are excluded
        assert "outputs" not in result

    def test_to_dict_excludes_none_values(self):
        """Test that model_dump excludes None values."""
        flow = FlowIR(nodes=[NodeIR(id="n", type="t", purpose="Test None value exclusion in serialization")])
        result = flow.model_dump(by_alias=True, exclude_none=True)

        # Optional None fields should not be in output
        assert "start_node" not in result
        assert "inputs" not in result
        assert "outputs" not in result

        # Required fields should be present
        assert "ir_version" in result
        assert "nodes" in result
        assert "edges" in result  # Empty list, not None

    def test_complex_flow_structure(self):
        """Test flow with complex nested structure."""
        flow = FlowIR(
            ir_version="2.0.0",
            nodes=[
                NodeIR(
                    id="processor",
                    type="complex-processor",
                    purpose="Process data with complex nested configuration",
                    params={
                        "config": {"mode": "fast", "options": ["a", "b", "c"]},
                        "templates": {"greeting": "Hello {{name}}"},
                    },
                )
            ],
            edges=[],
            inputs={
                "data": {"type": "dict", "schema": {"type": "object"}},
                "options": {"type": "list", "items": {"type": "str"}},
            },
            outputs={"result": {"type": "Any", "optional": True}},
        )

        # Verify structure is preserved
        result = flow.model_dump(by_alias=True, exclude_none=True)
        assert result["nodes"][0]["params"]["config"]["mode"] == "fast"
        assert result["inputs"]["data"]["schema"] == {"type": "object"}


class TestModelInteraction:
    """Test interaction between models."""

    def test_flow_with_multiple_edges(self):
        """Test creating flow with multiple edges."""
        flow = FlowIR(
            nodes=[
                NodeIR(id="n1", type="t1", purpose="First node in multi-edge flow test"),
                NodeIR(id="n2", type="t2", purpose="Middle node in multi-edge flow test"),
                NodeIR(id="n3", type="t3", purpose="Final node in multi-edge flow test"),
            ],
            edges=[
                EdgeIR(**{"from": "n1", "to": "n2"}),
                EdgeIR(**{"from": "n2", "to": "n3"}),
            ],
        )

        # Both edges should work correctly
        assert flow.edges[0].from_node == "n1"
        assert flow.edges[0].to_node == "n2"
        assert flow.edges[1].from_node == "n2"
        assert flow.edges[1].to_node == "n3"

    def test_flow_to_dict_preserves_node_params(self):
        """Test that node params are preserved through model_dump."""
        flow = FlowIR(
            nodes=[
                NodeIR(
                    id="complex",
                    type="test",
                    purpose="Test preservation of all param value types",
                    params={
                        "null_value": None,
                        "empty_string": "",
                        "zero": 0,
                        "false": False,
                        "empty_list": [],
                        "empty_dict": {},
                    },
                )
            ]
        )

        result = flow.model_dump(by_alias=True, exclude_none=True)
        params = result["nodes"][0]["params"]

        # All values should be preserved, including falsy ones
        assert params["null_value"] is None
        assert params["empty_string"] == ""
        assert params["zero"] == 0
        assert params["false"] is False
        assert params["empty_list"] == []
        assert params["empty_dict"] == {}
