"""Test discovery prompt adaptation based on available metadata.

WHEN TO RUN:
- After modifying _adapt_prompt_to_context in WorkflowDiscoveryNode
- After changing the discovery prompt template (Step 3 section)
- After changing build_workflows_context metadata handling

WHAT IT VALIDATES:
- Prompt strips Capabilities/For references when metadata is absent
- Prompt preserves references when metadata is present
- Partial metadata (only capabilities or only use cases) handled correctly
- Prompt unchanged when exact string not found (resilience)

NOTE: These tests are NOT gated by Task 107 — they test pure string
manipulation logic with no LLM or JSON format dependency.
"""

import pytest

from pflow.planning.nodes import WorkflowDiscoveryNode


@pytest.fixture(autouse=True)
def skip_planning_tests():
    """Override the parent conftest skip — these tests have no LLM/format dependency."""


# The exact Step 3 section from the discovery prompt
STEP3_FULL = (
    "### Step 3: Verify Alignment\n"
    "Check if the workflow truly matches:\n"
    "- **Capabilities** confirm what the workflow can do\n"
    "- **For** (use cases) shows when to use it\n"
    "- **Description** provides overall context"
)

STEP3_DESCRIPTION_ONLY = (
    "### Step 3: Verify Alignment\nCheck if the workflow truly matches:\n- **Description** provides overall context"
)


def _make_prompt(step3: str = STEP3_FULL) -> str:
    """Build a minimal prompt template containing the Step 3 section."""
    return f"Some instructions\n\n{step3}\n\n## Context\n\n{{{{discovery_context}}}}"


class TestAdaptPromptToContext:
    """Test _adapt_prompt_to_context strips irrelevant metadata references."""

    def test_no_metadata_strips_capabilities_and_for(self):
        """When no workflows have Can/For metadata, both bullets are removed."""
        context = "**1. `my-workflow`** - Does something\n   **Flow:** `shell → llm`"
        prompt = _make_prompt()

        result = WorkflowDiscoveryNode._adapt_prompt_to_context(prompt, context)

        assert "**Capabilities**" not in result
        assert "**For**" not in result
        assert "**Description** provides overall context" in result
        assert STEP3_DESCRIPTION_ONLY in result

    def test_both_metadata_present_keeps_all(self):
        """When workflows have both Can and For, prompt is unchanged."""
        context = (
            "**1. `my-workflow`** - Does something\n"
            "   **Flow:** `shell → llm`\n"
            "   **Can:** fetch data, analyze\n"
            "   **For:** code review, PR analysis"
        )
        prompt = _make_prompt()

        result = WorkflowDiscoveryNode._adapt_prompt_to_context(prompt, context)

        assert result == prompt
        assert STEP3_FULL in result

    def test_only_capabilities_keeps_capabilities_removes_for(self):
        """When only Can is present, For bullet is removed."""
        context = "**1. `my-workflow`** - Does something\n   **Can:** fetch data, analyze"
        prompt = _make_prompt()

        result = WorkflowDiscoveryNode._adapt_prompt_to_context(prompt, context)

        assert "**Capabilities** confirm what the workflow can do" in result
        assert "**For**" not in result
        assert "**Description** provides overall context" in result

    def test_only_use_cases_keeps_for_removes_capabilities(self):
        """When only For is present, Capabilities bullet is removed."""
        context = "**1. `my-workflow`** - Does something\n   **For:** code review, PR analysis"
        prompt = _make_prompt()

        result = WorkflowDiscoveryNode._adapt_prompt_to_context(prompt, context)

        assert "**Capabilities**" not in result
        assert "**For** (use cases) shows when to use it" in result
        assert "**Description** provides overall context" in result

    def test_empty_context_strips_metadata_references(self):
        """Empty context (no workflows) also strips metadata references."""
        prompt = _make_prompt()

        result = WorkflowDiscoveryNode._adapt_prompt_to_context(prompt, "")

        assert "**Capabilities**" not in result
        assert "**For**" not in result
        assert "**Description** provides overall context" in result

    def test_prompt_without_step3_section_unchanged(self):
        """If the prompt doesn't contain the expected Step 3 text, return as-is."""
        context = "**1. `my-workflow`** - Does something"
        prompt = "Some prompt without Step 3 content"

        result = WorkflowDiscoveryNode._adapt_prompt_to_context(prompt, context)

        assert result == prompt
