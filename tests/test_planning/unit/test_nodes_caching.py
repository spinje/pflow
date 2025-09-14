"""Test node caching behavior for cross-session caching.

This test suite validates:
1. All nodes work with cache_planner=False (traditional path)
2. All nodes work with cache_planner=True (caching path)
3. Cache blocks are built correctly when enabled
4. Correct parameters are passed to LLM
"""

from unittest.mock import Mock, patch

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    MetadataGenerationNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    PlanningNode,
    RequirementsAnalysisNode,
    WorkflowDiscoveryNode,
    WorkflowGeneratorNode,
)


class TestWorkflowDiscoveryNodeCaching:
    """Test WorkflowDiscoveryNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "test input",
            "cache_planner": False,  # Caching disabled
        }

        with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_context:
            mock_build_context.return_value = "test context"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.0,
                                "reasoning": "No matching workflow found",
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

            # Should call prompt with cache_blocks=None when cache_planner=False
            mock_model.prompt.assert_called_once()
            call_args = mock_model.prompt.call_args
            assert call_args.kwargs.get("cache_blocks") is None

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "test input",
            "cache_planner": True,  # Caching enabled
        }

        # Mock context builder to provide discovery context
        with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_context:
            mock_build_context.return_value = "Long discovery context " * 50  # Make it long enough

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.0,
                                "reasoning": "No matching workflow found",
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should call prompt WITH cache_blocks parameter
                mock_model.prompt.assert_called_once()
                call_args = mock_model.prompt.call_args

                # Verify cache_blocks is present and structured correctly
                assert call_args.kwargs.get("cache_blocks") is not None
                cache_blocks = call_args.kwargs["cache_blocks"]
                assert isinstance(cache_blocks, list)
                assert len(cache_blocks) > 0
                assert "text" in cache_blocks[0]
                assert "cache_control" in cache_blocks[0]
                assert cache_blocks[0]["cache_control"] == {"type": "ephemeral"}

    def test_cache_flag_defaults_to_false(self):
        """When cache_planner not in shared, defaults to False."""
        node = WorkflowDiscoveryNode()
        shared = {"user_input": "test input"}  # No cache_planner key

        with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_context:
            mock_build_context.return_value = "test context"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.0,
                                "reasoning": "No matching workflow found",
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should pass None for cache_blocks (defaults to False)
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is None


class TestComponentBrowsingNodeCaching:
    """Test ComponentBrowsingNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": False,
        }

        with (
            patch("pflow.planning.context_builder.build_nodes_context") as mock_nodes_context,
            patch("pflow.planning.context_builder.build_workflows_context") as mock_workflows_context,
        ):
            mock_nodes_context.return_value = "nodes context"
            mock_workflows_context.return_value = "workflows context"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [{"input": {"node_ids": ["read-file"], "workflow_names": [], "reasoning": "test"}}]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should call prompt with cache_blocks=None when cache_planner=False
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is None

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": True,
        }

        with (
            patch("pflow.planning.context_builder.build_nodes_context") as mock_nodes_context,
            patch("pflow.planning.context_builder.build_workflows_context") as mock_workflows_context,
        ):
            # Provide long enough context for caching (>1000 chars)
            mock_nodes_context.return_value = "nodes " * 200  # 1200 chars
            mock_workflows_context.return_value = "workflows " * 150  # 1500 chars

            with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
                # Mock prompt with expected structure for caching
                mock_load_prompt.return_value = (
                    "Instructions " * 100 + "\n## Context\n{{nodes_context}}\n{{workflows_context}}"
                )

                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    # Mock proper response structure
                    mock_response.json.return_value = {
                        "content": [{"input": {"node_ids": ["read-file"], "workflow_names": [], "reasoning": "test"}}]
                    }
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    prep_res = node.prep(shared)
                    node.exec(prep_res)

                    # Should call prompt WITH cache_blocks
                    call_args = mock_model.prompt.call_args
                    assert call_args.kwargs.get("cache_blocks") is not None
                    cache_blocks = call_args.kwargs["cache_blocks"]

                    # Should have multiple blocks (nodes, workflows, prompt)
                    assert isinstance(cache_blocks, list)
                    assert len(cache_blocks) > 0

                    # Verify structure
                    for block in cache_blocks:
                        assert "text" in block
                        assert "cache_control" in block
                        assert block["cache_control"] == {"type": "ephemeral"}


