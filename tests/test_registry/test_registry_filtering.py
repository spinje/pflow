"""Test registry filtering based on settings.

This test ensures the core filtering mechanism works correctly
at the registry level, which is the foundation for all other
filtering (CLI, LLM, execution).
"""

import json
from unittest.mock import MagicMock, patch


def test_registry_load_respects_settings(tmp_path):
    """Ensure Registry.load() applies settings-based filtering.

    This test verifies that the registry correctly filters nodes
    based on settings when load() is called. This is the core
    mechanism that protects users from accessing denied nodes.

    FIX HISTORY:
    - Registry version must match current pflow version to prevent
      _core_nodes_outdated() from triggering a refresh that replaces
      the test's fake nodes with real core nodes.
    """
    import pflow
    from pflow.registry import Registry

    # Use the current pflow version to prevent version-based refresh
    current_version = getattr(pflow, "__version__", "0.0.1")

    # Create a test registry file with various node types
    registry_data = {
        "version": current_version,
        "nodes": {
            "echo": {"module": "pflow.nodes.test.echo", "class_name": "EchoNode", "type": "core"},
            "test-node": {"module": "pflow.nodes.test_node", "class_name": "TestNode", "type": "core"},
            "git-push": {"module": "pflow.nodes.git.push", "class_name": "GitPushNode", "type": "core"},
            "git-status": {"module": "pflow.nodes.git.status", "class_name": "GitStatusNode", "type": "core"},
            "file-read": {"module": "pflow.nodes.file.read", "class_name": "ReadFileNode", "type": "core"},
        },
    }

    # Create test registry file
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry_data))

    # Create test settings that deny test nodes and git-push
    settings_data = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": ["test.*", "test-*", "echo", "git-push"]},
            "include_test_nodes": False,
        },
    }
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings_data))

    # Mock the settings manager to use our test settings
    with patch("pflow.core.settings.SettingsManager") as MockSettingsManager:
        mock_settings = MagicMock()
        MockSettingsManager.return_value = mock_settings

        # Configure the mock to deny test nodes and git-push
        def should_include(name, module=None):
            denied = ["echo", "test-node", "git-push"]
            return name not in denied

        mock_settings.should_include_node.side_effect = should_include

        # Create registry with test path
        registry = Registry(registry_path=registry_path)
        registry._settings_manager = mock_settings

        # Load with default filtering
        filtered_nodes = registry.load(include_filtered=False)

        # Verify denied nodes are filtered out
        assert "echo" not in filtered_nodes, "echo should be filtered out"
        assert "test-node" not in filtered_nodes, "test-node should be filtered out"
        assert "git-push" not in filtered_nodes, "git-push should be filtered out"

        # Verify allowed nodes are present
        assert "git-status" in filtered_nodes, "git-status should be included"
        assert "file-read" in filtered_nodes, "file-read should be included"

        # Load with include_filtered=True (bypass filtering)
        all_nodes = registry.load(include_filtered=True)

        # Verify all nodes are present when bypassing filter
        assert "echo" in all_nodes, "echo should be present when include_filtered=True"
        assert "test-node" in all_nodes, "test-node should be present when include_filtered=True"
        assert "git-push" in all_nodes, "git-push should be present when include_filtered=True"
        assert "git-status" in all_nodes, "git-status should be present"
        assert "file-read" in all_nodes, "file-read should be present"

        # Verify the counts
        assert len(filtered_nodes) == 2, f"Should have 2 filtered nodes, got {len(filtered_nodes)}"
        assert len(all_nodes) == 5, f"Should have 5 total nodes, got {len(all_nodes)}"


def test_dotted_module_pattern_filtering(tmp_path):
    """Ensure dotted module patterns (pflow.nodes.git.*) work correctly.

    This test verifies that filtering uses the 'module' field (dotted path)
    instead of 'file_path' (filesystem path) for pattern matching.

    Regression test for: patterns like 'pflow.nodes.git.*' should match
    nodes that have module='pflow.nodes.git.status' even when module_path
    is None and file_path is a filesystem path.
    """
    import json

    from pflow.core.settings import SettingsManager
    from pflow.registry import Registry

    # Create a test registry with nodes that have 'module' but no 'module_path'
    # This mirrors how core nodes are stored in the actual registry
    registry_data = {
        "git-status": {
            "module": "pflow.nodes.git.status",
            "file_path": "/some/path/to/pflow/nodes/git/status.py",
            # Note: no 'module_path' key - this is the key scenario
            "class_name": "GitStatusNode",
        },
        "git-commit": {
            "module": "pflow.nodes.git.commit",
            "file_path": "/some/path/to/pflow/nodes/git/commit.py",
            "class_name": "GitCommitNode",
        },
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "file_path": "/some/path/to/pflow/nodes/file/read_file.py",
            "class_name": "ReadFileNode",
        },
    }

    # Create test registry file
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry_data))

    # Create settings that deny git nodes using dotted pattern
    settings_data = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": ["pflow.nodes.git.*"]},
            "include_test_nodes": True,
        },
    }
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings_data))

    # Create registry and settings manager with test paths
    settings_manager = SettingsManager(settings_path=settings_path)
    registry = Registry(registry_path=registry_path)
    registry._settings_manager = settings_manager

    # Load with filtering
    filtered_nodes = registry.load(include_filtered=False)

    # Verify: git nodes should be filtered out by dotted pattern
    assert "git-status" not in filtered_nodes, "git-status should be filtered by pflow.nodes.git.*"
    assert "git-commit" not in filtered_nodes, "git-commit should be filtered by pflow.nodes.git.*"

    # Verify: file nodes should still be present
    assert "read-file" in filtered_nodes, "read-file should not be filtered"

    # Double-check: without filtering, all nodes should be present
    all_nodes = registry.load(include_filtered=True)
    assert len(all_nodes) == 3, "All 3 nodes should be present when bypassing filter"


def test_registry_list_nodes_uses_load_filtering():
    """Verify that Registry.list_nodes() uses the load() filtering.

    This test ensures list_nodes() is correctly delegating to load()
    for consistent filtering behavior.
    """
    from pflow.registry import Registry

    # Create a mock registry
    registry = Registry()

    # Mock the load method to return specific nodes
    with patch.object(registry, "load") as mock_load:
        # When filtered (default)
        mock_load.return_value = {
            "git-status": {"module": "pflow.nodes.git.status"},
            "file-read": {"module": "pflow.nodes.file.read"},
        }

        # Call list_nodes with default (filtered)
        filtered_list = registry.list_nodes(include_filtered=False)

        # Verify load was called with correct parameter
        mock_load.assert_called_with(include_filtered=False)

        # Verify correct nodes returned
        assert sorted(filtered_list) == ["file-read", "git-status"]

        # Reset mock
        mock_load.reset_mock()

        # When unfiltered
        mock_load.return_value = {
            "echo": {"module": "pflow.nodes.test.echo"},
            "git-status": {"module": "pflow.nodes.git.status"},
            "file-read": {"module": "pflow.nodes.file.read"},
        }

        # Call list_nodes with include_filtered=True
        all_list = registry.list_nodes(include_filtered=True)

        # Verify load was called with correct parameter
        mock_load.assert_called_with(include_filtered=True)

        # Verify all nodes returned
        assert sorted(all_list) == ["echo", "file-read", "git-status"]
