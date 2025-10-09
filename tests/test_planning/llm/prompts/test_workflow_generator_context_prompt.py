"""Tests for workflow generator with new cache-optimized context architecture.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

WHAT THESE TESTS VALIDATE:
--------------------------
Tests the NEW production path where WorkflowGeneratorNode uses:
- Cache-optimized context blocks from PlannerContextBuilder
- Extended context including planning output
- workflow_generator_instructions.md prompt (not the legacy workflow_generator.md)

This tests the actual production flow without needing the full pipeline.

Run with:
  RUN_LLM_TESTS=1 pytest test_workflow_generator_context_prompt.py -n auto -v
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

from pflow.planning.context_blocks import PlannerContextBuilder
from pflow.planning.context_builder import build_planning_context
from pflow.planning.nodes import WorkflowGeneratorNode
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver

# For LLM tests, we need to enable the Anthropic model wrapper
# This gives us cache_blocks support which is required for the new architecture
if os.getenv("RUN_LLM_TESTS"):
    from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

    install_anthropic_model()

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
            logger.debug(f"Failed to write to failure file: {e}")


# Skip tests unless LLM tests enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


@dataclass
class WorkflowTestCase:
    """Test case for workflow generation with context architecture."""

    name: str
    user_input: str
    discovered_params: dict[str, str]
    browsed_node_ids: list[str]
    validation_errors: Optional[list[str]]  # For retry tests
    expected_nodes: list[str]
    min_nodes: int
    max_nodes: int
    must_have_inputs: list[str]
    must_not_have_inputs: list[str]
    node_output_refs: list[str]
    category: str
    why_hard: str
    critical_nodes: Optional[list[str]] = None
    allowed_extra_nodes: Optional[list[str]] = None
    browsed_workflow_names: list[str] = field(default_factory=list)

    def get_browsed_components(self) -> dict:
        """Get browsed_components in the correct format."""
        return {
            "node_ids": self.browsed_node_ids,
            "workflow_names": self.browsed_workflow_names,
            "reasoning": f"Components selected for {self.name} test case",
        }


def simulate_planning_output(test_case: WorkflowTestCase) -> tuple[str, dict]:
    """Simulate what PlanningNode would produce.

    TODO: HIGH PRIORITY - Replace with real PlanningNode output
    -----------------------------------------------------
    Current approach uses a generic, minimal plan that doesn't provide the rich
    context that WorkflowGeneratorNode would get in production. This makes the
    test less representative and forces the generator to work harder.

    Proposed improvement:
    1. Pre-generate real plans for each test case using PlanningNode (one-time)
    2. Store these as fixtures in tests/test_planning/llm/fixtures/plans/
    3. Load the appropriate fixture based on test_case.name

    Benefits:
    - More realistic testing with actual architectural guidance
    - Tests would better represent production behavior
    - WorkflowGeneratorNode gets proper step-by-step execution plans
    - Still avoids runtime LLM calls (using cached fixtures)

    Similar approach could be applied to other simulated nodes:
    - RequirementsAnalysisNode output (currently simulated)
    - ComponentBrowsingNode selections (currently hardcoded)
    - ParameterDiscoveryNode results (currently provided)

    But PlanningNode is HIGHEST PRIORITY since it provides critical
    architectural decisions that significantly impact generation quality.

    Returns:
        Tuple of (plan_markdown, parsed_result)
    """
    # Create a simple but realistic plan based on the test case
    node_chain = " >> ".join(test_case.browsed_node_ids[:3])  # Simplified chain

    plan_markdown = f"""## Workflow Plan

Based on the requirements, I'll create a workflow that {test_case.name.replace("_", " ")}.

The workflow will:
1. Start by gathering the necessary data
2. Process and transform the information
3. Generate the final output

This follows a clear data pipeline pattern.

