#!/usr/bin/env python3
"""Debug script for analyzing "sprint summary report" matching issue.

This script creates the same workflow as in the test, generates metadata,
and analyzes why "sprint summary report" doesn't match a changelog workflow.
"""

import json
import os
import tempfile
from pathlib import Path
from pprint import pprint

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import MetadataGenerationNode, WorkflowDiscoveryNode
from pflow.planning.context_builder import build_discovery_context


def create_sample_changelog_workflow():
    """Create the same changelog workflow as in the test."""
    return {
        "name": "github_changelog_generator",
        "description": "Generate changelog from GitHub issues",
        "nodes": [
            {
                "id": "fetch_issues",
                "type": "github-issues",
                "config": {"repo": "{{repo}}", "state": "closed", "limit": 30},
            },
            {
                "id": "format_changelog",
                "type": "llm",
                "config": {"prompt": "Create a changelog from these issues: {{issues}}"},
            },
            {
                "id": "save_output",
                "type": "write-file",
                "config": {"path": "CHANGELOG.md", "content": "{{changelog}}"},
            },
        ],
        "edges": [
            {"from": "fetch_issues", "to": "format_changelog"},
            {"from": "format_changelog", "to": "save_output"},
        ],
    }


def analyze_metadata_generation():
    """Analyze what metadata gets generated for the changelog workflow."""
    print("=" * 80)
    print("1. ANALYZING METADATA GENERATION")
    print("=" * 80)

    workflow_ir = create_sample_changelog_workflow()
    print("\nOriginal workflow IR:")
    pprint(workflow_ir)

    # Generate metadata using MetadataGenerationNode
    metadata_generator = MetadataGenerationNode()
    shared = {
        "generated_workflow": workflow_ir,
        "user_input": "Create changelog from GitHub issues"
    }

    print(f"\nUser input: '{shared['user_input']}'")

    try:
        prep_res = metadata_generator.prep(shared)
        exec_res = metadata_generator.exec(prep_res)
        metadata_generator.post(shared, prep_res, exec_res)

        metadata = shared["workflow_metadata"]

        print("\n" + "-" * 50)
        print("GENERATED METADATA:")
        print("-" * 50)
        for key, value in metadata.items():
            print(f"{key}: {value}")

        print("\n" + "-" * 50)
        print("SEARCH KEYWORDS ANALYSIS:")
        print("-" * 50)
        keywords = metadata.get("search_keywords", [])
        print(f"Generated {len(keywords)} keywords:")
        for i, keyword in enumerate(keywords, 1):
            print(f"  {i}. '{keyword}'")

        # Check if "sprint" appears in any metadata
        all_text = " ".join([
            str(metadata.get("suggested_name", "")),
            str(metadata.get("description", "")),
            " ".join(metadata.get("search_keywords", [])),
            " ".join(metadata.get("capabilities", [])),
            " ".join(metadata.get("typical_use_cases", []))
        ]).lower()

        print(f"\nDoes 'sprint' appear anywhere in metadata? {'YES' if 'sprint' in all_text else 'NO'}")
        print(f"Does 'summary' appear anywhere in metadata? {'YES' if 'summary' in all_text else 'NO'}")
        print(f"Does 'report' appear anywhere in metadata? {'YES' if 'report' in all_text else 'NO'}")

        return metadata

    except Exception as e:
        print(f"ERROR generating metadata: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_sprint_summary_discovery(metadata, workflow_ir):
    """Test discovery specifically with 'sprint summary report' query."""
    print("\n" + "=" * 80)
    print("2. TESTING 'SPRINT SUMMARY REPORT' DISCOVERY")
    print("=" * 80)

    # Create temporary workflow manager and save the workflow
    with tempfile.TemporaryDirectory() as temp_dir:
        workflow_manager = WorkflowManager(workflows_dir=Path(temp_dir))

        # Add metadata to workflow and save it
        workflow_ir["metadata"] = metadata
        workflow_name = metadata["suggested_name"]
        workflow_manager.save(workflow_name, workflow_ir)

        print(f"\nSaved workflow as: '{workflow_name}'")

        # Test the specific failing query
        query = "sprint summary report"
        print(f"Testing query: '{query}'")

        discovery = WorkflowDiscoveryNode()
        shared_discovery = {
            "user_input": query,
            "workflow_manager": workflow_manager,
        }

        try:
            prep_res = discovery.prep(shared_discovery)
            print(f"\nDiscovery context length: {len(prep_res['discovery_context'])} chars")

            # Show the discovery context the LLM sees
            print("\n" + "-" * 50)
            print("DISCOVERY CONTEXT (what LLM sees):")
            print("-" * 50)
            print(prep_res['discovery_context'])

            exec_res = discovery.exec(prep_res)
            action = discovery.post(shared_discovery, prep_res, exec_res)

            print("\n" + "-" * 50)
            print("DISCOVERY RESULTS:")
            print("-" * 50)
            result = shared_discovery["discovery_result"]
            print(f"Found: {result['found']}")
            print(f"Confidence: {result['confidence']}")
            print(f"Workflow name: {result.get('workflow_name', 'N/A')}")
            print(f"Reasoning: {result.get('reasoning', 'N/A')}")
            print(f"Action: {action}")

            return result

        except Exception as e:
            print(f"ERROR in discovery: {e}")
            import traceback
            traceback.print_exc()
            return None


def test_working_queries(metadata, workflow_ir):
    """Test the queries that DO work to understand the difference."""
    print("\n" + "=" * 80)
    print("3. TESTING WORKING QUERIES FOR COMPARISON")
    print("=" * 80)

    working_queries = [
        "generate changelog",
        "create release notes",
        "summarize closed issues",
        "version history from github"
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        workflow_manager = WorkflowManager(workflows_dir=Path(temp_dir))
        workflow_ir["metadata"] = metadata
        workflow_name = metadata["suggested_name"]
        workflow_manager.save(workflow_name, workflow_ir)

        discovery = WorkflowDiscoveryNode()

        for query in working_queries:
            print(f"\n--- Testing: '{query}' ---")

            shared_discovery = {
                "user_input": query,
                "workflow_manager": workflow_manager,
            }

            try:
                prep_res = discovery.prep(shared_discovery)
                exec_res = discovery.exec(prep_res)
                action = discovery.post(shared_discovery, prep_res, exec_res)

                result = shared_discovery["discovery_result"]
                status = "✓ FOUND" if result['found'] else "✗ NOT FOUND"
                print(f"{status} (confidence: {result['confidence']:.2f})")
                if result.get('reasoning'):
                    print(f"   Reasoning: {result['reasoning'][:100]}...")

            except Exception as e:
                print(f"✗ ERROR: {e}")


def analyze_semantic_gap():
    """Analyze the semantic gap between 'sprint summary report' and changelog concepts."""
    print("\n" + "=" * 80)
    print("4. SEMANTIC GAP ANALYSIS")
    print("=" * 80)

    print("Key question: Is 'sprint summary report' conceptually similar to 'changelog'?")
    print()

    print("CHANGELOG concepts:")
    print("- Changes made between versions")
    print("- What was fixed/added/changed")
    print("- Organized by release/version")
    print("- Focus: WHAT changed")
    print()

    print("SPRINT SUMMARY concepts:")
    print("- Work completed in a time period")
    print("- Team productivity/velocity")
    print("- Stories/tasks completed")
    print("- Focus: WHO did WHAT and HOW MUCH")
    print()

    print("SIMILARITY ANALYSIS:")
    print("- Both involve summarizing work done ✓")
    print("- Both use GitHub issues as input ✓")
    print("- Both generate reports ✓")
    print("- Different audiences (users vs team) ✗")
    print("- Different time frames (releases vs sprints) ✗")
    print("- Different purposes (user-facing vs internal) ✗")

    print()
    print("VERDICT:")
    print("While similar at a high level, these are conceptually different:")
    print("- Changelog = user-facing release documentation")
    print("- Sprint summary = internal team productivity report")
    print()
    print("A well-trained LLM might reasonably distinguish between these purposes.")


def suggest_improvements():
    """Suggest how to improve discoverability."""
    print("\n" + "=" * 80)
    print("5. IMPROVEMENT SUGGESTIONS")
    print("=" * 80)

    print("To make 'sprint summary report' match a changelog workflow:")
    print()

    print("OPTION A: Broaden the metadata")
    print("- Add 'sprint', 'summary', 'report' to search_keywords")
    print("- Include use cases like 'team reporting', 'sprint reviews'")
    print("- Risk: False positives, less precise matching")
    print()

    print("OPTION B: Accept the limitation")
    print("- Acknowledge these are different use cases")
    print("- 'sprint summary' requires different formatting/focus than changelog")
    print("- Path B would generate a sprint-specific workflow")
    print("- Pro: More precise, purpose-built workflows")
    print()

    print("OPTION C: Improve the prompt")
    print("- Ask metadata generation to consider broader use cases")
    print("- Include team reporting scenarios in typical_use_cases")
    print("- Balance precision vs recall")
    print()

    print("RECOMMENDATION:")
    print("Option B - Accept that 'sprint summary report' is conceptually")
    print("different from 'changelog generation'. Path B should create")
    print("a sprint-specific workflow with team-focused formatting.")


def main():
    """Run the complete debug analysis."""
    print("DEBUGGING: Why 'sprint summary report' doesn't match changelog workflow")
    print("=" * 80)

    # Check if LLM tests are enabled
    if not os.environ.get("RUN_LLM_TESTS"):
        print("ERROR: This script requires LLM access.")
        print("Set RUN_LLM_TESTS=1 to run.")
        return

    # Create the workflow
    workflow_ir = create_sample_changelog_workflow()

    # Analyze metadata generation
    metadata = analyze_metadata_generation()
    if not metadata:
        return

    # Test the failing query
    test_sprint_summary_discovery(metadata, workflow_ir)

    # Test working queries for comparison
    test_working_queries(metadata, workflow_ir)

    # Analyze the semantic gap
    analyze_semantic_gap()

    # Suggest improvements
    suggest_improvements()

    print("\n" + "=" * 80)
    print("DEBUG ANALYSIS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
