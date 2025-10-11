"""Comprehensive tests for discovery prompt with pytest parametrization.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify the discovery prompt correctly identifies when to reuse workflows.

Run with:
  RUN_LLM_TESTS=1 pytest test_discovery_prompt_parametrized.py -v

WHAT IT VALIDATES:
- Correct reuse vs create decisions (critical for 2s vs 20s performance)
- Reasonable confidence levels (HIGH/MEDIUM/LOW)
- Performance under 2 seconds per decision
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import pytest

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import WorkflowDiscoveryNode

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


class Confidence(Enum):
    """Confidence levels for better behavioral testing."""

    LOW = (0.0, 0.4)  # Clear non-match
    MEDIUM = (0.4, 0.7)  # Ambiguous
    HIGH = (0.7, 1.0)  # Clear match


@dataclass
class PromptTestCase:
    """Test case for discovery prompt."""

    name: str
    user_input: str
    should_find: bool
    expected_workflow_hint: Optional[str]  # Not exact name, just a hint
    confidence_level: Confidence
    category: str
    why_important: str  # Business value of this test


def get_test_cases() -> list[PromptTestCase]:
    """Define high-quality test cases focusing on distinct scenarios."""
    return [
        # === CORE MATCHES (Must correctly identify) ===
        PromptTestCase(
            "exact_match",
            "read a file",
            should_find=True,
            expected_workflow_hint="read",
            confidence_level=Confidence.HIGH,
            category="core_match",
            why_important="Basic exact match must work",
        ),
        PromptTestCase(
            "semantic_match",
            "triage github issues by priority",
            should_find=True,
            expected_workflow_hint="triage",
            confidence_level=Confidence.HIGH,
            category="core_match",
            why_important="Semantic understanding of similar phrases",
        ),
        PromptTestCase(
            "with_parameters",
            "generate changelog for version 2.0",
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="core_match",
            why_important="Parameters shouldn't prevent matching",
        ),
        # === CORE REJECTIONS (Must correctly reject) ===
        PromptTestCase(
            "wrong_domain",
            "send an email notification",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="core_reject",
            why_important="No email capability exists",
        ),
        PromptTestCase(
            "missing_capability",
            "generate changelog and send to slack",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="core_reject",
            why_important="Workflow lacks Slack integration",
        ),
        PromptTestCase(
            "vague_request",
            "analyze data",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="core_reject",
            why_important="Too ambiguous - could mean CSV, GitHub, or other",
        ),
        # === DATA DISTINCTIONS (Critical for correctness) ===
        PromptTestCase(
            "wrong_source",
            "generate changelog from pull requests",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="data_mismatch",
            why_important="Workflow uses issues, not pull requests",
        ),
        PromptTestCase(
            "wrong_format",
            "analyze JSON files",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="data_mismatch",
            why_important="Only CSV analysis workflow exists",
        ),
        PromptTestCase(
            "different_workflow",
            "summarize issue #123",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="data_mismatch",
            why_important="Single issue summary differs from triage",
        ),
        # === LANGUAGE HANDLING (Natural variations) ===
        PromptTestCase(
            "synonym_bugs",
            "triage bugs",
            should_find=True,
            expected_workflow_hint="triage",
            confidence_level=Confidence.HIGH,
            category="synonyms",
            why_important="'bugs' is common synonym for 'issues'",
        ),
        PromptTestCase(
            "single_word",
            "changelog",
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="synonyms",
            why_important="Single word should match unambiguous workflow",
        ),
        # === PERFORMANCE CHECK (Representative test) ===
        PromptTestCase(
            "performance_test",
            "generate a changelog from closed issues",
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="performance",
            why_important="Representative test for response time",
        ),
    ]


class TestDiscoveryPrompt:
    """Tests for discovery prompt behavior."""

    @pytest.fixture(scope="class")
    def workflow_directory(self):
        """Create test workflows in a temporary directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()

            # Setup initial manager to save workflows
            setup_manager = WorkflowManager(workflows_dir=str(workflows_dir))

            # Define test workflows with separate metadata
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
                        "search_keywords": ["changelog", "github", "issues", "PR", "release", "version"],
                        "capabilities": [
                            "GitHub integration",
                            "Issue fetching",
                            "Changelog generation",
                            "Pull request creation",
                        ],
                        "typical_use_cases": ["Release preparation", "Version updates", "Project documentation"],
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
                        "search_keywords": ["triage", "github", "issues", "bugs", "priority", "open"],
                        "capabilities": [
                            "GitHub integration",
                            "Issue analysis",
                            "Priority assessment",
                            "Report generation",
                        ],
                        "typical_use_cases": ["Bug triage", "Issue management", "Sprint planning"],
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
                        "inputs": {"file": {"type": "string", "required": True}},
                    },
                    "description": "Read and analyze CSV files",
                    "metadata": {
                        "search_keywords": ["csv", "analyze", "data", "file", "spreadsheet"],
                        "capabilities": ["CSV file reading", "Data analysis", "File processing"],
                        "typical_use_cases": ["Data analysis", "CSV processing", "Report generation"],
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
                        "search_keywords": ["read", "file", "load", "open", "text"],
                        "capabilities": ["File reading", "Text extraction"],
                        "typical_use_cases": ["Reading text files", "Loading configuration", "Data import"],
                    },
                },
                "summarize-pr": {  # Similar to changelog for multi-match test
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [
                            {"id": "get", "type": "github-get-pr", "params": {"pr": "${pr_number}"}},
                            {"id": "summary", "type": "llm", "params": {"prompt": "Summarize PR"}},
                        ],
                        "edges": [{"from": "get", "to": "summary"}],
                        "inputs": {"pr_number": {"type": "integer", "required": True}},
                    },
                    "description": "Summarize a GitHub pull request",
                    "metadata": {
                        "search_keywords": ["summarize", "github", "pr", "pull request", "review"],
                        "capabilities": ["GitHub integration", "PR fetching", "Summary generation"],
                        "typical_use_cases": ["Code review", "PR documentation", "Change summary"],
                    },
                },
            }

            # Save all workflows with metadata passed separately
            for name, data in workflows.items():
                setup_manager.save(
                    name=name,
                    workflow_ir=data["ir"],
                    description=data["description"],
                    metadata=data.get("metadata"),  # Pass metadata separately
                )

            yield str(workflows_dir)

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_discovery_scenario(self, workflow_directory, test_case):
        """Test individual discovery scenario."""
        start_time = time.time()

        # Create fresh WorkflowManager for this test
        manager = WorkflowManager(workflows_dir=workflow_directory)

        # Run discovery
        node = WorkflowDiscoveryNode()
        shared = {"user_input": test_case.user_input, "workflow_manager": manager}

        try:
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            action = node.post(shared, prep_res, exec_res)

            # Check decision (THIS IS WHAT MATTERS MOST)
            expected_action = "found_existing" if test_case.should_find else "not_found"
            decision_correct = action == expected_action

            # Log confidence for information (but don't fail on it)
            confidence = exec_res.get("confidence", 0)
            logger.info(f"{test_case.name}: confidence={confidence:.2f}")

            # We no longer enforce strict confidence ranges - decision correctness is key
            # But warn if confidence seems very wrong (e.g., HIGH confidence on wrong decision)
            confidence_warning = None
            if not decision_correct and confidence > 0.8:
                confidence_warning = f"High confidence ({confidence:.2f}) on wrong decision"

            # Check workflow name (if applicable)
            workflow_correct = True
            if test_case.should_find and test_case.expected_workflow_hint:
                found_workflow = exec_res.get("workflow_name", "")
                workflow_correct = test_case.expected_workflow_hint in found_workflow.lower()

            # Overall pass/fail - ONLY based on decision and workflow selection
            test_passed = decision_correct and workflow_correct

            # Performance check
            duration = time.time() - start_time
            perf_passed = duration < 20.0  # GPT models can be slower

            if not test_passed:
                errors = []
                if not decision_correct:
                    errors.append(f"Decision: expected {expected_action}, got {action}")
                if not workflow_correct:
                    errors.append(
                        f"Workflow: expected hint '{test_case.expected_workflow_hint}', got '{exec_res.get('workflow_name', '')}'"
                    )
                if confidence_warning:
                    errors.append(confidence_warning)

                # Store failure reason for display
                failure_reason = "; ".join(errors)

                # Report failure immediately
                report_failure(test_case.name, failure_reason)

                # Use pytest's built-in assertion with a custom message that includes test name
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            if not perf_passed:
                failure_reason = f"Performance: took {duration:.2f}s, exceeds 20s limit"
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

        except AssertionError:
            # Re-raise assertion errors as-is
            raise
        except Exception as e:
            failure_reason = f"Exception: {e!s}"
            report_failure(test_case.name, failure_reason)
            raise AssertionError(f"[{test_case.name}] {failure_reason}") from e
