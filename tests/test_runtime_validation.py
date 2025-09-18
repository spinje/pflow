"""Tests for RuntimeValidationNode and template path detection."""

from unittest.mock import MagicMock, patch

from pflow.planning.nodes import RuntimeValidationNode


def test_runtime_validation_detects_missing_template_paths():
    """Test that RuntimeValidationNode detects missing nested template paths."""

    # Create a workflow that references nested fields that don't exist
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "http",
                "type": "http",  # Real HTTP node
                "params": {"url": "https://api.github.com/users/torvalds"},
            },
            {
                "id": "process",
                "type": "llm",  # Real LLM node
                "params": {
                    # These template paths might not exist in the HTTP response
                    # Using incorrect field names to trigger runtime validation
                    "prompt": "User: ${http.response.username}, Bio: ${http.response.biography}"
                },
            },
        ],
        "edges": [{"from": "http", "to": "process"}],
    }

    # Create RuntimeValidationNode
    node = RuntimeValidationNode()

    # Prepare shared store with workflow and empty params
    shared = {"generated_workflow": workflow_ir, "execution_params": {}, "runtime_attempts": 0}

    # Run the node
    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    action = node.post(shared, prep_res, exec_res)

    # Verify it detected the issues and wants to fix them
    assert action == "runtime_fix", f"Expected 'runtime_fix' action, got '{action}'"
    assert "runtime_errors" in shared
    assert len(shared["runtime_errors"]) > 0

    # Check that the errors mention the missing paths
    error_messages = [err["message"] for err in shared["runtime_errors"]]
    error_text = " ".join(error_messages)

    # Should mention the missing template paths
    assert "${http.response.username}" in error_text or "http.response.username" in error_text
    assert "${http.response.biography}" in error_text or "http.response.biography" in error_text

    # Should have incremented attempts
    assert shared["runtime_attempts"] == 1

    print("✓ RuntimeValidationNode successfully detected missing template paths")
    print(f"  Found {len(shared['runtime_errors'])} runtime errors")
    for err in shared["runtime_errors"]:
        print(f"  - {err.get('category', 'unknown')}: {err.get('message', 'no message')}")


def test_runtime_validation_with_valid_workflow():
    """Test that RuntimeValidationNode passes valid workflows."""

    # Create a simple valid workflow
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "writer",
                "type": "write-file",
                "params": {"file_path": "/tmp/test_runtime_val.txt", "content": "Hello World"},  # noqa: S108
            }
        ],
        "edges": [],  # No edges needed for single node
    }

    node = RuntimeValidationNode()

    shared = {"generated_workflow": workflow_ir, "execution_params": {}, "runtime_attempts": 0}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    action = node.post(shared, prep_res, exec_res)

    # Should pass with no issues
    assert action == "default", f"Expected 'default' action for valid workflow, got '{action}'"
    assert "runtime_errors" not in shared or len(shared.get("runtime_errors", [])) == 0

    print("✓ RuntimeValidationNode correctly passes valid workflows")


def test_runtime_validation_respects_attempt_limit():
    """Test that RuntimeValidationNode stops after 3 attempts."""

    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "${nonexistent.field}"}}],
        "edges": [],
    }

    node = RuntimeValidationNode()

    # Already at attempt limit
    shared = {"generated_workflow": workflow_ir, "execution_params": {}, "runtime_attempts": 3}

    prep_res = node.prep(shared)
    exec_res = node.exec(prep_res)
    action = node.post(shared, prep_res, exec_res)

    # Should fail after 3 attempts
    assert action == "failed_runtime", f"Expected 'failed_runtime' after 3 attempts, got '{action}'"
    assert shared["runtime_attempts"] == 3  # Should not increment beyond 3

    print("✓ RuntimeValidationNode respects 3-attempt limit")


