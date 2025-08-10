#!/usr/bin/env python3
"""
Debug script to investigate workflow discovery process.

This script traces through the entire discovery process to understand:
1. What metadata is generated for a workflow
2. How the discovery context is built
3. What the discovery prompt looks like
4. Why certain queries fail to match
"""

import json
import logging
import tempfile
from pathlib import Path

# Set up logging to see everything
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import MetadataGenerationNode, WorkflowDiscoveryNode
from pflow.planning.context_builder import build_discovery_context


def create_sample_workflow_ir():
    """Create the same workflow IR used in tests."""
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
                "config": {
                    "prompt": "Format these GitHub issues into a changelog:\n\n{{issues}}\n\nCreate a proper changelog with sections for different types of changes.",
                    "model": "anthropic/claude-sonnet-4-0",
                },
            },
            {
                "id": "save_changelog",
                "type": "write-file",
                "config": {"path": "CHANGELOG.md", "content": "{{changelog}}"},
            },
        ],
        "edges": [
            {"from": "fetch_issues", "to": "format_changelog"},
            {"from": "format_changelog", "to": "save_changelog"},
        ],
        "inputs": {
            "repo": {
                "type": "string",
                "description": "GitHub repository in format 'owner/repo'",
                "required": True,
            }
        },
    }


def print_section(title: str, content: str = "", separator: str = "="):
    """Print a formatted section header."""
    print(f"\n{separator * 80}")
    print(f"{title}")
    print(f"{separator * 80}")
    if content:
        print(content)
    print()


def debug_metadata_generation(workflow_ir: dict, user_input: str) -> dict:
    """Debug the metadata generation process."""
    print_section("🔍 STEP 1: METADATA GENERATION")

    print(f"Original user input: {user_input}")
    print(f"Workflow name: {workflow_ir['name']}")
    print(f"Workflow description: {workflow_ir['description']}")
    print(f"Workflow nodes: {[node['type'] for node in workflow_ir['nodes']]}")

    # Generate metadata using MetadataGenerationNode
    metadata_generator = MetadataGenerationNode()
    shared = {
        "generated_workflow": workflow_ir,
        "user_input": user_input
    }

    print("\n➤ Running MetadataGenerationNode...")
    prep_res = metadata_generator.prep(shared)

    print(f"✓ Prep complete - model: {prep_res['model_name']}")

    exec_res = metadata_generator.exec(prep_res)

    print("✓ Exec complete - Generated metadata:")
    for key, value in exec_res.items():
        print(f"  {key}: {value}")

    metadata_generator.post(shared, prep_res, exec_res)
    metadata = shared["workflow_metadata"]

    print("\n➤ Final metadata stored in shared:")
    print(json.dumps(metadata, indent=2))

    return metadata


def debug_workflow_saving(workflow_manager: WorkflowManager, workflow_ir: dict, metadata: dict):
    """Debug the workflow saving process."""
    print_section("💾 STEP 2: WORKFLOW SAVING")

    # Add metadata to workflow
    workflow_ir["metadata"] = metadata
    suggested_name = metadata["suggested_name"]

    print(f"Saving workflow with name: {suggested_name}")

    # Save the workflow
    saved_path = workflow_manager.save(suggested_name, workflow_ir)
    print(f"✓ Workflow saved to: {saved_path}")

    # Verify it was saved correctly
    all_workflows = workflow_manager.list_all()
    print(f"✓ All workflows in manager: {[w['name'] for w in all_workflows]}")

    # Try to load it back
    try:
        loaded_workflow = workflow_manager.load(suggested_name)
        print(f"✓ Successfully loaded workflow back:")
        print(f"  Name: {loaded_workflow.get('name')}")
        print(f"  Description: {loaded_workflow.get('description', '')}")
        if 'metadata' in loaded_workflow:
            print(f"  Has metadata: Yes")
            print(f"  Metadata keys: {list(loaded_workflow['metadata'].keys())}")
        else:
            print(f"  Has metadata: No")
        return loaded_workflow
    except Exception as e:
        print(f"✗ Failed to load workflow back: {e}")
        return None


def debug_discovery_context(workflow_manager: WorkflowManager):
    """Debug the discovery context building."""
    print_section("🏗️ STEP 3: DISCOVERY CONTEXT BUILDING")

    print("Building discovery context...")
    discovery_context = build_discovery_context(
        node_ids=None,  # All nodes
        workflow_names=None,  # All workflows
        registry_metadata=None,  # Load from registry
        workflow_manager=workflow_manager,
    )

    print(f"✓ Discovery context built ({len(discovery_context)} chars)")
    print("\n➤ Discovery context content:")
    print("-" * 40)
    print(discovery_context)
    print("-" * 40)

    return discovery_context


