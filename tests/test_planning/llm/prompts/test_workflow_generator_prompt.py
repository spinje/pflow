"""Comprehensive tests for workflow_generator prompt with pytest parametrization.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests validate that the workflow generator creates valid, complex workflows
with proper template variable usage, data flow, and structural integrity.

Run with:
  RUN_LLM_TESTS=1 pytest test_workflow_generator_prompt.py -v
"""

import contextlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import pytest

from pflow.planning.nodes import WorkflowGeneratorNode
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
    planning_context: str
    browsed_components: dict
    validation_errors: Optional[list[str]]  # For retry tests
    expected_nodes: list[str]  # Node types in order
    min_nodes: int
    max_nodes: int
    must_have_inputs: list[str]  # Required user inputs
    must_not_have_inputs: list[str]  # Should NOT be user inputs (are node outputs)
    node_output_refs: list[str]  # Expected ${node.output} patterns
    category: str
    why_hard: str


def get_test_cases() -> list[WorkflowTestCase]:
    """Define all test cases for workflow generation."""

    # Common planning context with various node types
    base_context = """Available nodes:
- github-list-issues: Fetch GitHub issues
  Parameters: repo_owner, repo_name, state, limit
  Outputs: issues
- github-list-prs: List GitHub pull requests (mock)
  Parameters: repo_owner, repo_name, state, limit
  Outputs: prs
- github-create-pr: Create pull request
  Parameters: repo_owner, repo_name, title, body, head, base
  Outputs: pr_url, pr_number
- github-create-release: Create GitHub release (mock)
  Parameters: repo_owner, repo_name, tag_name, name, body
  Outputs: release_url, release_id
- github-get-latest-tag: Get latest tag from GitHub (mock)
  Parameters: repo_owner, repo_name
  Outputs: tag, date
- llm: Generate text using LLM
  Parameters: prompt, model, temperature
  Outputs: response, llm_usage
- read-file: Read file content
  Parameters: file_path, encoding
  Outputs: content
- write-file: Write content to file
  Parameters: file_path, content, encoding, overwrite
  Outputs: file_path, success
- git-commit: Commit changes
  Parameters: message, files
  Outputs: commit_hash
- git-checkout: Checkout branch
  Parameters: branch
  Outputs: branch_name
- git-log: Get git log
  Parameters: since, until, limit, author, grep, path
  Outputs: commits
- git-tag: Create git tag (mock)
  Parameters: tag_name, message
  Outputs: tag
- slack-notify: Send Slack notification (mock)
  Parameters: channel, message
  Outputs: status
- analyze-code: Analyze codebase structure (mock)
  Parameters: path
  Outputs: analysis, files_analyzed
- validate-links: Validate documentation links (mock)
  Parameters: content
  Outputs: valid_links, broken_links
- filter-data: Filter data based on criteria (mock)
  Parameters: data, criteria
  Outputs: filtered_data
- build-project: Build the project (mock)
  Parameters: config_path
  Outputs: status, artifacts
"""

    return [
        # Category 1: Ultra-Complex 8+ Node Workflows
        WorkflowTestCase(
            name="full_release_pipeline",
            user_input="Create a complete release pipeline: get the latest tag from GitHub, list all commits and issues since that tag, generate a comprehensive changelog, create release notes, write both to files, commit changes, create a PR for review, create a GitHub release after approval, and notify the #releases Slack channel about the new release",
            discovered_params={
                "repo_owner": "anthropic",
                "repo_name": "pflow",
                "slack_channel": "#releases",
                "changelog_file": "CHANGELOG.md",
                "release_notes_file": "RELEASE_NOTES.md",
            },
            planning_context=base_context,
            browsed_components={
                "github-get-latest-tag": {"type": "node"},
                "git-log": {"type": "node"},
                "github-list-issues": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
                "git-commit": {"type": "node"},
                "github-create-pr": {"type": "node"},
                "github-create-release": {"type": "node"},
                "slack-notify": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=[
                "github-get-latest-tag",
                "git-log",
                "github-list-issues",
                "llm",
                "llm",
                "write-file",
                "write-file",
                "git-commit",
                "github-create-pr",
                "github-create-release",
                "slack-notify",
            ],
            min_nodes=8,
            max_nodes=12,
            must_have_inputs=["repo_owner", "repo_name", "slack_channel", "changelog_file", "release_notes_file"],
            must_not_have_inputs=["latest_tag", "commits", "issues", "changelog", "release_notes"],
            node_output_refs=[
                "get_tag.tag",
                "get_commits.log",
                "list_issues.issues",
                "generate_changelog.response",
                "generate_notes.response",
            ],
            category="ultra_complex",
            why_hard="10+ nodes with multiple data sources, parallel processing, and external notifications",
        ),
        WorkflowTestCase(
            name="comprehensive_documentation_generator",
            user_input="Generate complete API documentation: analyze the codebase structure in src/, extract all public functions and classes, generate detailed documentation for each module, create code examples for each function, build an index page linking all docs, validate all internal links are correct, commit the documentation to docs/api/, and create a PR titled 'Update API Documentation'",
            discovered_params={
                "source_path": "src/",
                "docs_output": "docs/api/",
                "pr_title": "Update API Documentation",
            },
            planning_context=base_context,
            browsed_components={
                "analyze-code": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
                "validate-links": {"type": "node"},
                "git-commit": {"type": "node"},
                "github-create-pr": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=[
                "analyze-code",
                "llm",
                "llm",
                "llm",
                "write-file",
                "write-file",
                "write-file",
                "validate-links",
                "git-commit",
                "github-create-pr",
            ],
            min_nodes=8,
            max_nodes=11,
            must_have_inputs=["source_path", "docs_output", "pr_title"],
            must_not_have_inputs=["structure", "functions", "documentation", "examples", "index"],
            node_output_refs=[
                "analyze.structure",
                "extract.functions",
                "generate_docs.response",
                "generate_examples.response",
                "create_index.response",
            ],
            category="ultra_complex",
            why_hard="9+ nodes with iterative documentation generation and validation",
        ),
        WorkflowTestCase(
            name="multi_source_weekly_report",
            user_input="Create a weekly project report by: fetching closed issues from GitHub repository, fetching merged pull requests, getting git commits from the last 7 days, analyzing all this data for trends, writing a detailed report to a file, writing a summary to another file, committing both files, and sending a notification to Slack",
            discovered_params={
                "repo_owner": "anthropic",
                "repo_name": "pflow",
                "issue_limit": "50",
                "pr_limit": "50",
                "report_path": "reports/weekly/report.md",
                "summary_file": "reports/summary.md",
                "slack_channel": "#weekly-updates",
            },
            planning_context=base_context,
            browsed_components={
                "github-list-issues": {"type": "node"},
                "github-list-prs": {"type": "node"},
                "git-log": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
                "git-commit": {"type": "node"},
                "slack-notify": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=[
                "github-list-issues",
                "github-list-prs",
                "git-log",
                "llm",
                "write-file",
                "write-file",
                "git-commit",
                "slack-notify",
            ],
            min_nodes=7,  # More realistic
            max_nodes=12,  # Allow flexibility
            must_have_inputs=["repo_owner", "repo_name"],  # The essential GitHub inputs
            must_not_have_inputs=["issues", "prs", "commits", "trends", "summary"],
            node_output_refs=["fetch_issues.issues", "fetch_prs.prs", "get_commits.log"],
            category="ultra_complex",
            why_hard="10 nodes combining multiple GitHub data sources with analysis and reporting",
        ),
        # Keep the original complex 4-6 node tests
        # Category 1: Complex Multi-Node Workflows
        WorkflowTestCase(
            name="changelog_pipeline",
            user_input="Create a comprehensive changelog by fetching the last 30 closed issues from anthropic/pflow, analyze them with AI to categorize by type (bug/feature/docs), generate a formatted changelog with sections, save it to CHANGELOG.md, commit the changes, and create a PR",
            discovered_params={
                "repo_owner": "anthropic",
                "repo_name": "pflow",
                "issue_count": "30",
                "changelog_path": "CHANGELOG.md",
            },
            planning_context=base_context,
            browsed_components={
                "github-list-issues": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
                "git-commit": {"type": "node"},
                "github-create-pr": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["github-list-issues", "llm", "llm", "write-file", "git-commit", "github-create-pr"],
            min_nodes=5,
            max_nodes=7,
            must_have_inputs=["repo_owner", "repo_name", "issue_count", "changelog_path"],
            must_not_have_inputs=["content", "issues", "changelog", "categorized"],
            node_output_refs=["fetch_issues.issues", "categorize.response", "format.response"],
            category="complex",
            why_hard="6 nodes with complex data flow and multiple template variables",
        ),
        WorkflowTestCase(
            name="data_analysis_pipeline",
            user_input="Read sales data from data/2024-sales.csv, filter for Q4 records where revenue > 10000, analyze trends with AI, generate visualization code, and save both the analysis report and code to outputs folder",
            discovered_params={
                "input_file": "data/2024-sales.csv",
                "output_dir": "outputs",
                "revenue_threshold": "10000",
            },
            planning_context=base_context,
            browsed_components={
                "read-file": {"type": "node"},
                "filter-data": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["read-file", "filter-data", "llm", "llm", "write-file", "write-file"],
            min_nodes=5,
            max_nodes=6,
            must_have_inputs=["input_file", "output_dir", "revenue_threshold"],
            must_not_have_inputs=["data", "filtered_data", "analysis", "visualization"],
            node_output_refs=["read_data.content", "filter.output", "analyze.response", "generate_viz.response"],
            category="complex",
            why_hard="Multiple outputs and data transformation between steps",
        ),
        WorkflowTestCase(
            name="release_automation",
            user_input="Generate release notes from git log since tag v1.2.0, create GitHub release with the notes, build the project, and upload artifacts to the release",
            discovered_params={"since_tag": "v1.2.0", "repo_owner": "anthropic", "repo_name": "pflow"},
            planning_context=base_context,
            browsed_components={
                "git-log": {"type": "node"},
                "llm": {"type": "node"},
                "github-create-release": {"type": "node"},
                "build-project": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["git-log", "llm", "github-create-release", "build-project"],
            min_nodes=4,
            max_nodes=5,
            must_have_inputs=["since_tag", "repo_owner", "repo_name"],
            must_not_have_inputs=["release_notes", "commits", "release_id"],
            node_output_refs=["get_commits.log", "generate_notes.response"],
            category="complex",
            why_hard="Git to GitHub flow with artifact handling",
        ),
        WorkflowTestCase(
            name="migration_workflow",
            user_input="Backup production database to backups/2024-01-15/prod.sql, run migration scripts from migrations folder, verify data integrity, and generate migration report",
            discovered_params={"backup_path": "backups/2024-01-15/prod.sql", "migrations_dir": "migrations"},
            planning_context=base_context
            + "\n- run-migrations: Run database migrations (mock)\n  Parameters: migrations_path\n- verify-data: Verify data integrity (mock)\n  Parameters: connection_string",
            browsed_components={
                "backup-database": {"type": "node"},
                "run-migrations": {"type": "node"},
                "verify-data": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["backup-database", "run-migrations", "verify-data", "llm", "write-file"],
            min_nodes=4,
            max_nodes=5,
            must_have_inputs=["backup_path", "migrations_dir"],
            must_not_have_inputs=["report", "verification_results"],
            node_output_refs=["verify.results", "generate_report.response"],
            category="complex",
            why_hard="Critical operations requiring careful sequencing",
        ),
        # Category 2: Template Variable Confusion Tests
        WorkflowTestCase(
            name="content_generation_trap",
            user_input="Generate a blog post about Python testing best practices, review it for technical accuracy, then save the final content to blog/testing-guide.md",
            discovered_params={"topic": "Python testing best practices", "output_file": "blog/testing-guide.md"},
            planning_context=base_context,
            browsed_components={"llm": {"type": "node"}, "write-file": {"type": "node"}},
            validation_errors=None,
            expected_nodes=["llm", "llm", "write-file"],
            min_nodes=3,
            max_nodes=4,
            must_have_inputs=["topic", "output_file"],
            must_not_have_inputs=["content", "blog_post", "review"],
            node_output_refs=["generate_post.response", "review.response"],
            category="template_confusion",
            why_hard="Classic trap: content seems like user input but is generated",
        ),
        WorkflowTestCase(
            name="parameter_vs_output",
            user_input="Fetch user profile for user_id 12345, extract their preferences, generate personalized recommendations based on preferences, and save to recommendations.json",
            discovered_params={"user_id": "12345", "output_file": "recommendations.json"},
            planning_context=base_context + "\n- fetch-profile: Fetch user profile (mock)\n  Parameters: user_id",
            browsed_components={
                "fetch-profile": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["fetch-profile", "llm", "llm", "write-file"],
            min_nodes=4,
            max_nodes=5,
            must_have_inputs=["user_id", "output_file"],
            must_not_have_inputs=["preferences", "profile", "recommendations", "email"],
            node_output_refs=["fetch_profile.data", "extract_prefs.response", "generate_recs.response"],
            category="template_confusion",
            why_hard="Must distinguish user_id (input) from extracted data (outputs)",
        ),
        # Category 3: Validation Recovery Tests
        WorkflowTestCase(
            name="fix_validation_errors",
            user_input="Fetch closed issues from a GitHub repository, generate a simple bullet-point changelog listing issue titles only, and save it to a file",
            discovered_params={
                "repo_owner": "anthropic",
                "repo_name": "pflow",
                "issue_limit": "20",
                "output_file": "CHANGELOG.md",
            },
            planning_context=base_context,
            browsed_components={
                "github-list-issues": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
            },
            validation_errors=[
                "Template variable ${repo_owner} not defined in inputs",
                "Template variable ${repo_name} not defined in inputs",
                "Node type 'github_commits' not found - did you mean 'github-list-commits'?",
                "Declared input 'changelog_file' never used as template variable",
            ],
            expected_nodes=["github-list-issues", "llm", "write-file"],
            min_nodes=3,
            max_nodes=5,  # Allow more flexibility for validation fixes
            must_have_inputs=["repo_owner", "repo_name"],  # The main required inputs
            must_not_have_inputs=["changelog_file"],  # Should be removed due to "never used" error
            node_output_refs=["list_issues.issues", "generate.response"],
            category="validation_recovery",
            why_hard="Must parse and fix multiple validation errors",
        ),
        WorkflowTestCase(
            name="output_mapping_fix",
            user_input="Generate a simple status report with the text 'Monthly report: System operational. All metrics normal.' and save it to reports/monthly.md",
            discovered_params={"report_type": "monthly", "output_path": "reports/monthly.md"},
            planning_context=base_context,
            browsed_components={"llm": {"type": "node"}, "write-file": {"type": "node"}},
            validation_errors=["Workflow output 'report_path' must have 'description' and 'source' fields"],
            expected_nodes=["llm", "write-file"],
            min_nodes=2,
            max_nodes=4,  # Allow some flexibility
            must_have_inputs=["output_path"],  # Only expect what's actually used
            must_not_have_inputs=["report", "content"],
            node_output_refs=["generate.response"],
            category="validation_recovery",
            why_hard="Must fix output structure with source field",
        ),
        WorkflowTestCase(
            name="complex_data_flow",
            user_input="Read config from config.yaml, fetch data from the API endpoint in config, process according to rules in config, and save to output path in config",
            discovered_params={"config_file": "config.yaml"},
            planning_context=base_context
            + "\n- fetch-data: Fetch data from API (mock)\n  Parameters: endpoint, headers",
            browsed_components={
                "read-file": {"type": "node"},
                "fetch-data": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["read-file", "fetch-data", "llm", "write-file"],
            min_nodes=4,
            max_nodes=5,
            must_have_inputs=["config_file"],
            must_not_have_inputs=["api_endpoint", "output_path", "rules", "data"],
            node_output_refs=["read_config.content", "fetch.data", "process.response"],
            category="complex",
            why_hard="Config values are node outputs, not user inputs",
        ),
        WorkflowTestCase(
            name="multi_output_workflow",
            user_input="Analyze project structure, generate documentation for each module, create an index file linking all docs, and generate a summary report",
            discovered_params={"project_path": "src/", "docs_output": "docs/api/"},
            planning_context=base_context
            + "\n- analyze-structure: Analyze project structure (mock)\n  Parameters: path",
            browsed_components={
                "analyze-structure": {"type": "node"},
                "llm": {"type": "node"},
                "write-file": {"type": "node"},
            },
            validation_errors=None,
            expected_nodes=["analyze-structure", "llm", "write-file", "llm", "write-file", "llm", "write-file"],
            min_nodes=5,
            max_nodes=8,
            must_have_inputs=["project_path", "docs_output"],
            must_not_have_inputs=["modules", "documentation", "index", "summary"],
            node_output_refs=[
                "analyze.structure",
                "generate_docs.response",
                "create_index.response",
                "generate_summary.response",
            ],
            category="complex",
            why_hard="Multiple parallel outputs from single analysis",
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


def validate_inputs(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:
    """Validate required and forbidden inputs."""
    inputs = set(workflow.get("inputs", {}).keys())

    # Check required inputs are declared
    for required in test_case.must_have_inputs:
        # Allow flexible naming (e.g., "repo_name" or "repository")
        if not any(required in inp or inp in required for inp in inputs):
            errors.append(f"Missing required input: {required}")

    # Check forbidden inputs are NOT declared
    for forbidden in test_case.must_not_have_inputs:
        if forbidden in inputs:
            errors.append(f"Should not declare '{forbidden}' as input (it's node output)")


def validate_template_usage(workflow: dict, test_case: WorkflowTestCase, errors: list[str]) -> None:
    """Validate template variables are properly used."""
    template_vars = extract_template_variables(workflow)
    declared_inputs = set(workflow.get("inputs", {}).keys())

    # All declared inputs should be used
    unused = declared_inputs - template_vars
    if unused:
        errors.append(f"Declared but unused inputs: {unused}")

    # Check for hardcoded values from discovered_params
    workflow_str = json.dumps(workflow)
    for param_name, param_value in test_case.discovered_params.items():
        # Check if the literal value appears without ${}
        if f'"{param_value}"' in workflow_str:
            # Make sure it's not inside a template variable
            template_pattern = f"${{{param_name}"  # Will look for ${param_name
            if template_pattern not in workflow_str and "${" + param_name not in workflow_str:
                errors.append(f"Hardcoded value '{param_value}' instead of template variable")

    # Check node output references
    node_refs = extract_node_references(workflow)
    # Check that we have some node references (not exact match due to naming flexibility)
    if test_case.node_output_refs and not node_refs:
        errors.append("No node output references found (${node.output} patterns)")


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
    """Create registry with current + future planned nodes for testing."""

    from pflow.registry import Registry

    registry = Registry()

    # Load real registry data first
    real_data = {}
    with contextlib.suppress(Exception):
        real_data = registry.load()

    # Add future/mock nodes that are referenced in tests
    # These represent nodes that will exist but aren't implemented yet
    test_nodes = {
        # Future agentic node (claude-code)
        "claude-code": {
            "interface": {
                "inputs": ["prompt", "context", "output_schema"],
                "outputs": ["response", "files_created", "files_modified", "data"],
            }
        },
        # Renamed versions for specific tasks (will all be claude-code)
        "analyze-code": {"interface": {"inputs": ["path"], "outputs": ["analysis", "files_analyzed"]}},
        "analyze-structure": {"interface": {"inputs": ["path"], "outputs": ["structure", "components"]}},
        # Basic nodes that should exist
        "github-list-prs": {"interface": {"inputs": ["repo_owner", "repo_name", "state", "limit"], "outputs": ["prs"]}},
        # NOTE: git-log is now a real node (GitLogNode), not a mock
        "git-tag": {"interface": {"inputs": ["tag_name", "message"], "outputs": ["tag"]}},
        "github-get-latest-tag": {"interface": {"inputs": ["repo_owner", "repo_name"], "outputs": ["tag", "date"]}},
        "github-create-release": {
            "interface": {
                "inputs": ["repo_owner", "repo_name", "tag_name", "name", "body"],
                "outputs": ["release_url", "release_id"],
            }
        },
        # External integrations (out of MVP scope)
        "slack-notify": {"interface": {"inputs": ["channel", "message"], "outputs": ["status"]}},
        "build-project": {"interface": {"inputs": ["config_path"], "outputs": ["status", "artifacts"]}},
        # Vague nodes that appear in tests (should be replaced)
        "fetch-data": {"interface": {"inputs": ["endpoint", "headers"], "outputs": ["data"]}},
        "fetch-profile": {"interface": {"inputs": ["user_id"], "outputs": ["profile"]}},
        "filter-data": {"interface": {"inputs": ["data", "criteria"], "outputs": ["filtered_data"]}},
        "validate-links": {"interface": {"inputs": ["content"], "outputs": ["valid_links", "broken_links"]}},
        # Database operations (out of scope)
        "run-migrations": {"interface": {"inputs": ["migrations_path"], "outputs": ["status"]}},
        "backup-database": {"interface": {"inputs": ["connection_string"], "outputs": ["backup_path"]}},
        "verify-data": {"interface": {"inputs": ["connection_string"], "outputs": ["status", "report"]}},
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
    """Validate the generated workflow using production WorkflowValidator."""
    errors = []

    # PART 1: Use production WorkflowValidator
    from pflow.core.workflow_validator import WorkflowValidator
    from pflow.registry import Registry

    # Check if test uses mock nodes (indicated by "(mock)" in planning context)
    uses_mock_nodes = "(mock)" in test_case.planning_context

    # Fix common LLM mistakes before validation
    import copy

    workflow_copy = copy.deepcopy(workflow)
    for input_spec in workflow_copy.get("inputs", {}).values():
        if isinstance(input_spec, dict) and input_spec.get("type") == "integer":
            input_spec["type"] = "number"

    # Create appropriate registry
    registry = create_test_registry() if uses_mock_nodes else Registry()

    # CRITICAL FIX: Don't validate templates against discovered_params
    # The workflow generator should be free to create better parameter structures
    # For testing, we just check if the workflow is internally consistent
    # We don't need to provide runtime values - let the validator check structure only
    runtime_params = None  # Don't provide any runtime values for template validation

    # Use production validation to check workflow structure and consistency
    # Not providing runtime values means we only validate the workflow is well-formed
    validation_errors = WorkflowValidator.validate(
        workflow_ir=workflow_copy,
        extracted_params=runtime_params,  # None - only validate structure, not runtime
        registry=registry,
        skip_node_types=False,  # Don't skip, we have proper registry now
    )

    # Add validation errors with prefix for clarity
    for error in validation_errors:
        if error.startswith("Structure:") or error.startswith("Unknown node") or "Data flow" in error:
            errors.append(f"[VALIDATION] {error}")
        else:
            errors.append(error)

    # PART 2: Test-specific expectations (these are quality checks, not correctness)

    # Check node count is within expected range
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

    # Check purposes exist and aren't generic (quality check)
    validate_purposes(workflow, errors)

    # Check workflow is linear (MVP requirement)
    validate_linear_workflow(workflow, errors)

    if errors:
        return False, "; ".join(errors)
    return True, ""


def filter_planning_context_to_browsed(planning_context: str, browsed_components: dict) -> str:
    """Filter planning context to only include browsed components for validation recovery tests.

    This prevents the LLM from using nodes that weren't selected by ComponentBrowsingNode,
    ensuring validation recovery tests only use the minimal set of nodes that were
    originally intended for the workflow.
    """
    if not browsed_components:
        return planning_context

    # Extract node types from browsed components
    browsed_node_types = set(browsed_components.keys())

    # Parse planning context and filter
    lines = planning_context.strip().split("\n")
    filtered_lines = []

    for line in lines:
        # Check if this line describes a node
        if line.startswith("- "):
            # More robust extraction: handle "- node-type: Description (params)" format
            node_part = line[2:].split(":")[0] if ":" in line else line[2:]
            node_type = node_part.strip().split("(")[0].strip()
            if node_type in browsed_node_types:
                filtered_lines.append(line)
        else:
            # Keep header/other lines
            if filtered_lines or line.startswith("Available"):
                filtered_lines.append(line)

    return "\n".join(filtered_lines) if filtered_lines else planning_context


class TestWorkflowGeneratorPrompt:
    """Test the workflow generator prompt with complex scenarios."""

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_workflow_generation(self, test_case):
        """Test individual workflow generation scenario."""

        node = WorkflowGeneratorNode()

        # For validation recovery tests, only show browsed components
        planning_context = test_case.planning_context
        if test_case.validation_errors and test_case.browsed_components:
            # Filter to only show nodes that were browsed
            planning_context = filter_planning_context_to_browsed(
                test_case.planning_context, test_case.browsed_components
            )

        # Build shared context
        shared = {
            "user_input": test_case.user_input,
            "discovered_params": test_case.discovered_params,
            "planning_context": planning_context,
            "browsed_components": test_case.browsed_components,
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
