#!/usr/bin/env python3
"""Debug script to test actual LLM workflow discovery responses.

This script simulates the exact LLM calls made by WorkflowDiscoveryNode
to understand why discovery is failing.
"""

import json
import os
import sys
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))
os.environ["PYTHONPATH"] = str(project_root / "src")

try:
    from typing import Optional

    import llm
    from pydantic import BaseModel, Field

    from pflow.planning.context_builder import build_discovery_context
    from pflow.planning.utils.llm_helpers import parse_structured_response

    HAS_LLM = True
except ImportError as e:
    print(f"Warning: LLM dependencies not available: {e}")
    HAS_LLM = False


class WorkflowDecision(BaseModel):
    """Decision structure for workflow discovery."""

    found: bool = Field(description="True if complete workflow match exists")
    workflow_name: Optional[str] = Field(None, description="Name of matched workflow (if found)")
    confidence: float = Field(description="Match confidence 0.0-1.0")
    reasoning: str = Field(description="LLM reasoning for decision")


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


def test_llm_discovery():
    """Test the actual LLM discovery process."""
    if not HAS_LLM:
        print("❌ Cannot test LLM - dependencies not available")
        return

    print("=== TESTING LLM WORKFLOW DISCOVERY ===\n")

    # Create test workflow
    workflow_path = create_test_workflow()

    try:
        # Build discovery context
        discovery_context = build_discovery_context()

        # Test queries
        test_queries = [
            "generate changelog",
            "create release notes",
            "github changelog generator",
            "changelog from issues",
            "generate changelog from GitHub issues",
        ]

        print(f"Discovery context length: {len(discovery_context)} characters")

        # Check if workflow appears in context
        if "github_changelog_generator" not in discovery_context:
            print("❌ Test workflow not found in discovery context!")
            return

        print("✓ Test workflow found in discovery context\n")

        for i, query in enumerate(test_queries):
            print(f"\n{'=' * 50}")
            print(f"TEST {i + 1}: '{query}'")
            print("=" * 50)

            # Build the exact prompt used by WorkflowDiscoveryNode
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

            try:
                # Make the actual LLM call
                model = llm.get_model("anthropic/claude-sonnet-4-0")
                response = model.prompt(prompt, schema=WorkflowDecision, temperature=0.0)
                result = parse_structured_response(response, WorkflowDecision)

                print("\n🤖 LLM RESPONSE:")
                print(f"Found: {result['found']}")
                print(f"Workflow: {result.get('workflow_name', 'None')}")
                print(f"Confidence: {result['confidence']}")
                print(f"Reasoning: {result['reasoning']}")

                if result["found"]:
                    print("✅ SUCCESS - Workflow discovered")
                else:
                    print("❌ FAILED - Workflow not discovered")

            except Exception as e:
                print(f"❌ LLM call failed: {e}")

                # Analyze manually
                print("\n🔍 MANUAL ANALYSIS:")
                context_lower = discovery_context.lower()
                query_lower = query.lower()

                # Look for our workflow specifically
                if "github_changelog_generator" in context_lower:
                    print("✓ Target workflow present in context")

                    # Check for keyword overlap
                    keywords = ["changelog", "generate", "github", "issues", "release"]
                    matches = []
                    for keyword in keywords:
                        if keyword in context_lower and keyword in query_lower:
                            matches.append(keyword)

                    print(f"✓ Keyword matches: {matches}")

                    # Check description match
                    description = "generate changelog from github issues"
                    desc_words = set(description.split())
                    query_words = set(query_lower.split())
                    overlap = desc_words.intersection(query_words)

                    print(f"✓ Description-query word overlap: {overlap}")

                else:
                    print("❌ Target workflow not in context")

    finally:
        # Cleanup
        if workflow_path.exists():
            workflow_path.unlink()
            print("\n✓ Cleaned up test workflow")


if __name__ == "__main__":
    test_llm_discovery()
