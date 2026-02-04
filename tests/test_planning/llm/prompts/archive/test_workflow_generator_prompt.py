"""Comprehensive tests for workflow_generator prompt with pytest parametrization.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

WHAT THESE TESTS VALIDATE:
--------------------------
These tests validate that WorkflowGeneratorNode creates STRUCTURALLY VALID workflows,
not that workflows can execute with specific runtime values. This is intentional.

The tests verify:
1. Workflows are structurally correct (valid JSON schema)
2. Data flow is valid (no forward references, proper execution order)
3. All node types exist in the registry (no hallucinated nodes)
4. All template variables are declared in workflow.inputs
5. Generated workflows follow quality standards (descriptive purposes, etc.)

The tests do NOT verify:
- Whether specific runtime values can resolve all template paths
- This is ParameterMappingNode's responsibility in the real planner

This separation matches the real planner architecture where:
- WorkflowGeneratorNode creates the workflow structure
- ParameterMappingNode extracts runtime values
- WorkflowValidatorNode validates with those runtime values

Run with:
  RUN_LLM_TESTS=1 pytest test_workflow_generator_prompt.py -v
"""

import contextlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import pytest

from pflow.planning.context_builder import build_planning_context
from pflow.planning.nodes import WorkflowGeneratorNode
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver

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
        except Exception as e:
            # Best effort - if we can't write to file, at least we logged to console
            logger.debug(f"Failed to write to failure file: {e}")


# Skip tests unless LLM tests enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


@dataclass
class WorkflowTestCase:
    """Test case for workflow generation."""

    name: str
    user_input: str
    discovered_params: dict[str, str]
    browsed_node_ids: list[str]  # Node IDs that were "browsed"
    validation_errors: Optional[list[str]]  # For retry tests
    expected_nodes: list[str]  # Node types in order
    min_nodes: int
    max_nodes: int
    must_have_inputs: list[str]  # Required user inputs
    must_not_have_inputs: list[str]  # Should NOT be user inputs (are node outputs)
    node_output_refs: list[str]  # Expected ${node.output} patterns
    category: str
    why_hard: str
    critical_nodes: Optional[list[str]] = None  # Must have these node types
    allowed_extra_nodes: Optional[list[str]] = None  # Can have these as extras
    browsed_workflow_names: list[str] = field(default_factory=list)  # Workflow names if any

    def get_browsed_components(self) -> dict:
        """Get browsed_components in the correct format for WorkflowGeneratorNode."""
        return {
            "node_ids": self.browsed_node_ids,
            "workflow_names": self.browsed_workflow_names,
            "reasoning": f"Components selected for {self.name} test case",
        }


def build_test_planning_context(browsed_components: dict, include_mcp_mocks: bool = False) -> str:
    """Build planning context using the real context builder, filtered to browsed components.

    This ensures tests use the exact same context formatting as production.

    Args:
        browsed_components: Dict with node_ids, workflow_names, reasoning
        include_mcp_mocks: Whether to include Slack MCP mock nodes

    Returns:
        Formatted planning context string
    """

    # Get real registry data
    registry = Registry()
    registry_data = {}
    with contextlib.suppress(Exception):
        registry_data = registry.load()

    # Add MCP mocks if needed
    if include_mcp_mocks:
        mcp_mocks = {
            "mcp-slack-slack_get_channel_history": {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "interface": {
                    "description": "Get Slack channel history",
                    "inputs": [
                        {"key": "channel_id", "type": "str", "description": "Slack channel ID"},
                        {"key": "limit", "type": "int", "description": "Number of messages to retrieve"},
                    ],
                    "outputs": [
                        {"key": "messages", "type": "list", "description": "Channel messages"},
                        {"key": "channel_info", "type": "dict", "description": "Channel information"},
                    ],
                    "params": [],
                },
            },
            "mcp-slack-slack_post_message": {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "interface": {
                    "description": "Post message to Slack channel",
                    "inputs": [
                        {"key": "channel_id", "type": "str", "description": "Slack channel ID"},
                        {"key": "text", "type": "str", "description": "Message text to post"},
                    ],
                    "outputs": [
                        {"key": "message_id", "type": "str", "description": "Posted message ID"},
                        {"key": "timestamp", "type": "str", "description": "Message timestamp"},
                    ],
                    "params": [],
                },
            },
        }
        registry_data.update(mcp_mocks)

    # Use real context builder with filtering
    try:
        context = build_planning_context(
            selected_node_ids=browsed_components.get("node_ids", []),
            selected_workflow_names=browsed_components.get("workflow_names", []),
            registry_metadata=registry_data,
            saved_workflows=[],
        )

        # If context is a dict (error case), return a simple fallback
        if isinstance(context, dict):
            # Build simple context manually
            lines = ["Available nodes:"]
            for node_id in browsed_components.get("node_ids", []):
                if node_id in registry_data:
                    lines.append(f"- {node_id}")
            return "\n".join(lines)

        return context
    except Exception:
        # Fallback to simple format if context builder fails
        lines = ["Available nodes:"]
        for node_id in browsed_components.get("node_ids", []):
            lines.append(f"- {node_id}")
        return "\n".join(lines)


