"""Comprehensive tests for component browsing prompt with pytest parametrization.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify the component_browsing prompt correctly selects nodes and workflows.

Run with:
  RUN_LLM_TESTS=1 pytest test_browsing_prompt.py -v

WHAT IT VALIDATES:
- Over-inclusive component selection (better to include uncertain components)
- Correct node type identification for various tasks
- Workflow selection as building blocks
- Reasoning quality for selection decisions
- Performance under 2 seconds per selection
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import ComponentBrowsingNode

# Set up logger for immediate failure reporting
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Get failure output file from environment (if running via test_prompt_accuracy.py)
FAILURE_OUTPUT_FILE = os.environ.get("PFLOW_TEST_FAILURE_FILE")


def report_failure(test_name: str, failure_reason: str):
    """Report a test failure immediately via file and logging."""
    # Always log for visibility
    logger.info(f"FAIL_REASON|{test_name}|{failure_reason}")

    # Also print for non-parallel execution
    print(f"FAIL_REASON|{test_name}|{failure_reason}", flush=True)

    # Write to file if provided (for real-time display with parallel execution)
    if FAILURE_OUTPUT_FILE:
        try:
            # Append to file with a lock to handle concurrent writes
            failure_data = {"test": test_name, "reason": failure_reason, "timestamp": time.time()}
            # Write as JSON line for easy parsing
            with open(FAILURE_OUTPUT_FILE, "a") as f:
                f.write(json.dumps(failure_data) + "\n")
                f.flush()
        except Exception:  # noqa: S110
            pass  # Ignore file write errors


# Skip tests unless LLM tests enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


@dataclass
class PromptTestCase:
    """Test case for component browsing prompt."""

    name: str
    user_input: str
    expected_node_types: list[str]  # Node types that SHOULD be selected
    expected_workflow_hints: list[str]  # Workflows that MIGHT be selected (optional)
    must_not_select: list[str]  # Components that should NOT be selected
    category: str
    why_important: str  # Business value of this test


def get_test_cases() -> list[PromptTestCase]:
    """Define domain-driven test cases reflecting real ComponentBrowsingNode usage patterns.

    60% failed discovery (vague domain inputs), 40% explicit creation requests.
    Based on north star examples from architecture/vision/north-star-examples.md.
    """
    return [
        # === GITHUB DOMAIN TESTS (Primary - Complex, 5 tests) ===
        # Failed Discovery → Component Selection
        PromptTestCase(
            "changelog_vague",
            "generate changelog",  # Vague request that failed Path A discovery
            expected_node_types=["github-list-issues", "llm", "write-file", "git-commit", "github-create-pr"],
            expected_workflow_hints=["changelog"],
            must_not_select=["delete-file", "move-file"],  # Irrelevant to changelog domain
            category="github_domain_vague",
            why_important="Tests domain-aware selection from vague failed discovery",
        ),
        # Explicit Creation
        PromptTestCase(
            "changelog_explicit",
            "create changelog from last 20 GitHub issues, write to CHANGELOG.md, commit changes, open PR titled 'Release v1.3'",
            expected_node_types=[
                "github-list-issues",
                "llm",
                "write-file",
                "git-checkout",
                "git-commit",
                "github-create-pr",
            ],
            expected_workflow_hints=["changelog"],
            must_not_select=["delete-file", "move-file"],
            category="github_domain_explicit",
            why_important="Tests explicit north star changelog workflow component selection",
        ),
        # Failed Discovery → Component Selection
        PromptTestCase(
            "issue_triage_vague",
            "triage issues",  # Failed discovery, needs component selection
            expected_node_types=["github-list-issues", "llm", "write-file"],
            expected_workflow_hints=["triage"],
            must_not_select=["git-push", "delete-file"],  # No deployment for triage
            category="github_domain_vague",
            why_important="Tests medium complexity GitHub workflow domain awareness",
        ),
        # Explicit Creation
        PromptTestCase(
            "issue_analysis_explicit",
            "analyze the last 50 open GitHub issues, categorize by priority and type, write report to triage/report-2025-08-21.md",
            expected_node_types=["github-list-issues", "llm", "write-file"],
            expected_workflow_hints=["triage"],
            must_not_select=["github-create-pr", "git-push"],  # Analysis task, no PR needed
            category="github_domain_explicit",
            why_important="Tests explicit medium complexity GitHub workflow",
        ),
        # Explicit Creation - Simple
        PromptTestCase(
            "github_simple",
            "get details for GitHub issue 1234 and summarize it",
            expected_node_types=["github-get-issue", "llm", "write-file"],
            expected_workflow_hints=[],
            must_not_select=["git-commit", "github-create-pr"],  # Simple read operation
            category="github_domain_explicit",
            why_important="Tests simple GitHub workflow component selection",
        ),
        # === DATA PROCESSING DOMAIN TESTS (Secondary - Medium, 4 tests) ===
        # Failed Discovery → Component Selection
        PromptTestCase(
            "data_analysis_vague",
            "analyze data",  # Vague request that failed discovery
            expected_node_types=["read-file", "llm", "write-file"],
            expected_workflow_hints=["analyze"],
            must_not_select=["github-list-issues", "git-commit"],  # No GitHub/Git needed
            category="data_domain_vague",
            why_important="Tests vague data processing domain component selection",
        ),
        # Explicit Creation
        PromptTestCase(
            "csv_analysis_explicit",
            "read CSV files from data/ folder, analyze sales trends, generate insights report to reports/sales-analysis.md",
            expected_node_types=["read-file", "llm", "write-file"],
            expected_workflow_hints=["analyze-csv"],
            must_not_select=["github-list-issues", "git-commit"],  # Pure data processing
            category="data_domain_explicit",
            why_important="Tests explicit data processing workflow matching north star complexity",
        ),
        # Failed Discovery → Component Selection
        PromptTestCase(
            "file_processing_vague",
            "process files",  # Vague file processing request
            expected_node_types=["read-file", "write-file", "llm"],
            expected_workflow_hints=["simple-read"],
            must_not_select=["github-create-pr"],  # No GitHub API needed
            category="data_domain_vague",
            why_important="Tests broad file processing domain component selection",
        ),
        # Explicit Creation
        PromptTestCase(
            "report_generation_explicit",
            "read log files from logs/ directory, extract error patterns, generate summary report",
            expected_node_types=["read-file", "llm", "write-file"],
            expected_workflow_hints=["analyze"],
            must_not_select=["github-list-issues", "delete-file"],  # Log analysis, no cleanup
            category="data_domain_explicit",
            why_important="Tests explicit log analysis workflow component selection",
        ),
        # === EDGE CASES & AMBIGUOUS REQUESTS (Tertiary - Simple, 3 tests) ===
        # Failed Discovery → Very Broad Selection
        PromptTestCase(
            "very_vague_automation",
            "help me automate tasks",  # Extremely vague failed discovery
            expected_node_types=["llm"],  # Minimum - need intelligence to understand automation
            expected_workflow_hints=[],
            must_not_select=[],  # Be very permissive for extremely vague requests
            category="edge_cases_vague",
            why_important="Tests extremely vague request handling with minimal but reasonable selection",
        ),
        # Explicit Creation - Cross-domain
        PromptTestCase(
            "mixed_domain_request",
            "analyze GitHub issues and generate local report files",  # Cross-domain workflow
            expected_node_types=["github-list-issues", "llm", "write-file"],
            expected_workflow_hints=["triage", "analyze"],
            must_not_select=["git-commit"],  # Analysis task, no version control needed
            category="edge_cases_explicit",
            why_important="Tests cross-domain component selection (GitHub + data processing)",
        ),
        # Failed Discovery → Ambiguous Domain
        PromptTestCase(
            "unclear_intent",
            "do something with data",  # Very unclear intent, failed discovery
            expected_node_types=["read-file", "llm", "write-file"],  # Assume file-based data processing
            expected_workflow_hints=["analyze", "simple-read"],
            must_not_select=[],  # Should make reasonable assumptions, be permissive
            category="edge_cases_vague",
            why_important="Tests handling of ambiguous domain requests with reasonable assumptions",
        ),
    ]


class TestComponentBrowsingPrompt:
    """Tests for component browsing prompt behavior."""

    def _validate_prep_result(self, prep_res: dict) -> None:
        """Validate prep result has required structure."""
        assert "model_name" in prep_res
        assert "temperature" in prep_res
        assert "nodes_context" in prep_res
        assert "workflows_context" in prep_res
        assert prep_res["model_name"] == "anthropic/claude-sonnet-4-5"
        assert prep_res["temperature"] == 0.0

    def _validate_exec_result(self, exec_res: dict) -> None:
        """Validate exec result has expected structure."""
        assert isinstance(exec_res, dict)
        assert "node_ids" in exec_res
        assert "workflow_names" in exec_res
        assert "reasoning" in exec_res
        assert isinstance(exec_res["node_ids"], list)
        assert isinstance(exec_res["workflow_names"], list)

    def _check_expected_nodes(self, selected_nodes: list[str], expected_node_types: list[str]) -> list[str]:
        """Check if expected nodes are selected, return missing ones."""
        missing_expected = []
        for expected_type in expected_node_types:
            # Handle partial matches (e.g., "git-" matches any git node)
            if expected_type.endswith("-"):
                found = any(node.startswith(expected_type) for node in selected_nodes)
            else:
                found = expected_type in selected_nodes
            if not found:
                missing_expected.append(expected_type)
        return missing_expected

    def _check_forbidden_nodes(self, selected_nodes: list[str], must_not_select: list[str]) -> list[str]:
        """Check that forbidden nodes are NOT selected, return wrongly selected ones."""
        wrongly_selected = []
        for must_not in must_not_select:
            if must_not.endswith("-"):
                # Check prefix
                wrong = [n for n in selected_nodes if n.startswith(must_not)]
                if wrong:
                    wrongly_selected.extend(wrong)
            else:
                if must_not in selected_nodes:
                    wrongly_selected.append(must_not)
        return wrongly_selected

    def _check_workflow_hints(self, selected_workflows: list[str], expected_workflow_hints: list[str]) -> list[str]:
        """Check workflow hints (optional), return found ones for logging."""
        workflow_hints_found = []
        for hint in expected_workflow_hints:
            found = any(hint in wf.lower() for wf in selected_workflows)
            if found:
                workflow_hints_found.append(hint)
        return workflow_hints_found

    def _validate_reasoning(self, reasoning: str) -> bool:
        """Check if reasoning is meaningful."""
        return len(reasoning) > 20  # At least some explanation

    def _format_failure_reason(
        self, missing_expected: list[str], wrongly_selected: list[str], has_reasoning: bool, selected_nodes: list[str]
    ) -> str:
        """Format failure reason with helpful context."""
        errors = []
        if missing_expected:
            errors.append(f"Missing expected nodes: {missing_expected}")
        if wrongly_selected:
            errors.append(f"Wrongly selected: {wrongly_selected}")
        if not has_reasoning:
            errors.append("Reasoning too short or missing")

        # Include helpful context
        errors.append(f"Selected: {selected_nodes[:10]}")  # First 10 for brevity

        return "; ".join(errors)

    @pytest.fixture(scope="class")
    def fixture(self):
        """Create test workflows and prepare registry context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()

            # Setup WorkflowManager and save test workflows
            manager = WorkflowManager(workflows_dir=str(workflows_dir))

            # Define test workflows that match our test scenarios
            workflows = {
                "generate-changelog": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {
                                "id": "list",
                                "type": "github-list-issues",
                                "params": {"state": "${state}", "limit": "${limit}"},
                            },
                            {"id": "gen", "type": "llm", "params": {"prompt": "Generate changelog"}},
                            {"id": "write", "type": "write-file", "params": {"file_path": "CHANGELOG.md"}},
                            {"id": "pr", "type": "github-create-pr", "params": {"title": "Changelog"}},
                        ],
                        "edges": [
                            {"from": "list", "to": "gen"},
                            {"from": "gen", "to": "write"},
                            {"from": "write", "to": "pr"},
                        ],
                        "inputs": {
                            "state": {"type": "string", "default": "closed"},
                            "limit": {"type": "integer", "default": 20},
                        },
                    },
                    "description": "Generate changelog from GitHub issues and create PR",
                    "metadata": {
                        "search_keywords": ["changelog", "github", "issues", "release"],
                        "capabilities": ["GitHub integration", "Changelog generation", "PR creation"],
                    },
                },
                "issue-triage": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {"id": "list", "type": "github-list-issues", "params": {"state": "open"}},
                            {"id": "triage", "type": "llm", "params": {"prompt": "Triage by priority"}},
                            {"id": "write", "type": "write-file", "params": {"file_path": "triage.md"}},
                        ],
                        "edges": [{"from": "list", "to": "triage"}, {"from": "triage", "to": "write"}],
                        "inputs": {},
                    },
                    "description": "Triage open GitHub issues by priority",
                    "metadata": {
                        "search_keywords": ["triage", "issues", "priority"],
                        "capabilities": ["Issue analysis", "Priority assessment"],
                    },
                },
                "analyze-csv": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {"id": "read", "type": "read-file", "params": {"file_path": "${file}"}},
                            {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze CSV"}},
                            {"id": "write", "type": "write-file", "params": {"file_path": "${output}"}},
                        ],
                        "edges": [{"from": "read", "to": "analyze"}, {"from": "analyze", "to": "write"}],
                        "inputs": {
                            "file": {"type": "string", "required": True},
                            "output": {"type": "string", "default": "analysis.md"},
                        },
                    },
                    "description": "Read and analyze CSV files",
                    "metadata": {
                        "search_keywords": ["csv", "analyze", "data"],
                        "capabilities": ["CSV processing", "Data analysis"],
                    },
                },
                "simple-read": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "${file}"}}],
                        "edges": [],
                        "inputs": {"file": {"type": "string", "required": True}},
                    },
                    "description": "Read a file",
                    "metadata": {
                        "search_keywords": ["read", "file", "load"],
                        "capabilities": ["File reading"],
                    },
                },
            }

            # Save all workflows
            for name, data in workflows.items():
                manager.save(
                    name=name,
                    workflow_ir=data["ir"],
                    description=data["description"],
                    metadata=data.get("metadata"),
                )

            # Prepare fixture data
            yield {"workflow_manager": manager, "workflows_dir": str(workflows_dir)}

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_component_selection_scenario(self, fixture, test_case):
        """Test individual component selection scenario."""
        start_time = time.time()

        # Create ComponentBrowsingNode
        node = ComponentBrowsingNode()
        shared = {"user_input": test_case.user_input, "workflow_manager": fixture["workflow_manager"]}

        try:
            # Run the node lifecycle
            prep_res = node.prep(shared)
            self._validate_prep_result(prep_res)

            # Execute with real LLM
            exec_res = node.exec(prep_res)
            self._validate_exec_result(exec_res)

            # Log the selection for debugging
            logger.info(f"{test_case.name}: selected nodes={exec_res['node_ids']}")
            logger.info(f"{test_case.name}: selected workflows={exec_res['workflow_names']}")

            # Validate selections using helper methods
            selected_nodes = exec_res.get("node_ids", [])
            missing_expected = self._check_expected_nodes(selected_nodes, test_case.expected_node_types)
            wrongly_selected = self._check_forbidden_nodes(selected_nodes, test_case.must_not_select)

            selected_workflows = exec_res.get("workflow_names", [])
            workflow_hints_found = self._check_workflow_hints(selected_workflows, test_case.expected_workflow_hints)

            reasoning = exec_res.get("reasoning", "")
            has_reasoning = self._validate_reasoning(reasoning)

            # Run post to verify it always returns "generate"
            action = node.post(shared, prep_res, exec_res)
            assert action == "generate"

            # Check overall test success
            test_passed = len(missing_expected) == 0 and len(wrongly_selected) == 0 and has_reasoning

            # Performance check
            duration = time.time() - start_time
            perf_passed = duration < 30.0

            if not test_passed:
                failure_reason = self._format_failure_reason(
                    missing_expected, wrongly_selected, has_reasoning, selected_nodes
                )
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            if not perf_passed:
                failure_reason = f"Performance: took {duration:.2f}s, exceeds 30s limit"
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            # Log successful workflow hints for information
            if workflow_hints_found:
                logger.info(f"{test_case.name}: Found workflow hints: {workflow_hints_found}")

        except AssertionError:
            # Re-raise assertion errors as-is
            raise
        except Exception as e:
            # Handle API errors gracefully
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            failure_reason = f"Exception: {e!s}"
            report_failure(test_case.name, failure_reason)
            raise AssertionError(f"[{test_case.name}] {failure_reason}") from e
