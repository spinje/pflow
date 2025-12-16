"""Test that settings-based node filtering works correctly.

These tests verify critical security and functionality aspects:
1. Denied nodes don't leak to LLM context (security)
2. Test environment override works (CI critical)
"""

import json
import os


def test_denied_nodes_not_in_llm_context(tmp_path):
    """Critical: Ensure denied nodes don't leak to LLM prompts.

    This test verifies that when nodes are denied via settings,
    they are completely hidden from the LLM/planner context.
    This is a security feature to prevent access to dangerous operations.

    FIX HISTORY:
    - 2025-01-05: Fixed overly broad test node detection in context_builder.py
      The previous logic skipped any node with "test" in the file path, which
      incorrectly excluded all nodes when the project directory contained "test"
      (e.g., "pflow-test-planner-north-star-examples"). Now uses more specific
      detection based on module paths to only skip actual test nodes.
    """
    # Create a temporary settings file with explicit denies
    settings_file = tmp_path / "settings.json"
    settings = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": ["git-push", "github-delete-*", "test.*", "echo"]},
            "include_test_nodes": False,
        },
        "env": {},
    }
    settings_file.write_text(json.dumps(settings))

    # Point to our test settings
    original_home = os.environ.get("HOME")
    test_home = tmp_path / "home"
    test_home.mkdir()
    pflow_dir = test_home / ".pflow"
    pflow_dir.mkdir()
    (pflow_dir / "settings.json").write_text(json.dumps(settings))

    try:
        os.environ["HOME"] = str(test_home)

        # Import after setting HOME to use test settings
        from pflow.planning.context_builder import build_discovery_context

        # Build the context that would be sent to LLM
        context = build_discovery_context()

        # Verify denied nodes are not present
        # Check for node definitions (these should NOT appear)
        assert '"git-push"' not in context, "git-push node leaked to LLM context"
        assert "'git-push'" not in context, "git-push node leaked to LLM context"
        assert "git-push:" not in context, "git-push node leaked to LLM context"

        assert '"echo"' not in context, "echo test node leaked to LLM context"
        assert "'echo'" not in context, "echo test node leaked to LLM context"
        assert "echo:" not in context, "echo test node leaked to LLM context"

        # Verify allowed nodes ARE present (sanity check)
        # Note: git nodes are denied by default, so we check for always-enabled nodes
        assert "llm" in context or "http" in context, "Allowed nodes should be in context"

    finally:
        # Restore original HOME
        if original_home:
            os.environ["HOME"] = original_home
        else:
            os.environ.pop("HOME", None)


def test_env_var_overrides_settings(tmp_path):
    """Critical: Ensure PFLOW_INCLUDE_TEST_NODES overrides settings for tests.

    This test verifies that the test environment can override
    settings to include test nodes. This is critical for CI/CD
    where tests need access to test nodes like 'echo'.
    """
    # Create strict deny settings
    settings = {
        "version": "1.0.0",
        "registry": {
            "nodes": {
                "allow": ["file.*", "git.*"],  # Very restrictive
                "deny": ["test.*", "echo", "*"],  # Deny everything else
            },
            "include_test_nodes": False,
        },
        "env": {},
    }

    # Set up test environment
    test_home = tmp_path / "home"
    test_home.mkdir()
    pflow_dir = test_home / ".pflow"
    pflow_dir.mkdir()
    (pflow_dir / "settings.json").write_text(json.dumps(settings))

    original_home = os.environ.get("HOME")
    original_env = os.environ.get("PFLOW_INCLUDE_TEST_NODES")

    try:
        os.environ["HOME"] = str(test_home)

        # First verify test nodes are denied without env var
        os.environ.pop("PFLOW_INCLUDE_TEST_NODES", None)

        from pflow.core.settings import SettingsManager
        from pflow.registry import Registry

        # Force reload settings
        sm = SettingsManager(pflow_dir / "settings.json")
        sm._settings = None  # Clear cache

        registry = Registry()
        registry._settings_manager = None  # Clear cache to reload

        nodes_without_env = registry.load()
        assert "echo" not in nodes_without_env, "echo should be denied without env var"

        # Now enable test nodes via environment variable
        os.environ["PFLOW_INCLUDE_TEST_NODES"] = "true"

        # Force reload with env var
        sm._settings = None  # Clear cache
        registry._settings_manager = None  # Clear cache

        nodes_with_env = registry.load()

        # Verify test nodes are now accessible
        assert "echo" in nodes_with_env, "echo should be available with PFLOW_INCLUDE_TEST_NODES=true"

        # Verify the env var truly overrides the strict deny rules
        test_nodes = [name for name in nodes_with_env if "test" in name or name == "echo"]
        assert len(test_nodes) > 0, "Test nodes should be accessible with env override"

    finally:
        # Restore environment
        if original_home:
            os.environ["HOME"] = original_home
        else:
            os.environ.pop("HOME", None)

        if original_env:
            os.environ["PFLOW_INCLUDE_TEST_NODES"] = original_env
        else:
            os.environ.pop("PFLOW_INCLUDE_TEST_NODES", None)