def debug_single_discovery(query: str, workflow_manager: WorkflowManager) -> dict:
    """Debug a single discovery query."""
    print_section(f"🔍 DISCOVERY TEST: '{query}'", separator="-")

    discovery = WorkflowDiscoveryNode()
    shared_discovery = {
        "user_input": query,
        "workflow_manager": workflow_manager,
    }

    print("➤ Running WorkflowDiscoveryNode prep...")
    prep_res = discovery.prep(shared_discovery)

    print(f"✓ Prep complete:")
    print(f"  Model: {prep_res['model_name']}")
    print(f"  Temperature: {prep_res['temperature']}")
    print(f"  Discovery context length: {len(prep_res['discovery_context'])} chars")

    print("\n➤ Discovery prompt being sent to LLM:")
    prompt = f"""You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

Available workflows and nodes:
{prep_res["discovery_context"]}

User request: {prep_res["user_input"]}

Analyze whether any existing workflow COMPLETELY satisfies this request. A complete match means the workflow does everything the user wants without modification.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false."""

    print("=" * 60)
    print(prompt)
    print("=" * 60)

    print("\n➤ Running exec...")
    exec_res = discovery.exec(prep_res)

    print(f"✓ Exec complete:")
    print(f"  Found: {exec_res['found']}")
    print(f"  Confidence: {exec_res['confidence']}")
    print(f"  Workflow name: {exec_res.get('workflow_name', 'N/A')}")
    print(f"  Reasoning: {exec_res['reasoning']}")

    print("\n➤ Running post...")
    action = discovery.post(shared_discovery, prep_res, exec_res)

    print(f"✓ Post complete - action: {action}")

    if "discovery_result" in shared_discovery:
        result = shared_discovery["discovery_result"]
        print(f"  Discovery result: {result}")

        if result["found"] and "found_workflow" in shared_discovery:
            found_workflow = shared_discovery["found_workflow"]
            print(f"  Found workflow name: {found_workflow.get('name')}")
            print(f"  Found workflow description: {found_workflow.get('description', 'N/A')}")

    return shared_discovery.get("discovery_result", exec_res)


def main():
    """Run the complete debug process."""
    print_section("🚀 WORKFLOW DISCOVERY DEBUG SCRIPT")

    # Create sample workflow
    workflow_ir = create_sample_workflow_ir()
    user_input = "Create changelog from GitHub issues"

    # Create temporary workflow manager
    with tempfile.TemporaryDirectory() as temp_dir:
        workflow_manager = WorkflowManager(workflows_dir=temp_dir)

        try:
            # Step 1: Generate metadata
            metadata = debug_metadata_generation(workflow_ir, user_input)

            # Step 2: Save workflow
            saved_workflow = debug_workflow_saving(workflow_manager, workflow_ir, metadata)
            if not saved_workflow:
                print("❌ Failed to save/load workflow - cannot continue")
                return

            # Step 3: Build discovery context
            discovery_context = debug_discovery_context(workflow_manager)

            # Step 4: Test different queries
            test_queries = [
                "generate changelog",
                "create release notes",
                "summarize closed issues",
                "version history from github",
                "sprint summary report",
                "Create changelog from GitHub issues",  # Exact match
            ]

            print_section("🎯 STEP 4: TESTING DISCOVERY QUERIES")

            results = {}
            for query in test_queries:
                result = debug_single_discovery(query, workflow_manager)
                results[query] = result

            # Summary
            print_section("📊 DISCOVERY RESULTS SUMMARY")

            successful_discoveries = 0
            for query, result in results.items():
                found = result.get("found", False)
                confidence = result.get("confidence", 0.0)

                status = "✅" if found and confidence > 0.5 else "❌"
                print(f"{status} '{query}' - Found: {found}, Confidence: {confidence:.2f}")

                if found and confidence > 0.5:
                    successful_discoveries += 1

                # Show reasoning for failed queries
                if not found or confidence <= 0.5:
                    reasoning = result.get("reasoning", "N/A")
                    print(f"    Reasoning: {reasoning}")
                    print()

            print(f"\n🎯 Success rate: {successful_discoveries}/{len(test_queries)} queries matched")

            if successful_discoveries < len(test_queries):
                print("\n🔍 Analysis of potential issues:")
                print("1. Check if metadata contains relevant keywords")
                print("2. Verify discovery context shows the workflow properly")
                print("3. Examine LLM reasoning for failed queries")
                print("4. Consider if the workflow name/description is too specific")

        except Exception as e:
            logger.exception("Debug script failed")
            print(f"\n❌ Script failed with error: {e}")
            raise


if __name__ == "__main__":
    main()
