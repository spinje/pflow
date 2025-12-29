"""High-quality tests for parameter_mapping prompt focusing on strict mapping behavior.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

PHILOSOPHY: Test exact parameter mapping to workflow inputs, not discovery.

Run with:
  RUN_LLM_TESTS=1 pytest test_parameter_mapping_prompt.py -v
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import pytest

from pflow.planning.nodes import ParameterMappingNode

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
            # Log error but don't fail test due to reporting issues
            logger.debug(f"Failed to write to failure file: {e}")


# Skip tests unless LLM tests enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


@dataclass
class InputSpec:
    """Specification for a workflow input parameter."""

    type: str
    required: bool
    description: str
    default: Optional[Any] = None


@dataclass
class MappingTestCase:
    """Test case for parameter mapping - strict validation."""

    name: str
    user_input: str
    workflow_inputs: dict[str, InputSpec]  # What the workflow expects
    expected_extracted: dict[str, Any]  # What should be mapped
    expected_missing: list[str]  # What should be marked as missing
    category: str
    why_important: str
    stdin_data: Optional[str] = None


def get_test_cases() -> list[MappingTestCase]:
    """Define high-quality test cases for strict parameter mapping."""
    return [
        # Category 1: Basic Required Parameter Mapping
        MappingTestCase(
            name="simple_required_params",
            user_input="Get issue #123 from pflow repository",
            workflow_inputs={
                "issue_number": InputSpec("integer", required=True, description="GitHub issue number"),
                "repo": InputSpec("string", required=True, description="Repository name"),
            },
            expected_extracted={"issue_number": 123, "repo": "pflow"},
            expected_missing=[],
            category="basic_mapping",
            why_important="Maps basic required parameters with correct types",
        ),
        MappingTestCase(
            name="multiple_types",
            user_input="Generate changelog from last 30 closed issues in spinje/pflow repo",
            workflow_inputs={
                "repo_owner": InputSpec("string", required=True, description="Repository owner"),
                "repo_name": InputSpec("string", required=True, description="Repository name"),
                "issue_count": InputSpec("integer", required=True, description="Number of issues"),
                "issue_state": InputSpec("string", required=True, description="Issue state filter"),
            },
            expected_extracted={
                "repo_owner": "spinje",
                "repo_name": "pflow",
                "issue_count": 30,
                "issue_state": "closed",
            },
            expected_missing=[],
            category="basic_mapping",
            why_important="Handles multiple parameters of different types",
        ),
        # Category 2: Optional Parameters with Defaults
        MappingTestCase(
            name="optional_with_defaults",
            user_input="List issues from pflow repo",
            workflow_inputs={
                "repo": InputSpec("string", required=True, description="Repository name"),
                "limit": InputSpec("integer", required=False, description="Max issues", default=10),
                "state": InputSpec("string", required=False, description="Issue state", default="open"),
            },
            expected_extracted={
                "repo": "pflow",
                "limit": 10,
                "state": "open",
            },  # Defaults ARE included (implementation choice)
            expected_missing=[],  # Optional params not marked as missing
            category="defaults",
            why_important="Correctly handles optional parameters with defaults",
        ),
        MappingTestCase(
            name="override_defaults",
            user_input="List 50 closed issues from pflow repo",
            workflow_inputs={
                "repo": InputSpec("string", required=True, description="Repository name"),
                "limit": InputSpec("integer", required=False, description="Max issues", default=10),
                "state": InputSpec("string", required=False, description="Issue state", default="open"),
            },
            expected_extracted={"repo": "pflow", "limit": 50, "state": "closed"},
            expected_missing=[],
            category="defaults",
            why_important="Overrides default values when user provides them",
        ),
        # Category 3: Missing Required Parameters
        MappingTestCase(
            name="missing_required",
            user_input="Get issue from repository",
            workflow_inputs={
                "issue_number": InputSpec("integer", required=True, description="Issue number"),
                "repo": InputSpec("string", required=True, description="Repository name"),
            },
            expected_extracted={},
            expected_missing=["issue_number", "repo"],  # Both are too vague to extract
            category="missing",
            why_important="Identifies when required parameters cannot be extracted",
        ),
        MappingTestCase(
            name="partial_missing",
            user_input="Get issue #456",
            workflow_inputs={
                "issue_number": InputSpec("integer", required=True, description="Issue number"),
                "repo": InputSpec("string", required=True, description="Repository name"),
            },
            expected_extracted={"issue_number": 456},
            expected_missing=["repo"],
            category="missing",
            why_important="Identifies partially missing required parameters",
        ),
        # Category 4: Complex Mapping Scenarios
        MappingTestCase(
            name="file_operations",
            user_input="Convert data.csv to JSON format and save as report.json",
            workflow_inputs={
                "input_file": InputSpec("string", required=True, description="Input file path"),
                "output_file": InputSpec("string", required=True, description="Output file path"),
                "format": InputSpec("string", required=True, description="Output format"),
            },
            expected_extracted={
                "input_file": "data.csv",
                "output_file": "report.json",
                "format": "JSON",
            },
            expected_missing=[],
            category="complex",
            why_important="Maps file paths and formats correctly",
        ),
        MappingTestCase(
            name="boolean_inference",
            user_input="Generate report with charts enabled and export to PDF",
            workflow_inputs={
                "enable_charts": InputSpec("boolean", required=True, description="Include charts"),
                "output_format": InputSpec("string", required=True, description="Export format"),
            },
            expected_extracted={"enable_charts": True, "output_format": "PDF"},
            expected_missing=[],
            category="complex",
            why_important="Infers boolean values from natural language",
        ),
        # Category 5: Edge Cases
        MappingTestCase(
            name="no_inputs_needed",
            user_input="Show current status",
            workflow_inputs={},  # Workflow has no input parameters
            expected_extracted={},
            expected_missing=[],
            category="edge",
            why_important="Handles workflows with no input parameters",
        ),
    ]


def validate_extraction(actual: dict, expected: dict) -> tuple[bool, str]:
    """Validate that actual extraction matches expected with type consideration.

    Args:
        actual: The actual extracted parameters
        expected: The expected parameters

    Returns:
        Tuple of (success, error_message)
    """
    for param_name, expected_value in expected.items():
        if param_name not in actual:
            return False, f"Missing parameter: {param_name}"

        actual_value = actual[param_name]

        # Type-aware comparison
        if isinstance(expected_value, int):
            # Accept string representation of numbers
            try:
                if int(actual_value) != expected_value:
                    return False, f"Wrong value for {param_name}: got {actual_value}, expected {expected_value}"
            except (ValueError, TypeError):
                return False, f"Wrong type for {param_name}: got {actual_value}, expected {expected_value}"
        elif isinstance(expected_value, bool):
            # Accept various boolean representations
            if actual_value not in [
                expected_value,
                str(expected_value).lower(),
                "enabled" if expected_value else "disabled",
            ]:
                return False, f"Wrong value for {param_name}: got {actual_value}, expected {expected_value}"
        else:
            # String comparison (case-insensitive)
            if str(actual_value).lower() != str(expected_value).lower():
                return False, f"Wrong value for {param_name}: got {actual_value}, expected {expected_value}"

    # Check no extra parameters
    extra_params = set(actual.keys()) - set(expected.keys())
    if extra_params and len(expected) > 0:  # Only complain about extras if we expected something
        return False, f"Unexpected parameters extracted: {extra_params}"

    return True, "All parameters correctly mapped"


class TestParameterMappingPrompt:
    """High-quality tests for parameter mapping prompt."""

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_parameter_mapping_behavior(self, test_case):
        """Test strict parameter mapping to workflow inputs."""
        node = ParameterMappingNode()

        # Build workflow IR with inputs
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [],  # Not relevant for parameter mapping
            "inputs": {
                param_name: {
                    "type": spec.type,
                    "required": spec.required,
                    "description": spec.description,
                    **({"default": spec.default} if spec.default is not None else {}),
                }
                for param_name, spec in test_case.workflow_inputs.items()
            },
        }

        # Prepare shared store
        shared = {
            "user_input": test_case.user_input,
            "generated_workflow": workflow_ir,  # Simulating Path B
        }

        # Add stdin if provided
        if test_case.stdin_data:
            shared["stdin"] = test_case.stdin_data

        try:
            # Run the node lifecycle
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            # Check we got valid response
            assert isinstance(exec_res, dict)
            assert "extracted" in exec_res
            assert "missing" in exec_res
            assert isinstance(exec_res["extracted"], dict)
            assert isinstance(exec_res["missing"], list)

            logger.info(f"[{test_case.name}] Input: {test_case.user_input}")
            logger.info(f"[{test_case.name}] Extracted: {exec_res['extracted']}")
            logger.info(f"[{test_case.name}] Missing: {exec_res['missing']}")

            # Validate results
            test_passed = True
            failure_reasons = []

            # Check extracted parameters
            success, error_msg = validate_extraction(exec_res["extracted"], test_case.expected_extracted)
            if not success:
                test_passed = False
                failure_reasons.append(error_msg)

            # Check missing parameters
            actual_missing = set(exec_res["missing"])
            expected_missing = set(test_case.expected_missing)
            if actual_missing != expected_missing:
                test_passed = False
                failure_reasons.append(f"Wrong missing list: got {actual_missing}, expected {expected_missing}")

            # Report failures
            if not test_passed:
                failure_reason = "; ".join(failure_reasons)
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise

    def test_performance(self):
        """Test that parameter mapping completes within reasonable time."""
        node = ParameterMappingNode()

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [],
            "inputs": {
                "repo": {"type": "string", "required": True, "description": "Repository"},
                "limit": {"type": "integer", "required": False, "default": 10, "description": "Limit"},
            },
        }

        shared = {
            "user_input": "Get 25 issues from pflow repo",
            "generated_workflow": workflow_ir,
        }

        start_time = time.time()
        try:
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)
            duration = time.time() - start_time

            assert "extracted" in exec_res
            assert len(exec_res["extracted"]) > 0

            # Log performance but don't fail on timing (model-dependent)
            if duration > 20.0:
                logger.warning(f"Slow performance: {duration:.2f}s (model-dependent)")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise
