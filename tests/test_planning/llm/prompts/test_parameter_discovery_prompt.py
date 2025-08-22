"""HARD tests for parameter_discovery - Testing what's actually challenging.

PHILOSOPHY: Test the edge cases and ambiguities that differentiate good from great.

Run with:
  RUN_LLM_TESTS=1 pytest test_parameter_discovery_prompt_hard.py -v
"""

import json
import logging
import os
import time
from dataclasses import dataclass

import pytest

from pflow.planning.nodes import ParameterDiscoveryNode

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FAILURE_OUTPUT_FILE = os.environ.get("PFLOW_TEST_FAILURE_FILE")


def report_failure(test_name: str, failure_reason: str):
    """Report a test failure immediately."""
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


pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


@dataclass
class HardTestCase:
    """Test case for challenging parameter extraction scenarios."""

    name: str
    user_input: str
    must_extract: set[str]  # Values that MUST be found
    must_not_extract: set[str]  # Values that must NOT be extracted
    acceptable_variations: set[str]  # Alternative acceptable extractions
    challenge: str  # What makes this hard
    why_matters: str  # Why this differentiates good systems


def get_test_cases() -> list[HardTestCase]:
    """7 HARD test cases that challenge the parameter extraction system."""
    return [
        # CHALLENGE 1: Topic vs Instruction Boundary
        HardTestCase(
            name="topic_instruction_boundary",
            user_input="Write a detailed analysis about machine learning applications in healthcare focusing on diagnostic accuracy improvements over traditional methods in radiology",
            must_extract={
                "machine learning applications in healthcare",  # Core topic
                "diagnostic accuracy improvements",  # Specific focus
                "radiology",  # Domain
            },
            must_not_extract={
                "Write a detailed analysis about",  # Instruction
                "focusing on",  # Connector
                "over traditional methods",  # Comparison phrase
            },
            acceptable_variations={"healthcare", "machine learning"},
            challenge="Distinguishing topic content from instruction verbs",
            why_matters="Prevents storing instructions while capturing topics",
        ),
        # CHALLENGE 2: Ambiguous References
        HardTestCase(
            name="ambiguous_references",
            user_input="Process this data from yesterday and compare it with last week's results, then export that to CSV",
            must_extract={
                "yesterday",  # Temporal reference
                "last week",  # Another temporal reference
                "CSV",  # Format
            },
            must_not_extract={
                "this",  # Stdin reference
                "it",  # Pronoun
                "that",  # Ambiguous reference
            },
            acceptable_variations={"last week's"},
            challenge="Identifying which references are parameters vs pronouns",
            why_matters="Correctly handles stdin and pronoun references",
        ),
        # CHALLENGE 3: Vague Quantifiers
        HardTestCase(
            name="vague_quantifiers",
            user_input="Analyze the last few dozen commits from the past couple of weeks in the main branch",
            must_extract={
                "main",  # Branch name
                # Should extract SOMETHING for the vague quantities
            },
            must_not_extract={
                "analyze the",  # Action
            },
            acceptable_variations={
                "few dozen",
                "dozen",
                "24",
                "36",  # Various interpretations
                "couple of weeks",
                "couple weeks",
                "2 weeks",
                "14 days",
            },
            challenge="Handling vague quantifiers that need interpretation",
            why_matters="Real users use vague language",
        ),
        # CHALLENGE 4: Negation and Exclusion
        HardTestCase(
            name="negation_exclusion",
            user_input="Process all files except PDFs and images, but include hidden files, limiting to 100MB total",
            must_extract={
                "100MB",  # Size limit
                "hidden files",  # Inclusion
            },
            must_not_extract={
                "process",  # Action
                "all files",  # Too generic when there are exclusions
            },
            acceptable_variations={
                "PDFs",
                "images",  # Could extract exclusions
                "except PDFs",
                "except images",  # Or with negation
            },
            challenge="Handling exclusions and complex boolean logic",
            why_matters="Complex filtering is common in real workflows",
        ),
        # CHALLENGE 5: Context-Dependent Ambiguity
        HardTestCase(
            name="context_dependent",
            user_input="Get the latest 50 from production starting from last Monday",
            must_extract={
                "50",  # Count
                "production",  # Source/environment
                "last Monday",  # Start date
            },
            must_not_extract={
                "get the",  # Action
                "starting from",  # Connector
            },
            acceptable_variations={"Monday", "latest 50"},
            challenge="'Latest 50' of what? Context determines meaning",
            why_matters="Ambiguous requests are common",
        ),
        # CHALLENGE 6: Composite Values
        HardTestCase(
            name="composite_values",
            user_input="Generate report for Q4 2023 including October through December sales data from regions NA and EMEA",
            must_extract={
                "Q4 2023",  # Period
                "October",  # Start month
                "December",  # End month
                "NA",  # Region 1
                "EMEA",  # Region 2
            },
            must_not_extract={
                "generate report",  # Action
                "including",  # Connector
                "through",  # Range connector
            },
            acceptable_variations={
                "October through December",  # Could be one param
                "Q4",
                "2023",  # Could be separate
                "NA and EMEA",  # Could be combined
            },
            challenge="Composite values that could be split or combined",
            why_matters="Data often has multiple dimensions",
        ),
        # CHALLENGE 7: Implicit Instructions
        HardTestCase(
            name="implicit_instructions",
            user_input="The data should be filtered for active users only, sorted by registration date descending, with email addresses redacted",
            must_extract={
                "active",  # Filter criterion
                "registration date",  # Sort field
                "descending",  # Sort order
                "email addresses",  # What to redact
            },
            must_not_extract={
                "should be filtered",  # Instruction
                "sorted by",  # Instruction
                "with",  # Connector
                "redacted",  # Action (though arguable)
            },
            acceptable_variations={
                "active users",  # Combined
                "registration",  # Shortened
                "desc",  # Alternative for descending
            },
            challenge="Extracting criteria from instruction-heavy input",
            why_matters="Users often mix instructions with parameters",
        ),
    ]


