"""PATH A (Reuse) Integration Tests - Metadata and Discovery.

Tests workflow DISCOVERY and REUSE through enhanced metadata.
Focuses on Path A where existing workflows are found and reused.

WHEN TO RUN:
- After changing MetadataGenerationNode
- After changing workflow search/discovery logic
- Before releases to ensure Path A works

WHAT IT VALIDATES:
- Metadata generation enables discovery
- Search keywords improve matching
- Different phrasings find same workflow

DEPENDENCIES:
- Requires RUN_LLM_TESTS=1
- Requires configured LLM API key

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_path_a_metadata_discovery.py -v
"""

import os

import pytest

# For LLM tests, we need to enable the Anthropic model wrapper
# This gives us cache_blocks support which is required for the new architecture
if os.getenv("RUN_LLM_TESTS"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

    install_anthropic_model()

from pflow.planning.nodes import MetadataGenerationNode

pytestmark = pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="LLM tests disabled. Set RUN_LLM_TESTS=1 to run")


class TestPathAMetadataDiscovery:
    """Test Path A workflow discovery through LLM-generated metadata."""

    @pytest.fixture
    def sample_workflow_ir(self):
        """Create a sample GitHub changelog workflow."""
        return {
            "name": "github_changelog",
            "description": "Generate changelog from GitHub issues",
            "nodes": [
                {
                    "id": "fetch",
                    "type": "github-issues",
                    "config": {"repo": "{{repo}}", "state": "closed", "limit": 30},
                },
                {"id": "format", "type": "llm", "config": {"prompt": "Create a changelog from: {{issues}}"}},
                {"id": "save", "type": "write-file", "config": {"path": "CHANGELOG.md", "content": "{{changelog}}"}},
            ],
            "edges": [{"from": "fetch", "to": "format"}, {"from": "format", "to": "save"}],
        }

    def test_metadata_generation_creates_rich_keywords(self, sample_workflow_ir):
        """Test that MetadataGenerationNode creates searchable keywords."""
        # Setup
        metadata_gen = MetadataGenerationNode()
        shared = {
            "generated_workflow": sample_workflow_ir,
            "workflow_ir": sample_workflow_ir,
            "user_input": "Create a changelog from the last 30 GitHub issues",
        }

        # Execute the full node lifecycle
        prep_res = metadata_gen.prep(shared)
        exec_res = metadata_gen.exec(prep_res)
        metadata_gen.post(shared, prep_res, exec_res)

        # Verify metadata was generated
        assert "workflow_metadata" in shared
        metadata = shared["workflow_metadata"]

        # Check metadata quality
        assert metadata["suggested_name"], "Should generate a name"
        assert len(metadata["description"]) > 20, "Should generate meaningful description"
        assert "search_keywords" in metadata, "Should include search keywords"

        # Verify keywords are relevant
        keywords = metadata["search_keywords"]
        assert len(keywords) >= 3, f"Should have at least 3 keywords, got {keywords}"

        # Check for expected terms (at least some should be present)
        keywords_lower = [kw.lower() for kw in keywords]
        expected_terms = ["changelog", "release", "github", "issues", "version", "history"]
        matches = sum(1 for term in expected_terms if any(term in kw for kw in keywords_lower))
        assert matches >= 2, f"Keywords {keywords} should contain terms related to {expected_terms}"

        print(f"Generated metadata name: {metadata['suggested_name']}")
        print(f"Generated description: {metadata['description']}")
        print(f"Generated keywords: {keywords}")

    def test_metadata_improves_semantic_search(self, sample_workflow_ir):
        """Test that metadata helps find workflows with different phrasings."""
        # Generate metadata
        metadata_gen = MetadataGenerationNode()
        shared = {
            "generated_workflow": sample_workflow_ir,
            "workflow_ir": sample_workflow_ir,
            "user_input": "Generate changelog from GitHub pull requests",
        }

        prep_res = metadata_gen.prep(shared)
        exec_res = metadata_gen.exec(prep_res)
        metadata_gen.post(shared, prep_res, exec_res)

        metadata = shared["workflow_metadata"]

        # Test various search queries that should match
        test_queries = [
            "create release notes",
            "summarize github activity",
            "version history report",
            "sprint changelog",
            "what changed recently",
        ]

        # Simple semantic matching simulation
        def would_match(query: str, metadata: dict) -> bool:
            """Check if query would likely match this workflow."""
            query_lower = query.lower()

            # Check description
            if any(word in metadata["description"].lower() for word in query_lower.split()):
                return True

            # Check keywords
            for keyword in metadata.get("search_keywords", []):
                if any(word in keyword.lower() for word in query_lower.split()):
                    return True

            # Check use cases
            for use_case in metadata.get("typical_use_cases", []):
                if any(word in use_case.lower() for word in query_lower.split()):
                    return True

            return False

        # Count how many queries would match
        matches = sum(1 for query in test_queries if would_match(query, metadata))

        print("\nMetadata matching results:")
        for query in test_queries:
            result = "✓" if would_match(query, metadata) else "✗"
            print(f"  {result} '{query}'")

        assert matches >= 2, f"Only {matches}/{len(test_queries)} queries matched. Metadata may be too narrow."

    def test_metadata_contains_use_cases(self, sample_workflow_ir):
        """Test that metadata includes practical use cases."""
        metadata_gen = MetadataGenerationNode()
        shared = {
            "generated_workflow": sample_workflow_ir,
            "workflow_ir": sample_workflow_ir,
            "user_input": "Create changelog from closed GitHub issues",
        }

        prep_res = metadata_gen.prep(shared)
        exec_res = metadata_gen.exec(prep_res)
        metadata_gen.post(shared, prep_res, exec_res)

        metadata = shared["workflow_metadata"]

        # Check use_cases field
        assert "typical_use_cases" in metadata, "Should include typical_use_cases field"
        use_cases = metadata["typical_use_cases"]

        assert isinstance(use_cases, list), "use_cases should be a list"
        assert len(use_cases) >= 2, f"Should have at least 2 use cases, got {len(use_cases)}"

        # Verify use cases are meaningful
        for i, use_case in enumerate(use_cases):
            assert len(use_case) > 15, f"Use case {i + 1} too short: '{use_case}'"
            # Should be actual use cases, not generic descriptions
            assert not use_case.lower().startswith("use case"), "Should be direct use case descriptions"
            assert not use_case.lower().startswith("example"), "Should be concrete use cases"

        print("\nGenerated use cases:")
        for i, use_case in enumerate(use_cases, 1):
            print(f"  {i}. {use_case}")

    @pytest.mark.parametrize(
        "workflow_type,description,expected_keywords",
        [
            ("data_processing", "Process CSV files and generate statistics", ["csv", "data", "statistics"]),
            ("notification", "Send Slack alerts for critical GitHub issues", ["slack", "alert", "github"]),
            ("reporting", "Generate weekly team productivity report", ["report", "productivity", "team"]),
        ],
    )
    def test_metadata_for_different_workflows(self, workflow_type, description, expected_keywords):
        """Test metadata generation for various workflow types."""
        workflow_ir = {
            "name": workflow_type,
            "description": description,
            "nodes": [
                {"id": "input", "type": "read-file"},
                {"id": "process", "type": "llm"},
                {"id": "output", "type": "write-file"},
            ],
            "edges": [{"from": "input", "to": "process"}, {"from": "process", "to": "output"}],
        }

        metadata_gen = MetadataGenerationNode()
        shared = {
            "generated_workflow": workflow_ir,  # MetadataGenerationNode expects generated_workflow
            "workflow_ir": workflow_ir,
            "user_input": description,  # MetadataGenerationNode expects user_input
        }

        prep_res = metadata_gen.prep(shared)
        exec_res = metadata_gen.exec(prep_res)
        metadata_gen.post(shared, prep_res, exec_res)

        metadata = shared["workflow_metadata"]

        # Check that keywords capture the essence
        keywords_text = " ".join(metadata.get("search_keywords", [])).lower()
        matched = sum(1 for kw in expected_keywords if kw in keywords_text or kw in metadata["description"].lower())

        assert matched >= 2, (
            f"Workflow '{workflow_type}' metadata doesn't capture expected terms. "
            f"Expected: {expected_keywords}, Got keywords: {metadata.get('search_keywords', [])}"
        )

    def test_metadata_prevents_duplicates(self):
        """Test that good metadata would prevent duplicate workflow creation."""
        # Create two similar requests that should map to the same workflow
        requests = ["Analyze GitHub issues for bug patterns", "Create a bug triage report from GitHub issues"]

        metadata_results = []

        for request in requests:
            workflow_ir = {
                "name": "github_analyzer",
                "description": request,
                "nodes": [{"id": "fetch", "type": "github-issues"}, {"id": "analyze", "type": "llm"}],
                "edges": [{"from": "fetch", "to": "analyze"}],
            }

            metadata_gen = MetadataGenerationNode()
            shared = {"generated_workflow": workflow_ir, "workflow_ir": workflow_ir, "user_input": request}

            prep_res = metadata_gen.prep(shared)
            exec_res = metadata_gen.exec(prep_res)
            metadata_gen.post(shared, prep_res, exec_res)

            metadata_results.append(shared["workflow_metadata"])

        # Check that both generate similar keywords
        keywords1 = {k.lower() for k in metadata_results[0].get("search_keywords", [])}
        keywords2 = {k.lower() for k in metadata_results[1].get("search_keywords", [])}

        # Should have significant overlap
        overlap = keywords1.intersection(keywords2)
        assert len(overlap) >= 2, (
            f"Similar requests should generate overlapping keywords. "
            f"Request 1 keywords: {keywords1}, Request 2 keywords: {keywords2}, Overlap: {overlap}"
        )

        print("\nKeyword overlap for similar requests:")
        print(f"  Request 1: {requests[0][:50]}...")
        print(f"  Keywords: {list(keywords1)[:5]}")
        print(f"  Request 2: {requests[1][:50]}...")
        print(f"  Keywords: {list(keywords2)[:5]}")
        print(f"  Overlap: {overlap}")

    def test_north_star_example_changelog(self):
        """Test the critical North Star use case: changelog generation."""
        workflow_ir = {
            "name": "sprint_changelog",
            "description": "Generate sprint changelog from GitHub PRs",
            "nodes": [
                {"id": "fetch_prs", "type": "github-pulls", "config": {"repo": "{{repo}}", "state": "merged"}},
                {"id": "generate", "type": "llm", "config": {"prompt": "Create changelog from PRs: {{pulls}}"}},
                {"id": "save", "type": "write-file", "config": {"path": "CHANGELOG.md"}},
            ],
            "edges": [{"from": "fetch_prs", "to": "generate"}, {"from": "generate", "to": "save"}],
        }

        metadata_gen = MetadataGenerationNode()
        shared = {
            "generated_workflow": workflow_ir,
            "workflow_ir": workflow_ir,
            "user_input": "Generate a changelog from merged pull requests in the last sprint",
        }

        prep_res = metadata_gen.prep(shared)
        exec_res = metadata_gen.exec(prep_res)
        metadata_gen.post(shared, prep_res, exec_res)

        metadata = shared["workflow_metadata"]

        # Critical terms that MUST be discoverable
        critical_terms = ["changelog", "release", "sprint", "pull request", "pr", "merge"]

        # Check metadata captures these concepts
        all_text = (
            metadata["description"].lower()
            + " "
            + " ".join(metadata.get("search_keywords", [])).lower()
            + " "
            + " ".join(metadata.get("typical_use_cases", [])).lower()
        )

        found_terms = [term for term in critical_terms if term in all_text]

        assert len(found_terms) >= 3, (
            f"North Star changelog workflow must be discoverable. "
            f"Found only {len(found_terms)}/{len(critical_terms)} critical terms: {found_terms}"
        )

        print("\nNorth Star changelog metadata coverage:")
        for term in critical_terms:
            status = "✓" if term in all_text else "✗"
            print(f"  {status} '{term}'")
