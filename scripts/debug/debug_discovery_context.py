#!/usr/bin/env python3
"""Debug script to test workflow discovery context building.

This script helps understand why workflow discovery is failing by:
1. Creating a test workflow with the metadata mentioned in the problem
2. Building the discovery context to see what the LLM actually sees
3. Testing the discovery prompt with different queries
"""

import json
import os
import sys
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

# Set PYTHONPATH to include src directory
os.environ["PYTHONPATH"] = str(project_root / "src")

from pflow.planning.context_builder import build_discovery_context


def create_test_workflow():
    """Create a test github_changelog_generator workflow."""
    workflow_data = {
        "name": "github_changelog_generator",
        "description": "Generate changelog from GitHub issues",
        "ir": {
            "ir_version": "0.1.0",
            "inputs": {
                "repo": {"type": "string", "description": "GitHub repository name", "required": True},
                "state": {
                    "type": "string",
                    "description": "Issue state to filter",
                    "required": False,
                    "default": "closed",
                },
            },
            "nodes": [
                {"id": "fetch_issues", "type": "github-list-issues", "params": {"repo": "$repo", "state": "$state"}},
                {
                    "id": "format_changelog",
                    "type": "llm",
                    "params": {
                        "prompt": "Create changelog from these issues: $issue_data",
                        "model": "anthropic/claude-sonnet-4-0",
                    },
                },
            ],
            "edges": [{"from": "fetch_issues", "to": "format_changelog"}],
        },
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "version": "1.0.0",
    }

    # Save to workflows directory
    workflows_dir = Path.home() / ".pflow" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    workflow_path = workflows_dir / "github_changelog_generator.json"
    with open(workflow_path, "w") as f:
        json.dump(workflow_data, f, indent=2)

    print(f"✓ Created test workflow at {workflow_path}")
    return workflow_path


def debug_discovery_context():
    """Debug the discovery context building process."""
    print("=== DEBUGGING WORKFLOW DISCOVERY CONTEXT ===\n")

    # Create test workflow
    workflow_path = create_test_workflow()

    try:
        # Build discovery context
        print("Building discovery context...")
        discovery_context = build_discovery_context()

        print(f"Discovery context length: {len(discovery_context)} characters")
        print("\n=== DISCOVERY CONTEXT ===")
        print(discovery_context)
        print("=== END DISCOVERY CONTEXT ===\n")

        # Check if our workflow appears
        if "github_changelog_generator" in discovery_context:
            print("✓ Test workflow found in discovery context")

            # Find the workflow section
            lines = discovery_context.split("\n")
            workflow_section = []
            in_workflow_section = False

            for line in lines:
                if "github_changelog_generator" in line:
                    in_workflow_section = True
                    workflow_section.append(line)
                elif in_workflow_section:
                    if line.startswith("###") and "workflow" not in line:
                        # New section started
                        break
                    workflow_section.append(line)

            print("\nWorkflow section in context:")
            print("\n".join(workflow_section))

        else:
            print("❌ Test workflow NOT found in discovery context")
            print("\nChecking workflows directory:")
            workflows = list(Path.home().glob(".pflow/workflows/*.json"))
            print(f"Found {len(workflows)} workflow files:")
            for w in workflows[:5]:  # Show first 5
                print(f"  - {w.name}")

        # Test different search queries
        test_queries = [
            "generate changelog",
            "create release notes",
            "github changelog generator",
            "changelog from issues",
            "generate changelog from GitHub issues",
        ]

        print("\n=== TESTING SEARCH QUERIES ===")
        for query in test_queries:
            print(f"\nQuery: '{query}'")

            # Build the discovery prompt (mimicking WorkflowDiscoveryNode)
            prompt = f"""You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

Available workflows and nodes:
{discovery_context}

User request: {query}

Analyze whether any existing workflow COMPLETELY satisfies this request. A complete match means the workflow does everything the user wants without modification.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false."""

            print(f"Prompt length: {len(prompt)} characters")

            # Look for key terms manually
            context_lower = discovery_context.lower()
            query_lower = query.lower()

            matches = []
            if "changelog" in context_lower and "changelog" in query_lower:
                matches.append("changelog")
            if "github" in context_lower and "github" in query_lower:
                matches.append("github")
            if "generate" in context_lower and "generate" in query_lower:
                matches.append("generate")
            if "issues" in context_lower and ("issues" in query_lower or "release" in query_lower):
                matches.append("issues/release")

            print(f"Manual keyword matches: {matches}")

    finally:
        # Cleanup
        if workflow_path.exists():
            workflow_path.unlink()
            print("\n✓ Cleaned up test workflow")


if __name__ == "__main__":
    debug_discovery_context()
