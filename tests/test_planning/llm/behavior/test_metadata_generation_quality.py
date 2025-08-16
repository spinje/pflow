"""Test MetadataGenerationNode with real LLM for quality and discoverability.

WHEN TO RUN:
- After modifying MetadataGenerationNode's prompt or logic
- After changing WorkflowMetadata schema
- Before releases to ensure metadata quality

WHAT IT VALIDATES:
- LLM generates high-quality, searchable metadata
- Descriptions capture workflow purpose, not just mechanics
- Search keywords enable discovery with alternative queries
- Metadata enables Path A workflow reuse

DEPENDENCIES:
- Requires RUN_LLM_TESTS=1 environment variable
- Requires configured LLM API key (llm keys set anthropic)
"""

import os

import pytest

from pflow.planning.nodes import MetadataGenerationNode

pytestmark = pytest.mark.skipif(not os.getenv("RUN_LLM_TESTS"), reason="LLM tests disabled. Set RUN_LLM_TESTS=1 to run")


class TestMetadataGenerationQuality:
    """Test that LLM generates high-quality metadata for workflow discovery."""

    def test_changelog_workflow_metadata_quality(self):
        """Test metadata generation for a GitHub changelog workflow."""
        # Setup
        node = MetadataGenerationNode(wait=0)
        node.params = {"temperature": 0.3}

        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {
                    "repo": {"type": "string", "required": True, "description": "Repository name"},
                    "since": {"type": "string", "required": False, "description": "Date filter"},
                },
                "nodes": [
                    {"id": "fetch", "type": "github-list-issues", "params": {"repo": "${repo}", "state": "closed"}},
                    {
                        "id": "analyze",
                        "type": "llm",
                        "params": {"prompt": "Categorize these issues into features, fixes, and breaking changes"},
                    },
                    {
                        "id": "write",
                        "type": "write-file",
                        "params": {"path": "CHANGELOG.md", "content": "${changelog}"},
                    },
                ],
                "edges": [{"from": "fetch", "to": "analyze"}, {"from": "analyze", "to": "write"}],
            },
            "user_input": "Create a changelog by fetching the last 30 closed issues from github repo pflow, analyze them for features and fixes, then write to CHANGELOG.md",
            "discovered_params": {"repo": "pflow", "limit": "30", "file": "CHANGELOG.md"},
            "planning_context": "User wants to generate release documentation",
        }

        # Execute
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Verify quality metrics
        assert "suggested_name" in exec_res
        assert "description" in exec_res
        assert "search_keywords" in exec_res
        assert "capabilities" in exec_res

        # Check name quality
        name = exec_res["suggested_name"]
        assert len(name) <= 50, "Name too long"
        assert "-" in name, "Should be kebab-case"
        assert "changelog" in name.lower() or "release" in name.lower(), "Name should indicate purpose"

        # Check description quality
        description = exec_res["description"]
        assert 100 <= len(description) <= 500, f"Description length {len(description)} out of range"
        assert any(term in description.lower() for term in ["changelog", "release", "documentation"]), (
            "Description should mention key purpose"
        )
        assert any(term in description.lower() for term in ["github", "issues"]), (
            "Description should mention data source"
        )

        # Check search keywords
        keywords = exec_res["search_keywords"]
        assert len(keywords) >= 3, "Need at least 3 search keywords"
        assert len(keywords) <= 10, "Too many keywords"

        # Verify keywords enable discovery
        keyword_terms = " ".join(keywords).lower()
        assert any(term in keyword_terms for term in ["release", "changelog", "history", "notes"]), (
            "Keywords should include alternative terms for changelog"
        )

        # Check capabilities
        capabilities = exec_res["capabilities"]
        assert len(capabilities) >= 2, "Need at least 2 capabilities"
        assert any("github" in cap.lower() or "issue" in cap.lower() for cap in capabilities), (
            "Should mention GitHub integration"
        )

    def test_issue_triage_workflow_metadata(self):
        """Test metadata for issue categorization workflow."""
        node = MetadataGenerationNode(wait=0)
        node.params = {"temperature": 0.3}

        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {
                    "repository": {"type": "string", "required": True},
                    "labels": {"type": "array", "required": False},
                },
                "nodes": [
                    {
                        "id": "fetch",
                        "type": "github-list-issues",
                        "params": {"repo": "${repository}", "labels": "${labels}"},
                    },
                    {"id": "categorize", "type": "llm", "params": {"prompt": "Categorize by priority and type"}},
                    {"id": "report", "type": "write-file", "params": {"path": "triage.md"}},
                ],
                "edges": [{"from": "fetch", "to": "categorize"}, {"from": "categorize", "to": "report"}],
            },
            "user_input": "Create an issue triage report for open bugs, categorize by priority",
            "discovered_params": {"state": "open", "labels": ["bug"]},
            "planning_context": "Workflow for issue management and prioritization",
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Verify metadata captures triage/categorization purpose
        description = exec_res["description"]
        assert any(term in description.lower() for term in ["triage", "categorize", "prioritize", "organize"]), (
            f"Description should mention triage purpose: {description}"
        )

        # Check keywords enable discovery with different terms
        keywords = exec_res["search_keywords"]
        keyword_text = " ".join(keywords).lower()
        assert any(term in keyword_text for term in ["triage", "priority", "categorize", "bugs"]), (
            f"Keywords should enable discovery: {keywords}"
        )

    def test_metadata_enables_discovery_variations(self):
        """Test that metadata enables discovery with query variations."""
        node = MetadataGenerationNode(wait=0)

        # Test with a data processing workflow
        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {"csv_file": {"type": "string", "required": True}},
                "nodes": [
                    {"id": "read", "type": "read-file", "params": {"path": "${csv_file}"}},
                    {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze CSV data and summarize"}},
                    {"id": "save", "type": "write-file", "params": {"path": "analysis.json"}},
                ],
                "edges": [{"from": "read", "to": "analyze"}, {"from": "analyze", "to": "save"}],
            },
            "user_input": "Read sales.csv file, analyze the data for trends, and save summary",
            "discovered_params": {"csv_file": "sales.csv"},
            "planning_context": "Data analysis workflow",
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Metadata should enable discovery with various queries
        all_text = (
            exec_res["description"]
            + " "
            + " ".join(exec_res["search_keywords"])
            + " "
            + " ".join(exec_res.get("capabilities", []))
        ).lower()

        # Should be findable with different phrasings
        alternative_queries = ["analyze csv", "data analysis", "summarize data", "process file", "trend analysis"]

        matches = sum(1 for query in alternative_queries if any(word in all_text for word in query.split()))

        assert matches >= 3, (
            f"Metadata should enable discovery with at least 3 alternative queries. Matched {matches}/5"
        )

    def test_metadata_consistency_across_runs(self):
        """Test that metadata generation is consistent with low temperature."""
        node = MetadataGenerationNode(wait=0)
        node.params = {"temperature": 0.1}  # Very low for consistency

        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {"url": {"type": "string", "required": True}},
                "nodes": [
                    {"id": "fetch", "type": "http-get", "params": {"url": "${url}"}},
                    {"id": "process", "type": "llm", "params": {"prompt": "Extract key information"}},
                ],
                "edges": [{"from": "fetch", "to": "process"}],
            },
            "user_input": "Fetch data from API and extract key information",
            "discovered_params": {"url": "https://api.example.com"},
            "planning_context": "API data extraction",
        }

        # Run twice
        prep_res1 = node.prep(shared)
        exec_res1 = node.exec(prep_res1)

        prep_res2 = node.prep(shared)
        exec_res2 = node.exec(prep_res2)

        # Names should be similar (not necessarily identical)
        name1 = exec_res1["suggested_name"]
        name2 = exec_res2["suggested_name"]

        # Check key terms appear in both
        key_terms = ["api", "fetch", "extract", "data", "http"]
        terms_in_name1 = sum(1 for term in key_terms if term in name1.lower())
        terms_in_name2 = sum(1 for term in key_terms if term in name2.lower())

        assert abs(terms_in_name1 - terms_in_name2) <= 1, f"Names should be consistent: {name1} vs {name2}"

    def test_metadata_handles_complex_workflows(self):
        """Test metadata generation for complex multi-step workflows."""
        node = MetadataGenerationNode(wait=0)

        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {
                    "repo": {"type": "string", "required": True},
                    "since_date": {"type": "string", "required": False},
                    "output_format": {"type": "string", "required": False},
                },
                "nodes": [
                    {"id": "issues", "type": "github-list-issues", "params": {"repo": "${repo}"}},
                    {"id": "commits", "type": "git-log", "params": {"since": "${since_date}"}},
                    {"id": "analyze_issues", "type": "llm", "params": {"prompt": "Analyze issues"}},
                    {"id": "analyze_commits", "type": "llm", "params": {"prompt": "Analyze commits"}},
                    {"id": "combine", "type": "llm", "params": {"prompt": "Create comprehensive report"}},
                    {"id": "format", "type": "llm", "params": {"prompt": "Format as ${output_format}"}},
                    {"id": "save", "type": "write-file", "params": {"path": "report.md"}},
                ],
                "edges": [
                    {"from": "issues", "to": "analyze_issues"},
                    {"from": "commits", "to": "analyze_commits"},
                    {"from": "analyze_issues", "to": "combine"},
                    {"from": "analyze_commits", "to": "combine"},
                    {"from": "combine", "to": "format"},
                    {"from": "format", "to": "save"},
                ],
            },
            "user_input": "Generate comprehensive development report combining GitHub issues and git commits, analyze both, create summary",
            "discovered_params": {"repo": "pflow", "output_format": "markdown"},
            "planning_context": "Complex reporting workflow",
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Complex workflow should have comprehensive metadata
        assert len(exec_res["description"]) >= 150, "Complex workflow needs detailed description"
        assert len(exec_res["search_keywords"]) >= 5, "Complex workflow needs more keywords"
        assert len(exec_res["capabilities"]) >= 3, "Should list multiple capabilities"

        # Should mention both data sources
        all_text = exec_res["description"].lower()
        assert "issue" in all_text and "commit" in all_text, "Should mention both GitHub issues and commits"

    def test_metadata_includes_use_cases(self):
        """Test that metadata includes typical use cases."""
        node = MetadataGenerationNode(wait=0)

        shared = {
            "generated_workflow": {
                "ir_version": "0.1.0",
                "inputs": {"directory": {"type": "string", "required": True}},
                "nodes": [
                    {"id": "list", "type": "list-files", "params": {"path": "${directory}"}},
                    {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze codebase structure"}},
                    {"id": "report", "type": "write-file", "params": {"path": "structure.md"}},
                ],
                "edges": [{"from": "list", "to": "analyze"}, {"from": "analyze", "to": "report"}],
            },
            "user_input": "Analyze project structure and create documentation",
            "discovered_params": {"directory": "./src"},
            "planning_context": "Documentation generation",
        }

        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        # Should include typical use cases
        assert "typical_use_cases" in exec_res, "Should include use cases"
        use_cases = exec_res["typical_use_cases"]
        assert len(use_cases) >= 1, "Should have at least one use case"
        assert all(len(case) > 10 for case in use_cases), "Use cases should be descriptive"