def check_extraction(discovered: dict, test_case: HardTestCase) -> tuple[bool, list[str]]:  # noqa: C901
    """Check if extraction meets the hard test requirements."""
    failures = []

    # Helper to check if value is found
    def found_value(target: str) -> bool:
        target_lower = target.lower()
        for param_value in discovered.values():
            value_str = str(param_value).lower()
            if target_lower in value_str or value_str in target_lower:
                return True
        return False

    # Check must_extract values
    for required in test_case.must_extract:
        if not found_value(required):
            # Check if an acceptable variation was found
            variation_found = False
            for variation in test_case.acceptable_variations:
                if found_value(variation):
                    variation_found = True
                    break

            if not variation_found:
                failures.append(f"Missing required: {required}")

    # Check must_not_extract values
    for forbidden in test_case.must_not_extract:
        if found_value(forbidden):
            # Check if it's part of a larger acceptable value
            for param_value in discovered.values():
                value_str = str(param_value).lower()
                if forbidden.lower() in value_str and len(value_str) > len(forbidden) + 5:
                    # It's part of a larger value, which might be OK
                    continue
                elif forbidden.lower() == value_str:
                    failures.append(f"Extracted forbidden: {forbidden}")
                    break

    # Check for prompt-like values (too long)
    for key, value in discovered.items():
        if isinstance(value, str) and len(value) > 100:
            failures.append(f"Likely prompt in {key}: {value[:50]}...")

    return len(failures) == 0, failures


class TestParameterDiscoveryHard:
    """Hard tests that challenge parameter extraction."""

    @pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
    def test_hard_parameter_extraction(self, test_case):
        """Test challenging parameter extraction scenarios."""
        node = ParameterDiscoveryNode()
        shared = {"user_input": test_case.user_input}

        try:
            prep_res = node.prep(shared)
            exec_res = node.exec(prep_res)

            assert isinstance(exec_res, dict)
            assert "parameters" in exec_res
            discovered = exec_res["parameters"]

            logger.info(f"[{test_case.name}] Challenge: {test_case.challenge}")
            logger.info(f"[{test_case.name}] Input: {test_case.user_input}")
            logger.info(f"[{test_case.name}] Discovered: {discovered}")

            # Check extraction quality
            passed, failures = check_extraction(discovered, test_case)

            if not passed:
                failure_msg = "; ".join(failures)
                report_failure(test_case.name, failure_msg)
                raise AssertionError(f"[{test_case.name}] {failure_msg}")

        except Exception as e:
            if "API" in str(e) or "key" in str(e).lower():
                pytest.skip(f"LLM API not configured: {e}")
            raise
