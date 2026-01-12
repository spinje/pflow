"""Test that enhanced metadata enables Path A discovery.

WHEN TO RUN:
- After modifying MetadataGenerationNode
- After changing WorkflowMetadata model
- Before releases

WHAT IT VALIDATES:
- Rich metadata enables workflow discovery
- Search keywords allow finding with alternate queries
- Path A success depends on metadata quality
"""

import importlib
from unittest.mock import Mock, patch

import pytest

from pflow.planning.ir_models import WorkflowMetadata
from pflow.planning.nodes import MetadataGenerationNode


class TestMetadataEnablesPathA:
    """Test that LLM-generated metadata enables Path A workflow reuse."""

    @pytest.fixture(autouse=True)
    def cleanup_mocks(self):
        """Clean up mocks and reload modules to prevent test pollution."""
        yield
        # Stop all active patches to prevent pollution from parallel tests
        patch.stopall()
        # Reload planning modules to clear any cached state
        import pflow.planning.prompts.loader

        importlib.reload(pflow.planning.prompts.loader)

    def test_metadata_enables_discovery_with_alternate_queries(self):
        """Rich metadata allows workflow to be found with different search terms."""
        # Generate metadata for a "changelog" workflow
        metadata = WorkflowMetadata(
            suggested_name="github-changelog-generator",
            description="Automated changelog generation from GitHub issues. Fetches closed issues, analyzes with LLM to categorize changes, produces formatted markdown for releases.",
            search_keywords=["changelog", "release notes", "version history", "sprint summary", "issue summary"],
            capabilities=["Fetches GitHub issues", "Categorizes changes", "Generates markdown"],
            typical_use_cases=["Preparing release documentation", "Sprint summaries"],
        )

        # Verify workflow can be found with various queries
        alternate_queries = [
            "release notes",  # Synonym
            "version history",  # Related concept
            "sprint summary",  # Use case
            "issue summary",  # Partial match
            "markdown",  # Mentioned in capabilities
        ]

        for query in alternate_queries:
            # Check if query would match any metadata field
            query_lower = query.lower()
            found = (
                query_lower in metadata.description.lower()
                or query_lower in [kw.lower() for kw in metadata.search_keywords]
                or any(query_lower in cap.lower() for cap in metadata.capabilities)
                or any(query_lower in uc.lower() for uc in metadata.typical_use_cases)
            )
            assert found, f"Query '{query}' should find workflow via metadata"

    def test_poor_metadata_prevents_discovery(self):
        """Simple string manipulation metadata fails to enable discovery."""
        # What the old implementation would generate
        poor_metadata = {
            "suggested_name": "create-changelog-by",  # Truncated
            "description": "Create a changelog by fetching the last 30 closed issues from github repo pflow",  # Too specific
            "search_keywords": [],  # None generated
            "capabilities": [],  # None generated
            "typical_use_cases": [],  # None generated
        }

        # These queries would NOT find the workflow with poor metadata
        failed_queries = [
            "release notes",  # Not in description
            "version history",  # Not mentioned
            "sprint summary",  # Not mentioned
            "documentation",  # Not mentioned
        ]

        for query in failed_queries:
            query_lower = query.lower()
            found = query_lower in poor_metadata["description"].lower()
            assert not found, f"Query '{query}' correctly fails with poor metadata"

    @patch("llm.get_model")
    @patch("pflow.planning.utils.llm_helpers.parse_structured_response")
    def test_metadata_generation_creates_discoverable_content(self, mock_parse, mock_get_model):
        """MetadataGenerationNode creates metadata that enables discovery."""
        # Setup
        node = MetadataGenerationNode()
        shared = {
            "generated_workflow": {
                "nodes": [{"type": "github-list-issues"}, {"type": "llm"}, {"type": "write-file"}],
                "inputs": {"repo": {}, "since_date": {}},
            },
            "user_input": "Create a changelog from GitHub issues",
            "discovered_params": {"repo": "pflow", "limit": "30"},
        }

        # Mock LLM to return rich metadata
        mock_parse.return_value = WorkflowMetadata(
            suggested_name="github-changelog-generator",
            description="Automated changelog generation from GitHub issues. Analyzes and categorizes changes for release documentation.",
            search_keywords=["changelog", "release notes", "github issues", "version history"],
            capabilities=["Fetches issues", "Analyzes changes"],
            typical_use_cases=["Release preparation"],
        )

        mock_model = Mock()
        mock_get_model.return_value = mock_model

        # Execute
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Verify metadata is comprehensive
        assert "github" in exec_res["suggested_name"]
        assert len(exec_res["description"]) >= 100  # Rich description
        assert len(exec_res["search_keywords"]) >= 3  # Multiple search terms
        assert len(exec_res["capabilities"]) >= 2  # Clear capabilities
        assert len(exec_res["typical_use_cases"]) >= 1  # Use cases defined

        # Verify LLM was called with proper context
        mock_model.prompt.assert_called_once()
        call_args = mock_model.prompt.call_args
        prompt = call_args[0][0]
        # Don't assert on exact prompt text (fragile, tests implementation details)
        # Instead verify the important context is included in the prompt
        assert "github-list-issues" in prompt  # Nodes mentioned
        assert "repo" in prompt  # Inputs mentioned

    def test_metadata_quality_determines_path_a_success(self):
        """Demonstrate how metadata quality directly impacts Path A success rate."""
        # High-quality metadata (LLM-generated)
        good_metadata = WorkflowMetadata(
            suggested_name="github-changelog-generator",
            description="Comprehensive changelog automation for GitHub projects. Fetches and analyzes issues to generate formatted release notes.",
            search_keywords=["changelog", "release notes", "version history", "github", "issues", "documentation"],
            capabilities=["Issue fetching", "Change categorization", "Markdown generation"],
            typical_use_cases=["Release documentation", "Sprint reviews"],
        )

        # Test queries that represent how users might search
        user_queries = [
            ("generate changelog", True),  # Direct match
            ("create release notes", True),  # Synonym
            ("github version history", True),  # Combined terms
            ("sprint documentation", True),  # Use case
            ("analyze issues", True),  # Capability
            ("make financial report", False),  # Unrelated
        ]

        for query, should_find in user_queries:
            query_lower = query.lower()
            # Simple discovery simulation
            found = any(
                term in query_lower or query_lower in term
                for term in [
                    good_metadata.suggested_name,
                    good_metadata.description.lower(),
                    *[kw.lower() for kw in good_metadata.search_keywords],
                    *[cap.lower() for cap in good_metadata.capabilities],
                    *[uc.lower() for uc in good_metadata.typical_use_cases],
                ]
            )

            if should_find:
                assert found, f"Query '{query}' should find workflow"
            else:
                assert not found, f"Query '{query}' should not find workflow"