### Feasibility Assessment
**Status**: FEASIBLE
**Node Chain**: {node_chain}
**Confidence**: High
"""

    parsed = {"status": "FEASIBLE", "node_chain": node_chain, "missing_capabilities": []}

    return plan_markdown, parsed


def _extract_steps_from_input(user_input_lower: str) -> list[str]:
    """Extract workflow steps based on keywords in user input."""
    steps = []

    # Mapping of keywords to step descriptions
    keyword_to_step = {
        "github": "Fetch data from GitHub repository",
        "issues": "Retrieve and filter issues",
        "changelog": "Generate formatted changelog",
        ("write", "save"): "Write output to file",
        "commit": "Commit changes to repository",
        "slack": "Send notification to Slack",
        ("shell", "run"): "Execute shell commands",
        "test": "Run tests and analyze results",
        "release": "Create release artifacts",
        ("pr", "pull request"): "Create pull request",
    }

    for keywords, step in keyword_to_step.items():
        if isinstance(keywords, tuple):
            if any(kw in user_input_lower for kw in keywords):
                steps.append(step)
        elif keywords in user_input_lower:
            steps.append(step)

    return steps if steps else ["Process input data", "Transform information", "Generate output"]


def simulate_requirements_result(test_case: WorkflowTestCase) -> dict:
    """Simulate what RequirementsAnalysisNode would produce."""
    user_input_lower = test_case.user_input.lower()
    steps = _extract_steps_from_input(user_input_lower)

    return {
        "is_clear": True,
        "clarification_needed": None,
        "steps": steps,
        "estimated_nodes": len(test_case.expected_nodes),
        "required_capabilities": list({node.split("-")[0] for node in test_case.browsed_node_ids}),
        "complexity_indicators": {
            "has_conditional": False,
            "has_iteration": "issues" in user_input_lower,
            "has_external_services": any(x in user_input_lower for x in ["github", "slack", "http"]),
        },
    }


def build_test_planning_context(browsed_components: dict, include_mcp_mocks: bool = False) -> str:
    """Build planning context for the test."""
    # Get real registry data
    registry = Registry()
    registry_data = {}
    with contextlib.suppress(Exception):
        registry_data = registry.load()

    # Add MCP mocks if needed
    if include_mcp_mocks:
        registry_data.update({
            "mcp-slack-slack_get_channel_history": {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "interface": {
                    "description": "Get Slack channel history",
                    "inputs": [
                        {"key": "channel_id", "type": "str", "description": "Slack channel ID"},
                        {"key": "limit", "type": "int", "description": "Number of messages"},
                    ],
                    "outputs": [
                        {"key": "messages", "type": "list", "description": "Channel messages"},
                        {"key": "channel_info", "type": "dict", "description": "Channel information"},
                    ],
                },
            },
            "mcp-slack-slack_post_message": {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "interface": {
                    "description": "Post message to Slack",
                    "inputs": [
                        {"key": "channel_id", "type": "str", "description": "Channel ID"},
                        {"key": "message", "type": "str", "description": "Message text"},
                        {"key": "text", "type": "str", "description": "Message text (alt)"},
                    ],
                    "outputs": [
                        {"key": "result", "type": "dict", "description": "Post result"},
                        {"key": "message_id", "type": "str", "description": "Message ID"},
                        {"key": "timestamp", "type": "str", "description": "Message timestamp"},
                    ],
                },
            },
        })

    # Build context using the real context builder
    return build_planning_context(
        selected_node_ids=browsed_components["node_ids"],
        selected_workflow_names=browsed_components.get("workflow_names", []),
        registry_metadata=registry_data,
    )


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


def validate_node_output_refs(workflow: dict, test_case: WorkflowTestCase) -> list[str]:
    """Validate that expected node output references are present."""
    errors = []
    actual_refs = extract_node_references(workflow)

    if not test_case.node_output_refs:
        return errors

    if not actual_refs and test_case.node_output_refs:
        errors.append("No node output references found (expected ${node.output} patterns)")
        return errors

    # Check each expected reference
    missing_outputs = []
    for expected_ref in test_case.node_output_refs:
        parts = expected_ref.split(".")
        if len(parts) != 2:
            continue

        expected_node_pattern, expected_output = parts

        # Check if any actual ref has this output field
        matching_refs = [ref for ref in actual_refs if ref.endswith(f".{expected_output}")]

        if not matching_refs:
            # Special handling for shell outputs
            if expected_output in ["stdout", "stderr", "exit_code"]:
                shell_outputs = ["stdout", "stderr", "exit_code"]
                if any(any(ref.endswith(f".{so}") for ref in actual_refs) for so in shell_outputs):
                    continue
            missing_outputs.append(f"*.{expected_output}")

    if missing_outputs:
        errors.append(f"Missing output references: {', '.join(missing_outputs)}")

    return errors


def validate_purposes(workflow: dict) -> list[str]:
    """Validate purpose field quality for all nodes."""
    errors = []
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

    return errors


def validate_linear_workflow(workflow: dict) -> list[str]:
    """Validate workflow is linear (no branching)."""
    errors = []
    edges = workflow.get("edges", [])
    from_counts = {}

    for edge in edges:
        from_node = edge.get("from")
        if from_node:
            from_counts[from_node] = from_counts.get(from_node, 0) + 1

    for node_id, count in from_counts.items():
        if count > 1:
            errors.append(f"Branching detected: node '{node_id}' has {count} outgoing edges")

    return errors


def validate_template_usage(workflow: dict, test_case: WorkflowTestCase) -> list[str]:
    """Validate template variables are properly used."""
    errors = []
    template_vars = extract_template_variables(workflow)
    declared_inputs = set(workflow.get("inputs", {}).keys())

    # All declared inputs should be used
    unused = declared_inputs - template_vars
    if unused:
        errors.append(f"Declared but unused inputs: {unused}")

    return errors


def create_test_registry():
    """Create registry with MCP mock nodes for testing.

    All other nodes come from the real registry.
    """
    registry = Registry()

    # Load real registry data first
    real_data = {}
    with contextlib.suppress(Exception):
        real_data = registry.load()

    # Add MCP mock nodes (based on real trace evidence)
    test_nodes = {
        "mcp-slack-slack_get_channel_history": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "interface": {
                "inputs": [
                    {"key": "channel_id", "type": "str", "description": "Slack channel ID"},
                    {"key": "limit", "type": "int", "description": "Number of messages"},
                ],
                "outputs": [
                    {"key": "messages", "type": "list", "description": "Channel messages"},
                    {"key": "channel_info", "type": "dict", "description": "Channel info"},
                ],
            },
        },
        "mcp-slack-slack_post_message": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "interface": {
                "inputs": [
                    {"key": "channel_id", "type": "str", "description": "Channel ID"},
                    {"key": "text", "type": "str", "description": "Message text"},
                ],
                "outputs": [
                    {"key": "message_id", "type": "str", "description": "Message ID"},
                    {"key": "timestamp", "type": "str", "description": "Timestamp"},
                ],
            },
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


def _validate_basic_structure(workflow: dict, test_case: WorkflowTestCase) -> Optional[tuple[bool, str]]:
    """Validate basic workflow structure (nodes, count, critical nodes).

    Returns None if validation passes, or (False, error_msg) if it fails.
    """
    if not workflow.get("nodes"):
        return False, "No nodes in workflow"

    node_count = len(workflow["nodes"])
    if node_count < test_case.min_nodes:
        return False, f"Too few nodes: {node_count} < {test_case.min_nodes}"
    if node_count > test_case.max_nodes:
        return False, f"Too many nodes: {node_count} > {test_case.max_nodes}"

    # Check critical nodes are present
    if test_case.critical_nodes:
        node_types = [node["type"] for node in workflow["nodes"]]
        for critical in test_case.critical_nodes:
            if critical not in node_types:
                return False, f"Missing critical node: {critical}"

    return None


def _check_required_inputs(workflow_inputs: set, must_have_inputs: list) -> Optional[str]:
    """Check that all required inputs are present."""
    for required_input in must_have_inputs:
        if required_input not in workflow_inputs:
            # Allow fuzzy matching for slight renames
            fuzzy_match = [inp for inp in workflow_inputs if required_input in inp or inp in required_input]
            if not fuzzy_match:
                return f"Missing required input: {required_input}"
    return None


def _check_discovered_params(
    workflow_inputs: set, discovered_params: dict, must_not_have_inputs: list
) -> Optional[str]:
    """Verify discovered params are declared as inputs."""
    if not discovered_params:
        return None

    expected_params = {k for k in discovered_params if k not in (must_not_have_inputs or [])}
    missing_params = expected_params - workflow_inputs
    if missing_params:
        # Check for obvious renames
        truly_missing = []
        for param in missing_params:
            # Look for partial matches
            if not any(param.split("_")[-1] in inp for inp in workflow_inputs):
                truly_missing.append(param)
        if truly_missing:
            return f"Discovered params not declared as inputs: {truly_missing}"
    return None


def _validate_inputs(workflow: dict, test_case: WorkflowTestCase) -> Optional[tuple[bool, str]]:
    """Validate workflow inputs match requirements.

    Returns None if validation passes, or (False, error_msg) if it fails.
    """
    workflow_inputs = set(workflow.get("inputs", {}).keys())

    # Check required inputs
    error = _check_required_inputs(workflow_inputs, test_case.must_have_inputs)
    if error:
        return False, error

    # Check forbidden inputs are NOT present
    for forbidden_input in test_case.must_not_have_inputs:
        if forbidden_input in workflow_inputs:
            return False, f"Has forbidden input: {forbidden_input} (should be node output, not user input)"

    # Check discovered params
    error = _check_discovered_params(workflow_inputs, test_case.discovered_params, test_case.must_not_have_inputs)
    if error:
        return False, error

    return None


def _check_hardcoded_values(workflow: dict, test_case: WorkflowTestCase) -> list[str]:
    """Check for hardcoded values that should be templates."""
    errors = []
    workflow_str = json.dumps(workflow)

    for param_name, param_value in test_case.discovered_params.items():
        if param_value and str(param_value) != "" and f'"{param_value}"' in workflow_str:
            # Check if it's properly templated
            template_pattern = f"${{{param_name}"
            if template_pattern not in workflow_str and f"${param_name}" not in workflow_str:
                # Exclude the inputs section from this check (defaults are OK there)
                workflow_copy = workflow.copy()
                workflow_copy.pop("inputs", None)
                workflow_nodes_str = json.dumps(workflow_copy)
                if f'"{param_value}"' in workflow_nodes_str:
                    errors.append(f"Hardcoded value '{param_value}' instead of template ${{{param_name}}}")

    return errors


def validate_workflow(workflow: dict, test_case: WorkflowTestCase) -> tuple[bool, str]:
    """Validate the generated workflow matches expectations.

    This performs comprehensive validation matching the original test:
    1. Basic structure checks
    2. Critical node presence
    3. Input validation with discovered params
    4. Template usage validation
    5. Node output references
    6. Purpose quality checks
    7. Linear workflow validation
    8. Full workflow validation
    """
    from pflow.core.workflow_validator import WorkflowValidator

    all_errors = []

    # Basic structure validation
    basic_result = _validate_basic_structure(workflow, test_case)
    if basic_result:
        return basic_result

    # Input validation
    input_result = _validate_inputs(workflow, test_case)
    if input_result:
        return input_result

    # Check for hardcoded values
    hardcoded_errors = _check_hardcoded_values(workflow, test_case)
    all_errors.extend(hardcoded_errors)

    # Additional quality validations

    # Validate template usage (unused inputs)
    template_errors = validate_template_usage(workflow, test_case)
    all_errors.extend(template_errors)

    # Validate node output references
    ref_errors = validate_node_output_refs(workflow, test_case)
    all_errors.extend(ref_errors)

    # Validate purposes are descriptive
    purpose_errors = validate_purposes(workflow)
    all_errors.extend(purpose_errors)

    # Validate workflow is linear (no branching)
    linear_errors = validate_linear_workflow(workflow)
    all_errors.extend(linear_errors)

    # Check if test uses MCP nodes
    uses_mcp_nodes = any("mcp" in node_id for node_id in test_case.browsed_node_ids)

    # Create appropriate registry
    registry = create_test_registry() if uses_mcp_nodes else Registry()

    # Run full production validation
    validation_errors, _ = WorkflowValidator.validate(
        workflow,
        extracted_params=test_case.discovered_params,
        registry=registry,
        skip_node_types=False,
    )

    # Combine all errors
    if validation_errors:
        all_errors.extend([f"Validation: {e}" for e in validation_errors[:3]])

    if all_errors:
        # Return first error for clarity
        return False, all_errors[0]

    return True, ""


# Test cases - all 15 from the original file
def get_test_cases():
    """Get all test cases for the new context-based workflow generation."""
    return [
        # Test 1: North Star Example - Generate Changelog
        WorkflowTestCase(
            name="changelog_from_issues",
            user_input="Get the last 20 closed issues from github repo anthropic/pflow, group them into sections (Features, Bugs, Documentation) based on their labels, create a markdown changelog with '## Version X.Y.Z' header and bullet points for each issue showing number and title, write to CHANGELOG.md, then commit with message 'Update changelog for release'",
            discovered_params={
                "repo_owner": "anthropic",
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
            critical_nodes=["github-list-issues", "llm", "write-file", "git-commit"],
            allowed_extra_nodes=["llm"],
        ),
        # Test 2: Multi-Repository Dependency Security Audit (HARDER)
        WorkflowTestCase(
            name="security_audit_pipeline",
            user_input="Check if package.json exists using 'test -f package.json', if it exists run 'npm audit --json'. Check if requirements.txt exists using 'test -f requirements.txt', if it exists run 'pip-audit requirements.txt --format json'. Run 'trivy fs . --format json --scanners vuln' for overall scan. Get GitHub issues with label 'security' or 'vulnerability' from repo anthropic/pflow. Parse all security reports extracting critical and high severity issues, correlate with GitHub issues, generate unified security report with vulnerabilities by severity and affected packages grouped by ecosystem. Write report to security-audit.md and machine-readable vulnerabilities.json.",
            discovered_params={
                "repo_owner": "anthropic",
                "repo_name": "pflow",
                "report_file": "security-audit.md",
                "json_file": "vulnerabilities.json",
            },
            browsed_node_ids=["shell", "github-list-issues", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["shell", "shell", "shell", "github-list-issues", "llm", "write-file", "write-file"],
            min_nodes=8,
            max_nodes=14,
            must_have_inputs=["repo_owner", "repo_name", "report_file", "json_file"],
            must_not_have_inputs=["vulnerabilities", "issues", "npm_audit", "pip_audit"],
            node_output_refs=["npm_check.stdout", "pip_check.stdout", "trivy.stdout", "get_issues.issues"],
            category="complex_pipeline",
            why_hard="Multiple security tools, JSON parsing, cross-referencing with GitHub",
            critical_nodes=["shell", "github-list-issues", "llm", "write-file"],
            allowed_extra_nodes=["shell", "llm"],
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
            max_nodes=5,
            must_have_inputs=["source_file", "test_file"],
            must_not_have_inputs=["content", "tests"],
            node_output_refs=["read.content", "generate.response"],
            category="developer_workflow",
            why_hard="Common developer task",
            critical_nodes=["read-file", "llm", "write-file"],
            allowed_extra_nodes=["llm"],
        ),
        # Test 4: Documentation Updater
        WorkflowTestCase(
            name="documentation_updater",
            user_input="Read README.md and api.json, find the section '## API Reference' in README.md, replace it with a new markdown table generated from api.json showing Method, Endpoint, and Description columns, write the updated README back to README.md",
            discovered_params={
                "readme_file": "README.md",
                "api_file": "api.json",
            },
            browsed_node_ids=["read-file", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["read-file", "read-file", "llm", "write-file"],
            min_nodes=4,
            max_nodes=6,
            must_have_inputs=["readme_file", "api_file"],
            must_not_have_inputs=["content", "updated_content"],
            node_output_refs=["read_readme.content", "read_api.content", "update.response"],
            category="developer_workflow",
            why_hard="Multiple file reads and updates",
            critical_nodes=["read-file", "llm", "write-file"],
            allowed_extra_nodes=["read-file", "llm"],
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
            max_nodes=5,
            must_have_inputs=["report_file"],
            must_not_have_inputs=["packages", "report"],
            node_output_refs=["check.stdout", "analyze.response"],
            category="developer_workflow",
            why_hard="Shell command integration",
            critical_nodes=["shell", "llm", "write-file"],
            allowed_extra_nodes=["llm"],
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
            max_nodes=6,
            must_have_inputs=["channel_id", "message_limit"],
            must_not_have_inputs=["messages", "answers"],
            node_output_refs=["get_history.messages", "answer.response"],
            category="mcp_integration",
            why_hard="Real MCP integration from trace",
            critical_nodes=["mcp-slack-slack_get_channel_history", "mcp-slack-slack_post_message"],
            allowed_extra_nodes=["llm"],
        ),
        # Test 7: Comprehensive Repository Analytics Pipeline (HARDER)
        WorkflowTestCase(
            name="repository_analytics_pipeline",
            user_input="Generate complete repository analytics: Run 'git log --since=\"30 days ago\" --pretty=format:\"%H|%an|%ae|%at|%s\" --numstat' for detailed commit history. Run 'git shortlog -sn --since=\"30 days ago\"' for contributor stats. Run 'cloc . --json --exclude-dir=node_modules,venv,.git' for code metrics. Run 'find . -type f -name \"*.md\" | wc -l' for documentation count. Get last 100 issues (both open and closed) from GitHub repo anthropic/pflow. Get all pull requests from last 30 days. Analyze commit patterns, calculate average time between commits, identify top contributors, calculate issue closure rate, PR merge rate, lines of code by language. Generate comprehensive analytics report with sections for velocity metrics, contributor analytics, code composition, issue/PR statistics. Write main report to analytics-report.md and data visualization file to analytics-data.json. Create branch 'analytics-$(date +%Y%m%d)', commit both files with message 'Analytics report $(date +%Y-%m-%d)', create PR requesting review.",
            discovered_params={
                "repo_owner": "anthropic",
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
            ],
            min_nodes=12,
            max_nodes=16,
            must_have_inputs=["repo_owner", "repo_name", "report_file", "data_file", "issue_limit"],
            must_not_have_inputs=["commits", "issues", "prs", "analytics"],
            node_output_refs=[
                "git_log.stdout",
                "shortlog.stdout",
                "cloc.stdout",
                "list_issues.issues",
                "list_prs.prs",
            ],
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
            ],
            allowed_extra_nodes=["shell", "llm"],
        ),
        # Test 8: HTTP Weather Integration
        WorkflowTestCase(
            name="http_weather_integration",
            user_input="Use HTTP to fetch weather data from https://api.openweathermap.org/data/2.5/weather?q=San Francisco&appid=YOUR_API_KEY, generate a human-readable weather report including temperature and conditions, format as markdown and save to weather-report.md",
            discovered_params={
                "api_key": "YOUR_API_KEY",
                "report_file": "weather-report.md",
            },
            browsed_node_ids=["http", "llm", "write-file"],
            validation_errors=None,
            expected_nodes=["http", "llm", "write-file"],
            min_nodes=3,
            max_nodes=5,
            must_have_inputs=["api_key", "report_file"],
            must_not_have_inputs=["weather", "report"],
            node_output_refs=["http.response", "llm.response"],
            category="integration",
            why_hard="HTTP API integration with data processing",
            critical_nodes=["http", "llm", "write-file"],
            allowed_extra_nodes=["llm"],
        ),
        # Test 9: GitHub Slack Notifier
        WorkflowTestCase(
            name="github_slack_notifier",
            user_input="Get issues closed in the last 7 days from github repo anthropic/pflow, create a summary showing total count, list of issue titles with numbers, and top contributors, post to slack channel updates with heading 'Weekly Closed Issues Report'",
            discovered_params={"repo_owner": "anthropic", "repo_name": "pflow", "channel_id": "updates"},
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
            critical_nodes=["github-list-issues", "llm", "mcp-slack-slack_post_message"],
            allowed_extra_nodes=["llm"],
        ),
        # Test 10: Automated Test Failure Analysis Pipeline (HARDER)
        WorkflowTestCase(
            name="test_failure_analysis",
            user_input="Run 'npm test -- --json --outputFile=test-results.json' to execute tests. Read test-results.json and parse to identify all failing tests. Run 'git log --since=\"7 days ago\" --oneline' to find recent changes. Run 'git blame --show-stats' to get overall contribution stats. Search GitHub issues for 'test failure' or 'broken test' in repo anthropic/pflow. Search GitHub PRs with label 'bug' or 'test'. Analyze failure patterns and correlate with recent repository activity. Generate detailed failure analysis report including: list of failing tests, recent commits that may be related, active issues and PRs about tests, recommendations for fixes. Write main report to test-analysis.md, create summary as test-failures.csv, post key findings to Slack channel 'testing'.",
            discovered_params={
                "repo_owner": "anthropic",
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
            min_nodes=9,
            max_nodes=16,
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
            allowed_extra_nodes=["shell", "llm"],
        ),
        # Test 11: Full Release Pipeline (Complex)
        WorkflowTestCase(
            name="full_release_pipeline",
            user_input="Get the latest git tag, then use that tag to get all commits since that tag with git-log, generate release notes grouping commits by type (feat/fix/docs), use shell to create git tag v1.3.0 and push it, use shell to run 'gh release create v1.3.0 --notes-file release-notes.md', append the release notes to CHANGELOG.md with ## v1.3.0 header, commit with message 'Release v1.3.0', create PR to main branch for repo anthropic/pflow",
            discovered_params={
                "repo_owner": "anthropic",
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
            max_nodes=12,
            must_have_inputs=["repo_owner", "repo_name", "new_tag", "changelog_file"],
            must_not_have_inputs=["commits", "release_notes", "latest_tag"],
            node_output_refs=["latest_tag", "commits", "response"],
            category="complex_pipeline",
            why_hard="8+ nodes with shell workarounds for git tag and gh release",
            critical_nodes=[
                "git-get-latest-tag",
                "git-log",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],
            allowed_extra_nodes=["llm", "shell"],
        ),
        # Test 12: Issue Triage Automation (Complex)
        WorkflowTestCase(
            name="issue_triage_automation",
            user_input="Get 50 open issues from github repo anthropic/pflow, categorize as high priority if labeled 'bug' or 'security', medium if 'enhancement', low otherwise, group by days since creation (0-7, 8-30, 30+), create markdown report with tables for each priority level and recommendations for issues older than 30 days, save to triage-$(date +%Y-%m-%d).md using shell for date, commit with message 'Triage report for $(date +%Y-%m-%d)', create PR to main branch",
            discovered_params={
                "repo_owner": "anthropic",
                "repo_name": "pflow",
                "issue_limit": "50",
            },
            browsed_node_ids=["github-list-issues", "llm", "shell", "write-file", "git-commit", "github-create-pr"],
            validation_errors=None,
            expected_nodes=[
                "github-list-issues",
                "llm",
                "shell",
                "write-file",
                "git-commit",
                "github-create-pr",
            ],
            min_nodes=6,
            max_nodes=10,
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
            ],
            allowed_extra_nodes=["shell", "llm"],
        ),
        # Test 13: Codebase Quality Report (Complex)
        WorkflowTestCase(
            name="codebase_quality_report",
            user_input="Run 'npm run lint' and capture output, run 'npm test -- --coverage --json' to get coverage percentage, run 'npx complexity-report src/ --format json' to analyze complexity, get last 10 open bugs from github repo anthropic/pflow, combine all results into a markdown quality report with sections for each metric, save to quality-report.md, checkout quality-reports branch, commit with message 'Quality report $(date +%Y-%m-%d)', push to origin, create PR to main",
            discovered_params={
                "repo_owner": "anthropic",
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
            ],
            allowed_extra_nodes=["llm", "shell"],
        ),
        # Test 14: Template Stress Test (Edge)
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
            expected_nodes=["read-file", "llm", "write-file", "shell", "mcp-slack-slack_post_message"],
            min_nodes=4,
            max_nodes=6,
            must_have_inputs=["config_file", "version_file", "deploy_url", "slack_channel"],
            must_not_have_inputs=["config", "data", "result"],
            node_output_refs=["read.content", "process.response"],
            category="edge_case",
            why_hard="Heavy template variable usage",
            critical_nodes=[
                "read-file",
                "write-file",
                "shell",
                "mcp-slack-slack_post_message",
            ],
            allowed_extra_nodes=["llm"],
        ),
        # Test 15: Validation Recovery Test (Edge)
        WorkflowTestCase(
            name="validation_recovery_test",
            user_input="Get open issues from github repo anthropic/pflow, analyze their labels and age to identify stale issues (>60 days without activity), generate a markdown report listing stale issues with recommendations for closure or follow-up, save to stale-issues-report.md",
            discovered_params={
                "repo_owner": "anthropic",
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
            critical_nodes=["github-list-issues", "llm", "write-file"],
            allowed_extra_nodes=["llm"],
        ),
    ]


class TestWorkflowGeneratorContextPrompt:
    """Test WorkflowGeneratorNode with new context architecture."""

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_workflow_generation_with_context(self, test_case):
        """Test workflow generation using cache-optimized context blocks."""

        # Step 1: Prepare components and context
        browsed_components = test_case.get_browsed_components()
        uses_mcp = any("mcp" in node_id for node_id in test_case.browsed_node_ids)
        planning_context = build_test_planning_context(browsed_components, include_mcp_mocks=uses_mcp)

        # Step 2: Templatize user input (like ParameterDiscoveryNode would)
        from pflow.planning.nodes import ParameterDiscoveryNode

        param_node = ParameterDiscoveryNode()
        templatized_input = param_node._templatize_user_input(test_case.user_input, test_case.discovered_params)

        # Step 3: Simulate requirements analysis
        requirements_result = simulate_requirements_result(test_case)

        # Step 4: Build base blocks using PlannerContextBuilder
        base_blocks = PlannerContextBuilder.build_base_blocks(
            user_request=templatized_input,
            requirements_result=requirements_result,
            browsed_components=browsed_components,
            planning_context=planning_context,
            discovered_params=test_case.discovered_params,
        )

        # Step 5: Simulate planning output and extend blocks
        plan_markdown, parsed_plan = simulate_planning_output(test_case)
        extended_blocks = PlannerContextBuilder.append_planning_block(base_blocks, plan_markdown, parsed_plan)

        # Step 6: Prepare shared store for WorkflowGeneratorNode
        shared = {
            "user_input": test_case.user_input,
            "templatized_input": templatized_input,
            "discovered_params": test_case.discovered_params,
            "browsed_components": browsed_components,
            "planner_extended_blocks": extended_blocks,  # NEW: Extended blocks from planning
            "generation_attempts": 0,
        }

        # Add validation errors for retry tests
        if test_case.validation_errors:
            # For retry, accumulate blocks with previous attempt
            accumulated_blocks = PlannerContextBuilder.append_errors_block(extended_blocks, test_case.validation_errors)
            shared["planner_accumulated_blocks"] = accumulated_blocks
            shared["validation_errors"] = test_case.validation_errors
            shared["generation_attempts"] = 1

        try:
            # Execute workflow generation
            node = WorkflowGeneratorNode()
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            workflow = exec_res.get("workflow", {})

            if not workflow:
                failure_reason = "No workflow generated"
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

            # Validate the workflow
            passed, failure_reason = validate_workflow(workflow, test_case)

            # Log for debugging
            if not passed:
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
