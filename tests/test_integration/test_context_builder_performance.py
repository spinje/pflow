"""Performance tests for context builder functions.

These tests verify that the context builder functions perform well under load
and with large amounts of data, ensuring they remain responsive for real-world usage.
"""

import time
from unittest.mock import Mock, patch

from pflow.planning.context_builder import (
    _format_structure_combined,
    build_discovery_context,
    build_planning_context,
)


class TestContextBuilderPerformance:
    """Test performance characteristics of context builder functions."""

    def test_discovery_context_large_registry_performance(self):
        """Test discovery context generation with large number of nodes."""
        # Create registry with 1000 mock nodes using names that trigger categorization
        large_registry = {}
        node_types = ["file", "llm", "git", "general"]
        for i in range(1000):
            node_type = node_types[i % len(node_types)]
            large_registry[f"{node_type}-node-{i:04d}"] = {
                "module": f"test.module.{i % 10}",  # 10 different modules
                "class_name": f"Node{i % 20}",  # 20 different classes
            }

        # Mock processed nodes to avoid actual imports
        processed_nodes = {}
        for i in range(1000):
            node_type = node_types[i % len(node_types)]
            node_name = f"{node_type}-node-{i:04d}"
            processed_nodes[node_name] = {
                "description": f"Test {node_type} node {i} for performance testing",
                "inputs": [{"key": "input", "type": "str", "description": "Input data"}],
                "outputs": [{"key": "output", "type": "str", "description": "Output data"}],
                "params": [{"key": "param", "type": "bool", "description": "Test parameter"}],
                "actions": ["default", "error"],
            }

        # Use context manager to ensure proper cleanup
        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (processed_nodes, 0)

            # Measure discovery context generation time
            start_time = time.time()
            discovery = build_discovery_context(registry_metadata=large_registry)
            discovery_time = time.time() - start_time

        # Should complete in reasonable time (< 2 seconds for 1000 nodes)
        assert discovery_time < 2.0, f"Discovery took {discovery_time:.2f}s, should be < 2.0s"

        # Should include all nodes in output
        assert "file-node-0500" in discovery
        assert "general-node-0999" in discovery

        # Should properly categorize nodes
        assert "File Operations" in discovery
        assert "AI/LLM Operations" in discovery
        assert "Git Operations" in discovery

        # Context size should be reasonable (< 500KB for 1000 nodes)
        context_size = len(discovery.encode("utf-8"))
        assert context_size < 500_000, f"Context size {context_size} bytes too large"

    def test_planning_context_performance_with_many_selected(self):
        """Test planning context with many selected components."""
        # Create registry with 100 nodes
        registry_metadata = {}
        for i in range(100):
            registry_metadata[f"node-{i:03d}"] = {"module": "test.module", "class_name": "TestNode"}

        # Select 50 nodes for planning
        selected_nodes = [f"node-{i:03d}" for i in range(50)]

        # Mock processed nodes with some having structures
        mock_process = Mock()
        processed_nodes = {}
        for i in range(100):
            outputs = [{"key": "output", "type": "str", "description": "Basic output"}]

            # Every 10th node has a complex structure
            if i % 10 == 0:
                outputs.append({
                    "key": "complex_data",
                    "type": "dict",
                    "description": "Complex structured data",
                    "structure": {
                        "id": {"type": "str", "description": "Record ID"},
                        "metadata": {
                            "type": "dict",
                            "description": "Record metadata",
                            "structure": {
                                "created": {"type": "str", "description": "Creation timestamp"},
                                "modified": {"type": "str", "description": "Modification timestamp"},
                                "tags": {
                                    "type": "list",
                                    "description": "Record tags",
                                    "structure": {
                                        "name": {"type": "str", "description": "Tag name"},
                                        "value": {"type": "str", "description": "Tag value"},
                                    },
                                },
                            },
                        },
                    },
                })

            processed_nodes[f"node-{i:03d}"] = {
                "description": f"Test node {i}",
                "inputs": [{"key": "input", "type": "str", "description": "Input data"}],
                "outputs": outputs,
                "params": [],
                "actions": ["default"],
            }

        # Only return the selected nodes from processing
        selected_processed = {k: v for k, v in processed_nodes.items() if k in selected_nodes}
        mock_process.return_value = (selected_processed, 0)

        with patch("pflow.planning.context_builder._process_nodes", mock_process):
            # Measure planning context generation time
            start_time = time.time()
            planning = build_planning_context(selected_nodes, [], registry_metadata)
            planning_time = time.time() - start_time

        # Should complete quickly even with many selected nodes
        assert planning_time < 1.0, f"Planning took {planning_time:.2f}s, should be < 1.0s"

        # Should include all selected nodes
        assert "node-000" in planning
        assert "node-049" in planning

        # Should include structure displays for structured nodes
        assert "Structure (JSON format):" in planning
        assert "Available paths:" in planning

    def test_structure_formatting_performance(self):
        """Test performance of structure formatting with deeply nested data."""
        # Create a deeply nested structure (5 levels)
        deep_structure = {
            "level1": {
                "type": "dict",
                "description": "Level 1 data",
                "structure": {
                    "level2": {
                        "type": "dict",
                        "description": "Level 2 data",
                        "structure": {
                            "level3": {
                                "type": "dict",
                                "description": "Level 3 data",
                                "structure": {
                                    "level4": {
                                        "type": "dict",
                                        "description": "Level 4 data",
                                        "structure": {"level5": {"type": "str", "description": "Deep nested value"}},
                                    }
                                },
                            }
                        },
                    }
                },
            }
        }

        # Add many fields at each level
        for i in range(10):
            deep_structure[f"field_{i}"] = {"type": "str", "description": f"Field {i} description"}

        # Test structure formatting performance
        start_time = time.time()
        for _ in range(100):  # Format 100 times to measure performance
            json_struct, paths = _format_structure_combined(deep_structure)
        format_time = time.time() - start_time

        # Should complete quickly even with deep nesting
        assert format_time < 0.5, f"Structure formatting took {format_time:.2f}s for 100 iterations"

        # Verify the formatting worked correctly
        assert "level1" in json_struct
        assert len(paths) > 10  # Should have multiple paths

        # Check that deep path exists
        deep_paths = [path for path, _, _ in paths if "level1.level2.level3.level4.level5" in path]
        assert len(deep_paths) > 0, "Deep nested path should be generated"

    def test_memory_usage_with_large_structures(self):
        """Test memory efficiency with large structured outputs."""
        # Create a structure with many fields to test memory usage
        large_structure = {}
        for i in range(500):  # 500 fields
            large_structure[f"field_{i:03d}"] = {
                "type": "dict",
                "description": f"Field {i} containing data",
                "structure": {
                    "id": {"type": "str", "description": "Record ID"},
                    "data": {"type": "str", "description": "Record data"},
                    "metadata": {
                        "type": "dict",
                        "description": "Metadata object",
                        "structure": {
                            "created": {"type": "str", "description": "Creation time"},
                            "tags": {
                                "type": "list",
                                "description": "Tag list",
                                "structure": {"name": {"type": "str", "description": "Tag name"}},
                            },
                        },
                    },
                },
            }

        # Test formatting without running out of memory
        start_time = time.time()
        json_struct, paths = _format_structure_combined(large_structure)
        format_time = time.time() - start_time

        # Should complete in reasonable time
        assert format_time < 1.0, f"Large structure formatting took {format_time:.2f}s"

        # Should generate correct number of paths
        # Each field generates: field_XXX, field_XXX.id, field_XXX.data, field_XXX.metadata,
        # field_XXX.metadata.created, field_XXX.metadata.tags[], field_XXX.metadata.tags[].name
        expected_paths_per_field = 7
        expected_total_paths = 500 * expected_paths_per_field

        # Allow some tolerance for variations in structure format
        assert len(paths) >= expected_total_paths * 0.9, f"Expected ~{expected_total_paths} paths, got {len(paths)}"
        assert len(paths) <= expected_total_paths * 1.1, f"Too many paths generated: {len(paths)}"

    def test_planning_context_with_large_workflows(self):
        """Test planning context performance with many workflows."""
        registry_metadata = {}

        # Mock many workflows
        workflows = []
        for i in range(100):
            workflows.append({
                "name": f"workflow-{i:03d}",
                "description": f"Test workflow {i} with complex operations and multiple steps",
                "inputs": [f"input_{j}" for j in range(5)],  # 5 inputs each
                "outputs": [f"output_{j}" for j in range(3)],  # 3 outputs each
                "ir": {
                    "nodes": [f"node_{j}" for j in range(10)],  # 10 nodes each
                    "flows": [f"flow_{j}" for j in range(5)],  # 5 flows each
                },
                "tags": [f"tag_{j}" for j in range(3)],
                "created_at": "2024-01-01T00:00:00Z",
            })

        # Select many workflows for planning
        selected_workflows = [f"workflow-{i:03d}" for i in range(50)]

        with patch("pflow.planning.context_builder._load_saved_workflows") as mock_load:
            mock_load.return_value = workflows

            start_time = time.time()
            planning = build_planning_context([], selected_workflows, registry_metadata)
            planning_time = time.time() - start_time

        # Should handle many workflows efficiently
        assert planning_time < 0.5, f"Planning with many workflows took {planning_time:.2f}s"

        # Should include all selected workflows
        assert "workflow-000" in planning
        assert "workflow-049" in planning

        # Context should be reasonably sized
        context_size = len(planning.encode("utf-8"))
        assert context_size < 200_000, f"Context with workflows too large: {context_size} bytes"

    def test_concurrent_performance_under_load(self):
        """Test performance when multiple threads access context builder."""
        import threading

        registry_metadata = {}
        for i in range(100):
            registry_metadata[f"node-{i:03d}"] = {"module": "test.module", "class_name": "TestNode"}

        results = []
        errors = []
        times = []

        def build_contexts():
            try:
                start = time.time()

                # Create thread-local mock to avoid conflicts
                mock_process = Mock()
                processed_nodes = {}
                for i in range(100):
                    processed_nodes[f"node-{i:03d}"] = {
                        "description": f"Test node {i}",
                        "inputs": [],
                        "outputs": [],
                        "params": [],
                        "actions": ["default"],
                    }
                mock_process.return_value = (processed_nodes, 0)

                with patch("pflow.planning.context_builder._process_nodes", mock_process):
                    # Build both discovery and planning contexts
                    discovery = build_discovery_context(registry_metadata=registry_metadata)
                    selected_nodes = [f"node-{i:03d}" for i in range(10)]
                    selected_processed = {k: v for k, v in processed_nodes.items() if k in selected_nodes}
                    mock_process.return_value = (selected_processed, 0)
                    planning = build_planning_context(selected_nodes, [], registry_metadata)

                end = time.time()
                times.append(end - start)
                results.append(len(discovery) + len(planning))  # Total context size

            except Exception as e:
                errors.append(str(e))

        # Run 5 threads concurrently
        threads = [threading.Thread(target=build_contexts) for _ in range(5)]

        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        total_time = time.time() - start_time

        # All threads should complete without errors
        assert len(errors) == 0, f"Errors during concurrent execution: {errors}"
        assert len(results) == 5, "All threads should complete"

        # Total time should be reasonable (< 3 seconds for 5 threads)
        assert total_time < 3.0, f"Concurrent execution took {total_time:.2f}s"

        # Individual thread times should be consistent
        avg_time = sum(times) / len(times)
        max_time = max(times)
        # Skip consistency check if times are too small (under 10ms)
        if avg_time > 0.01:
            assert max_time < avg_time * 2, f"Thread times inconsistent: avg={avg_time:.2f}s, max={max_time:.2f}s"