def test_bug_empty_execution_params_doesnt_fallback():
    """Documents the BUG: RuntimeValidationNode doesn't fall back when execution_params is empty dict.

    CURRENT BEHAVIOR (BUGGY): Empty dict doesn't trigger fallback to extracted_params.
    DESIRED BEHAVIOR: Should fall back to extracted_params when execution_params is empty.

    This is critical for workflows with required inputs where ParameterMappingNode
    populates extracted_params but ParameterPreparationNode hasn't run yet.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {
            "api_key": {"type": "string", "required": True},
            "slack_channel_id": {"type": "string", "required": True},
        },
        "nodes": [
            {
                "id": "sender",
                "type": "write-file",  # Simple node for testing
                "params": {
                    "file_path": "/tmp/test_params.txt",  # noqa: S108
                    "content": "API: ${api_key}, Channel: ${slack_channel_id}",
                },
            }
        ],
        "edges": [],
    }

    shared = {
        "generated_workflow": workflow_ir,
        "execution_params": {},  # Empty! ParameterPreparationNode hasn't run
        "extracted_params": {"api_key": "test_key_123", "slack_channel_id": "C123ABC"},  # Has the values!
        "runtime_attempts": 0,
    }

    node = RuntimeValidationNode()
    prep_result = node.prep(shared)

    # CURRENT BROKEN BEHAVIOR: empty dict does NOT trigger fallback
    assert prep_result["execution_params"] == {}  # Stays empty - this is the BUG!
    assert prep_result["workflow_ir"] == workflow_ir
    assert prep_result["runtime_attempts"] == 0

    print("✓ BUG DOCUMENTED: Empty execution_params doesn't fall back to extracted_params")
    print("  This causes RuntimeValidationNode to miss parameter values from ParameterMappingNode")


def test_uses_extracted_params_when_execution_params_none():
    """Test that RuntimeValidationNode falls back to extracted_params when execution_params is None."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {
            "database_url": {"type": "string", "required": True},
        },
        "nodes": [
            {
                "id": "connector",
                "type": "write-file",
                "params": {"file_path": "/tmp/db.txt", "content": "${database_url}"},  # noqa: S108
            }
        ],
        "edges": [],
    }

    shared = {
        "generated_workflow": workflow_ir,
        # Note: execution_params key is NOT present (None)
        "extracted_params": {"database_url": "postgres://localhost:5432/testdb"},
        "runtime_attempts": 0,
    }

    node = RuntimeValidationNode()
    prep_result = node.prep(shared)

    # Should use extracted_params as fallback when execution_params is not in shared
    assert prep_result["execution_params"] == {"database_url": "postgres://localhost:5432/testdb"}

    print("✓ RuntimeValidationNode correctly falls back to extracted_params when execution_params is None")


