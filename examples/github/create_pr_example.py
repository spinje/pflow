#!/usr/bin/env python3
"""Example demonstrating how to use the GitHubCreatePRNode.

This example shows the critical two-step process:
1. gh pr create returns only a URL (not JSON)
2. We parse the PR number from the URL and fetch full data with gh pr view
"""

import sys
from pathlib import Path

# Add pflow to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pflow.pocketflow import Flow
from src.pflow.nodes.github.create_pr import GitHubCreatePRNode


def create_pr_example():
    """Example of creating a GitHub pull request."""

    # Create a flow
    flow = Flow(name="create-pr-flow")

    # Create the GitHub PR node
    create_pr_node = GitHubCreatePRNode()

    # Add node to flow
    flow.add_node(create_pr_node)

    # Set up shared store with PR details
    shared = {
        "title": "Add new feature X",
        "body": """## Summary

This PR adds feature X with the following changes:
- Added new module for X
- Updated documentation
- Added comprehensive tests

## Testing
- All tests pass
- Manual testing completed
        """,
        "head": "feature-x",
        "base": "main",
        # Optional: specify repository (uses current repo if omitted)
        # "repo": "owner/repo"
    }

    # Run the flow
    try:
        flow.run(shared)

        # The node writes PR data to shared["pr_data"]
        pr_data = shared.get("pr_data", {})

        print("✅ Pull request created successfully!")
        print(f"   PR Number: #{pr_data.get('number')}")
        print(f"   URL: {pr_data.get('url')}")
        print(f"   Title: {pr_data.get('title')}")
        print(f"   State: {pr_data.get('state')}")
        print(f"   Author: {pr_data.get('author', {}).get('login')}")

    except ValueError as e:
        print(f"❌ Error creating PR: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


def create_pr_with_params_example():
    """Example using parameters instead of shared store."""

    flow = Flow(name="create-pr-params-flow")

    # Create node with parameters
    create_pr_node = GitHubCreatePRNode()
    create_pr_node.params = {
        "title": "Fix bug in module Y",
        "body": "This fixes the issue where Y was not handling edge cases correctly.",
        "head": "bugfix/module-y",
        "base": "develop",
        "repo": "myorg/myproject",
    }

    flow.add_node(create_pr_node)

    # Run with empty shared store (will use params)
    shared = {}

    try:
        flow.run(shared)
        pr_data = shared.get("pr_data", {})
        print(f"✅ PR #{pr_data.get('number')} created: {pr_data.get('url')}")
    except ValueError as e:
        print(f"❌ Error: {e}")


def main():
    """Run the examples."""
    print("GitHub Create PR Node Example")
    print("=" * 50)
    print()

    print("⚠️  Note: This example requires:")
    print("   1. GitHub CLI (gh) to be installed")
    print("   2. Authentication via 'gh auth login'")
    print("   3. A git repository with branches to create PR from/to")
    print()

    # Uncomment to run the example you want:
    # create_pr_example()
    # create_pr_with_params_example()

    print("Examples are commented out to prevent accidental PR creation.")
    print("Uncomment the example you want to run in the main() function.")


if __name__ == "__main__":
    main()
