"""Refined test cases for discovery prompt - quality over quantity.

These test cases focus on distinct, important scenarios that validate
the discovery system's ability to make correct decisions.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TestCase:
    """Test case for discovery prompt."""

    name: str
    user_input: str
    should_find: bool
    expected_workflow_hint: Optional[str]
    category: str
    rationale: str


def get_refined_test_cases() -> list[TestCase]:
    """High-quality test cases covering essential scenarios."""
    return [
        # === CORE MATCHES (Must correctly identify) ===
        TestCase(
            "exact_match",
            "read a file",
            should_find=True,
            expected_workflow_hint="read",
            category="core_match",
            rationale="Basic exact match must work",
        ),
        TestCase(
            "semantic_match",
            "triage github issues by priority",
            should_find=True,
            expected_workflow_hint="triage",
            category="core_match",
            rationale="Semantic understanding of similar phrases",
        ),
        TestCase(
            "single_word",
            "changelog",
            should_find=True,
            expected_workflow_hint="changelog",
            category="core_match",
            rationale="Single word should match unambiguous workflow",
        ),
        # === CORE NON-MATCHES (Must correctly reject) ===
        TestCase(
            "wrong_domain",
            "send an email notification",
            should_find=False,
            expected_workflow_hint=None,
            category="core_reject",
            rationale="No email capability exists in any workflow",
        ),
        TestCase(
            "missing_capability",
            "generate changelog and send to slack",
            should_find=False,
            expected_workflow_hint=None,
            category="core_reject",
            rationale="Workflow lacks Slack integration capability",
        ),
        # === DATA SOURCE MISMATCHES (Critical distinctions) ===
        TestCase(
            "wrong_source",
            "generate changelog from pull requests",
            should_find=False,
            expected_workflow_hint=None,
            category="data_mismatch",
            rationale="Workflow uses issues, not pull requests",
        ),
        TestCase(
            "wrong_format",
            "analyze JSON files",
            should_find=False,
            expected_workflow_hint=None,
            category="data_mismatch",
            rationale="Only CSV analysis workflow exists",
        ),
        # === PARAMETER FLEXIBILITY (Should still match) ===
        TestCase(
            "with_parameters",
            "generate changelog for version 2.0",
            should_find=True,
            expected_workflow_hint="changelog",
            category="parameters",
            rationale="Parameters shouldn't prevent matching",
        ),
        # === SYNONYM HANDLING (Domain language) ===
        TestCase(
            "synonym_bugs",
            "triage bugs",
            should_find=True,
            expected_workflow_hint="triage",
            category="synonyms",
            rationale="'bugs' is common synonym for 'issues'",
        ),
        TestCase(
            "synonym_pr",
            "create PR with changelog",
            should_find=True,
            expected_workflow_hint="changelog",
            category="synonyms",
            rationale="'PR' is common abbreviation for pull request",
        ),
        # === AMBIGUOUS CASES (Should reject when unclear) ===
        TestCase(
            "too_vague",
            "analyze data",
            should_find=False,
            expected_workflow_hint=None,
            category="ambiguous",
            rationale="Too vague - could mean CSV, GitHub, or other analysis",
        ),
        # === PERFORMANCE CHECK (Just one representative) ===
        TestCase(
            "performance_test",
            "generate a changelog from closed issues",
            should_find=True,
            expected_workflow_hint="changelog",
            category="performance",
            rationale="Representative test for response time",
        ),
    ]


# Total: 12 high-quality test cases
# Down from 19, but each one tests something distinct and important
