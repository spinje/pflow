#!/usr/bin/env python3
"""Debug script to show actual LLM metadata generation input and output."""

import json
import sys

from pflow.planning.nodes import MetadataGenerationNode


def show_metadata_generation():
    """Run MetadataGenerationNode and display input/output."""

    # Create the node
    node = MetadataGenerationNode(wait=0)
    node.params = {"temperature": 0.3}  # Low temperature for consistency

    # Example: GitHub Changelog Workflow
    shared = {
        "generated_workflow": {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {
                    "type": "string",
                    "required": True,
                    "description": "GitHub repository name",
                },
                "since_date": {
                    "type": "string",
                    "required": False,
                    "description": "Filter issues closed after this date",
                    "default": "30 days ago",
                },
                "output_file": {
                    "type": "string",
                    "required": False,
                    "description": "Output file path",
                    "default": "CHANGELOG.md",
                },
            },
            "nodes": [
                {
                    "id": "fetch_issues",
                    "type": "github-list-issues",
                    "params": {"repo": "$repo", "state": "closed", "since": "$since_date"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "params": {
                        "prompt": "Analyze these GitHub issues and categorize them into: Features, Bug Fixes, Breaking Changes, and Documentation. Format as markdown changelog entries.",
                    },
                },
                {
                    "id": "write_file",
                    "type": "write-file",
                    "params": {"path": "$output_file", "content": "$changelog"},
                },
            ],
            "edges": [
                {"from": "fetch_issues", "to": "analyze"},
                {"from": "analyze", "to": "write_file"},
            ],
        },
        "user_input": "Create a changelog by fetching the last 30 closed issues from github repo pflow, analyze them for features and fixes, then write to CHANGELOG.md",
        "discovered_params": {"repo": "pflow", "limit": "30", "file": "CHANGELOG.md"},
        "planning_context": "User wants to generate release documentation by analyzing GitHub issues",
    }

    print("=" * 80)
    print("INPUT TO METADATAGENERATIONNODE")
    print("=" * 80)

    print("\n📝 User Input:")
    print(f"  '{shared['user_input']}'")

    print("\n🔧 Generated Workflow Structure:")
    workflow = shared["generated_workflow"]
    print(f"  - Inputs: {list(workflow['inputs'].keys())}")
    print(f"  - Nodes: {[n['type'] for n in workflow['nodes']]}")
    print(
        "  - Flow: " + " → ".join([workflow["nodes"][0]["id"], workflow["nodes"][1]["id"], workflow["nodes"][2]["id"]])
    )

    print("\n🔍 Discovered Parameters:")
    for key, value in shared["discovered_params"].items():
        print(f"  - {key}: {value}")

    print("\n📋 Planning Context:")
    print(f"  '{shared['planning_context']}'")

    print("\n" + "=" * 80)
    print("CALLING LLM TO GENERATE METADATA...")
    print("=" * 80)

    # Execute the node
    try:
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        # Post updates shared store; return value not used in this debug script
        node.post(shared, prep_res, exec_res)

        print("\n✅ LLM GENERATED METADATA:")
        print("=" * 80)

        metadata = shared.get("workflow_metadata", exec_res)

        print("\n📌 Suggested Name:")
        print(f"  '{metadata.get('name', metadata.get('suggested_name'))}'")

        print(f"\n📄 Description ({len(metadata.get('description', ''))} chars):")
        print(f'  "{metadata.get("description")}"')

        print(f"\n🔍 Search Keywords ({len(metadata.get('search_keywords', []))} keywords):")
        for keyword in metadata.get("search_keywords", []):
            print(f"  • {keyword}")

        print(f"\n⚡ Capabilities ({len(metadata.get('capabilities', []))} items):")
        for cap in metadata.get("capabilities", []):
            print(f"  • {cap}")

        print(
            f"\n💡 Typical Use Cases ({len(metadata.get('use_cases', metadata.get('typical_use_cases', [])))} scenarios):"
        )
        for use_case in metadata.get("use_cases", metadata.get("typical_use_cases", [])):
            print(f"  • {use_case}")

        print("\n" + "=" * 80)
        print("ANALYSIS")
        print("=" * 80)

        print("\n🎯 Why This Metadata Enables Path A:")
        print("  1. Rich description captures PURPOSE, not just mechanics")
        print("  2. Keywords cover alternative ways users might search")
        print("  3. Use cases help users recognize when to use this workflow")

        print("\n🔮 Discovery Scenarios:")
        test_queries = [
            "generate changelog",
            "release notes",
            "version history",
            "sprint summary",
            "what changed",
            "issue summary",
        ]

        all_searchable_text = (
            metadata.get("description", "").lower()
            + " "
            + " ".join(metadata.get("search_keywords", [])).lower()
            + " "
            + " ".join(metadata.get("capabilities", [])).lower()
        )

        print("\n  Query                 | Would Find?")
        print("  " + "-" * 40)
        for query in test_queries:
            would_find = any(word in all_searchable_text for word in query.split())
            status = "✅ Yes" if would_find else "❌ No"
            print(f"  {query:<20} | {status}")

        print("\n" + "=" * 80)
        print("COMPLETE METADATA OBJECT")
        print("=" * 80)
        print(json.dumps(metadata, indent=2))

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(show_metadata_generation())
