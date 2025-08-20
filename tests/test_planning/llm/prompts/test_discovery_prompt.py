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
class TestCase:
    """Test case for discovery prompt."""

    name: str
    user_input: str
    should_find: bool
    expected_workflow_hint: Optional[str]  # Not exact name, just a hint
    confidence_level: Confidence
    category: str
    why_important: str  # Business value of this test


def get_test_cases() -> list[TestCase]:
    """Define all test cases organized by user journey."""
    return [
        # === CORE BEHAVIORS (Must work correctly) ===
        TestCase(
            "exact_match",
            "read a file",
            should_find=True,
            expected_workflow_hint="read",
            confidence_level=Confidence.HIGH,
            category="core",
            why_important="Most basic reuse case must work",
        ),
        TestCase(
            "no_match",
            "send an email notification",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="core",
            why_important="Avoid false matches that would fail",
        ),
        TestCase(
            "semantic_match",
            "triage github issues by priority",
            should_find=True,
            expected_workflow_hint="triage",
            confidence_level=Confidence.HIGH,
            category="core",
            why_important="Semantic understanding is critical",
        ),
        TestCase(
            "parameter_variation",
            "generate changelog for version 2.0",
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="core",
            why_important="Parameters shouldn't affect matching",
        ),
        # === AMBIGUITY HANDLING ===
        TestCase(
            "different_function",
            "analyze github issues",  # Generic vs specific triage
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.MEDIUM,
            category="ambiguous",
            why_important="Distinguish generic from specific functions",
        ),
        TestCase(
            "additional_steps",
            "generate changelog and send to slack",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="ambiguous",
            why_important="Don't match if significant functionality missing",
        ),
        TestCase(
            "different_source",
            "generate changelog from pull requests",  # PRs not issues
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="ambiguous",
            why_important="Data source differences matter",
        ),
        TestCase(
            "wrong_file_type",
            "analyze JSON files",  # When only CSV exists
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="ambiguous",
            why_important="File format incompatibilities",
        ),
        # === EDGE CASES ===
        TestCase(
            "vague_request",
            "changelog",  # Single word
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="edge",
            why_important="Support quick commands from power users",
        ),
        TestCase(
            "overly_specific",
            "generate a changelog for v1.3 from last 20 closed issues from repo pflow to CHANGELOG.md",
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="edge",
            why_important="Handle detailed first-time requests",
        ),
        TestCase(
            "partial_name",
            "triage",  # Partial workflow name
            should_find=True,
            expected_workflow_hint="triage",
            confidence_level=Confidence.HIGH,
            category="edge",
            why_important="Support abbreviated commands",
        ),
        # === MULTIPLE MATCHES ===
        TestCase(
            "ambiguous_github",
            "summarize github",  # Could match changelog OR summarize-pr
            should_find=False,  # Too ambiguous
            expected_workflow_hint=None,
            confidence_level=Confidence.MEDIUM,
            category="multiple",
            why_important="Handle multiple potential matches safely",
        ),
        # === SYNONYMS ===
        TestCase(
            "synonym_pr",
            "create pull request with changelog",  # "pull request" vs "PR"
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="synonyms",
            why_important="Handle common terminology variations",
        ),
        TestCase(
            "synonym_issues",
            "triage bugs",  # "bugs" vs "issues"
            should_find=True,
            expected_workflow_hint="triage",
            confidence_level=Confidence.HIGH,
            category="synonyms",
            why_important="Domain-specific synonyms",
        ),
        # === PERFORMANCE BENCHMARKS ===
        TestCase(
            "perf_changelog",
            "generate changelog",
            should_find=True,
            expected_workflow_hint="changelog",
            confidence_level=Confidence.HIGH,
            category="performance",
            why_important="Basic performance test for common request",
        ),
        TestCase(
            "perf_analyze",
            "analyze data",
            should_find=False,  # No generic data analysis workflow
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="performance",
            why_important="Performance test for non-match",
        ),
        TestCase(
            "perf_triage",
            "triage issues",
            should_find=True,
            expected_workflow_hint="triage",
            confidence_level=Confidence.HIGH,
            category="performance",
            why_important="Performance test for triage",
        ),
        TestCase(
            "perf_deploy",
            "deploy to production",
            should_find=False,
            expected_workflow_hint=None,
            confidence_level=Confidence.LOW,
            category="performance",
            why_important="Performance test for unrelated request",
        ),
        TestCase(
            "perf_read",
            "read file",
            should_find=True,
            expected_workflow_hint="read",
            confidence_level=Confidence.HIGH,
            category="performance",
            why_important="Performance test for simple match",
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

            # Define test workflows
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
                },
                "simple-read": {
                    "ir": {
                        "ir_version": "0.1.0",
                        "nodes": [{"id": "read", "type": "read-file", "params": {"file_path": "${file}"}}],
                        "edges": [],
                        "inputs": {"file": {"type": "string", "required": True}},
                    },
                    "description": "Read a file",
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
                },
            }

            # Save all workflows
            for name, data in workflows.items():
                setup_manager.save(name=name, workflow_ir=data["ir"], description=data["description"])

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

            # Check decision
            expected_action = "found_existing" if test_case.should_find else "not_found"
            decision_correct = action == expected_action

            # Check confidence level
            confidence = exec_res.get("confidence", 0)
            conf_min, conf_max = test_case.confidence_level.value
            confidence_correct = conf_min <= confidence <= conf_max

            # Check workflow name (if applicable)
            workflow_correct = True
            if test_case.should_find and test_case.expected_workflow_hint:
                found_workflow = exec_res.get("workflow_name", "")
                workflow_correct = test_case.expected_workflow_hint in found_workflow.lower()

            # Overall pass/fail
            test_passed = decision_correct and confidence_correct and workflow_correct

            # Performance check
            duration = time.time() - start_time
            perf_passed = duration < 10.0  # GPT models can be slower

            if not test_passed:
                errors = []
                if not decision_correct:
                    errors.append(f"Decision: expected {expected_action}, got {action}")
                if not confidence_correct:
                    errors.append(f"Confidence: expected {conf_min}-{conf_max}, got {confidence:.2f}")
                if not workflow_correct:
                    errors.append(
                        f"Workflow: expected hint '{test_case.expected_workflow_hint}', got '{exec_res.get('workflow_name', '')}'"
                    )

                # Store failure reason for display
                failure_reason = "; ".join(errors)

                # Report failure immediately
                report_failure(test_case.name, failure_reason)

                # Use pytest's built-in assertion with a custom message that includes test name
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            if not perf_passed:
                failure_reason = f"Performance: took {duration:.2f}s, exceeds 10s limit"
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

        except AssertionError:
            # Re-raise assertion errors as-is
            raise
        except Exception as e:
            failure_reason = f"Exception: {e!s}"
            report_failure(test_case.name, failure_reason)
            raise AssertionError(f"[{test_case.name}] {failure_reason}") from e