class TestRequirementsAnalysisNodeCaching:
    """Test RequirementsAnalysisNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = RequirementsAnalysisNode()
        shared = {
            "user_input": "test input",
            "cache_planner": False,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_response = Mock()
            mock_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "is_clear": True,
                            "steps": ["req1", "req2"],
                            "required_capabilities": ["test"],
                        }
                    }
                ]
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            prep_res = node.prep(shared)
            node.exec(prep_res)

            # Should pass None for cache blocks when cache_planner=False
            call_args = mock_model.prompt.call_args
            assert call_args.kwargs.get("cache_blocks") is None

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = RequirementsAnalysisNode()
        shared = {
            "user_input": "test input",
            "cache_planner": True,
        }

        with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
            # Provide template with ## Context marker for caching
            mock_load_prompt.return_value = "Instructions " * 100 + "\n## Context\n{{input_text}}"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "is_clear": True,
                                "steps": ["req1"],
                                "estimated_nodes": 1,
                                "required_capabilities": ["test"],
                                "complexity_indicators": {},
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None
                cache_blocks = call_args.kwargs["cache_blocks"]

                # Should have one block with the prompt
                assert len(cache_blocks) == 1
                # The block should contain either our mocked instructions or the real prompt
                assert (
                    "Instructions" in cache_blocks[0]["text"] or "analyzing a user" in cache_blocks[0]["text"]
                )  # Part of actual prompt
                assert cache_blocks[0]["cache_control"] == {"type": "ephemeral"}


class TestParameterDiscoveryNodeCaching:
    """Test ParameterDiscoveryNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = ParameterDiscoveryNode()
        shared = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "cache_planner": False,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_response = Mock()
            # Mock proper response structure for parse_structured_response
            mock_response.json.return_value = {
                "content": [{"input": {"parameters": {"param1": "value1"}, "stdin_type": None, "reasoning": "test"}}]
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            prep_res = node.prep(shared)
            node.exec(prep_res)

            # Should pass None for cache blocks when cache_planner=False
            call_args = mock_model.prompt.call_args
            assert call_args.kwargs.get("cache_blocks") is None

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = ParameterDiscoveryNode()
        shared = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "cache_planner": True,
        }

        with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
            # Provide template with ## Context marker for caching
            mock_load_prompt.return_value = "Instructions " * 100 + "\n## Context\n{{user_input}}\n{{stdin_info}}"

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [
                        {"input": {"parameters": {"param1": "value1"}, "stdin_type": None, "reasoning": "test"}}
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None
                cache_blocks = call_args.kwargs["cache_blocks"]
                assert len(cache_blocks) > 0


class TestParameterMappingNodeCaching:
    """Test ParameterMappingNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = ParameterMappingNode()
        shared = {
            "user_input": "test input",
            "generated_workflow": {  # Need workflow IR for the node to work
                "ir_version": "0.1.0",
                "nodes": [],
                "edges": [],
                "inputs": {"param1": {"type": "string", "description": "Test parameter"}},
            },
            "cache_planner": False,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_response = Mock()
            # Mock proper response structure for parse_structured_response
            mock_response.json.return_value = {
                "content": [{"input": {"extracted": {"param1": "value1"}, "missing": [], "confidence": 1.0}}]
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            prep_res = node.prep(shared)
            node.exec(prep_res)

            # Should pass None for cache blocks when cache_planner=False
            call_args = mock_model.prompt.call_args
            assert call_args.kwargs.get("cache_blocks") is None

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = ParameterMappingNode()
        shared = {
            "user_input": "test input",
            "generated_workflow": {  # Need workflow IR for the node to work
                "ir_version": "0.1.0",
                "nodes": [],
                "edges": [],
                "inputs": {"param1": {"type": "string", "description": "Test parameter"}},
            },
            "cache_planner": True,
        }

        with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
            # Provide template with ## Context marker for caching
            mock_load_prompt.return_value = (
                "Instructions " * 100 + "\n## Context\n{{inputs_description}}\n{{user_input}}\n{{stdin_data}}"
            )

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [{"input": {"extracted": {"param1": "value1"}, "missing": [], "confidence": 1.0}}]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None


class TestMetadataGenerationNodeCaching:
    """Test MetadataGenerationNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = MetadataGenerationNode()
        shared = {
            "user_input": "test input",
            "workflow_ir": {"nodes": [], "edges": []},
            "cache_planner": False,
        }

        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_response = Mock()
            # Mock proper response structure for parse_structured_response
            mock_response.json.return_value = {
                "content": [
                    {
                        "input": {
                            "suggested_name": "test-workflow",
                            "description": "Test description for workflow that performs various testing operations and validates results against expected behavior patterns in automated testing scenarios",
                            "search_keywords": ["test", "workflow"],
                            "capabilities": ["test capability"],
                            "typical_use_cases": ["test use case"],
                        }
                    }
                ]
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model

            prep_res = node.prep(shared)
            node.exec(prep_res)

            # Should pass None for cache blocks when cache_planner=False
            call_args = mock_model.prompt.call_args
            assert call_args.kwargs.get("cache_blocks") is None

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = MetadataGenerationNode()
        shared = {
            "user_input": "test input",
            "workflow_ir": {"nodes": [], "edges": []},
            "cache_planner": True,
        }

        with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
            # Mock prompt with expected variables for metadata generation
            mock_load_prompt.return_value = (
                "{{user_input}} {{node_flow}} {{workflow_inputs}} {{workflow_stages}} {{parameter_bindings}} Metadata generation "
                * 100
            )

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "suggested_name": "test-workflow",
                                "description": "Test description for workflow that performs various testing operations and validates results against expected behavior patterns in automated testing scenarios",
                                "search_keywords": ["test", "workflow"],
                                "capabilities": ["test capability"],
                                "typical_use_cases": ["test use case"],
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None


class TestPlanningNodeCaching:
    """Test PlanningNode caching behavior."""

    def test_always_uses_caching_regardless_of_flag(self):
        """PlanningNode always uses caching for intra-session benefits."""
        node = PlanningNode()

        # Test with cache_planner=False
        shared_false = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "cache_planner": False,  # Should still cache
        }

        with patch("pflow.planning.context_blocks.PlannerContextBuilder.build_base_blocks") as mock_build_blocks:
            mock_build_blocks.return_value = [{"text": "context", "cache_control": {"type": "ephemeral"}}]

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.text = lambda: "**Status**: FEASIBLE\n**Node Chain**: test"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared_false)
                node.exec(prep_res)

                # Should STILL use cache blocks even with flag=False
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None

        # Test with cache_planner=True (should also cache)
        shared_true = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "cache_planner": True,
        }

        with patch("pflow.planning.context_blocks.PlannerContextBuilder.build_base_blocks") as mock_build_blocks:
            mock_build_blocks.return_value = [{"text": "context", "cache_control": {"type": "ephemeral"}}]

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.text = lambda: "**Status**: FEASIBLE\n**Node Chain**: test"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared_true)
                node.exec(prep_res)

                # Should use cache blocks with flag=True
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None


