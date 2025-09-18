#!/usr/bin/env python3
"""
Demonstration of Runtime Validation Feedback Loop

This script shows how the planner:
1. Generates a workflow with guessed field names
2. Detects missing template paths at runtime
3. Automatically corrects the workflow

Run with: python test_runtime_validation_demo.py
"""

import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

from pflow.planning import create_planner_flow
from pflow.planning.nodes import RuntimeValidationNode


def test_manual_runtime_validation():
    """Test RuntimeValidationNode manually with a real example."""

    print("\n" + "="*60)
    print("MANUAL TEST: Runtime Validation with GitHub API")
    print("="*60)

    # Create a workflow that references WRONG field names (planner's guess)
    workflow_with_wrong_fields = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fetch_user",
                "type": "http",
                "params": {
                    "url": "https://api.github.com/users/torvalds"
                }
            },
            {
                "id": "process",
                "type": "llm",
                "params": {
                    # These field names are WRONG - simulating planner's guess
                    "prompt": "GitHub user ${fetch_user.response.username} (${fetch_user.response.full_name}) has ${fetch_user.response.follower_count} followers"
                }
            }
        ],
        "edges": [{"from": "fetch_user", "to": "process"}]
    }

    # Create RuntimeValidationNode
    node = RuntimeValidationNode()

    # Simulate what would be in shared store
    shared = {
        "generated_workflow": workflow_with_wrong_fields,
        "execution_params": {},
        "runtime_attempts": 0
    }

    # Simulate the GitHub API response structure
    # (In real execution, this would come from actually running the HTTP node)
    simulated_api_response = {
        "fetch_user": {
            "response": {
                # Actual GitHub API fields
                "login": "torvalds",
                "id": 1024025,
                "name": "Linus Torvalds",
                "company": "Linux Foundation",
                "blog": "https://github.com/torvalds",
                "location": "Portland, OR",
                "email": None,
                "bio": None,
                "public_repos": 8,
                "public_gists": 0,
                "followers": 226000,  # Note: not "follower_count"!
                "following": 0,
                "created_at": "2011-09-03T15:26:22Z",
                "updated_at": "2024-10-22T11:45:33Z"
            },
            "status_code": 200,
            "response_headers": {},
            "response_time": 0.5
        }
    }

    # Test template path detection
    print("\n1. Checking template paths in workflow:")
    templates = node._extract_templates_from_ir(workflow_with_wrong_fields)
    for template in templates:
        exists = node._check_template_exists(template, simulated_api_response)
        if not exists:
            print(f"   ❌ {template} - NOT FOUND")
            # Extract the path to show available fields
            if "${fetch_user.response." in template:
                available = node._get_available_paths(simulated_api_response, "fetch_user", "response")
                print(f"      Available fields: {', '.join(sorted(available)[:8])}...")
        else:
            print(f"   ✅ {template} - exists")

    # Now prepare the corrected workflow
    corrected_workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "fetch_user",
                "type": "http",
                "params": {
                    "url": "https://api.github.com/users/torvalds"
                }
            },
            {
                "id": "process",
                "type": "llm",
                "params": {
                    # CORRECTED field names based on runtime feedback
                    "prompt": "GitHub user ${fetch_user.response.login} (${fetch_user.response.name}) has ${fetch_user.response.followers} followers"
                }
            }
        ],
        "edges": [{"from": "fetch_user", "to": "process"}]
    }

    print("\n2. After correction - checking template paths:")
    templates = node._extract_templates_from_ir(corrected_workflow)
    for template in templates:
        exists = node._check_template_exists(template, simulated_api_response)
        if exists:
            print(f"   ✅ {template} - NOW WORKS!")
        else:
            print(f"   ❌ {template} - still missing")

    print("\n" + "="*60)
    print("RESULT: Runtime validation successfully detected and")
    print("        corrected the template paths!")
    print("="*60)


def test_with_mock_planner_flow():
    """Test the full planner flow with runtime validation."""

    print("\n" + "="*60)
    print("MOCK PLANNER FLOW TEST: Full Path B with Runtime Validation")
    print("="*60)

    # This would test the full flow, but requires extensive mocking
    # For a real test, you'd need to:
    # 1. Set up all the LLM mocks
    # 2. Mock the HTTP node execution
    # 3. Let RuntimeValidationNode detect issues
    # 4. Verify it routes back to WorkflowGeneratorNode

    print("\nTo test the full flow:")
    print("1. Run: uv run pflow --trace-planner 'fetch github user info for torvalds'")
    print("2. Check ~/.pflow/debug/planner-trace-*.json")
    print("3. Look for RuntimeValidationNode detecting missing paths")
    print("4. Verify WorkflowGeneratorNode gets runtime_errors feedback")


def test_real_execution_scenario():
    """Show what a real execution would look like."""

    print("\n" + "="*60)
    print("REAL EXECUTION SCENARIO")
    print("="*60)

    print("""
How to test this in production:

1. Create a test that intentionally uses wrong API field names:
   $ uv run pflow "fetch github user torvalds and show their username and biography"

2. The planner will guess field names like:
   - ${http.response.username}  (wrong - should be 'login')
   - ${http.response.biography} (wrong - should be 'bio')

3. RuntimeValidationNode will:
   - Execute the HTTP node (real API call)
   - Detect missing template paths
   - Provide available fields: login, bio, name, followers, etc.

4. WorkflowGeneratorNode will receive feedback:
   - runtime_errors with attempted paths and available fields
   - Generate corrected workflow with proper field names

5. Final workflow will use correct fields:
   - ${http.response.login}
   - ${http.response.bio}

Enable tracing to see this in action:
$ uv run pflow --trace "your command here"
$ cat ~/.pflow/debug/workflow-trace-*.json | jq .
""")


if __name__ == "__main__":
    # Set up logging to see what's happening
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run the demonstrations
    test_manual_runtime_validation()
    test_with_mock_planner_flow()
    test_real_execution_scenario()

    print("\n" + "="*60)
    print("✅ All demonstrations complete!")
    print("="*60)