def get_test_cases() -> list[WorkflowTestCase]:
    """Define all test cases for workflow generation.

    This now uses ONLY real nodes from the registry plus 2 Slack MCP mocks.
    Shell workarounds are used for missing git/github features.
    """

    return [
        # Test 1: North Star - Changelog Generation ⭐
        WorkflowTestCase(
            name="changelog_from_issues",
            user_input="Get the last 20 closed issues from github repo spinje/pflow, group them into sections (Features, Bugs, Documentation) based on their labels, create a markdown changelog with '## Version X.Y.Z' header and bullet points for each issue showing number and title, write to CHANGELOG.md, then commit with message 'Update changelog for release'",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "issue_limit": "20",
                "changelog_file": "CHANGELOG.md",
                "commit_message": "Update changelog",
            },
            browsed_node_ids=["github-list-issues", "llm", "write-file", "git-commit"],
            validation_errors=None,
            expected_nodes=["github-list-issues", "llm", "write-file", "git-commit"],
            min_nodes=4,
            max_nodes=5,
            must_have_inputs=["repo_owner", "repo_name", "issue_limit", "changelog_file", "commit_message"],
            must_not_have_inputs=["issues", "changelog"],
            node_output_refs=["list_issues.issues", "generate.response"],
            category="north_star",
            why_hard="Primary example showing GitHub → LLM → Git pipeline",
            critical_nodes=["github-list-issues", "llm", "write-file", "git-commit"],  # ALL expected nodes
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
        # Test 2: Multi-Repository Dependency Security Audit (HARDER)
        WorkflowTestCase(
            name="security_audit_pipeline",
            user_input="Check if package.json exists using 'test -f package.json', if it exists run 'npm audit --json'. Check if requirements.txt exists using 'test -f requirements.txt', if it exists run 'pip-audit requirements.txt --format json'. Run 'trivy fs . --format json --scanners vuln' for overall scan. Get GitHub issues with label 'security' or 'vulnerability' from repo spinje/pflow. Parse all security reports extracting critical and high severity issues, correlate with GitHub issues, generate unified security report with vulnerabilities by severity and affected packages grouped by ecosystem. Write report to security-audit.md and machine-readable vulnerabilities.json.",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "report_file": "security-audit.md",
                "json_file": "vulnerabilities.json",
            },
            browsed_node_ids=["shell", "github-list-issues", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["shell", "shell", "shell", "github-list-issues", "llm", "write-file", "write-file"],
            min_nodes=8,
            max_nodes=14,  # Complex multi-tool security pipeline - allow extra analysis steps
            must_have_inputs=["repo_owner", "repo_name", "report_file", "json_file"],
            must_not_have_inputs=["vulnerabilities", "issues", "npm_audit", "pip_audit"],
            node_output_refs=["npm_check.stdout", "pip_check.stdout", "trivy.stdout", "get_issues.issues"],
            category="complex_pipeline",
            why_hard="Multiple security tools, JSON parsing, cross-referencing with GitHub",
            critical_nodes=["shell", "github-list-issues", "llm", "write-file"],
            allowed_extra_nodes=["shell", "llm"],  # Multiple shells for different tools
        ),
        # Test 3: Test Generator
        WorkflowTestCase(
            name="test_generator",
            user_input="Read main.py, identify all functions that don't start with underscore, generate pytest unit tests with at least one test per function using assert statements, include import statements, write to test_main.py",
            discovered_params={"source_file": "main.py", "test_file": "test_main.py"},
            browsed_node_ids=["read-file", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["read-file", "llm", "write-file"],
            min_nodes=3,
            max_nodes=5,  # Allow extra processing
            must_have_inputs=["source_file", "test_file"],
            must_not_have_inputs=["content", "tests"],
            node_output_refs=["read.content", "generate.response"],
            category="developer_workflow",
            why_hard="Common developer task",
            critical_nodes=["read-file", "llm", "write-file"],  # ALL expected nodes
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
        # Test 4: Documentation Updater
        # Note: Less capable models may miss the commit_message parameter - this is a legitimate test of parameter discovery
        WorkflowTestCase(
            name="documentation_updater",
            user_input="Read README.md and api.json, find the section '## API Reference' in README.md, replace it with a new markdown table generated from api.json showing Method, Endpoint, and Description columns, commit with message 'Update API documentation from api.json'",
            discovered_params={
                "readme_file": "README.md",
                "api_file": "api.json",
                "commit_message": "Update README with API changes",
            },
            browsed_node_ids=["read-file", "llm", "write-file", "git-commit"],
            validation_errors=None,
            expected_nodes=["read-file", "read-file", "llm", "write-file", "git-commit"],
            min_nodes=5,
            max_nodes=7,  # Allow extra processing
            must_have_inputs=["readme_file", "api_file", "commit_message"],
            must_not_have_inputs=["content", "updated_content"],
            node_output_refs=["read_readme.content", "read_api.content", "update.response"],
            category="developer_workflow",
            why_hard="Multiple file reads and updates",
            critical_nodes=[
                "read-file",
                "llm",
                "write-file",
                "git-commit",
            ],  # ALL expected nodes (note: 2 read-files expected)
            allowed_extra_nodes=["read-file", "llm"],  # Allow second read-file and extra LLM
        ),
        # Test 5: Dependency Checker
        WorkflowTestCase(
            name="dependency_checker",
            user_input="Run 'npm outdated --json' to check for outdated packages, parse the output to create a markdown table with columns: Package, Current, Wanted, Latest, and highlight major version changes, write to deps-report.md",
            discovered_params={"report_file": "deps-report.md"},
            browsed_node_ids=["shell", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["shell", "llm", "write-file"],
            min_nodes=3,
            max_nodes=5,  # Allow extra processing
            must_have_inputs=["report_file"],
            must_not_have_inputs=["packages", "report"],
            node_output_refs=["check.stdout", "analyze.response"],
            category="developer_workflow",
            why_hard="Shell command integration",
            critical_nodes=["shell", "llm", "write-file"],  # ALL expected nodes
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
        # Test 6: Slack Q&A Automation (MCP)
        WorkflowTestCase(
            name="slack_qa_automation",
            user_input="Get the last 10 messages from slack channel C09C16NAU5B, identify messages that end with '?' as questions, generate helpful answers for each question using context from the thread, then post a consolidated Q&A summary to the channel",
            discovered_params={"channel_id": "C09C16NAU5B", "message_limit": "10"},
            browsed_node_ids=["mcp-slack-slack_get_channel_history", "llm", "mcp-slack-slack_post_message"],
            validation_errors=None,
            expected_nodes=["mcp-slack-slack_get_channel_history", "llm", "mcp-slack-slack_post_message"],
            min_nodes=3,
            max_nodes=6,  # Allow for: get messages, identify questions, generate answers, format summary, post
            must_have_inputs=["channel_id", "message_limit"],
            must_not_have_inputs=["messages", "answers"],
            node_output_refs=["get_history.messages", "answer.response"],
            category="mcp_integration",
            why_hard="Real MCP integration from trace",
            critical_nodes=[
                "mcp-slack-slack_get_channel_history",
                "mcp-slack-slack_post_message",
            ],  # Must get messages and post back
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
        # Test 7: Comprehensive Repository Analytics Pipeline (HARDER)
        WorkflowTestCase(
            name="repository_analytics_pipeline",
            user_input="Generate complete repository analytics: Run 'git log --since=\"30 days ago\" --pretty=format:\"%H|%an|%ae|%at|%s\" --numstat' for detailed commit history. Run 'git shortlog -sn --since=\"30 days ago\"' for contributor stats. Run 'cloc . --json --exclude-dir=node_modules,venv,.git' for code metrics. Run 'find . -type f -name \"*.md\" | wc -l' for documentation count. Get last 100 issues (both open and closed) from GitHub repo spinje/pflow. Get all pull requests from last 30 days. Analyze commit patterns, calculate average time between commits, identify top contributors, calculate issue closure rate, PR merge rate, lines of code by language. Generate comprehensive analytics report with sections for velocity metrics, contributor analytics, code composition, issue/PR statistics. Write main report to analytics-report.md and data visualization file to analytics-data.json. Create branch 'analytics-$(date +%Y%m%d)', commit both files with message 'Analytics report $(date +%Y-%m-%d)', create PR requesting review.",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "report_file": "analytics-report.md",
                "data_file": "analytics-data.json",
                "issue_limit": "100",
            },
            browsed_node_ids=[
                "shell",
                "github-list-issues",
                "github-list-prs",
                "llm",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],
            validation_errors=None,
            expected_nodes=[
                "shell",
                "shell",
                "shell",
                "shell",
                "shell",
                "github-list-issues",
                "github-list-prs",
                "llm",
                "llm",
                "write-file",
                "write-file",
                "shell",
                "git-commit",
                "github-create-pr",
            ],  # 6 shells for: git log, git shortlog, cloc, find, date, git checkout -b
            min_nodes=12,
            max_nodes=16,  # Very complex analytics pipeline
            must_have_inputs=["repo_owner", "repo_name", "report_file", "data_file", "issue_limit"],
            must_not_have_inputs=["commits", "issues", "prs", "analytics"],
            node_output_refs=[
                "git_log.stdout",
                "shortlog.stdout",
                "cloc.stdout",
                "list_issues.issues",
                "list_prs.prs",
            ],  # Using shell stdout for git log
            category="complex_pipeline",
            why_hard="14+ nodes, multiple data sources, complex analysis, dynamic branch naming",
            critical_nodes=[
                "shell",
                "github-list-issues",
                "github-list-prs",
                "llm",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],  # Shell handles branch creation with date substitution
            allowed_extra_nodes=[
                "shell",
                "llm",
            ],  # Allow multiple shells and LLMs for complex analysis
        ),
        # Test 8: HTTP Weather Integration (renamed from MCP since we don't have weather MCP)
        WorkflowTestCase(
            name="http_weather_integration",
            user_input="Use HTTP to fetch weather data from api.openweathermap.org for location San Francisco, generate a human-readable weather report including temperature and conditions, format as markdown and save to weather-report.md",
            discovered_params={
                "location": "San Francisco",
                "api_url": "https://api.openweathermap.org/data/2.5/weather",
                "report_file": "weather-report.md",
            },
            browsed_node_ids=["http", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["http", "llm", "write-file"],
            min_nodes=3,
            max_nodes=5,  # Allow extra processing nodes
            must_have_inputs=["location", "api_url", "report_file"],
            must_not_have_inputs=["weather", "report"],
            node_output_refs=["http.response", "llm.response"],
            category="integration",
            why_hard="HTTP API integration with data processing",
            critical_nodes=["http", "llm", "write-file"],  # ALL expected nodes
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
        # Test 9: GitHub Slack Notifier
        WorkflowTestCase(
            name="github_slack_notifier",
            user_input="Get issues closed in the last 7 days from github repo spinje/pflow, create a summary showing total count, list of issue titles with numbers, and top contributors, post to slack channel updates with heading 'Weekly Closed Issues Report'",
            discovered_params={"repo_owner": "spinje", "repo_name": "pflow", "channel_id": "updates"},
            browsed_node_ids=["github-list-issues", "llm", "mcp-slack-slack_post_message"],
            validation_errors=None,
            expected_nodes=["github-list-issues", "llm", "mcp-slack-slack_post_message"],
            min_nodes=3,
            max_nodes=4,
            must_have_inputs=["repo_owner", "repo_name", "channel_id"],
            must_not_have_inputs=["issues", "summary"],
            node_output_refs=["list.issues", "summarize.response"],
            category="mcp_integration",
            why_hard="Cross-service integration",
            critical_nodes=["github-list-issues", "llm", "mcp-slack-slack_post_message"],  # ALL expected nodes
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
        # Test 10: Automated Test Failure Analysis Pipeline (HARDER)
        WorkflowTestCase(
            name="test_failure_analysis",
            user_input="Run 'npm test -- --json --outputFile=test-results.json' to execute tests. Read test-results.json and parse to identify all failing tests. Run 'git log --since=\"7 days ago\" --oneline' to find recent changes. Run 'git blame --show-stats' to get overall contribution stats. Search GitHub issues for 'test failure' or 'broken test' in repo spinje/pflow. Search GitHub PRs with label 'bug' or 'test'. Analyze failure patterns and correlate with recent repository activity. Generate detailed failure analysis report including: list of failing tests, recent commits that may be related, active issues and PRs about tests, recommendations for fixes. Write main report to test-analysis.md, create summary as test-failures.csv, post key findings to Slack channel 'testing'.",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "test_results_file": "test-results.json",
                "report_file": "test-analysis.md",
                "csv_file": "test-failures.csv",
                "channel_id": "testing",
            },
            browsed_node_ids=[
                "shell",
                "read-file",
                "github-list-issues",
                "github-list-prs",
                "llm",
                "write-file",
                "mcp-slack-slack_post_message",
            ],
            validation_errors=None,
            expected_nodes=[
                "shell",
                "read-file",
                "llm",
                "shell",
                "shell",
                "github-list-issues",
                "github-list-prs",
                "llm",
                "llm",
                "write-file",
                "write-file",
                "mcp-slack-slack_post_message",
            ],
            min_nodes=9,  # Reduced from 10 - allows more efficient implementations
            max_nodes=14,  # Complex forensics and analysis pipeline
            must_have_inputs=["repo_owner", "repo_name", "test_results_file", "report_file", "csv_file", "channel_id"],
            must_not_have_inputs=["test_results", "failures", "issues", "prs"],
            node_output_refs=[
                "run_tests.stdout",
                "read_results.content",
                "git_log.stdout",
                "git_blame.stdout",
                "list_issues.issues",
                "list_prs.prs",
            ],
            category="complex_pipeline",
            why_hard="Test forensics, git blame analysis, multi-source correlation, developer attribution",
            critical_nodes=[
                "shell",
                "read-file",
                "github-list-issues",
                "github-list-prs",
                "llm",
                "write-file",
                "mcp-slack-slack_post_message",
            ],
            allowed_extra_nodes=["shell", "llm"],  # Multiple git commands and analysis steps
        ),
        # Test 11: Full Release Pipeline (Complex)
        WorkflowTestCase(
            name="full_release_pipeline",
            user_input="Get the latest git tag, then use that tag to get all commits since that tag with git-log, generate release notes grouping commits by type (feat/fix/docs), use shell to create git tag v1.3.0 and push it, use shell to run 'gh release create v1.3.0 --notes-file release-notes.md', append the release notes to CHANGELOG.md with ## v1.3.0 header, commit with message 'Release v1.3.0', create PR to main branch for repo spinje/pflow",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "new_tag": "v1.3.0",
                "changelog_file": "CHANGELOG.md",
            },
            browsed_node_ids=[
                "git-get-latest-tag",
                "git-log",
                "llm",
                "shell",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],
            validation_errors=None,
            expected_nodes=[
                "git-get-latest-tag",
                "git-log",
                "llm",
                "shell",
                "shell",
                "shell",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],
            min_nodes=8,
            max_nodes=12,  # Complex workflow needs flexibility
            must_have_inputs=["repo_owner", "repo_name", "new_tag", "changelog_file"],
            must_not_have_inputs=["commits", "release_notes", "latest_tag"],
            node_output_refs=["latest_tag", "commits", "response"],  # Key outputs that should be referenced
            category="complex_pipeline",
            why_hard="8+ nodes with shell workarounds for git tag and gh release",
            critical_nodes=[
                "git-get-latest-tag",
                "git-log",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],  # Core required operations
            allowed_extra_nodes=["llm", "shell"],  # Allow flexibility in implementation
        ),
        # Test 12: Issue Triage Automation (Complex)
        WorkflowTestCase(
            name="issue_triage_automation",
            user_input="Get 50 open issues from github repo spinje/pflow, categorize as high priority if labeled 'bug' or 'security', medium if 'enhancement', low otherwise, group by days since creation (0-7, 8-30, 30+), create markdown report with tables for each priority level and recommendations for issues older than 30 days, save to triage-$(date +%Y-%m-%d).md using shell for date, commit with message 'Triage report for $(date +%Y-%m-%d)', create PR requesting review from @teamlead",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "issue_limit": "50",
                # Note: report_file is NOT a param - it's dynamically generated using shell date
            },
            browsed_node_ids=["llm", "shell", "write-file", "git-commit", "github-create-pr"],
            validation_errors=None,
            expected_nodes=[
                "github-list-issues",
                "llm",
                "shell",
                "write-file",
                "git-commit",
                "github-create-pr",
                "shell",
            ],
            min_nodes=6,
            max_nodes=10,  # Allow for modular design with separate categorization, grouping, and recommendation steps
            must_have_inputs=["repo_owner", "repo_name", "issue_limit"],
            must_not_have_inputs=["issues", "report", "date"],
            node_output_refs=["list.issues", "analyze.response", "get_date.stdout"],
            category="complex_pipeline",
            why_hard="Multiple data sources and shell integration",
            critical_nodes=[
                "github-list-issues",
                "llm",
                "shell",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],  # ALL expected including shell for date
            allowed_extra_nodes=["shell", "llm"],  # Allow extra shell for review request and LLM for modular analysis
        ),
        # Test 13: Codebase Quality Report (Complex)
        WorkflowTestCase(
            name="codebase_quality_report",
            user_input="Run 'npm run lint' and capture output, run 'npm test -- --coverage --json' to get coverage percentage, run 'npx complexity-report src/ --format json' to analyze complexity, get last 10 open bugs from github repo spinje/pflow, combine all results into a markdown quality report with sections for each metric, save to quality-report.md, checkout quality-reports branch, commit with message 'Quality report $(date +%Y-%m-%d)', push to origin, create PR to main",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "branch_name": "quality-reports",
                "report_file": "quality-report.md",
            },
            browsed_node_ids=[
                "shell",
                "github-list-issues",
                "llm",
                "write-file",
                "git-checkout",
                "git-commit",
                "git-push",
                "github-create-pr",
            ],
            validation_errors=None,
            expected_nodes=[
                "shell",
                "shell",
                "shell",
                "github-list-issues",
                "llm",
                "write-file",
                "git-checkout",
                "git-commit",
                "git-push",
                "github-create-pr",
            ],
            min_nodes=9,
            max_nodes=11,
            must_have_inputs=["repo_owner", "repo_name", "branch_name", "report_file"],
            must_not_have_inputs=["lint_results", "coverage", "issues"],
            node_output_refs=[
                "lint.stdout",
                "coverage.stdout",
                "complexity.stdout",
                "list.issues",
                "generate.response",
            ],
            category="complex_pipeline",
            why_hard="10+ nodes with multiple shell commands",
            critical_nodes=[
                "shell",
                "github-list-issues",
                "write-file",
                "git-checkout",
                "git-commit",
                "git-push",
                "github-create-pr",
            ],  # Core required operations
            allowed_extra_nodes=["llm", "shell"],  # Allow flexibility with multiple shells and LLMs
        ),
        # Test 14: Template Stress Test (Edge) - Fixed to use natural language
        WorkflowTestCase(
            name="template_stress_test",
            user_input="Read config.yaml and extract the version field, write it to VERSION.txt, use shell to run 'curl -X POST https://api.example.com/deploy -d @VERSION.txt', then send 'Deployment complete' to slack channel deployments",
            discovered_params={
                "config_file": "config.yaml",
                "version_file": "VERSION.txt",
                "deploy_url": "https://api.example.com/deploy",
                "slack_channel": "deployments",
            },
            browsed_node_ids=["read-file", "write-file", "llm", "shell", "mcp-slack-slack_post_message"],
            validation_errors=None,
            expected_nodes=["read-file", "llm", "shell", "mcp-slack-slack_post_message"],
            min_nodes=4,
            max_nodes=6,  # Allow extra processing for template confusion
            must_have_inputs=["config_file", "version_file", "deploy_url", "slack_channel"],
            must_not_have_inputs=["config", "data", "result"],
            node_output_refs=["read.content", "process.response", "deploy.stdout"],
            category="edge_case",
            why_hard="Heavy template variable usage",
            critical_nodes=[
                "read-file",
                "write-file",
                "shell",
                "mcp-slack-slack_post_message",
            ],  # Clear required operations
            allowed_extra_nodes=["llm"],  # Might need for extracting version
        ),
        # Test 15: Validation Recovery Test (Edge)
        WorkflowTestCase(
            name="validation_recovery_test",
            user_input="Get open issues from github repo spinje/pflow, analyze their labels and age to identify stale issues (>60 days without activity), generate a markdown report listing stale issues with recommendations for closure or follow-up, save to stale-issues-report.md",
            discovered_params={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "report_file": "stale-issues-report.md",
            },
            browsed_node_ids=["github-list-issues", "llm", "write-file"],
            validation_errors=[
                "Missing required input: repo_owner",
                "Template variable ${repo_owner} not defined in inputs",
            ],
            expected_nodes=["github-list-issues", "llm", "write-file"],
            min_nodes=3,
            max_nodes=4,
            must_have_inputs=["repo_owner", "repo_name", "report_file"],
            must_not_have_inputs=["issues", "report"],
            node_output_refs=["fetch.issues", "analyze.response"],
            category="edge_case",
            why_hard="Must recover from validation errors",
            critical_nodes=["github-list-issues", "llm", "write-file"],  # ALL expected nodes
            allowed_extra_nodes=["llm"],  # Allow extra LLM for processing
        ),
    ]


def extract_template_variables(workflow: dict) -> set[str]:
    """Extract all template variables used in the workflow."""
    variables = set()

    for node in workflow.get("nodes", []):
        params = node.get("params", {})
        for param_value in params.values():
            if isinstance(param_value, str):
                # Extract ${var} patterns
                variables.update(TemplateResolver.extract_variables(param_value))

    return variables


def extract_node_references(workflow: dict) -> set[str]:
    """Extract all ${node.output} references."""
    references = set()

    for node in workflow.get("nodes", []):
        params = node.get("params", {})
        for param_value in params.values():
            if isinstance(param_value, str):
                # Find ${node_id.output_key} patterns
                matches = re.findall(r"\$\{([a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+)\}", param_value)
                references.update(matches)

    # Also check workflow outputs
    for output in workflow.get("outputs", {}).values():
        if isinstance(output, dict) and "source" in output:
            source = output["source"]
            if isinstance(source, str):
                matches = re.findall(r"\$\{([a-zA-Z0-9_-]+\.[a-zA-Z0-9_]+)\}", source)
                references.update(matches)

    return references


def validate_node_count(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:
    """Validate node count is within expected range."""
    node_count = len(workflow.get("nodes", []))
    if node_count < test_case.min_nodes:
        errors.append(f"Too few nodes: {node_count} < {test_case.min_nodes}")
    if node_count > test_case.max_nodes:
        errors.append(f"Too many nodes: {node_count} > {test_case.max_nodes}")


def validate_inputs(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:  # noqa: C901
    """Validate required and forbidden inputs with STRICT checking."""
    inputs = set(workflow.get("inputs", {}).keys())

    # STRICT: Check required inputs are declared (exact match preferred)
    for required in test_case.must_have_inputs:
        if required not in inputs:
            # Only allow flexibility if there's a clear match
            fuzzy_match = [inp for inp in inputs if required in inp or inp in required]
            if not fuzzy_match:
                errors.append(f"[STRICT] Missing required input: {required}")
            elif len(fuzzy_match) > 1:
                errors.append(f"[STRICT] Ambiguous input matching for '{required}': {fuzzy_match}")

    # Check forbidden inputs are NOT declared
    for forbidden in test_case.must_not_have_inputs:
        if forbidden in inputs:
            errors.append(f"Should not declare '{forbidden}' as input (it's node output)")

    # STRICT CHECK: Ensure discovered params that should be inputs ARE inputs
    # This catches cases where the model might rename parameters
    if hasattr(test_case, "discovered_params"):
        expected_input_params = {
            k for k in test_case.discovered_params if k not in (test_case.must_not_have_inputs or [])
        }
        missing_discovered = expected_input_params - inputs
        if missing_discovered:
            # Check if they're renamed (e.g., repo_owner → repository_owner)
            truly_missing = []
            for param in missing_discovered:
                # Look for obvious renames
                if not any(param.split("_")[-1] in inp for inp in inputs):
                    truly_missing.append(param)
            if truly_missing:
                errors.append(f"[STRICT] Discovered params not in inputs: {truly_missing}")


def validate_template_usage(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:  # noqa: C901
    """Validate template variables are properly used with STRICT checking."""
    template_vars = extract_template_variables(workflow)
    declared_inputs = set(workflow.get("inputs", {}).keys())

    # All declared inputs should be used
    unused = declared_inputs - template_vars
    if unused:
        errors.append(f"Declared but unused inputs: {unused}")

    # STRICT CHECK 1: Deep inspection for ANY hardcoded values
    workflow_str = json.dumps(workflow)

    # Check each discovered param value
    for param_name, param_value in test_case.discovered_params.items():
        if param_value is None or param_value == "":
            continue

        # Convert to string for searching
        str_value = str(param_value)

        # ENHANCED: Check for value in ANY context (not just quoted)
        # This catches: "value", value, 'value', /value/, etc.
        if str_value in workflow_str:
            # Get workflow without inputs section for checking
            # (We exclude inputs section because defaults are allowed there)
            workflow_copy = workflow.copy()
            workflow_copy.pop("inputs", None)
            workflow_nodes_str = json.dumps(workflow_copy)

            # If value appears in nodes/edges/outputs (not just inputs defaults)
            if str_value in workflow_nodes_str:
                # Check if it's properly templated
                template_pattern = f"${{{param_name}"
                if template_pattern not in workflow_nodes_str:
                    errors.append(f"[STRICT] Hardcoded value '{str_value}' found - should use ${{{param_name}}}")

    # STRICT CHECK 2: Verify ALL discovered params are declared as inputs
    workflow_inputs = workflow.get("inputs", {})
    for param_name, param_value in test_case.discovered_params.items():
        if param_name not in workflow_inputs:
            errors.append(f"[STRICT] Discovered param '{param_name}' not declared in workflow inputs")
        else:
            # Check that default matches discovered value if present
            input_spec = workflow_inputs[param_name]
            if "default" in input_spec and str(input_spec["default"]) != str(param_value):
                errors.append(
                    f"[STRICT] Input '{param_name}' default '{input_spec['default']}' doesn't match discovered value '{param_value}'"
                )

    # STRICT CHECK 3: Verify no compound strings with hardcoded values
    # Look for patterns like "repo spinje/pflow" or "channel C09C16NAU5B"
    for node in workflow.get("nodes", []):
        for param_key, param_value in node.get("params", {}).items():
            if isinstance(param_value, str):
                for disc_name, disc_value in test_case.discovered_params.items():
                    if (
                        disc_value
                        and str(disc_value) in param_value
                        and not (f"${{{disc_name}}}" in param_value or f"${disc_name}" in param_value)
                    ):
                        errors.append(
                            f"[STRICT] Node '{node.get('id')}' param '{param_key}' contains hardcoded '{disc_value}'"
                        )

    # Node output references are validated in validate_node_output_refs function


def validate_node_output_refs(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:  # noqa: C901
    """Validate that expected node output references are present in the workflow.

    This ensures the workflow has the correct data flow by checking that expected
    output fields (like 'issues', 'response', 'stdout') are actually referenced.
    We're flexible on node IDs but strict on output field names.
    """
    # Extract actual references from workflow
    actual_refs = extract_node_references(workflow)

    # If no expected refs, nothing to validate
    if not test_case.node_output_refs:
        return

    # If we expect refs but found none at all
    if not actual_refs:
        errors.append("[STRICT] No node output references found in workflow (expected ${node.output} patterns)")
        return

    # Check each expected reference
    missing_outputs = []
    for expected_ref in test_case.node_output_refs:
        # Split into node_id and output_field (e.g., "list_issues.issues" -> ["list_issues", "issues"])
        parts = expected_ref.split(".")
        if len(parts) != 2:
            continue  # Skip malformed expectations

        _expected_node_pattern, expected_output = parts

        # Check if any actual ref has this output field
        # We're flexible on node naming but strict on output field
        matching_refs = [ref for ref in actual_refs if ref.endswith(f".{expected_output}")]

        if not matching_refs:
            # Special handling for shell outputs - accept any valid shell output field
            # Shell nodes can output: stdout, stderr, or exit_code - all are valid
            if expected_output in ["stdout", "stderr", "exit_code"]:
                shell_outputs = ["stdout", "stderr", "exit_code"]
                shell_match_found = False
                for shell_output in shell_outputs:
                    if any(ref.endswith(f".{shell_output}") for ref in actual_refs):
                        # Found a valid shell output, even if not the exact one expected
                        shell_match_found = True
                        break
                if shell_match_found:
                    continue  # Don't add to missing outputs, shell output was found

            # Try to find similar refs to provide helpful feedback
            similar_refs = [ref for ref in actual_refs if expected_output.lower() in ref.lower()]
            if similar_refs:
                missing_outputs.append(
                    f"*.{expected_output} (expected like {expected_ref}, found similar: {similar_refs[0]})"
                )
            else:
                missing_outputs.append(f"*.{expected_output} (expected like {expected_ref})")

    if missing_outputs:
        errors.append(f"[STRICT] Missing expected output references: {', '.join(missing_outputs)}")


def validate_node_types(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:
    """Validate that critical node types are present and no forbidden types exist."""
    actual_types = [node.get("type") for node in workflow.get("nodes", [])]

    # Use critical_nodes if specified, otherwise fall back to expected_nodes
    required_types = test_case.critical_nodes if test_case.critical_nodes is not None else test_case.expected_nodes

    # Check all required types are present (order doesn't matter)
    missing_types = set(required_types) - set(actual_types)
    if missing_types:
        errors.append(f"Missing required node types: {sorted(missing_types)}")

    # If allowed_extra_nodes is specified, check for forbidden extras
    if test_case.allowed_extra_nodes is not None:
        allowed = set(required_types) | set(test_case.allowed_extra_nodes)
        forbidden = set(actual_types) - allowed
        if forbidden:
            errors.append(f"Unexpected node types: {sorted(forbidden)}")


def validate_purposes(workflow: dict, errors: list[str]) -> None:
    """Validate purpose field quality for all nodes."""
    generic_purposes = ["process data", "use llm", "write file", "read file", "fetch data"]

    for node in workflow.get("nodes", []):
        if "purpose" not in node:
            errors.append(f"Node {node.get('id')} missing purpose field")
        else:
            purpose = node["purpose"]
            if len(purpose) < 10:
                errors.append(f"Purpose too short: '{purpose}'")
            if len(purpose) > 200:
                errors.append(f"Purpose too long: '{purpose}'")
            if purpose.lower() in generic_purposes:
                errors.append(f"Generic purpose: '{purpose}'")


def validate_outputs(workflow: dict, errors: list[str]) -> None:
    """Validate workflow outputs have proper structure."""
    for output_name, output_spec in workflow.get("outputs", {}).items():
        if not isinstance(output_spec, dict):
            errors.append(f"Output '{output_name}' must be an object with description and source")
        elif "source" not in output_spec:
            errors.append(f"Output '{output_name}' missing 'source' field for namespacing")


def validate_linear_workflow(workflow: dict, errors: list[str]) -> None:
    """Validate workflow is linear (no branching)."""
    edges = workflow.get("edges", [])
    from_counts = {}
    for edge in edges:
        from_node = edge.get("from")
        if from_node:
            from_counts[from_node] = from_counts.get(from_node, 0) + 1

    for node_id, count in from_counts.items():
        if count > 1:
            errors.append(f"Branching detected: node '{node_id}' has {count} outgoing edges")


# Data flow validation functions have been moved to pflow.core.workflow_data_flow
# and are now used via WorkflowValidator for production consistency


def create_test_registry():
    """Create registry with ONLY 2 Slack MCP mock nodes.

    All other nodes come from the real registry.
    """

    registry = Registry()

    # Load real registry data first
    real_data = {}
    with contextlib.suppress(Exception):
        real_data = registry.load()

    # Add ONLY 2 Slack MCP mock nodes (based on real trace evidence)
    test_nodes = {
        "mcp-slack-slack_get_channel_history": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "interface": {"inputs": ["channel_id", "limit"], "outputs": ["messages", "channel_info"]},
        },
        "mcp-slack-slack_post_message": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "interface": {"inputs": ["channel_id", "text"], "outputs": ["message_id", "timestamp"]},
        },
    }

    # Merge test nodes with real data
    merged_data = {**real_data, **test_nodes}

    # Monkey-patch the load method to return our merged data
    def mock_load():
        return merged_data

    registry.load = mock_load

    # Also patch get_nodes_metadata to use our merged data
    def mock_get_metadata(node_types):
        if node_types is None:
            raise TypeError("node_types cannot be None")
        result = {}
        for node_type in node_types:
            if node_type in merged_data:
                result[node_type] = merged_data[node_type]
        return result

    registry.get_nodes_metadata = mock_get_metadata

    return registry


def validate_workflow(workflow: dict, test_case: WorkflowTestCase) -> tuple[bool, str]:
    """Validate the generated workflow using production WorkflowValidator.

    This function performs TWO types of validation:

    1. PRODUCTION VALIDATION (via WorkflowValidator):
       - Structural correctness (JSON schema)
       - Data flow validation (node ordering, dependencies)
       - Node type verification (all nodes exist in registry)
       - Input declaration validation (all ${params} are declared)

    2. TEST-SPECIFIC QUALITY CHECKS:
       - Node count within expected range (flexibility for good engineering)
       - Expected inputs are declared (but allows flexibility in naming)
       - No hardcoded values where templates should be used
       - Critical node types are present (via validate_node_types)
       - Purposes are descriptive (not generic)
       - Workflow is linear (no branching - MVP requirement)

    The production validation ensures the workflow is EXECUTABLE.
    The test-specific checks ensure the workflow meets our QUALITY standards.
    """
    errors = []

    # PART 1: Use production WorkflowValidator for correctness
    from pflow.core.workflow_validator import WorkflowValidator

    # Check if test uses MCP nodes
    uses_mcp_nodes = any("mcp" in node_id for node_id in test_case.browsed_node_ids)

    # Fix common LLM mistakes before validation
    import copy

    workflow_copy = copy.deepcopy(workflow)
    for input_spec in workflow_copy.get("inputs", {}).values():
        if isinstance(input_spec, dict) and input_spec.get("type") == "integer":
            input_spec["type"] = "number"

    # Create appropriate registry
    registry = create_test_registry() if uses_mcp_nodes else Registry()

    # ================================================================================
    # CRITICAL VALIDATION DESIGN: Understanding What We Validate and Why
    # ================================================================================
    #
    # We intentionally pass extracted_params=None to the WorkflowValidator.
    # This is NOT skipping validation - it's testing the RIGHT thing for workflow generation.
    #
    # What validation DOES happen (even with extracted_params=None):
    # ----------------------------------------------------------------
    # 1. STRUCTURAL VALIDATION (WorkflowValidator lines 50-51) - ALWAYS runs
    #    - JSON schema compliance (all required fields present)
    #    - Correct data types for all fields
    #    - No duplicate node IDs
    #
    # 2. DATA FLOW VALIDATION (WorkflowValidator lines 54-55) - ALWAYS runs
    #    - No forward references (can't use ${node2.output} in node1)
    #    - No circular dependencies
    #    - All referenced nodes must exist
    #    - All ${input_param} refs must be DECLARED in workflow.inputs
    #    - Validates execution order is possible
    #
    # 3. NODE TYPE VALIDATION (WorkflowValidator lines 65-69) - runs since skip_node_types=False
    #    - All node types exist in the registry
    #    - No hallucinated/fantasy nodes
    #
    # What validation DOESN'T happen (because extracted_params=None):
    # ----------------------------------------------------------------
    # 4. RUNTIME TEMPLATE RESOLUTION (WorkflowValidator lines 58-62) - SKIPPED
    #    - Whether user PROVIDED values for all required inputs
    #    - Whether complex template paths resolve with actual values
    #    - This is ParameterMappingNode's job in the real planner
    #
    # Why this is CORRECT for these tests:
    # -------------------------------------
    # These tests validate that WorkflowGeneratorNode creates STRUCTURALLY VALID workflows.
    # We're testing "can the generator create a valid workflow?" not "can this workflow
    # execute with these specific runtime values?"
    #
    # The real planner also separates these concerns:
    # - WorkflowGeneratorNode: Creates structurally valid workflow
    # - ParameterMappingNode: Extracts runtime values from user input
    # - WorkflowValidatorNode: Validates with extracted_params for execution
    #
    # By passing extracted_params=None, we're testing ONLY the generator's responsibility,
    # not the entire planner pipeline. This is proper separation of concerns.
    # ================================================================================

    runtime_params = None  # Intentionally None - see detailed explanation above

    # Use production WorkflowValidator with same validation as real planner
    # (except runtime template resolution which requires extracted_params)
    validation_errors, _ = WorkflowValidator.validate(
        workflow_ir=workflow_copy,
        extracted_params=runtime_params,  # None - validates structure, not runtime execution
        registry=registry,
        skip_node_types=False,  # Always validate node types exist in registry
    )

    # Add validation errors with prefix for clarity
    for error in validation_errors:
        if error.startswith("Structure:") or error.startswith("Unknown node") or "Data flow" in error:
            errors.append(f"[VALIDATION] {error}")
        else:
            errors.append(error)

    # PART 2: Test-specific expectations (quality and convention checks)
    # ===================================================================
    # These checks ensure the workflow meets our QUALITY standards and conventions.
    # They're not about whether the workflow can execute (that's Part 1's job),
    # but whether it follows best practices and meets test expectations.
    # The model adding extra nodes for validation/formatting is GOOD engineering,
    # so we allow flexibility with ranges rather than exact counts.
    # ===================================================================

    # Check node count is within expected range (allows good engineering practices)
    validate_node_count(workflow, test_case, errors)

    # Check expected inputs (test expectation, not correctness)
    validate_inputs(workflow, test_case, errors)

    # Check for hardcoded values (quality check)
    workflow_str = json.dumps(workflow)
    for param_name, param_value in test_case.discovered_params.items():
        if param_value and f'"{param_value}"' in workflow_str:
            template_pattern = f"${{{param_name}"
            if template_pattern not in workflow_str and "${" + param_name not in workflow_str:
                errors.append(f"[TEST] Hardcoded value '{param_value}' instead of template variable")

    # Check node types are appropriate (critical validation)
    validate_node_types(workflow, test_case, errors)

    # Check node output references for correct data flow (critical validation)
    validate_node_output_refs(workflow, test_case, errors)

    # Check purposes exist and aren't generic (quality check)
    validate_purposes(workflow, errors)

    # Check workflow is linear (MVP requirement)
    validate_linear_workflow(workflow, errors)

    if errors:
        return False, "; ".join(errors)
    return True, ""


class TestWorkflowGeneratorPrompt:
    """Test the workflow generator prompt with real-world scenarios."""

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_workflow_generation(self, test_case):
        """Test individual workflow generation scenario."""

        node = WorkflowGeneratorNode()

        # Get properly formatted browsed_components
        browsed_components = test_case.get_browsed_components()

        # Build planning context dynamically using real context builder
        # Check if test uses MCP nodes
        uses_mcp = any("mcp" in node_id for node_id in test_case.browsed_node_ids)
        planning_context = build_test_planning_context(browsed_components, include_mcp_mocks=uses_mcp)

        # Templatize the user input to match real planner behavior
        # In the real planner, ParameterDiscoveryNode does this
        from pflow.planning.nodes import ParameterDiscoveryNode

        param_node = ParameterDiscoveryNode()
        templatized_input = param_node._templatize_user_input(test_case.user_input, test_case.discovered_params)

        # TEST: Temporarily disable templatization to verify strict validation works
        # templatized_input = test_case.user_input  # UNCOMMENT TO TEST STRICT VALIDATION

        # Build shared context with correct structure
        shared = {
            "user_input": test_case.user_input,  # Keep original for reference
            "templatized_input": templatized_input,  # ADD templatized version!
            "discovered_params": test_case.discovered_params,
            "planning_context": planning_context,  # Now dynamically built and already filtered
            "browsed_components": browsed_components,  # Correct format: {"node_ids": [...], "workflow_names": [...], "reasoning": "..."}
        }

        # Add validation errors for retry tests
        if test_case.validation_errors:
            shared["validation_errors"] = test_case.validation_errors
            shared["generation_attempts"] = 1  # This is a retry

        try:
            # Prepare and execute
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            # Extract workflow
            workflow = exec_res.get("workflow", {})

            if not workflow:
                failure_reason = "No workflow generated"
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            # Validate the workflow
            passed, failure_reason = validate_workflow(workflow, test_case)

            # ALWAYS log the workflow for analysis
            print(f"\n{'=' * 60}")
            print(f"WORKFLOW OUTPUT for {test_case.name}:")
            print(f"{'=' * 60}")
            print(json.dumps(workflow, indent=2))
            print(f"{'=' * 60}\n")

            if not passed:
                # Log the generated workflow for debugging
                logger.info(f"Generated workflow for {test_case.name}:")
                logger.info(json.dumps(workflow, indent=2))

                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            # Success
            logger.info(f"✅ {test_case.name} passed - Generated {len(workflow['nodes'])} nodes")

        except Exception as e:
            failure_reason = f"Exception: {e!s}"
            report_failure(test_case.name, failure_reason)
            raise
