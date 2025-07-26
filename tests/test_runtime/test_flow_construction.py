"""Tests for flow construction functionality in the compiler module."""

from unittest.mock import Mock, patch

import pytest

from pflow.registry import Registry
from pflow.runtime.compiler import (
    CompilationError,
    _get_start_node,
    _instantiate_nodes,
    _wire_nodes,
    compile_ir_to_flow,
)
from pocketflow import BaseNode, Flow


class MockNode(BaseNode):
    """Mock node for testing without real implementations."""

    def __init__(self):
        super().__init__()
        self.connections = []  # Track connections for testing

    def __rshift__(self, other):
        """Override >> operator to track connections."""
        self.connections.append(("default", other))
        return super().__rshift__(other)

    def __sub__(self, action):
        """Override - operator to track action-based connections."""

        # Create a mock transition that tracks the connection
        class MockTransition:
            def __init__(self, source, action):
                self.source = source
                self.action = action

            def __rshift__(self, target):
                self.source.connections.append((self.action, target))
                return self.source.next(target, self.action)

        return MockTransition(self, action)


class TestInstantiateNodes:
    """Test the _instantiate_nodes helper function."""

    def test_instantiate_single_node(self):
        """Test instantiating a single node."""
        # Create IR with one node
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.return_value = MockNode

            # Call function
            nodes = _instantiate_nodes(ir_dict, mock_registry)

            # Verify
            assert len(nodes) == 1
            assert "node1" in nodes
            assert isinstance(nodes["node1"], MockNode)
            mock_import.assert_called_once_with("test-node", mock_registry)

    def test_instantiate_multiple_nodes(self):
        """Test instantiating multiple nodes."""
        # Create IR with multiple nodes
        ir_dict = {
            "nodes": [
                {"id": "node1", "type": "type-a"},
                {"id": "node2", "type": "type-b"},
                {"id": "node3", "type": "type-a"},  # Same type as node1
            ]
        }

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.return_value = MockNode

            # Call function
            nodes = _instantiate_nodes(ir_dict, mock_registry)

            # Verify
            assert len(nodes) == 3
            assert all(key in nodes for key in ["node1", "node2", "node3"])
            assert all(isinstance(node, MockNode) for node in nodes.values())
            assert mock_import.call_count == 3

    def test_instantiate_with_params(self):
        """Test instantiating nodes with parameters."""
        # Create IR with parameterized node
        ir_dict = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {"threshold": 0.5, "model": "gpt-4", "template": "$input_var"},
                }
            ]
        }

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            # Create a mock that tracks set_params calls
            mock_node = MockNode()
            mock_node.set_params = Mock()
            mock_import.return_value = lambda: mock_node

            # Call function
            nodes = _instantiate_nodes(ir_dict, mock_registry)

            # Verify
            assert len(nodes) == 1
            # When templates are present, node gets wrapped and only static params are set on inner node
            mock_node.set_params.assert_called_once_with({"threshold": 0.5, "model": "gpt-4"})

    def test_instantiate_import_error(self):
        """Test error handling when import fails."""
        # Create IR
        ir_dict = {"nodes": [{"id": "node1", "type": "bad-node"}]}

        # Mock registry and import failure
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.side_effect = CompilationError(
                "Node type 'bad-node' not found", phase="node_resolution", node_type="bad-node"
            )

            # Call function and expect error
            with pytest.raises(CompilationError) as exc_info:
                _instantiate_nodes(ir_dict, mock_registry)

            # Verify error has node_id added
            error = exc_info.value
            assert error.node_id == "node1"
            assert "bad-node" in str(error)

    def test_instantiate_empty_params(self):
        """Test that empty params dict is handled correctly."""
        # Create IR with empty params
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node", "params": {}}]}

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_node = MockNode()
            mock_node.set_params = Mock()
            mock_import.return_value = lambda: mock_node

            # Call function
            nodes = _instantiate_nodes(ir_dict, mock_registry)

            # Verify set_params not called for empty dict
            assert len(nodes) == 1
            mock_node.set_params.assert_not_called()


