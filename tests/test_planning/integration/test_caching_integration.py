"""Integration tests for cross-session caching functionality.

This test suite validates the end-to-end caching behavior:
1. Cache flag propagation through the system
2. Cache blocks are built when flag is enabled
3. LLM is called with appropriate cache parameters
"""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    RequirementsAnalysisNode,
    WorkflowDiscoveryNode,
)


class TestCachingIntegration:
    """Test end-to-end caching functionality."""

    def test_discovery_node_uses_cache_when_enabled(self):
        """Test that WorkflowDiscoveryNode properly uses caching when enabled."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "Build me a workflow to process files",
            "cache_planner": True,  # Enable caching
        }
        
        # Mock dependencies
        with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_context:
            mock_build_context.return_value = "A" * 1000  # Long enough to cache
            
            with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
                # Return a template with placeholders
                mock_load_prompt.return_value = "Discovery prompt: {discovery_context}\nUser request: {user_input}"
                
                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    
                    # Mock the nested response structure (Anthropic format)
                    mock_response.json.return_value = {
                        "content": [{
                            "input": {
                                "found": False,
                                "workflow_name": None,
                                "confidence": 0.0,
                                "reasoning": "No matching workflow found"
                            }
                        }]
                    }
                    mock_response.text.return_value = "PATH_A"
                    
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model
                    
                    # Execute
                    prep_res = node.prep(shared)
                    result = node.exec(prep_res)
                    
                    # Verify cache blocks were passed to LLM
                    mock_model.prompt.assert_called_once()
                    call_args = mock_model.prompt.call_args
                    
                    # Check that cache_blocks parameter was provided
                    assert "cache_blocks" in call_args.kwargs
                    cache_blocks = call_args.kwargs["cache_blocks"]
                    assert isinstance(cache_blocks, list)
                    assert len(cache_blocks) > 0
                    
                    # Verify cache block structure
                    for block in cache_blocks:
                        assert "text" in block
                        assert "cache_control" in block
                        assert block["cache_control"]["type"] == "ephemeral"

    def test_discovery_node_no_cache_when_disabled(self):
        """Test that WorkflowDiscoveryNode doesn't use caching when disabled."""
        node = WorkflowDiscoveryNode()
        shared = {
            "user_input": "Build me a workflow to process files",
            "cache_planner": False,  # Caching disabled
        }
        
        with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_context:
            mock_build_context.return_value = "A" * 1000
            
            with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
                # Return a template with placeholders
                mock_load_prompt.return_value = "Discovery prompt: {discovery_context}\nUser request: {user_input}"
                
                with patch("llm.get_model") as mock_get_model:
                    mock_model = Mock()
                    mock_response = Mock()
                    mock_response.text.return_value = "PATH_A"
                    mock_model.prompt.return_value = mock_response
                    mock_get_model.return_value = mock_model
                    
                    # Execute
                    prep_res = node.prep(shared)
                    result = node.exec(prep_res)
                    
                    # Verify NO cache blocks were passed
                    mock_model.prompt.assert_called_once()
                    call_args = mock_model.prompt.call_args
                    
                    # cache_blocks should NOT be in kwargs
                    assert "cache_blocks" not in call_args.kwargs

    def test_requirements_node_uses_cache_when_enabled(self):
        """Test that RequirementsAnalysisNode properly uses caching when enabled."""
        node = RequirementsAnalysisNode()
        shared = {
            "user_input": "Build me a workflow",
            "cache_planner": True,  # Enable caching
        }
        
        with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
            mock_load_prompt.return_value = "Requirements analysis prompt " * 50  # Long enough
            
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
                
                # Execute
                prep_res = node.prep(shared)
                result = node.exec(shared, prep_res=prep_res)
                
                # Verify cache blocks were used
                call_args = mock_model.prompt.call_args
                assert "cache_blocks" in call_args.kwargs
                cache_blocks = call_args.kwargs["cache_blocks"]
                assert len(cache_blocks) > 0

    def test_component_browsing_uses_multiple_cache_blocks(self):
        """Test that ComponentBrowsingNode creates multiple cache blocks."""
        node = ComponentBrowsingNode()
        shared = {
            "user_input": "test input",
            "selected_path": "PATH_A",
            "cache_planner": True,
        }
        
        # Mock all the context builders
        with patch("pflow.planning.context_builder.build_nodes_context") as mock_build_nodes:
            mock_build_nodes.return_value = "Node documentation " * 100
            
            with patch("pflow.planning.context_builder.build_workflows_context") as mock_build_workflows:
                mock_build_workflows.return_value = "Workflow documentation " * 100
                
                with patch("pflow.planning.prompts.loader.load_prompt") as mock_load_prompt:
                    mock_load_prompt.return_value = "Browsing instructions " * 100
                    
                    with patch("pflow.registry.registry.Registry.load") as mock_registry:
                        mock_registry.return_value = {}
                        
                        with patch("llm.get_model") as mock_get_model:
                            mock_model = Mock()
                            mock_response = Mock()
                            mock_response.json.return_value = {
                                "selected_nodes": ["read-file"],
                                "selected_workflows": [],
                            }
                            mock_model.prompt.return_value = mock_response
                            mock_get_model.return_value = mock_model
                            
                            # Execute
                            prep_res = node.prep(shared)
                            result = node.exec(prep_res)
                            
                            # Verify multiple cache blocks were created
                            call_args = mock_model.prompt.call_args
                            assert "cache_blocks" in call_args.kwargs
                            cache_blocks = call_args.kwargs["cache_blocks"]
                            
                            # Should have multiple blocks (up to 3)
                            assert len(cache_blocks) >= 1
                            assert len(cache_blocks) <= 3  # Capped at 3
                            
                            # Each block should be properly structured
                            for block in cache_blocks:
                                assert "text" in block
                                assert "cache_control" in block
                                assert len(block["text"]) > 100  # Should be substantial


