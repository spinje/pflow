"""Improved tests for discovery prompt focusing on decision correctness.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

WHAT IT VALIDATES:
- Correct found/not_found decisions (CRITICAL)
- Reasonable confidence levels (INFORMATIONAL)
- Performance under 10 seconds

The key insight: We care about DECISIONS, not exact confidence scores.
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import WorkflowDiscoveryNode

# Set up logger for immediate failure reporting
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Get failure output file from environment
FAILURE_OUTPUT_FILE = os.environ.get("PFLOW_TEST_FAILURE_FILE")


def report_failure(test_name: str, failure_reason: str):
    """Report a test failure immediately via file and logging."""
    logger.info(f"FAIL_REASON|{test_name}|{failure_reason}")
    print(f"FAIL_REASON|{test_name}|{failure_reason}", flush=True)

    if FAILURE_OUTPUT_FILE:
        try:
            failure_data = {"test": test_name, "reason": failure_reason, "timestamp": time.time()}
            with open(FAILURE_OUTPUT_FILE, "a") as f:
                f.write(json.dumps(failure_data) + "\n")
                f.flush()
        except Exception:  # noqa: S110
            pass  # Best effort logging, don't fail the test


# Skip tests unless LLM tests enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


@dataclass
class TestCase:
    """Simplified test case focusing on decision correctness."""

    name: str
    user_input: str
    should_find: bool
    expected_workflow_hint: Optional[str]  # Which workflow should match (if any)
    category: str
    rationale: str  # Why this decision is correct


def get_test_cases() -> list[TestCase]:
    """Define test cases focused on decision correctness."""
    return [
        # === MUST WORK: Clear Matches ===
        TestCase(
            "exact_match_read",
            "read a file",
            should_find=True,
            expected_workflow_hint="read",
            category="exact",
            rationale="Direct match to 'Read a file' workflow",
        ),
        TestCase(
            "exact_match_changelog",
            "generate changelog",
            should_find=True,
            expected_workflow_hint="changelog",
            category="exact",
            rationale="Direct match to changelog generation workflow",
        ),
        TestCase(
            "keyword_match_triage",
            "triage bugs",
            should_find=True,
            expected_workflow_hint="triage",
            category="synonym",
            rationale="'bugs' is synonym for 'issues' in triage workflow",
        ),
        TestCase(
            "single_word_changelog",
            "changelog",
            should_find=True,
            expected_workflow_hint="changelog",
            category="brief",
            rationale="Single word should match if unambiguous",
        ),
        # === MUST WORK: Clear Non-Matches ===
        TestCase(
            "wrong_domain_email",
            "send an email notification",
            should_find=False,
            expected_workflow_hint=None,
            category="wrong_domain",
            rationale="No email capability in any workflow",
        ),
        TestCase(
            "wrong_domain_deploy",
            "deploy to production",
            should_find=False,
            expected_workflow_hint=None,
            category="wrong_domain",
            rationale="No deployment capability in any workflow",
        ),
        TestCase(
            "wrong_format_json",
            "analyze JSON files",
            should_find=False,
            expected_workflow_hint=None,
            category="wrong_format",
            rationale="Only CSV analysis workflow exists, not JSON",
        ),
        TestCase(
            "missing_capability_slack",
            "generate changelog and send to slack",
            should_find=False,
            expected_workflow_hint=None,
            category="missing_feature",
            rationale="Changelog workflow lacks Slack integration",
        ),
        # === PARAMETERS: Should Still Match ===
        TestCase(
            "with_parameters",
            "generate changelog for version 2.0",
            should_find=True,
            expected_workflow_hint="changelog",
            category="parameters",
            rationale="Parameters shouldn't prevent matching",
        ),
        TestCase(
            "specific_file",
            "read config.json",
            should_find=True,
            expected_workflow_hint="read",
            category="parameters",
            rationale="Specific filename shouldn't prevent matching",
        ),
        # === AMBIGUOUS: Reasonable to Not Match ===
        TestCase(
            "vague_analyze",
            "analyze data",
            should_find=False,
            expected_workflow_hint=None,
            category="ambiguous",
            rationale="Too vague - could mean CSV, GitHub, or other analysis",
        ),
        TestCase(
            "generic_github",
            "do something with github",
            should_find=False,
            expected_workflow_hint=None,
            category="ambiguous",
            rationale="Multiple GitHub workflows, unclear which one",
        ),
        # === DATA SOURCE: Important Distinctions ===
        TestCase(
            "wrong_source_pr",
            "generate changelog from pull requests",
            should_find=False,
            expected_workflow_hint=None,
            category="wrong_source",
            rationale="Changelog uses issues, not PRs",
        ),
        TestCase(
            "wrong_source_commits",
            "generate changelog from commits",
            should_find=False,
            expected_workflow_hint=None,
            category="wrong_source",
            rationale="Changelog uses issues, not commits",
        ),
    ]


class TestDiscoveryPromptImproved:
    """Improved tests focusing on decision correctness."""

    @pytest.fixture(scope="class")
    def workflow_directory(self):
        """Create test workflows with rich metadata in a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()

            # Setup manager
            setup_manager = WorkflowManager(workflows_dir=str(workflows_dir))

            # Define workflows with rich metadata
            workflows = {
                "generate-changelog": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {"id": "list", "type": "github-list-issues", "params": {"state": "${state}"}},
                            {"id": "gen", "type": "llm", "params": {"prompt": "Generate changelog"}},
                            {"id": "write", "type": "write-file", "params": {"file_path": "CHANGELOG.md"}},
                            {"id": "pr", "type": "github-create-pr", "params": {"title": "Changelog"}},
                        ],
                        "edges": [
                            {"from": "list", "to": "gen"},
                            {"from": "gen", "to": "write"},
                            {"from": "write", "to": "pr"},
                        ],
                    },
                    "description": "Generate changelog from GitHub issues and create PR",
                    "metadata": {
                        "search_keywords": ["changelog", "github", "issues", "release", "version"],
                        "capabilities": [
                            "GitHub integration",
                            "Issue fetching",
                            "Changelog generation",
                            "Pull request creation",
                        ],
                        "typical_use_cases": ["Release preparation", "Version updates"],
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
                    },
                    "description": "Triage open GitHub issues by priority",
                    "metadata": {
                        "search_keywords": ["triage", "github", "issues", "bugs", "priority"],
                        "capabilities": ["GitHub integration", "Issue analysis", "Priority assessment"],
                        "typical_use_cases": ["Bug triage", "Sprint planning"],
                    },
                },
                "analyze-csv": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {"id": "read", "type": "read-file", "params": {"file_path": "${file}"}},
                            {"id": "analyze", "type": "llm", "params": {"prompt": "Analyze CSV"}},
                        ],
                        "edges": [{"from": "read", "to": "analyze"}],
                    },
                    "description": "Read and analyze CSV files",
                    "metadata": {
                        "search_keywords": ["csv", "analyze", "data", "spreadsheet"],
                        "capabilities": ["CSV file reading", "Data analysis"],
                        "typical_use_cases": ["Data analysis", "CSV processing"],
                    },
                },
                "simple-read": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "${file}"}}],
                        "edges": [],
                    },
                    "description": "Read a file",
                    "metadata": {
                        "search_keywords": ["read", "file", "load", "text"],
                        "capabilities": ["File reading", "Text extraction"],
                        "typical_use_cases": ["Loading configuration", "Reading data"],
                    },
                },
            }

            # Save all workflows with metadata
            for name, data in workflows.items():
                setup_manager.save(
                    name=name,
                    workflow_ir=data["ir"],
                    description=data["description"],
                    metadata=data.get("metadata"),
                )

            yield str(workflows_dir)

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_discovery_decision(self, workflow_directory, test_case):
        """Test that discovery makes the correct decision."""
        start_time = time.time()

        # Create WorkflowManager for this test
        manager = WorkflowManager(workflows_dir=workflow_directory)

        # Run discovery
        node = WorkflowDiscoveryNode()
        shared = {"user_input": test_case.user_input, "workflow_manager": manager}

        try:
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # Check decision correctness (THIS IS WHAT MATTERS)
            expected_action = "found_existing" if test_case.should_find else "not_found"
            decision_correct = action == expected_action

            # Check workflow name (if applicable)
            workflow_correct = True
            if test_case.should_find and test_case.expected_workflow_hint:
                found_workflow = exec_res.get("workflow_name", "")
                workflow_correct = test_case.expected_workflow_hint in found_workflow.lower()

            # Log confidence for information (but don't fail on it)
            confidence = exec_res.get("confidence", 0)
            logger.info(f"{test_case.name}: confidence={confidence:.2f}")

            # Check performance
            duration = time.time() - start_time
            perf_passed = duration < 10.0

            # Build failure message if needed
            if not decision_correct or not workflow_correct or not perf_passed:
                errors = []
                if not decision_correct:
                    errors.append(f"Wrong decision: expected {expected_action}, got {action}")
                if not workflow_correct:
                    errors.append(f"Wrong workflow: expected '{test_case.expected_workflow_hint}' in name")
                if not perf_passed:
                    errors.append(f"Too slow: {duration:.2f}s")

                failure_reason = "; ".join(errors)
                report_failure(test_case.name, failure_reason)

                # Include rationale in error for debugging
                raise AssertionError(
                    f"[{test_case.name}] {failure_reason}\n"
                    f"  Expected: {test_case.rationale}\n"
                    f"  Confidence: {confidence:.2f}"
                )

        except AssertionError:
            raise
        except Exception as e:
            failure_reason = f"Exception: {e!s}"
            report_failure(test_case.name, failure_reason)
            raise AssertionError(f"[{test_case.name}] {failure_reason}") from e
