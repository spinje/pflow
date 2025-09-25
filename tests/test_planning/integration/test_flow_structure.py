"""Test the structure of the planner flow without execution.

This module tests that the flow is correctly wired with all edges and action strings,
without actually running the flow. This provides fast verification of the flow structure.
"""

from pflow.planning import create_planner_flow
from pflow.planning.nodes import (
    ComponentBrowsingNode,
    MetadataGenerationNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    ParameterPreparationNode,
    PlanningNode,
    RequirementsAnalysisNode,
    ResultPreparationNode,
    ValidatorNode,
    WorkflowDiscoveryNode,
    WorkflowGeneratorNode,
)


class TestFlowStructure:
    """Test the planner flow structure without execution."""

    def test_flow_has_correct_start_node(self):
        """Test that the flow starts with WorkflowDiscoveryNode."""
        flow = create_planner_flow(wait=0)

        assert flow.start_node is not None
        assert isinstance(flow.start_node, WorkflowDiscoveryNode)
        assert flow.start_node.name == "workflow-discovery"

    def test_all_nodes_are_connected(self):
        """Test that all 11 nodes are connected in the flow."""
        flow = create_planner_flow(wait=0)

        # Collect all nodes by traversing successors
        visited_nodes = set()
        nodes_to_visit = [flow.start_node]

        while nodes_to_visit:
            node = nodes_to_visit.pop(0)
            if node in visited_nodes:
                continue
            visited_nodes.add(node)

            # Add all successors
            for successor in node.successors.values():
                if successor not in visited_nodes:
                    nodes_to_visit.append(successor)

        # Check we have all 11 node types
        node_types = {type(node).__name__ for node in visited_nodes}
        expected_types = {
            "WorkflowDiscoveryNode",
            "ComponentBrowsingNode",
            "ParameterDiscoveryNode",
            "RequirementsAnalysisNode",
            "PlanningNode",
            "ParameterMappingNode",
            "ParameterPreparationNode",
            "WorkflowGeneratorNode",
            "ValidatorNode",
            "MetadataGenerationNode",
            "ResultPreparationNode",
        }

        assert node_types == expected_types
        assert len(visited_nodes) == 11  # 11 nodes after removing RuntimeValidationNode

    def test_path_a_edges(self):
        """Test Path A edges: Discovery → ParameterMapping → Preparation → Result."""
        flow = create_planner_flow(wait=0)

        # Get nodes
        discovery = flow.start_node

        # Check discovery has "found_existing" edge
        assert "found_existing" in discovery.successors
        param_mapping = discovery.successors["found_existing"]
        assert isinstance(param_mapping, ParameterMappingNode)

        # Check parameter mapping has both edges
        assert "params_complete" in param_mapping.successors
        assert "params_incomplete" in param_mapping.successors

        # Check params_complete leads to preparation
        param_prep = param_mapping.successors["params_complete"]
        assert isinstance(param_prep, ParameterPreparationNode)

        # Check params_incomplete leads to result
        result = param_mapping.successors["params_incomplete"]
        assert isinstance(result, ResultPreparationNode)

        # Check preparation leads to result (default transition)
        assert "default" in param_prep.successors
        assert param_prep.successors["default"] is result

    def test_path_b_edges(self):
        """Test Path B edges: Discovery → ParamDisc → Requirements → Browse → Planning → Generate → Validate."""
        flow = create_planner_flow(wait=0)

        # Get nodes
        discovery = flow.start_node

        # Check discovery has "not_found" edge leading to parameter discovery (MOVED)
        assert "not_found" in discovery.successors
        param_disc = discovery.successors["not_found"]
        assert isinstance(param_disc, ParameterDiscoveryNode)

        # Check parameter discovery leads to requirements analysis (default)
        assert "default" in param_disc.successors
        requirements = param_disc.successors["default"]
        assert isinstance(requirements, RequirementsAnalysisNode)

        # Check requirements analysis leads to component browsing (default)
        assert "default" in requirements.successors
        browsing = requirements.successors["default"]
        assert isinstance(browsing, ComponentBrowsingNode)

        # Check component browsing leads to planning (generate)
        assert "generate" in browsing.successors
        planning = browsing.successors["generate"]
        assert isinstance(planning, PlanningNode)

        # Check planning leads to generator (default)
        assert "default" in planning.successors
        generator = planning.successors["default"]
        assert isinstance(generator, WorkflowGeneratorNode)

        # VALIDATION REDESIGN: Generator now leads to ParameterMapping first
        # Check generator leads to parameter mapping (validate action but goes to mapping)
        assert "validate" in generator.successors
        param_mapping = generator.successors["validate"]
        assert isinstance(param_mapping, ParameterMappingNode)

    def test_retry_loop_edges(self):
        """Test the retry loop: Validator → Generator."""
        flow = create_planner_flow(wait=0)

        # Navigate to validator (NEW PATH: Discovery → ParamDisc → Requirements → Browse → Planning → Generator)
        discovery = flow.start_node
        param_disc = discovery.successors["not_found"]
        requirements = param_disc.successors["default"]
        browsing = requirements.successors["default"]
        planning = browsing.successors["generate"]
        generator = planning.successors["default"]
        # Generator now goes to ParameterMapping first
        param_mapping = generator.successors["validate"]
        # From ParameterMapping, if params complete for generated workflow → Validator
        validator = param_mapping.successors["params_complete_validate"]

        # Check validator has all three edges
        assert "retry" in validator.successors
        assert "metadata_generation" in validator.successors
        assert "failed" in validator.successors

        # Check retry loops back to generator
        assert validator.successors["retry"] is generator

        # Check metadata_generation leads directly to metadata node
        metadata = validator.successors["metadata_generation"]
        assert isinstance(metadata, MetadataGenerationNode)

        # Check failed leads to result
        result = validator.successors["failed"]
        assert isinstance(result, ResultPreparationNode)

    def test_convergence_at_parameter_mapping(self):
        """Test that both paths use ParameterMappingNode (VALIDATION REDESIGN)."""
        flow = create_planner_flow(wait=0)

        # Get nodes from Path A
        discovery = flow.start_node
        param_mapping_a = discovery.successors["found_existing"]

        # Get nodes from Path B (NEW PATH with Requirements and Planning)
        param_disc = discovery.successors["not_found"]
        requirements = param_disc.successors["default"]
        browsing = requirements.successors["default"]
        planning = browsing.successors["generate"]
        generator = planning.successors["default"]
        # Path B now goes to ParameterMapping immediately after generation
        param_mapping_b = generator.successors["validate"]

        # Verify it's the same node (both paths use the same ParameterMappingNode)
        assert param_mapping_a is param_mapping_b
        assert isinstance(param_mapping_a, ParameterMappingNode)

        # Verify ParameterMappingNode routes differently for each path
        assert "params_complete" in param_mapping_a.successors  # Path A
        assert "params_complete_validate" in param_mapping_a.successors  # Path B
        assert "params_incomplete" in param_mapping_a.successors  # Both paths

    def test_result_node_has_six_entry_points(self):
        """Test that ResultPreparationNode has seven entry points (updated for RuntimeValidationNode)."""
        flow = create_planner_flow(wait=0)

        # Helper to find all predecessors
        def find_predecessors(target_node, all_nodes):
            predecessors = []
            for node in all_nodes:
                for action, successor in node.successors.items():
                    if successor is target_node:
                        predecessors.append((node, action))
            return predecessors

        # Collect all nodes
        all_nodes = set()
        nodes_to_visit = [flow.start_node]
        while nodes_to_visit:
            node = nodes_to_visit.pop(0)
            if node in all_nodes:
                continue
            all_nodes.add(node)
            for successor in node.successors.values():
                if successor not in all_nodes:
                    nodes_to_visit.append(successor)

        # Find ResultPreparationNode
        result_node = next(n for n in all_nodes if isinstance(n, ResultPreparationNode))

        # Find predecessors
        predecessors = find_predecessors(result_node, all_nodes)

        # Should have 6 entry points
        assert len(predecessors) == 6

        # Check the six entry points
        predecessor_types = [(type(node).__name__, action) for node, action in predecessors]
        expected_entries = [
            ("ParameterPreparationNode", "default"),  # Success path
            ("ParameterMappingNode", "params_incomplete"),  # Missing params
            ("ValidatorNode", "failed"),  # Generation failed
            ("RequirementsAnalysisNode", "clarification_needed"),  # Vague input
            ("PlanningNode", "impossible_requirements"),  # Can't do with available nodes
            ("PlanningNode", "partial_solution"),  # Missing capabilities
        ]

        for expected in expected_entries:
            assert expected in predecessor_types

    def test_all_action_strings_have_edges(self):
        """Test that all possible action strings have corresponding edges."""
        flow = create_planner_flow(wait=0)

        # Expected action strings for each node type
        expected_actions = {
            WorkflowDiscoveryNode: ["found_existing", "not_found"],
            ComponentBrowsingNode: ["generate"],  # Returns "generate"
            ParameterDiscoveryNode: ["default"],  # Returns "" so uses default
            RequirementsAnalysisNode: ["default", "clarification_needed"],  # New node
            PlanningNode: ["default", "impossible_requirements", "partial_solution"],  # New node
            ParameterMappingNode: [
                "params_complete",
                "params_complete_validate",
                "params_incomplete",
            ],  # VALIDATION REDESIGN
            ParameterPreparationNode: ["default"],  # Returns "" so uses default
            WorkflowGeneratorNode: ["validate"],  # Returns "validate"
            ValidatorNode: ["retry", "metadata_generation", "failed"],
            MetadataGenerationNode: ["default"],  # Returns "" so uses default
            ResultPreparationNode: [],  # Final node, no successors
        }

        # Collect all nodes
        all_nodes = set()
        nodes_to_visit = [flow.start_node]
        while nodes_to_visit:
            node = nodes_to_visit.pop(0)
            if node in all_nodes:
                continue
            all_nodes.add(node)
            for successor in node.successors.values():
                if successor not in all_nodes:
                    nodes_to_visit.append(successor)

        # Check each node has expected edges
        for node in all_nodes:
            node_type = type(node)
            expected = expected_actions.get(node_type, [])
            actual = list(node.successors.keys())

            # ResultPreparationNode should have no successors
            if node_type == ResultPreparationNode:
                assert len(actual) == 0, f"ResultPreparationNode should have no successors, has {actual}"
            else:
                # Other nodes should have expected actions
                assert set(actual) == set(expected), f"{node_type.__name__} has {actual} but expected {expected}"

    def test_no_orphaned_nodes(self):
        """Test that there are no orphaned nodes (unreachable from start)."""
        flow = create_planner_flow(wait=0)

        # Find all reachable nodes
        reachable = set()
        nodes_to_visit = [flow.start_node]

        while nodes_to_visit:
            node = nodes_to_visit.pop(0)
            if node in reachable:
                continue
            reachable.add(node)

            for successor in node.successors.values():
                if successor not in reachable:
                    nodes_to_visit.append(successor)

        # All 11 nodes should be reachable
        assert len(reachable) == 11

        # Check all node types are reachable
        node_types = {type(node).__name__ for node in reachable}
        assert len(node_types) == 11  # 11 nodes after removing RuntimeValidationNode

    def test_flow_is_deterministic(self):
        """Test that creating the flow multiple times produces same structure."""
        flow1 = create_planner_flow(wait=0)
        flow2 = create_planner_flow(wait=0)

        # Both should start with discovery
        assert isinstance(flow1.start_node, type(flow2.start_node))
        assert flow1.start_node.name == flow2.start_node.name

        # Count nodes in both flows
        def count_nodes(flow):
            nodes = set()
            to_visit = [flow.start_node]
            while to_visit:
                node = to_visit.pop(0)
                if node in nodes:
                    continue
                nodes.add(node)
                to_visit.extend(node.successors.values())
            return len(nodes)

        assert count_nodes(flow1) == count_nodes(flow2) == 11  # RuntimeValidationNode removed