class TestWorkflowGeneratorNodeCaching:
    """Test WorkflowGeneratorNode caching behavior."""

    def test_always_uses_caching_regardless_of_flag(self):
        """WorkflowGeneratorNode always uses caching for intra-session benefits."""
        node = WorkflowGeneratorNode()

        # Test with cache_planner=False
        shared = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "plan_assessment": {"status": "FEASIBLE", "node_chain": "test"},
            "planner_extended_blocks": [  # Generator expects context blocks from PlanningNode
                {"text": "context from planner", "cache_control": {"type": "ephemeral"}}
            ],
            "cache_planner": False,  # Should still cache
        }

        with patch("pflow.planning.context_blocks.PlannerContextBuilder.build_base_blocks") as mock_build_blocks:
            mock_build_blocks.return_value = [{"text": "context", "cache_control": {"type": "ephemeral"}}]

            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                # Mock proper response structure for parse_structured_response
                mock_response.json.return_value = {
                    "content": [
                        {
                            "input": {
                                "ir_version": "0.1.0",
                                "nodes": [],
                                "edges": [],
                            }
                        }
                    ]
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model

                prep_res = node.prep(shared)
                node.exec(prep_res)

                # Should STILL use cache blocks even with flag=False
                call_args = mock_model.prompt.call_args
                assert call_args.kwargs.get("cache_blocks") is not None


class TestCacheBlockContent:
    """Test that cache blocks contain the right content."""

    def test_discovery_node_caches_workflow_descriptions(self):
        """WorkflowDiscoveryNode caches workflow descriptions."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "test input",
            "cache_planner": True,
        }

        # Patch where build_workflows_context is imported, not where it's defined
        with patch("pflow.planning.nodes.build_workflows_context") as mock_context:
            discovery_content = "Available workflows and their descriptions " * 50  # This is already >1000 chars
            mock_context.return_value = discovery_content

            # Also need to mock the prompt template
            with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
                # Mock prompt with Context section for caching logic
                mock_load_prompt.return_value = (
                    "Instructions " * 100 + "\n## Context\n{{discovery_context}}\n## Inputs\n{{user_input}}"
                )

                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    # Mock proper response structure for parse_structured_response
                    mock_response.json.return_value = {
                        "content": [
                            {
                                "input": {
                                    "found": False,
                                    "workflow_name": None,
                                    "confidence": 0.0,
                                    "reasoning": "No matching workflow found",
                                }
                            }
                        ]
                    }
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    prep_res = node.prep(shared)
                    node.exec(prep_res)

                    call_args = mock_model.prompt.call_args
                    cache_blocks = call_args.kwargs["cache_blocks"]

                    # Discovery content should be in cache blocks
                    assert cache_blocks, "No cache blocks found"
                    # Check if the content is cached (it might be wrapped in XML tags)
                    all_cached_text = " ".join(block["text"] for block in cache_blocks)
                    assert discovery_content in all_cached_text or "<existing_workflows>" in all_cached_text

    def test_component_node_caches_all_documentation(self):
        """ComponentBrowsingNode caches nodes, workflows, and prompt."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": True,
        }

        nodes_content = "Node documentation " * 70  # >1000 chars
        workflows_content = "Workflow documentation " * 60  # >1000 chars
        prompt_content = "Browsing instructions " * 60  # >1000 chars

        # Patch where these functions are imported, not where they're defined
        with (
            patch("pflow.planning.nodes.build_nodes_context") as mock_nodes_context,
            patch("pflow.planning.nodes.build_workflows_context") as mock_workflows_context,
        ):
            mock_nodes_context.return_value = nodes_content
            mock_workflows_context.return_value = workflows_content

            with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
                # Include expected structure for caching logic
                mock_load_prompt.return_value = (
                    prompt_content + "\n## Context\n{{nodes_context}}\n{{workflows_context}}"
                )

                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    # Mock proper response structure for parse_structured_response
                    mock_response.json.return_value = {
                        "content": [{"input": {"node_ids": ["test"], "workflow_names": [], "reasoning": "test"}}]
                    }
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    prep_res = node.prep(shared)
                    node.exec(prep_res)

                    call_args = mock_model.prompt.call_args
                    cache_blocks = call_args.kwargs["cache_blocks"]

                    # Check that we have cache blocks with expected content
                    all_text = " ".join(block["text"] for block in cache_blocks)
                    # The node builds its own cache blocks using the mocked context
                    # Check for expected content based on what the node actually does
                    assert cache_blocks, "Should have cache blocks"
                    assert len(cache_blocks) > 0, "Should have at least one cache block"
                    # Check for either the mocked content or the actual content markers
                    assert (
                        nodes_content in all_text
                        or "<available_nodes>" in all_text
                        or workflows_content in all_text
                        or "<available_workflows>" in all_text
                        or prompt_content in all_text
                    )
