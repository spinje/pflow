"""Comprehensive tests for metadata generation prompt with pytest parametrization.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify the metadata_generation prompt correctly generates workflow metadata.

Run with:
  RUN_LLM_TESTS=1 pytest test_metadata_generation_prompt.py -v

WHAT IT VALIDATES:
- Suggested names are appropriate and kebab-case
- Descriptions are generic (no specific values)
- Search keywords are relevant and varied
- Capabilities accurately reflect the workflow
- Typical use cases are realistic
- Performance is tracked (warnings only, not failures)
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import pytest

from pflow.planning.nodes import MetadataGenerationNode

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
class MetadataTestCase:
    """Test case for metadata generation prompt."""

    name: str
    user_input: str
    nodes_summary: str
    workflow_inputs: str
    discovered_params: str
    expected_name_pattern: Optional[str]  # Regex pattern for name validation
    expected_keywords: list[str]  # Keywords that SHOULD appear
    forbidden_values: list[str]  # Specific values that should NOT appear
    category: str
    why_important: str  # Business value of this test


def get_test_cases() -> list[MetadataTestCase]:
    """Define high-quality test cases for metadata generation."""
    return [
        # === GITHUB WORKFLOWS ===
        MetadataTestCase(
            "changelog_with_specifics",
            "generate changelog from last 30 closed issues in pflow repo",
            "github-list-issues, llm, write-file, github-create-pr",
            "repo_owner, repo_name, issue_count",
            "repo, count, state",
            expected_name_pattern=r".*changelog.*",
            expected_keywords=["changelog", "github", "issues", "release"],
            forbidden_values=["30", "pflow", "last 30"],
            category="github",
            why_important="Must not embed specific values in metadata",
        ),
        MetadataTestCase(
            "issue_triage_vague",
            "triage github issues",
            "github-list-issues, llm, write-file",
            "none",
            "none",
            expected_name_pattern=r".*triage.*|.*issue.*",
            expected_keywords=["triage", "issues", "priorit", "github"],  # Changed to match stem
            forbidden_values=[],
            category="github",
            why_important="Handle vague requests with reasonable metadata",
        ),
        MetadataTestCase(
            "pr_summary_explicit",
            "summarize PR #123 from kubernetes/kubernetes repo",
            "github-get-pr, llm, write-file",
            "repo_owner, repo_name, pr_number",
            "repo, pr",
            expected_name_pattern=r".*pr.*|.*pull.*request.*",
            expected_keywords=["pr", "pull request", "summary", "github"],
            forbidden_values=["123", "kubernetes", "#123"],
            category="github",
            why_important="PR workflows need distinct metadata from issue workflows",
        ),
        # === DATA PROCESSING WORKFLOWS ===
        MetadataTestCase(
            "csv_analysis_specific",
            "analyze sales_2024.csv file and generate insights report",
            "read-file, llm, write-file",
            "input_file, output_file",
            "file, output",
            expected_name_pattern=r".*file.*|.*data.*|.*analyz.*",  # Changed: csv removed since filename is parameterized
            expected_keywords=["analyze", "data", "insights", "file"],  # Changed: csv removed, file added
            forbidden_values=["sales_2024.csv", "sales_2024", "2024"],
            category="data",
            why_important="File-specific names should not leak into metadata",
        ),
        MetadataTestCase(
            "report_generation",
            "generate monthly report from logs",
            "read-file, llm, write-file",
            "log_directory",
            "directory",
            expected_name_pattern=r".*report.*|.*log.*",
            expected_keywords=["report", "log", "analysis", "generate"],  # Changed to match log/logs variations
            forbidden_values=["monthly"],
            category="data",
            why_important="Time-specific values should be parameterizable",
        ),
        MetadataTestCase(
            "data_transformation",
            "transform JSON to CSV format",
            "read-file, llm, write-file",
            "input_file, output_file",
            "input, output",
            expected_name_pattern=r".*transform.*|.*convert.*",
            expected_keywords=["json", "csv", "transform", "convert"],
            forbidden_values=[],
            category="data",
            why_important="Format conversion workflows need clear metadata",
        ),
        # === FILE OPERATIONS WORKFLOWS ===
        MetadataTestCase(
            "bulk_rename_specific",
            "rename all IMG_*.jpg files to vacation_*.jpg in photos folder",
            "read-file, move-file, write-file",
            "source_pattern, target_pattern, directory",
            "pattern, directory",
            expected_name_pattern=r".*rename.*|.*file.*",
            expected_keywords=["rename", "files", "bulk", "batch"],
            forbidden_values=["IMG_", "vacation_", "photos", ".jpg"],
            category="file_ops",
            why_important="Pattern-specific operations should be generic in metadata",
        ),
        MetadataTestCase(
            "backup_creation",
            "create backup of config files",
            "read-file, write-file, git-commit",
            "source_directory, backup_location",
            "source, backup",
            expected_name_pattern=r".*backup.*",
            expected_keywords=["backup", "files", "archiv", "save"],  # Changed to match archive/archival/archiving
            forbidden_values=[],  # Removed "config" - too generic to forbid
            category="file_ops",
            why_important="Backup workflows are common and need discoverable metadata",
        ),
        # === EDGE CASES ===
        MetadataTestCase(
            "overly_specific_request",
            "fetch exactly 42 issues from microsoft/vscode labeled 'bug' created after 2024-01-15 and summarize them in markdown format saved to ~/reports/bugs_jan.md",
            "github-list-issues, llm, write-file",
            "repo_owner, repo_name, label, since_date, count, output_path",
            "repo, label, date, count, path",
            expected_name_pattern=r".*issue.*|.*bug.*",
            expected_keywords=["issues", "bugs", "github", "summary", "report"],
            forbidden_values=["42", "microsoft", "vscode", "2024-01-15", "bugs_jan.md", "~/reports"],
            category="edge",
            why_important="Strip all specific values from overly detailed requests",
        ),
        MetadataTestCase(
            "mixed_domain_workflow",
            "analyze GitHub activity and generate CSV report",
            "github-list-issues, github-list-prs, llm, write-file",
            "repo_owner, repo_name, output_format",
            "repo, format",
            expected_name_pattern=r".*github.*|.*activity.*|.*report.*",
            expected_keywords=["github", "activity", "csv", "report", "analysis"],
            forbidden_values=[],
            category="mixed",
            why_important="Cross-domain workflows need comprehensive keywords",
        ),
    ]


class TestMetadataGenerationPrompt:
    """Tests for metadata generation prompt behavior."""

    def _validate_metadata_structure(self, metadata: dict) -> list[str]:
        """Validate metadata has required structure and format."""
        errors = []

        # Check required fields
        errors.extend(self._check_required_fields(metadata))

        # Validate individual fields
        errors.extend(self._validate_suggested_name(metadata))
        errors.extend(self._validate_description(metadata))
        errors.extend(self._validate_list_field(metadata, "search_keywords", 3, 20))
        errors.extend(self._validate_list_field(metadata, "capabilities", 2, 6))
        errors.extend(self._validate_list_field(metadata, "typical_use_cases", 1, 3))

        return errors

    def _check_required_fields(self, metadata: dict) -> list[str]:
        """Check for required fields in metadata."""
        errors = []
        required_fields = ["suggested_name", "description", "search_keywords", "capabilities", "typical_use_cases"]
        for field in required_fields:
            if field not in metadata:
                errors.append(f"Missing required field: {field}")
        return errors

    def _validate_suggested_name(self, metadata: dict) -> list[str]:
        """Validate the suggested_name field."""
        errors = []
        if "suggested_name" in metadata:
            name = metadata["suggested_name"]
            if not isinstance(name, str):
                errors.append("suggested_name must be a string")
            elif len(name) > 50:
                errors.append(f"suggested_name too long: {len(name)} > 50")
            elif not re.match(r"^[a-z0-9-]+$", name):
                errors.append(f"suggested_name not kebab-case: {name}")
        return errors

    def _validate_description(self, metadata: dict) -> list[str]:
        """Validate the description field."""
        errors = []
        if "description" in metadata:
            desc = metadata["description"]
            if not isinstance(desc, str):
                errors.append("description must be a string")
            elif len(desc) < 50 or len(desc) > 500:
                errors.append(f"description length out of range: {len(desc)}")
        return errors

    def _validate_list_field(self, metadata: dict, field_name: str, min_count: int, max_count: int) -> list[str]:
        """Validate a list field in metadata."""
        errors = []
        if field_name in metadata:
            field_value = metadata[field_name]
            if not isinstance(field_value, list):
                errors.append(f"{field_name} must be a list")
            elif len(field_value) < min_count or len(field_value) > max_count:
                errors.append(f"{field_name} count out of range: {len(field_value)}")
        return errors

    def _check_forbidden_values(self, metadata: dict, forbidden_values: list[str]) -> list[str]:
        """Check that forbidden specific values don't appear in metadata."""
        violations = []

        # Convert metadata to string for searching
        metadata_str = json.dumps(metadata).lower()

        for forbidden in forbidden_values:
            forbidden_lower = forbidden.lower()

            # Only flag if it appears as a distinct value, not as part of a generic term
            # Check for word boundaries to avoid false positives
            if forbidden_lower in metadata_str and self._should_flag_forbidden(forbidden_lower, metadata_str):
                violations.append(f"Found forbidden value: {forbidden}")

        return violations

    def _should_flag_forbidden(self, forbidden_lower: str, metadata_str: str) -> bool:
        """Check if a forbidden value should be flagged."""
        # For specific numbers and names, always flag them
        specific_values = ["pflow", "microsoft", "kubernetes", "vscode", "sales_2024", "bugs_jan.md", "~/reports"]
        return (
            forbidden_lower.isdigit()
            or forbidden_lower in specific_values
            or re.search(r"\b" + re.escape(forbidden_lower) + r"\b", metadata_str) is not None
        )

    def _check_expected_keywords(self, metadata: dict, expected_keywords: list[str]) -> list[str]:
        """Check that expected keywords appear somewhere in metadata (with semantic matching)."""
        combined_text = self._get_searchable_text(metadata)
        keyword_variations = self._get_keyword_variations()

        missing = []
        for keyword in expected_keywords:
            if not self._is_keyword_found(keyword, combined_text, keyword_variations):
                missing.append(keyword)

        return missing

    def _get_searchable_text(self, metadata: dict) -> str:
        """Extract and combine all searchable text from metadata."""
        searchable_text = []
        if "suggested_name" in metadata:
            searchable_text.append(metadata["suggested_name"])
        if "description" in metadata:
            searchable_text.append(metadata["description"])
        if "search_keywords" in metadata:
            searchable_text.extend(metadata["search_keywords"])
        if "capabilities" in metadata:
            searchable_text.extend(metadata["capabilities"])
        return " ".join(searchable_text).lower()

    def _get_keyword_variations(self) -> dict[str, list[str]]:
        """Get keyword variations for semantic matching."""
        return {
            "priorit": ["priority", "prioritize", "prioritizes", "prioritization", "prioritizing", "prioritised"],
            "archiv": ["archive", "archival", "archiving", "archived", "archives"],
            "log": ["log", "logs", "logging", "logged"],
            "analyz": ["analyze", "analysis", "analyzing", "analytical", "analyse"],
            "transform": ["transform", "transformation", "transforming", "transforms"],
            "convert": ["convert", "conversion", "converting", "converts"],
        }

    def _is_keyword_found(self, keyword: str, combined_text: str, keyword_variations: dict[str, list[str]]) -> bool:
        """Check if a keyword or its variations are found in the text."""
        keyword_lower = keyword.lower()

        # Check if it's a stem pattern (for keywords we expect variations of)
        if keyword_lower in keyword_variations:
            # Check if any variation exists in the text
            for variation in keyword_variations[keyword_lower]:
                if variation in combined_text:
                    return True
        else:
            # For non-stem keywords, check exact match
            if keyword_lower in combined_text:
                return True

        return False

    def _check_name_pattern(self, name: str, pattern: Optional[str]) -> bool:
        """Check if name matches expected pattern."""
        if not pattern:
            return True
        return bool(re.match(pattern, name.lower()))

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_metadata_generation_scenario(self, test_case):
        """Test individual metadata generation scenario."""
        start_time = time.time()

        try:
            # Setup and execute the test
            node, shared = self._setup_test(test_case)
            metadata = self._execute_node(node, shared)

            # Validate the results
            all_errors = self._validate_results(metadata, test_case)

            # Check performance
            self._check_performance(test_case.name, start_time)

            # Report any failures
            if all_errors:
                failure_reason = "; ".join(all_errors)
                report_failure(test_case.name, failure_reason)
                raise AssertionError(f"[{test_case.name}] {failure_reason}")

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

    def _setup_test(self, test_case):
        """Set up the test with node and shared store."""
        node = MetadataGenerationNode()

        # IMPORTANT: In the actual pipeline, ParameterMappingNode runs before MetadataGenerationNode
        # and creates extracted_params, which maps discovered values to workflow input names.
        # MetadataGenerationNode uses this to transform the user input, replacing specific values
        # with [parameter_name] placeholders. Without this, the tests don't accurately simulate
        # the real behavior, and forbidden values would appear in the metadata.

        extracted_params = self._create_extracted_params(test_case)

        shared = {
            "user_input": test_case.user_input,
            "generated_workflow": {
                "nodes": self._create_nodes_from_summary(test_case.nodes_summary),
                "inputs": self._create_inputs_from_string(test_case.workflow_inputs),
            },
            "discovered_params": self._create_params_from_string(test_case.discovered_params),
            "extracted_params": extracted_params,  # Add extracted_params to simulate full pipeline
        }

        return node, shared

    def _execute_node(self, node, shared):
        """Execute the node and return metadata."""
        # Run the node lifecycle
        prep_res = node.prep(shared)
        assert "workflow" in prep_res
        assert "user_input" in prep_res
        assert "discovered_params" in prep_res
        assert "extracted_params" in prep_res  # Now included in the pipeline
        assert "model_name" in prep_res

        # Execute with real LLM
        exec_res = node.exec(prep_res)
        assert isinstance(exec_res, dict)

        # Run post to verify it returns success
        action = node.post(shared, prep_res, exec_res)
        assert action == ""  # MetadataGenerationNode returns empty string on success

        # Log the generated metadata for debugging
        metadata = exec_res
        logger.info(f"Generated name={metadata.get('suggested_name')}")
        logger.info(f"Keywords={metadata.get('search_keywords')}")

        return metadata

    def _validate_results(self, metadata, test_case):
        """Validate metadata against test case expectations."""
        all_errors = []

        # Validate metadata structure
        all_errors.extend(self._validate_metadata_structure(metadata))

        # Check forbidden values aren't included
        all_errors.extend(self._check_forbidden_values(metadata, test_case.forbidden_values))

        # Check expected keywords are present
        missing_keywords = self._check_expected_keywords(metadata, test_case.expected_keywords)
        if missing_keywords:
            all_errors.append(f"Missing expected keywords: {missing_keywords}")

        # Check name pattern if specified
        if (
            test_case.expected_name_pattern
            and "suggested_name" in metadata
            and not self._check_name_pattern(metadata["suggested_name"], test_case.expected_name_pattern)
        ):
            all_errors.append(
                f"Name '{metadata.get('suggested_name')}' doesn't match pattern '{test_case.expected_name_pattern}'"
            )

        return all_errors

    def _check_performance(self, test_name: str, start_time: float):
        """Check and log performance warnings."""
        duration = time.time() - start_time
        if duration > 20.0:
            logger.warning(f"[{test_name}] Slow performance: {duration:.2f}s (model-dependent, not a prompt issue)")
            print(f"⚠️ PERFORMANCE WARNING: {test_name} took {duration:.2f}s", flush=True)

    def _create_nodes_from_summary(self, nodes_summary: str) -> list[dict]:
        """Create node list from comma-separated summary."""
        if nodes_summary == "none":
            return []
        node_types = [t.strip() for t in nodes_summary.split(",")]
        return [{"type": node_type, "id": f"node_{i}"} for i, node_type in enumerate(node_types)]

    def _create_inputs_from_string(self, inputs_str: str) -> dict:
        """Create inputs dict from comma-separated string."""
        if inputs_str == "none":
            return {}
        input_names = [n.strip() for n in inputs_str.split(",")]
        return {name: {"type": "string"} for name in input_names}

    def _create_params_from_string(self, params_str: str) -> dict:
        """Create params dict from comma-separated string."""
        if params_str == "none":
            return {}
        param_names = [n.strip() for n in params_str.split(",")]
        return {name: f"${{{name}}}" for name in param_names}

    def _create_extracted_params(self, test_case: MetadataTestCase) -> dict:
        """Create realistic extracted_params that maps discovered values to workflow inputs.

        This simulates what ParameterMappingNode would produce in the real pipeline.
        The extracted_params maps workflow input names to their discovered values.
        """
        # Map test case names to the actual parameter values that would be extracted
        param_mappings = {
            # GitHub workflows
            "changelog_with_specifics": {
                "repo_owner": "pflow",  # Would be extracted from "pflow repo"
                "repo_name": "pflow",
                "issue_count": 30,  # From "last 30 closed issues" - numeric value
            },
            "issue_triage_vague": {},  # No specific values in vague request
            "pr_summary_explicit": {
                "repo_owner": "kubernetes",  # From "kubernetes/kubernetes"
                "repo_name": "kubernetes",
                "pr_number": 123,  # From "PR #123" - numeric value
            },
            # Data processing workflows
            "csv_analysis_specific": {
                "input_file": "sales_2024.csv",  # From filename
                "output_file": "insights_report",  # Inferred from "insights report"
            },
            "report_generation": {
                "log_directory": "logs",  # Inferred from "from logs"
                "report_period": "monthly",  # From "monthly report"
            },
            "data_transformation": {
                "input_file": "input.json",  # Generic defaults for format conversion
                "output_file": "output.csv",
            },
            # File operations workflows
            "bulk_rename_specific": {
                "source_pattern": "IMG_*.jpg",  # From "IMG_*.jpg files"
                "target_pattern": "vacation_*.jpg",  # From "to vacation_*.jpg"
                "directory": "photos",  # From "in photos folder"
            },
            "backup_creation": {
                "source_directory": "config",  # Inferred from "config files"
                "backup_location": "backups",  # Default backup location
            },
            # Edge cases
            "overly_specific_request": {
                "repo_owner": "microsoft",  # From "microsoft/vscode"
                "repo_name": "vscode",
                "label": "bug",  # From "labeled 'bug'"
                "since_date": "2024-01-15",  # From date in request
                "count": 42,  # From "exactly 42 issues" - numeric value
                "output_path": "~/reports/bugs_jan.md",  # From path
            },
            "mixed_domain_workflow": {
                "repo_owner": "",  # Would need to be provided
                "repo_name": "",
                "output_format": "csv",  # From "CSV report"
            },
        }

        # Return the mapped parameters for this test case
        return param_mappings.get(test_case.name, {})