def test_prefers_execution_params_when_both_present():
    """Test that RuntimeValidationNode prefers execution_params over extracted_params when both exist."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "test", "type": "write-file", "params": {"file_path": "/tmp/test.txt", "content": "test"}}],  # noqa: S108
        "edges": [],
    }

    shared = {
        "generated_workflow": workflow_ir,
        "execution_params": {"final_value": "from_execution"},  # This should be preferred
        "extracted_params": {"final_value": "from_extracted"},  # This should be ignored
        "runtime_attempts": 0,
    }

    node = RuntimeValidationNode()
    prep_result = node.prep(shared)

    # Should prefer execution_params when both are present
    assert prep_result["execution_params"] == {"final_value": "from_execution"}

    print("✓ RuntimeValidationNode correctly prefers execution_params when both are present")


def test_handles_both_params_empty_gracefully():
    """Test that RuntimeValidationNode handles gracefully when both params are empty."""
    workflow_ir = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "simple", "type": "write-file", "params": {"file_path": "/tmp/test.txt", "content": "hello"}}],  # noqa: S108
        "edges": [],
    }

    shared = {
        "generated_workflow": workflow_ir,
        "execution_params": {},  # Empty
        "extracted_params": {},  # Also empty
        "runtime_attempts": 0,
    }

    node = RuntimeValidationNode()
    prep_result = node.prep(shared)

    # Should handle empty params gracefully
    assert prep_result["execution_params"] == {}
    assert prep_result["workflow_ir"] == workflow_ir

    print("✓ RuntimeValidationNode handles empty params gracefully")


def test_integration_with_required_inputs_none_execution_params():
    """Test integration where execution_params is None (not just empty).

    This tests the WORKING case where execution_params is None/missing.
    """
    # Create a workflow that requires inputs and uses them
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {
            "github_token": {"type": "string", "required": True, "description": "GitHub API token"},
            "repo_name": {"type": "string", "required": True, "description": "Repository name"},
            "issue_number": {"type": "integer", "required": True, "description": "Issue number"},
        },
        "nodes": [
            {
                "id": "fetch_issue",
                "type": "write-file",  # Using simple node for test
                "params": {
                    "file_path": "/tmp/issue_${issue_number}.txt",  # noqa: S108
                    "content": "Fetching issue ${issue_number} from ${repo_name} using token ${github_token}",
                },
            }
        ],
        "edges": [],
    }

    # Simulate ParameterMappingNode having extracted these values
    shared = {
        "generated_workflow": workflow_ir,
        # No execution_params key at all (ParameterPreparationNode hasn't run)
        "extracted_params": {
            "github_token": "ghp_abc123xyz789",
            "repo_name": "myorg/myrepo",
            "issue_number": 42,
        },
        "runtime_attempts": 0,
    }

    # Create and run the node
    node = RuntimeValidationNode()

    # Mock compile_ir_to_flow to avoid actual compilation
    with patch("pflow.runtime.compiler.compile_ir_to_flow") as mock_compile:
        # Create a mock flow that simulates successful execution
        mock_flow = MagicMock()
        mock_flow.run.return_value = {"status": "success"}
        mock_compile.return_value = mock_flow

        # Run the full lifecycle
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)
        action = node.post(shared, prep_res, exec_res)

        # Verify it used extracted_params for execution
        assert prep_res["execution_params"] == {
            "github_token": "ghp_abc123xyz789",
            "repo_name": "myorg/myrepo",
            "issue_number": 42,
        }

        # Verify compile was called with the correct params
        mock_compile.assert_called_once()
        # Get the actual call arguments
        call_args, call_kwargs = mock_compile.call_args
        # Check that initial_params contains the extracted values
        assert call_kwargs.get("initial_params") == {
            "github_token": "ghp_abc123xyz789",
            "repo_name": "myorg/myrepo",
            "issue_number": 42,
        }
        # flow.run() is called with an empty shared store, not the params
        mock_flow.run.assert_called_once_with({})

        # Should pass without errors
        assert action == "default"  # Success case
        assert "runtime_errors" not in shared or len(shared.get("runtime_errors", [])) == 0

    print("✓ Integration test: RuntimeValidationNode successfully uses extracted_params when execution_params is None")


def test_execution_params_updated_in_shared_after_prep():
    """Test that prep provides execution params for downstream processing.

    This ensures downstream nodes see the resolved params.
    """
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {"webhook_url": {"type": "string", "required": True}},
        "nodes": [
            {
                "id": "webhook",
                "type": "write-file",
                "params": {"file_path": "/tmp/hook.txt", "content": "${webhook_url}"},  # noqa: S108
            }
        ],
        "edges": [],
    }

    shared = {
        "generated_workflow": workflow_ir,
        # execution_params missing
        "extracted_params": {"webhook_url": "https://hooks.slack.com/services/T123/B456/xyz"},
        "runtime_attempts": 0,
    }

    node = RuntimeValidationNode()
    prep_result = node.prep(shared)

    # Verify prep result has the fallback params
    assert prep_result["execution_params"] == {"webhook_url": "https://hooks.slack.com/services/T123/B456/xyz"}

    # Note: In real execution, downstream nodes would see these params
    # through the prep_result passed to exec(), not through shared store modification
    print("✓ RuntimeValidationNode prep correctly provides execution params for downstream processing")


def test_real_world_scenario_with_required_inputs():
    """Demonstrates the real-world scenario where the bug manifests.

    Scenario: User provides a workflow with required inputs.
    ParameterMappingNode extracts the values into extracted_params.
    RuntimeValidationNode should use those values but currently doesn't when execution_params is empty dict.
    """
    # Real-world workflow that would fail validation
    workflow_ir = {
        "ir_version": "0.1.0",
        "inputs": {
            "slack_webhook": {"type": "string", "required": True, "description": "Slack webhook URL"},
            "channel_id": {"type": "string", "required": True, "description": "Channel to post to"},
            "message": {"type": "string", "required": True, "description": "Message to send"},
        },
        "nodes": [
            {
                "id": "post_to_slack",
                "type": "http",
                "params": {
                    "url": "${slack_webhook}",
                    "method": "POST",
                    "json_body": {
                        "channel": "${channel_id}",
                        "text": "${message}",
                    },
                },
            }
        ],
        "edges": [],
    }

    # State after ParameterMappingNode but before ParameterPreparationNode
    shared = {
        "generated_workflow": workflow_ir,
        "execution_params": {},  # Empty because ParameterPreparationNode hasn't run
        "extracted_params": {  # ParameterMappingNode extracted these from user input
            "slack_webhook": "https://hooks.slack.com/services/T00000000/B00000000/xxxxxxxxxxxx",
            "channel_id": "C1234567890",
            "message": "Deployment completed successfully!",
        },
        "runtime_attempts": 0,
    }

    node = RuntimeValidationNode()
    prep_result = node.prep(shared)

    # BUG: execution_params stays empty, missing the extracted values!
    assert prep_result["execution_params"] == {}
    # This means RuntimeValidationNode will try to execute with no parameters
    # even though the workflow REQUIRES them and they ARE available in extracted_params

    print("✓ Real-world scenario documented: Slack notification workflow would fail")
    print("  because RuntimeValidationNode doesn't see the extracted parameters")


def test_proposed_fix_implementation():
    """Documents the proposed fix for the empty execution_params bug.

    THE FIX: In RuntimeValidationNode.prep(), change the fallback logic from:
        if execution_params is None:
    To:
        if not execution_params:

    This would handle both None and empty dict cases.
    """
    # Show what the fix would look like
    print("\n" + "=" * 60)
    print("PROPOSED FIX for RuntimeValidationNode.prep()")
    print("=" * 60)
    print("Current code (lines 2778-2780):")
    print("    execution_params = shared.get('execution_params')")
    print("    if execution_params is None:")
    print("        execution_params = shared.get('extracted_params', {})")
    print("\nProposed fix:")
    print("    execution_params = shared.get('execution_params')")
    print("    if not execution_params:  # <- CHANGED: handles None AND empty dict")
    print("        execution_params = shared.get('extracted_params', {})")
    print("\nThis ensures RuntimeValidationNode gets parameter values even when")
    print("ParameterPreparationNode hasn't run yet.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    # Run all tests
    print("\nRunning RuntimeValidationNode tests...\n")
    test_runtime_validation_detects_missing_template_paths()
    test_runtime_validation_with_valid_workflow()
    test_runtime_validation_respects_attempt_limit()

    print("\n--- Testing parameter fallback behavior ---")
    test_bug_empty_execution_params_doesnt_fallback()
    test_uses_extracted_params_when_execution_params_none()
    test_prefers_execution_params_when_both_present()
    test_handles_both_params_empty_gracefully()
    test_integration_with_required_inputs_none_execution_params()
    test_execution_params_updated_in_shared_after_prep()

    print("\n--- Real-world impact and proposed fix ---")
    test_real_world_scenario_with_required_inputs()
    test_proposed_fix_implementation()

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("✅ All tests passed!")
    print("⚠️  BUG IDENTIFIED: Empty execution_params doesn't fall back to extracted_params")
    print("💡 FIX: Change 'if execution_params is None:' to 'if not execution_params:'")
    print("=" * 60)
