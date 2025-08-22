"""Examine metadata test expectations vs actual generation."""

import os

os.environ["RUN_LLM_TESTS"] = "1"

from tests.test_planning.llm.prompts.test_metadata_generation_prompt import get_test_cases

# Print all test cases and their expectations
test_cases = get_test_cases()

print("=" * 80)
print("TEST CASE EXPECTATIONS")
print("=" * 80)

for tc in test_cases:
    print(f"\n{'=' * 60}")
    print(f"Test: {tc.name}")
    print(f"User Input: {tc.user_input}")
    print(f"Nodes: {tc.nodes_summary}")
    print(f"Inputs: {tc.workflow_inputs}")
    print(f"Expected Keywords: {tc.expected_keywords}")
    print(f"Forbidden Values: {tc.forbidden_values}")
    print(f"Name Pattern: {tc.expected_name_pattern}")
    print(f"Why Important: {tc.why_important}")

# Focus on specific test cases that were problematic
print("\n" + "=" * 80)
print("ANALYZING SPECIFIC TEST EXPECTATIONS")
print("=" * 80)

problematic_tests = ["backup_creation", "overly_specific_request", "report_generation", "issue_triage_vague"]

for tc in test_cases:
    if tc.name in problematic_tests:
        print(f"\n{tc.name}:")
        print(f"  Expected keywords: {tc.expected_keywords}")
        print("  Are these reasonable?")

        # Check if expectations make sense
        if tc.name == "backup_creation":
            print("  - 'backup': Core action, definitely needed")
            print("  - 'files': Operating on files, makes sense")
            print("  - 'archiv': Archive is a synonym for backup, reasonable")
            print("  - 'save': Another synonym, reasonable")

        elif tc.name == "overly_specific_request":
            print("  - 'issues': Core concept, needed")
            print("  - 'bugs': The request mentions bugs, should be included")
            print("  - 'github': Domain, needed")
            print("  - 'summary': The action being performed")
            print("  - 'report': Output type")

        elif tc.name == "report_generation":
            print("  - 'report': Core concept")
            print("  - 'log': Source of data")
            print("  - 'analysis': What's being done")
            print("  - 'generate': The action")

        elif tc.name == "issue_triage_vague":
            print("  - 'triage': Core action")
            print("  - 'issues': What's being triaged")
            print("  - 'priorit': Related to prioritization")
            print("  - 'github': Domain")
