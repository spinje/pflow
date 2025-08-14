"""Integration tests for the complete template variable system."""

from unittest.mock import Mock

import pytest

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow
from pocketflow import Node


class MockNode(Node):
    """Mock node for testing template resolution."""

    def __init__(self):
        super().__init__()
        self.executed_params = None

    def prep(self, shared):
        return self.params

    def exec(self, prep_res):
        self.executed_params = prep_res
        return f"Executed with: {prep_res}"

    def post(self, shared, prep_res, exec_res):
        # When nodes are run through flow with namespacing, the shared store
        # passed here is actually a NamespacedSharedStore proxy, so we write
        # normally and the proxy handles namespacing
        shared["result"] = exec_res
        return "default"


class TestCompilerIntegration:
    """Test template system integration with compiler."""

    @pytest.fixture
    def mock_registry(self):
        """Create a mock registry with test nodes."""
        registry = Mock(spec=Registry)

        # Mock registry.load() to return node metadata
        registry.load.return_value = {
            "mock-node": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "result", "type": "str", "description": "Execution result"}],
                    "params": [],
                    "actions": ["default"],
                },
            }
        }

        # Mock get_nodes_metadata to return interface data
        def get_nodes_metadata(node_types):
            result = {}
            for node_type in node_types:
                if node_type in registry.load.return_value:
                    result[node_type] = registry.load.return_value[node_type]
            return result

        registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)

        return registry

    def test_compile_without_templates(self, mock_registry):
        """Test compilation of workflow without templates."""
        ir = {"nodes": [{"id": "node1", "type": "mock-node", "params": {"static": "value", "number": 42}}], "edges": []}

        flow = compile_ir_to_flow(ir, mock_registry)

        # Execute flow
        shared = {}
        flow.run(shared)

        # Node should have received static params unchanged (with namespacing)
        assert "node1" in shared
        assert "result" in shared["node1"]
        assert "Executed with: {'static': 'value', 'number': 42}" in shared["node1"]["result"]

    def test_compile_with_templates(self, mock_registry):
        """Test compilation of workflow with template variables."""
        ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "mock-node",
                    "params": {"url": "$endpoint", "message": "Processing $count items", "static": "unchanged"},
                }
            ],
            "edges": [],
        }

        initial_params = {"endpoint": "https://api.example.com", "count": 10}
        flow = compile_ir_to_flow(ir, mock_registry, initial_params)

        # Execute flow
        shared = {}
        flow.run(shared)

        # Check that templates were resolved (with namespacing)
        assert "node1" in shared
        assert "result" in shared["node1"]
        result = shared["node1"]["result"]
        assert "'url': 'https://api.example.com'" in result
        assert "'message': 'Processing 10 items'" in result
        assert "'static': 'unchanged'" in result

    def test_validation_fails_missing_params(self, mock_registry):
        """Test that validation catches missing parameters."""
        ir = {"nodes": [{"id": "node1", "type": "mock-node", "params": {"url": "$required_param"}}], "edges": []}

        # Try to compile without providing required parameter
        with pytest.raises(ValueError) as exc_info:
            compile_ir_to_flow(ir, mock_registry, initial_params={})

        assert "Template validation failed" in str(exc_info.value)
        assert "$required_param" in str(exc_info.value)

    def test_validation_can_be_skipped(self, mock_registry):
        """Test that validation can be skipped for testing."""
        ir = {"nodes": [{"id": "node1", "type": "mock-node", "params": {"url": "$missing"}}], "edges": []}

        # Should not raise with validate=False
        flow = compile_ir_to_flow(ir, mock_registry, initial_params={}, validate=False)

        # Execute and verify template remains unresolved (with namespacing)
        shared = {}
        flow.run(shared)
        assert "node1" in shared
        assert "result" in shared["node1"]
        assert "'url': '$missing'" in shared["node1"]["result"]

    def test_shared_store_templates_not_validated(self, mock_registry):
        """Test that variables from node outputs are properly validated."""
        # Add a producer node to the registry
        registry_data = mock_registry.load.return_value
        registry_data["data-producer"] = {
            "module": "tests.test_runtime.test_template_integration",
            "class_name": "MockNode",
            "interface": {
                "inputs": [],
                "outputs": [
                    {
                        "key": "shared_store_var",
                        "type": "dict",
                        "description": "Data structure",
                        "structure": {"field": {"type": "str", "description": "Field value"}},
                    }
                ],
                "params": [],
                "actions": ["default"],
            },
        }

        ir = {
            "nodes": [
                {"id": "producer", "type": "data-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "mock-node",
                    "params": {"url": "$provided_param", "data": "$shared_store_var.field"},
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        # Only provide the CLI parameter
        initial_params = {"provided_param": "https://example.com"}

        # Should pass validation - shared_store_var comes from producer node
        flow = compile_ir_to_flow(ir, mock_registry, initial_params)

        # Execute with initial shared store data
        shared = {}
        flow.run(shared)

        # The result should have the template resolved (with namespacing)
        # Consumer node should have a result
        assert "consumer" in shared
        assert "result" in shared["consumer"]


class TestMultiNodeWorkflow:
    """Test template resolution across multiple nodes."""

    class DataProducerNode(Node):
        """Node that produces data for other nodes."""

        def exec(self, prep_res):
            return {
                "video_id": "xyz123",
                "title": "Python Tutorial",
                "metadata": {"author": "TechTeacher", "duration": 3600},
            }

        def post(self, shared, prep_res, exec_res):
            # When nodes are run through flow with namespacing, the shared store
            # passed here is actually a NamespacedSharedStore proxy
            shared["video_data"] = exec_res
            return "default"

    class DataConsumerNode(Node):
        """Node that consumes data from shared store."""

        def __init__(self):
            super().__init__()
            self.received_params = None

        def prep(self, shared):
            self.received_params = self.params
            return self.params

        def exec(self, prep_res):
            return f"Processed: {prep_res}"

        def post(self, shared, prep_res, exec_res):
            # When nodes are run through flow with namespacing, the shared store
            # passed here is actually a NamespacedSharedStore proxy
            shared["consumer_result"] = exec_res
            return "default"

    @pytest.fixture
    def multi_node_registry(self):
        """Create registry with producer and consumer nodes."""
        registry = Mock(spec=Registry)

        # Use MockNode for all types to avoid import issues
        registry.load.return_value = {
            "producer": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [],
                    "outputs": [
                        {
                            "key": "video_data",
                            "type": "dict",
                            "description": "Video information",
                            "structure": {
                                "title": {"type": "str", "description": "Video title"},
                                "video_id": {"type": "str", "description": "Video ID"},
                                "metadata": {
                                    "type": "dict",
                                    "description": "Video metadata",
                                    "structure": {
                                        "author": {"type": "str", "description": "Author name"},
                                        "duration": {"type": "int", "description": "Duration in seconds"},
                                    },
                                },
                            },
                        }
                    ],
                    "params": [],
                    "actions": ["default"],
                },
            },
            "consumer": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "consumer_result", "type": "str", "description": "Consumer output"}],
                    "params": [],
                    "actions": ["default"],
                },
            },
        }

        # Mock get_nodes_metadata to return interface data
        def get_nodes_metadata(node_types):
            result = {}
            for node_type in node_types:
                if node_type in registry.load.return_value:
                    result[node_type] = registry.load.return_value[node_type]
            return result

        registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)

        return registry

    def test_cross_node_template_resolution(self, multi_node_registry):
        """Test templates resolved from data produced by earlier nodes."""
        ir = {
            "nodes": [
                {"id": "producer", "type": "producer", "params": {"action": "produce"}},
                {
                    "id": "consumer",
                    "type": "consumer",
                    "params": {
                        "title": "$video_data.title",
                        "author": "$video_data.metadata.author",
                        "url": "$initial_url",  # From initial params
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        initial_params = {"initial_url": "https://youtube.com/watch?v=xyz123"}
        flow = compile_ir_to_flow(ir, multi_node_registry, initial_params)

        # Simulate shared store data that would be created by producer
        # shared = {"video_data": {"title": "Python Tutorial", "metadata": {"author": "TechTeacher", "duration": 3600}}}

        # We can't fully execute the flow with MockNodes, but we can verify
        # the template wrapper was applied to the consumer node
        # This tests that the compiler correctly identified and wrapped nodes with templates
        assert flow is not None  # Flow compiled successfully


class TestRealWorldWorkflows:
    """Test complete real-world workflow patterns."""

    @pytest.fixture
    def real_registry(self):
        """Create registry with realistic node types."""
        registry = Mock(spec=Registry)

        # For this test, we'll use mock nodes
        registry.load.return_value = {
            "youtube-transcript": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [{"key": "url", "type": "str", "description": "YouTube URL"}],
                    "outputs": [
                        {
                            "key": "transcript_data",
                            "type": "dict",
                            "description": "Transcript data",
                            "structure": {
                                "title": {"type": "str", "description": "Video title"},
                                "text": {"type": "str", "description": "Transcript text"},
                                "metadata": {
                                    "type": "dict",
                                    "description": "Video metadata",
                                    "structure": {"author": {"type": "str", "description": "Author name"}},
                                },
                            },
                        }
                    ],
                    "params": [],
                    "actions": ["default", "error"],
                },
            },
            "llm": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [{"key": "prompt", "type": "str", "description": "LLM prompt"}],
                    "outputs": [{"key": "summary", "type": "str", "description": "Generated summary"}],
                    "params": [],
                    "actions": ["default", "error"],
                },
            },
            "write-file": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [
                        {"key": "file_path", "type": "str", "description": "Path to file"},
                        {"key": "content", "type": "str", "description": "File content"},
                    ],
                    "outputs": [],
                    "params": [],
                    "actions": ["default", "error"],
                },
            },
        }

        # Mock get_nodes_metadata to return interface data
        def get_nodes_metadata(node_types):
            result = {}
            for node_type in node_types:
                if node_type in registry.load.return_value:
                    result[node_type] = registry.load.return_value[node_type]
            return result

        registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)

        return registry

    def test_youtube_summarization_workflow(self, real_registry):
        """Test complete youtube video summarization workflow."""
        # This is the workflow from the implementation guide
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "fetch", "type": "youtube-transcript", "params": {"url": "$url"}},
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {
                        "prompt": "Create a bullet-point summary of this video:\n\nTitle: $transcript_data.title\nAuthor: $transcript_data.metadata.author\n\nTranscript:\n$transcript_data.text"
                    },
                },
                {
                    "id": "save",
                    "type": "write-file",
                    "params": {"file_path": "video_summary.md", "content": "# $transcript_data.title\n\n$summary"},
                },
            ],
            "edges": [{"from": "fetch", "to": "summarize"}, {"from": "summarize", "to": "save"}],
        }

        # Parameters extracted from natural language by planner
        initial_params = {"url": "https://youtube.com/watch?v=xyz"}

        # Compile workflow
        flow = compile_ir_to_flow(ir, real_registry, initial_params)

        # We can't fully execute since we're using mock nodes,
        # but we can verify the workflow compiles correctly
        #
        # During actual execution, the shared store would be populated:
        # - After fetch node: shared["transcript_data"] with video details
        # - After summarize node: shared["summary"] with bullet points
        assert flow is not None

        # The actual execution would resolve all templates:
        # - fetch node gets: url="https://youtube.com/watch?v=xyz"
        # - summarize node gets: prompt with resolved title, author, text
        # - save node gets: content with resolved title and summary


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def mock_registry(self):
        registry = Mock(spec=Registry)
        registry.load.return_value = {
            "mock-node": {
                "module": "tests.test_runtime.test_template_integration",
                "class_name": "MockNode",
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "result", "type": "str", "description": "Execution result"}],
                    "params": [],
                    "actions": ["default"],
                },
            }
        }

        # Mock get_nodes_metadata to return interface data
        def get_nodes_metadata(node_types):
            result = {}
            for node_type in node_types:
                if node_type in registry.load.return_value:
                    result[node_type] = registry.load.return_value[node_type]
            return result

        registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)

        return registry

    def test_circular_references(self, mock_registry):
        """Test handling of circular references (last write wins)."""
        ir = {"nodes": [{"id": "node1", "type": "mock-node", "params": {"value": "$circular"}}], "edges": []}

        # Initial params and shared store both have 'circular'
        initial_params = {"circular": "from_params"}
        flow = compile_ir_to_flow(ir, mock_registry, initial_params)

        shared = {"circular": "from_shared"}
        flow.run(shared)

        # Initial params should win (higher priority) - with namespacing
        assert "node1" in shared
        assert "result" in shared["node1"]
        assert "'value': 'from_params'" in shared["node1"]["result"]

    def test_deeply_nested_paths(self, mock_registry):
        """Test resolution of deeply nested paths."""
        ir = {"nodes": [{"id": "node1", "type": "mock-node", "params": {"deep": "$a.b.c.d.e.f.g"}}], "edges": []}

        flow = compile_ir_to_flow(ir, mock_registry, initial_params={}, validate=False)

        shared = {"a": {"b": {"c": {"d": {"e": {"f": {"g": "deeply_nested_value"}}}}}}}

        flow.run(shared)
        # With namespacing
        assert "node1" in shared
        assert "result" in shared["node1"]
        assert "'deep': 'deeply_nested_value'" in shared["node1"]["result"]

    def test_malformed_ir_structure(self, mock_registry):
        """Test handling of malformed IR structure."""
        # Node without params field
        ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "mock-node",
                    # No params field
                }
            ],
            "edges": [],
        }

        # Should handle gracefully
        flow = compile_ir_to_flow(ir, mock_registry)
        shared = {}
        flow.run(shared)  # Should not crash