class TestCacheFlagPropagation:
    """Test that cache flag propagates correctly through the system."""

    def test_cache_flag_in_shared_store(self):
        """Test that cache_planner flag is available in shared store."""
        shared_with_cache = {"cache_planner": True, "user_input": "test"}
        shared_without_cache = {"cache_planner": False, "user_input": "test"}
        shared_no_flag = {"user_input": "test"}  # No flag
        
        node = WorkflowDiscoveryNode()
        
        with patch("pflow.planning.context_builder.build_workflows_context"):
            # Test with cache enabled
            prep_res = node.prep(shared_with_cache)
            assert prep_res["cache_planner"] is True
            
            # Test with cache disabled
            prep_res = node.prep(shared_without_cache)
            assert prep_res["cache_planner"] is False
            
            # Test default (no flag)
            prep_res = node.prep(shared_no_flag)
            assert prep_res["cache_planner"] is False  # Defaults to False

    def test_all_nodes_respect_cache_flag(self):
        """Test that all LLM nodes check and respect the cache flag."""
        nodes_to_test = [
            WorkflowDiscoveryNode(),
            RequirementsAnalysisNode(),
        ]
        
        for node in nodes_to_test:
            shared = {"user_input": "test", "cache_planner": True}
            
            # Mock minimal dependencies
            with patch("pflow.planning.context_builder.build_workflows_context", return_value="context"):
                with patch("pflow.planning.context_builder.build_nodes_context", return_value="nodes"):
                    with patch("pflow.registry.registry.Registry.load", return_value={}):
                        prep_res = node.prep(shared)
                        
                        # Verify cache flag is preserved
                        assert "cache_planner" in prep_res
                        assert prep_res["cache_planner"] is True


class TestCacheEffectiveness:
    """Test that caching actually provides the expected benefits."""

    def test_cache_blocks_contain_static_content(self):
        """Test that cache blocks contain the static documentation."""
        from pflow.planning.utils.cache_builder import (
            build_component_cache_blocks,
            build_discovery_cache_blocks,
            build_simple_cache_blocks,
        )
        
        # Test discovery cache blocks
        discovery_context = "Workflow documentation " * 100
        blocks = build_discovery_cache_blocks(discovery_context)
        assert len(blocks) == 1
        assert discovery_context in blocks[0]["text"]
        
        # Test component cache blocks
        nodes_ctx = "Nodes " * 100
        workflows_ctx = "Workflows " * 100
        prompt = "Instructions " * 100
        blocks = build_component_cache_blocks(nodes_ctx, workflows_ctx, prompt)
        assert len(blocks) <= 3  # Max 3 blocks
        
        # All content should be in the blocks
        all_text = " ".join(b["text"] for b in blocks)
        assert "Nodes" in all_text or "Available Nodes" in all_text
        assert "Workflows" in all_text or "Available Workflows" in all_text
        
        # Test simple cache blocks
        static_prompt = "Static instructions " * 50
        blocks = build_simple_cache_blocks(static_prompt)
        assert len(blocks) == 1
        assert static_prompt in blocks[0]["text"]

    def test_cache_blocks_marked_as_ephemeral(self):
        """Test that all cache blocks use ephemeral cache control."""
        from pflow.planning.utils.cache_builder import (
            build_discovery_cache_blocks,
            build_simple_cache_blocks,
        )
        
        # All blocks should be marked as ephemeral
        blocks = build_discovery_cache_blocks("A" * 1000)
        for block in blocks:
            assert block["cache_control"]["type"] == "ephemeral"
        
        blocks = build_simple_cache_blocks("B" * 1000)
        for block in blocks:
            assert block["cache_control"]["type"] == "ephemeral"