class TestWireNodes:
    """Test the _wire_nodes helper function."""

    def test_wire_default_connection(self):
        """Test wiring nodes with default (>>) connection."""
        # Create nodes
        node1 = MockNode()
        node2 = MockNode()
        nodes = {"node1": node1, "node2": node2}

        # Create edges
        edges = [{"source": "node1", "target": "node2"}]

        # Wire nodes
        _wire_nodes(nodes, edges)

        # Verify connection
        assert len(node1.connections) == 1
        assert node1.connections[0] == ("default", node2)

    def test_wire_action_connection(self):
        """Test wiring nodes with action-based (-) connection."""
        # Create nodes
        node1 = MockNode()
        node2 = MockNode()
        node3 = MockNode()
        nodes = {"node1": node1, "node2": node2, "node3": node3}

        # Create edges with actions
        edges = [
            {"source": "node1", "target": "node2", "action": "success"},
            {"source": "node1", "target": "node3", "action": "error"},
        ]

        # Wire nodes
        _wire_nodes(nodes, edges)

        # Verify connections
        assert len(node1.connections) == 2
        assert ("success", node2) in node1.connections
        assert ("error", node3) in node1.connections

    def test_wire_chain_connection(self):
        """Test wiring a chain of nodes."""
        # Create nodes
        node1 = MockNode()
        node2 = MockNode()
        node3 = MockNode()
        nodes = {"node1": node1, "node2": node2, "node3": node3}

        # Create chain edges
        edges = [
            {"source": "node1", "target": "node2"},
            {"source": "node2", "target": "node3"},
        ]

        # Wire nodes
        _wire_nodes(nodes, edges)

        # Verify connections
        assert len(node1.connections) == 1
        assert node1.connections[0] == ("default", node2)
        assert len(node2.connections) == 1
        assert node2.connections[0] == ("default", node3)

    def test_wire_missing_source_node(self):
        """Test error when edge references non-existent source."""
        # Create nodes
        nodes = {"node1": MockNode()}

        # Create edge with missing source
        edges = [{"source": "missing", "target": "node1"}]

        # Wire nodes and expect error
        with pytest.raises(CompilationError) as exc_info:
            _wire_nodes(nodes, edges)

        # Verify error details
        error = exc_info.value
        assert error.phase == "flow_wiring"
        assert error.node_id == "missing"
        assert "non-existent source node" in str(error)
        assert "Available nodes: node1" in error.suggestion

    def test_wire_missing_target_node(self):
        """Test error when edge references non-existent target."""
        # Create nodes
        nodes = {"node1": MockNode()}

        # Create edge with missing target
        edges = [{"source": "node1", "target": "missing"}]

        # Wire nodes and expect error
        with pytest.raises(CompilationError) as exc_info:
            _wire_nodes(nodes, edges)

        # Verify error details
        error = exc_info.value
        assert error.phase == "flow_wiring"
        assert error.node_id == "missing"
        assert "non-existent target node" in str(error)
        assert "Available nodes: node1" in error.suggestion

    def test_wire_empty_edges(self):
        """Test wiring with no edges."""
        # Create nodes
        nodes = {"node1": MockNode(), "node2": MockNode()}

        # Wire with empty edges
        _wire_nodes(nodes, [])

        # Verify no connections made
        assert len(nodes["node1"].connections) == 0
        assert len(nodes["node2"].connections) == 0


class TestGetStartNode:
    """Test the _get_start_node helper function."""

    def test_get_start_node_first_fallback(self):
        """Test using first node as start when no explicit start specified."""
        # Create nodes
        nodes = {"node1": MockNode(), "node2": MockNode()}

        # Create IR with nodes in specific order
        ir_dict = {"nodes": [{"id": "node2"}, {"id": "node1"}]}

        # Get start node
        start = _get_start_node(nodes, ir_dict)

        # Verify first node in IR is used
        assert start is nodes["node2"]

    def test_get_start_node_explicit(self):
        """Test using explicit start_node when specified."""
        # Create nodes
        nodes = {"node1": MockNode(), "node2": MockNode()}

        # Create IR with explicit start_node
        ir_dict = {"nodes": [{"id": "node1"}, {"id": "node2"}], "start_node": "node2"}

        # Get start node
        start = _get_start_node(nodes, ir_dict)

        # Verify explicit start is used
        assert start is nodes["node2"]

    def test_get_start_node_no_nodes(self):
        """Test error when no nodes exist."""
        # Empty nodes
        nodes = {}
        ir_dict = {"nodes": []}

        # Get start node and expect error
        with pytest.raises(CompilationError) as exc_info:
            _get_start_node(nodes, ir_dict)

        # Verify error
        error = exc_info.value
        assert error.phase == "start_detection"
        assert "Cannot create flow with no nodes" in str(error)

    def test_get_start_node_invalid_explicit(self):
        """Test error when explicit start_node doesn't exist."""
        # Create nodes
        nodes = {"node1": MockNode()}

        # Create IR with invalid start_node
        ir_dict = {"nodes": [{"id": "node1"}], "start_node": "missing"}

        # Get start node and expect error
        with pytest.raises(CompilationError) as exc_info:
            _get_start_node(nodes, ir_dict)

        # Verify error
        error = exc_info.value
        assert error.phase == "start_detection"
        assert "Could not determine start node" in str(error)


