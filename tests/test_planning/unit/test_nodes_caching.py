"""Test node caching behavior for cross-session caching.

This test suite validates:
1. All nodes work with cache_planner=False (traditional path)
2. All nodes work with cache_planner=True (caching path) 
3. Cache blocks are built correctly when enabled
4. Correct parameters are passed to LLM
"""

from unittest.mock import Mock, patch

import pytest

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
                mock_response.text = lambda: "PATH_A"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                prep_res = node.prep(shared)
                result = node.exec(shared, prep_res=prep_res)
            
            # Should call prompt without cache_blocks parameter
            mock_model.prompt.assert_called_once()
            call_args = mock_model.prompt.call_args
            assert "cache_blocks" not in call_args.kwargs

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "test input",
            "cache_planner": True,  # Caching enabled
        }
        
        # Mock context builder to provide discovery context
        with patch("pflow.planning.nodes.build_discovery_context") as mock_build_context:
            mock_build_context.return_value = "Long discovery context " * 50  # Make it long enough
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.text = lambda: "PATH_A"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should call prompt WITH cache_blocks parameter
                mock_model.prompt.assert_called_once()
                call_args = mock_model.prompt.call_args
                
                # Verify cache_blocks is present and structured correctly
                assert "cache_blocks" in call_args.kwargs
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
        
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_response = Mock()
            mock_response.text = lambda: "PATH_A"
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model
            
            node.prep(shared)
            result = node.exec(shared)
            
            # Should NOT use caching
            call_args = mock_model.prompt.call_args
            assert "cache_blocks" not in call_args.kwargs


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
        
        with patch("pflow.planning.nodes.build_browsing_context") as mock_context:
            mock_context.return_value = ("nodes context", "workflows context")
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "selected_nodes": ["read-file"],
                    "selected_workflows": [],
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should call prompt without cache_blocks
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" not in call_args.kwargs

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.build_browsing_context") as mock_context:
            # Provide long enough context for caching
            mock_context.return_value = ("nodes " * 100, "workflows " * 100)
            
            with patch("pflow.planning.nodes.load_prompt") as mock_load_prompt:
                mock_load_prompt.return_value = "prompt " * 200  # Long prompt
                
                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        "selected_nodes": ["read-file"],
                        "selected_workflows": [],
                    }
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model
                    
                    node.prep(shared)
                    result = node.exec(shared)
                    
                    # Should call prompt WITH cache_blocks
                    call_args = mock_model.prompt.call_args
                    assert "cache_blocks" in call_args.kwargs
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
                "requirements": ["req1", "req2"],
                "constraints": ["const1"],
                "success_criteria": ["success1"],
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model
            
            node.prep(shared)
            result = node.exec(shared)
            
            # Should NOT use cache blocks
            call_args = mock_model.prompt.call_args
            assert "cache_blocks" not in call_args.kwargs

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = RequirementsAnalysisNode()
        shared = {
            "user_input": "test input",
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.load_prompt") as mock_load_prompt:
            mock_load_prompt.return_value = "Long prompt " * 100  # Make it cacheable
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "requirements": ["req1"],
                    "constraints": ["const1"],
                    "success_criteria": ["success1"],
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs
                cache_blocks = call_args.kwargs["cache_blocks"]
                
                # Should have one block with the prompt
                assert len(cache_blocks) == 1
                assert "Long prompt" in cache_blocks[0]["text"]
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
            mock_response.json.return_value = {
                "discovered_parameters": ["param1"],
                "validation_notes": [],
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model
            
            node.prep(shared)
            result = node.exec(shared)
            
            # Should NOT use cache blocks
            call_args = mock_model.prompt.call_args
            assert "cache_blocks" not in call_args.kwargs

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = ParameterDiscoveryNode()
        shared = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.load_prompt") as mock_load_prompt:
            mock_load_prompt.return_value = "Parameter discovery prompt " * 50
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "discovered_parameters": ["param1"],
                    "validation_notes": [],
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs
                cache_blocks = call_args.kwargs["cache_blocks"]
                assert len(cache_blocks) > 0


class TestParameterMappingNodeCaching:
    """Test ParameterMappingNode caching behavior."""

    def test_traditional_path_without_caching(self):
        """Node works normally when cache_planner=False."""
        node = ParameterMappingNode()
        shared = {
            "user_input": "test input",
            "discovered_parameters": ["param1"],
            "cache_planner": False,
        }
        
        with patch("llm.get_model") as mock_get_model:
            mock_model = Mock()
            mock_response = Mock()
            mock_response.json.return_value = {
                "mapped_parameters": {"param1": "value1"},
                "unmapped_parameters": [],
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model
            
            node.prep(shared)
            result = node.exec(shared)
            
            # Should NOT use cache blocks
            call_args = mock_model.prompt.call_args
            assert "cache_blocks" not in call_args.kwargs

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = ParameterMappingNode()
        shared = {
            "user_input": "test input",
            "discovered_parameters": ["param1"],
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.load_prompt") as mock_load_prompt:
            mock_load_prompt.return_value = "Mapping prompt " * 100
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "mapped_parameters": {"param1": "value1"},
                    "unmapped_parameters": [],
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs


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
            mock_response.json.return_value = {
                "name": "test-workflow",
                "display_name": "Test Workflow",
                "description": "Test description",
                "tags": ["test"],
            }
            mock_model.prompt.return_value = mock_response
            mock_get_model.return_value = mock_model
            
            node.prep(shared)
            result = node.exec(shared)
            
            # Should NOT use cache blocks
            call_args = mock_model.prompt.call_args
            assert "cache_blocks" not in call_args.kwargs

    def test_caching_path_with_cache_blocks(self):
        """Node uses cache blocks when cache_planner=True."""
        node = MetadataGenerationNode()
        shared = {
            "user_input": "test input",
            "workflow_ir": {"nodes": [], "edges": []},
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.load_prompt") as mock_load_prompt:
            mock_load_prompt.return_value = "Metadata generation " * 100
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "name": "test-workflow",
                    "display_name": "Test Workflow",
                    "description": "Test description",
                    "tags": ["test"],
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should use cache blocks
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs


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
        
        with patch("pflow.planning.nodes.build_context_blocks") as mock_build_blocks:
            mock_build_blocks.return_value = [
                {"text": "context", "cache_control": {"type": "ephemeral"}}
            ]
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.text = lambda: "**Status**: FEASIBLE\n**Node Chain**: test"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared_false)
                result = node.exec(shared_false)
                
                # Should STILL use cache blocks even with flag=False
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs
        
        # Test with cache_planner=True (should also cache)
        shared_true = {
            "user_input": "test input",
            "browsed_components": {"nodes": ["read-file"]},
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.build_context_blocks") as mock_build_blocks:
            mock_build_blocks.return_value = [
                {"text": "context", "cache_control": {"type": "ephemeral"}}
            ]
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.text = lambda: "**Status**: FEASIBLE\n**Node Chain**: test"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared_true)
                result = node.exec(shared_true)
                
                # Should use cache blocks with flag=True
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs


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
            "cache_planner": False,  # Should still cache
        }
        
        with patch("pflow.planning.nodes.build_context_blocks") as mock_build_blocks:
            mock_build_blocks.return_value = [
                {"text": "context", "cache_control": {"type": "ephemeral"}}
            ]
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.json.return_value = {
                    "ir_version": "0.1.0",
                    "nodes": [],
                    "edges": [],
                }
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                # Should STILL use cache blocks even with flag=False
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs


class TestCacheBlockContent:
    """Test that cache blocks contain the right content."""

    def test_discovery_node_caches_workflow_descriptions(self):
        """WorkflowDiscoveryNode caches workflow descriptions."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "test input",
            "cache_planner": True,
        }
        
        with patch("pflow.planning.nodes.build_discovery_context") as mock_context:
            discovery_content = "Available workflows and their descriptions " * 50
            mock_context.return_value = discovery_content
            
            with patch("llm.get_model") as mock_get_model:
                mock_model = Mock()
                mock_response = Mock()
                mock_response.text = lambda: "PATH_A"
                mock_model.prompt.return_value = mock_response
                mock_get_model.return_value = mock_model
                
                node.prep(shared)
                result = node.exec(shared)
                
                call_args = mock_model.prompt.call_args
                cache_blocks = call_args.kwargs["cache_blocks"]
                
                # Discovery content should be in cache blocks
                assert any(discovery_content in block["text"] for block in cache_blocks)

    def test_component_node_caches_all_documentation(self):
        """ComponentBrowsingNode caches nodes, workflows, and prompt."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": True,
        }
        
        nodes_content = "Node documentation " * 50
        workflows_content = "Workflow documentation " * 50
        prompt_content = "Browsing instructions " * 50
        
        with patch("pflow.planning.nodes.build_browsing_context") as mock_context:
            mock_context.return_value = (nodes_content, workflows_content)
            
            with patch("pflow.planning.nodes.load_prompt") as mock_load_prompt:
                mock_load_prompt.return_value = prompt_content
                
                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    mock_response.json.return_value = {
                        "selected_nodes": ["test"],
                        "selected_workflows": [],
                    }
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model
                    
                    node.prep(shared)
                    result = node.exec(shared)
                    
                    call_args = mock_model.prompt.call_args
                    cache_blocks = call_args.kwargs["cache_blocks"]
                    
                    # All three types of content should be cached
                    all_text = " ".join(block["text"] for block in cache_blocks)
                    assert nodes_content in all_text or "Available Nodes" in all_text
                    assert workflows_content in all_text or "Available Workflows" in all_text
                    assert prompt_content in all_text