class TestEdgeCasePerformance:
    """Test performance with edge cases and boundary conditions."""

    def test_empty_inputs_performance(self):
        """Test performance with various empty input scenarios."""
        start_time = time.time()

        # Test empty registry
        discovery = build_discovery_context(registry_metadata={})

        # Test empty selections - need to mock the empty processing
        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = ({}, 0)
            result = build_planning_context([], [], {})

        empty_time = time.time() - start_time

        # Empty inputs should be very fast
        assert empty_time < 0.1, f"Empty inputs took {empty_time:.2f}s, should be < 0.1s"

        # Should handle gracefully
        assert "## Available Nodes" in discovery
        assert "## Selected Components" in result  # Empty selection returns valid context

    def test_malformed_data_performance(self):
        """Test performance doesn't degrade with malformed input data."""
        # Registry with malformed entries
        bad_registry = {
            "empty-node": {},  # Empty dict
            "missing-module": {"class_name": "Missing"},  # Missing module
            "missing-class": {"module": "missing"},  # Missing class_name
            "valid-node": {"module": "test", "class_name": "Test"},  # Valid
        }

        # Simulate that bad entries are skipped (return only valid processed nodes)
        valid_processed = {
            "valid-node": {
                "description": "Valid test node",
                "inputs": [],
                "outputs": [],
                "params": [],
                "actions": ["default"],
            }
        }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (valid_processed, 3)  # 3 skipped out of 4

            start_time = time.time()
            discovery = build_discovery_context(registry_metadata=bad_registry)
            malformed_time = time.time() - start_time

        # Should handle malformed data quickly without hanging
        assert malformed_time < 0.5, f"Malformed data handling took {malformed_time:.2f}s"

        # Should produce valid output despite bad inputs
        assert "## Available Nodes" in discovery
        assert "valid-node" in discovery  # Should include the valid node

    def test_unicode_content_performance(self):
        """Test performance with Unicode-heavy content."""
        # Create registry with Unicode-heavy descriptions
        unicode_registry = {}
        unicode_texts = [
            "🚀 High-performance data processing with émojis and special chars",
            "中文描述：这是一个处理中文文本的节点，包含复杂的字符",  # noqa: RUF001
            "Ñode cōn caractéres especiáles y acentuación compleja",
            "Кириллический текст с различными символами и кодировкой",  # noqa: RUF001
            "मिश्रित भाषा support with हिंदी और English content",
        ]

        for i in range(200):
            unicode_registry[f"unicode-node-{i}"] = {"module": "test.unicode", "class_name": "UnicodeNode"}

        # Mock processed nodes with Unicode content
        processed_nodes = {}
        for i in range(200):
            processed_nodes[f"unicode-node-{i}"] = {
                "description": unicode_texts[i % len(unicode_texts)],
                "inputs": [{"key": "input", "type": "str", "description": unicode_texts[(i + 1) % len(unicode_texts)]}],
                "outputs": [
                    {"key": "output", "type": "str", "description": unicode_texts[(i + 2) % len(unicode_texts)]}
                ],
                "params": [],
                "actions": ["default"],
            }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (processed_nodes, 0)

            start_time = time.time()
            discovery = build_discovery_context(registry_metadata=unicode_registry)
            unicode_time = time.time() - start_time

        # Unicode content should not significantly impact performance
        assert unicode_time < 1.0, f"Unicode content processing took {unicode_time:.2f}s"

        # Should properly include Unicode content
        assert "🚀" in discovery
        assert "中文" in discovery
        assert "émojis" in discovery