class TestCompileIrToFlow:
    """Test the main compile_ir_to_flow function."""

    def test_compile_simple_flow(self):
        """Test compiling a simple linear flow."""
        # Create IR
        ir_dict = {
            "nodes": [
                {"id": "input", "type": "input-node"},
                {"id": "process", "type": "process-node"},
                {"id": "output", "type": "output-node"},
            ],
            "edges": [
                {"source": "input", "target": "process"},
                {"source": "process", "target": "output"},
            ],
        }

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.return_value = MockNode

            # Compile
            flow = compile_ir_to_flow(ir_dict, mock_registry)

            # Verify
            assert isinstance(flow, Flow)
            assert flow.start_node is not None
            assert mock_import.call_count == 3

    def test_compile_with_actions(self):
        """Test compiling flow with action-based routing."""
        # Create IR with actions
        ir_dict = {
            "nodes": [
                {"id": "decide", "type": "decision-node"},
                {"id": "success", "type": "success-node"},
                {"id": "error", "type": "error-node"},
            ],
            "edges": [
                {"source": "decide", "target": "success", "action": "ok"},
                {"source": "decide", "target": "error", "action": "fail"},
            ],
        }

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.return_value = MockNode

            # Compile
            flow = compile_ir_to_flow(ir_dict, mock_registry)

            # Verify
            assert isinstance(flow, Flow)

    def test_compile_with_params(self):
        """Test compiling flow with node parameters."""
        # Create IR with params
        ir_dict = {
            "nodes": [
                {
                    "id": "llm",
                    "type": "llm-node",
                    "params": {"model": "gpt-4", "temperature": 0.7, "prompt": "Hello $name"},
                }
            ],
            "edges": [],
        }

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            # Track set_params calls
            mock_node = MockNode()
            mock_node.set_params = Mock()
            mock_import.return_value = lambda: mock_node

            # Compile (disable validation since we're testing param passing, not template validation)
            compile_ir_to_flow(ir_dict, mock_registry, validate=False)

            # Verify params were set (template params excluded from inner node)
            mock_node.set_params.assert_called_once()
            params = mock_node.set_params.call_args[0][0]
            assert params["model"] == "gpt-4"
            assert params["temperature"] == 0.7
            # Template param "prompt" is not passed to inner node

    def test_compile_string_input(self):
        """Test compiling from JSON string input."""
        # Create JSON string
        ir_json = '{"nodes": [{"id": "test", "type": "test-node"}], "edges": []}'

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.return_value = MockNode

            # Compile
            flow = compile_ir_to_flow(ir_json, mock_registry)

            # Verify
            assert isinstance(flow, Flow)

    def test_compile_invalid_json(self):
        """Test error on invalid JSON string."""
        # Invalid JSON
        ir_json = '{"nodes": [invalid json}'

        # Mock registry
        mock_registry = Mock(spec=Registry)

        # Compile and expect JSONDecodeError
        with pytest.raises(Exception) as exc_info:  # JSONDecodeError is a subclass of Exception
            compile_ir_to_flow(ir_json, mock_registry)

        # Verify it's a JSON error - check the type name
        assert exc_info.type.__name__ == "JSONDecodeError"

    def test_compile_validation_error(self):
        """Test error during IR validation."""
        # IR missing required fields
        ir_dict = {"edges": []}  # Missing nodes

        # Mock registry
        mock_registry = Mock(spec=Registry)

        # Compile and expect CompilationError
        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir_dict, mock_registry)

        # Verify
        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'nodes' key" in str(error)

    def test_compile_with_logging(self, caplog):
        """Test that compilation logs appropriate messages."""
        # Simple IR
        ir_dict = {"nodes": [{"id": "test", "type": "test-node"}], "edges": []}

        # Mock registry and import_node_class
        mock_registry = Mock(spec=Registry)
        with patch("pflow.runtime.compiler.import_node_class") as mock_import:
            mock_import.return_value = MockNode

            # Enable debug logging
            caplog.set_level("DEBUG")

            # Compile
            compile_ir_to_flow(ir_dict, mock_registry)

            # Verify logging
            log_messages = [record.message for record in caplog.records]
            assert any("Starting IR compilation" in msg for msg in log_messages)
            assert any("IR validated" in msg for msg in log_messages)
            assert any("Starting node instantiation" in msg for msg in log_messages)
            assert any("Starting node wiring" in msg for msg in log_messages)
            assert any("Identifying start node" in msg for msg in log_messages)
            assert any("Creating Flow object" in msg for msg in log_messages)
            assert any("Compilation successful" in msg for msg in log_messages)


# Integration test with real node
def test_compile_with_real_test_node():
    """Test compiling with actual test node from registry."""
    # Create real registry
    registry = Registry()

    # Check if test node exists
    nodes = registry.load()
    if "test-node" not in nodes:
        pytest.skip("Test node not found in registry")

    # Create IR with test node
    ir_dict = {
        "nodes": [
            {"id": "test1", "type": "test-node", "params": {"test_param": "value"}},
            {"id": "test2", "type": "test-node"},
        ],
        "edges": [{"source": "test1", "target": "test2"}],
    }

    # Compile
    flow = compile_ir_to_flow(ir_dict, registry)

    # Verify
    assert isinstance(flow, Flow)
    assert flow.start_node is not None
    # The actual test node should have the params set
    assert hasattr(flow.start_node, "params")
    assert flow.start_node.params.get("test_param") == "value"
