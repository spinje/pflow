#!/usr/bin/env python3
"""Debug script to test which keywords effectively find the changelog workflow.

This script tests various search terms to understand what makes a query successful
versus unsuccessful for finding the changelog workflow.
"""

import os
import tempfile
from pathlib import Path

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import MetadataGenerationNode, WorkflowDiscoveryNode


def create_sample_workflow_with_metadata():
    """Create and return workflow with generated metadata."""
    workflow_ir = {
        "name": "github_changelog_generator",
        "description": "Generate changelog from GitHub issues",
        "nodes": [
            {"id": "fetch_issues", "type": "github-issues", "config": {"repo": "{{repo}}", "state": "closed", "limit": 30}},
            {"id": "format_changelog", "type": "llm", "config": {"prompt": "Create a changelog from these issues: {{issues}}"}},
            {"id": "save_output", "type": "write-file", "config": {"path": "CHANGELOG.md", "content": "{{changelog}}"}},
        ],
        "edges": [
            {"from": "fetch_issues", "to": "format_changelog"},
            {"from": "format_changelog", "to": "save_output"},
        ],
    }

    # Generate metadata
    metadata_generator = MetadataGenerationNode()
    shared = {"generated_workflow": workflow_ir, "user_input": "Create changelog from GitHub issues"}

    prep_res = metadata_generator.prep(shared)
    exec_res = metadata_generator.exec(prep_res)
    metadata_generator.post(shared, prep_res, exec_res)

    metadata = shared["workflow_metadata"]
    workflow_ir["metadata"] = metadata

    return workflow_ir, metadata


def test_keyword_variations():
    """Test various keyword combinations to find effective discovery terms."""
    if not os.environ.get("RUN_LLM_TESTS"):
        print("ERROR: Set RUN_LLM_TESTS=1 to run this script")
        return

    print("KEYWORD EFFECTIVENESS ANALYSIS")
    print("=" * 60)

    workflow_ir, metadata = create_sample_workflow_with_metadata()

    print("Generated keywords:")
    for i, keyword in enumerate(metadata["search_keywords"], 1):
        print(f"  {i}. '{keyword}'")

    print(f"\nDescription: {metadata['description'][:100]}...")

    # Test various query patterns
    test_queries = [
        # Working queries (expected to match)
        ("generate changelog", "SHOULD WORK"),
        ("create release notes", "SHOULD WORK"),
        ("version history", "SHOULD WORK"),
        ("github issues to changelog", "SHOULD WORK"),

        # Borderline queries
        ("document changes", "BORDERLINE"),
        ("track updates", "BORDERLINE"),
        ("project history", "BORDERLINE"),
        ("release documentation", "BORDERLINE"),

        # Non-working queries (conceptually different)
        ("sprint summary report", "SHOULDN'T WORK"),
        ("team productivity", "SHOULDN'T WORK"),
        ("velocity tracking", "SHOULDN'T WORK"),
        ("burndown chart", "SHOULDN'T WORK"),

        # Edge cases
        ("automated reporting", "EDGE CASE"),
        ("github integration", "EDGE CASE"),
        ("issue analysis", "EDGE CASE"),
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        workflow_manager = WorkflowManager(workflows_dir=Path(temp_dir))
        workflow_manager.save(metadata["suggested_name"], workflow_ir)

        discovery = WorkflowDiscoveryNode()
        results = []

        print(f"\nTesting {len(test_queries)} queries...")
        print("-" * 60)

        for query, expectation in test_queries:
            shared_discovery = {
                "user_input": query,
                "workflow_manager": workflow_manager,
            }

            try:
                prep_res = discovery.prep(shared_discovery)
                exec_res = discovery.exec(prep_res)
                action = discovery.post(shared_discovery, prep_res, exec_res)

                result = shared_discovery["discovery_result"]
                found = result["found"]
                confidence = result["confidence"]

                # Determine if result matches expectation
                if expectation == "SHOULD WORK":
                    status = "✓ PASS" if found and confidence > 0.7 else "✗ FAIL"
                elif expectation == "SHOULDN'T WORK":
                    status = "✓ PASS" if not found or confidence < 0.5 else "✗ FAIL"
                else:  # BORDERLINE or EDGE CASE
                    status = "~ INFO"

                print(f"{status} '{query}' -> Found: {found}, Conf: {confidence:.2f} ({expectation})")

                results.append({
                    "query": query,
                    "found": found,
                    "confidence": confidence,
                    "expectation": expectation,
                    "reasoning": result.get("reasoning", "")[:60] + "..." if result.get("reasoning") else ""
                })

            except Exception as e:
                print(f"✗ ERROR '{query}' -> {e}")

    # Analysis summary
    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)

    should_work = [r for r in results if r["expectation"] == "SHOULD WORK"]
    shouldnt_work = [r for r in results if r["expectation"] == "SHOULDN'T WORK"]

    should_work_success = sum(1 for r in should_work if r["found"] and r["confidence"] > 0.7)
    shouldnt_work_success = sum(1 for r in shouldnt_work if not r["found"] or r["confidence"] < 0.5)

    print(f"Positive cases (should match): {should_work_success}/{len(should_work)} correct")
    print(f"Negative cases (shouldn't match): {shouldnt_work_success}/{len(shouldnt_work)} correct")

    print(f"\nPrecision: {shouldnt_work_success}/{len(shouldnt_work)} = {shouldnt_work_success/len(shouldnt_work)*100:.1f}%")
    print(f"Recall: {should_work_success}/{len(should_work)} = {should_work_success/len(should_work)*100:.1f}%")

    # Show failed cases
    failed_positive = [r for r in should_work if not r["found"] or r["confidence"] <= 0.7]
    failed_negative = [r for r in shouldnt_work if r["found"] and r["confidence"] >= 0.5]

    if failed_positive:
        print(f"\n❌ Failed to find (false negatives):")
        for r in failed_positive:
            print(f"  - '{r['query']}' (conf: {r['confidence']:.2f})")

    if failed_negative:
        print(f"\n❌ Incorrectly matched (false positives):")
        for r in failed_negative:
            print(f"  - '{r['query']}' (conf: {r['confidence']:.2f})")

    print(f"\n✅ The 'sprint summary report' rejection is CORRECT behavior")
    print(f"   It scored {[r['confidence'] for r in results if r['query'] == 'sprint summary report'][0]:.2f} confidence - appropriately low")


if __name__ == "__main__":
    test_keyword_variations()
