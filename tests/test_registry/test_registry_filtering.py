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
    - last_core_scan must also be set to a fresh timestamp so the
      mtime-based refresh path doesn't fire (a missing field is
      treated as stale for legacy registries).
    """
    import pflow
    from pflow.registry import Registry

    # Use the current pflow version to prevent version-based refresh
    current_version = pflow.get_version()

    # Create a test registry file with various node types
    registry_data = {
        "version": current_version,
        "last_core_scan": Registry._now_iso(),
        "nodes": {
            "shell": {"module": "pflow.nodes.shell.shell", "class_name": "ShellNode", "type": "core"},
            "http": {"module": "pflow.nodes.http.http", "class_name": "HttpNode", "type": "core"},
            "llm": {"module": "pflow.nodes.llm.llm", "class_name": "LLMNode", "type": "core"},
            "read-file": {"module": "pflow.nodes.file.read_file", "class_name": "ReadFileNode", "type": "core"},
            "write-file": {"module": "pflow.nodes.file.write_file", "class_name": "WriteFileNode", "type": "core"},
        },
    }

    # Create test registry file
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    # Create test settings that deny some nodes
    settings_data = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": ["shell", "http", "llm"]},
        },
    }
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings_data), encoding="utf-8")

    # Mock the settings manager to use our test settings
    with patch("pflow.core.settings.SettingsManager") as MockSettingsManager:
        mock_settings = MagicMock()
        MockSettingsManager.return_value = mock_settings

        # Configure the mock to deny some nodes
        def should_include(name, module=None):
            denied = ["shell", "http", "llm"]
            return name not in denied

        mock_settings.should_include_node.side_effect = should_include

        # Create registry with test path
        registry = Registry(registry_path=registry_path)
        registry._settings_manager = mock_settings

        # Load with default filtering
        filtered_nodes = registry.load(include_filtered=False)

        # Verify denied nodes are filtered out
        assert "shell" not in filtered_nodes, "shell should be filtered out"
        assert "http" not in filtered_nodes, "http should be filtered out"
        assert "llm" not in filtered_nodes, "llm should be filtered out"

        # Verify allowed nodes are present
        assert "read-file" in filtered_nodes, "read-file should be included"
        assert "write-file" in filtered_nodes, "write-file should be included"

        # Load with include_filtered=True (bypass filtering)
        all_nodes = registry.load(include_filtered=True)

        # Verify all nodes are present when bypassing filter
        assert "shell" in all_nodes, "shell should be present when include_filtered=True"
        assert "http" in all_nodes, "http should be present when include_filtered=True"
        assert "llm" in all_nodes, "llm should be present when include_filtered=True"
        assert "read-file" in all_nodes, "read-file should be present"
        assert "write-file" in all_nodes, "write-file should be present"

        # Verify the counts
        assert len(filtered_nodes) == 2, f"Should have 2 filtered nodes, got {len(filtered_nodes)}"
        assert len(all_nodes) == 5, f"Should have 5 total nodes, got {len(all_nodes)}"


def test_dotted_module_pattern_filtering(tmp_path):
    """Ensure dotted module patterns (pflow.nodes.http.*) work correctly.

    This test verifies that filtering uses the 'module' field (dotted path)
    instead of 'file_path' (filesystem path) for pattern matching.

    Regression test for: patterns like 'pflow.nodes.http.*' should match
    nodes that have module='pflow.nodes.http.http' even when module_path
    is None and file_path is a filesystem path.
    """
    import json

    from pflow.core.settings import SettingsManager
    from pflow.registry import Registry

    # Create a test registry with nodes that have 'module' but no 'module_path'
    # This mirrors how core nodes are stored in the actual registry
    registry_data = {
        "http": {
            "module": "pflow.nodes.http.http",
            "file_path": "/some/path/to/pflow/nodes/http/http.py",
            # Note: no 'module_path' key - this is the key scenario
            "class_name": "HttpNode",
        },
        "http-download": {
            "module": "pflow.nodes.http.download",
            "file_path": "/some/path/to/pflow/nodes/http/download.py",
            "class_name": "HttpDownloadNode",
        },
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "file_path": "/some/path/to/pflow/nodes/file/read_file.py",
            "class_name": "ReadFileNode",
        },
    }

    # Create test registry file
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    # Create settings that deny http nodes using dotted pattern
    settings_data = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": ["pflow.nodes.http.*"]},
        },
    }
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings_data), encoding="utf-8")

    # Create registry and settings manager with test paths
    settings_manager = SettingsManager(settings_path=settings_path)
    registry = Registry(registry_path=registry_path)
    registry._settings_manager = settings_manager

    # Load with filtering
    filtered_nodes = registry.load(include_filtered=False)

    # Verify: http nodes should be filtered out by dotted pattern
    assert "http" not in filtered_nodes, "http should be filtered by pflow.nodes.http.*"
    assert "http-download" not in filtered_nodes, "http-download should be filtered by pflow.nodes.http.*"

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
            "read-file": {"module": "pflow.nodes.file.read_file"},
            "write-file": {"module": "pflow.nodes.file.write_file"},
        }

        # Call list_nodes with default (filtered)
        filtered_list = registry.list_nodes(include_filtered=False)

        # Verify load was called with correct parameter
        mock_load.assert_called_with(include_filtered=False)

        # Verify correct nodes returned
        assert sorted(filtered_list) == ["read-file", "write-file"]

        # Reset mock
        mock_load.reset_mock()

        # When unfiltered
        mock_load.return_value = {
            "shell": {"module": "pflow.nodes.shell.shell"},
            "read-file": {"module": "pflow.nodes.file.read_file"},
            "write-file": {"module": "pflow.nodes.file.write_file"},
        }

        # Call list_nodes with include_filtered=True
        all_list = registry.list_nodes(include_filtered=True)

        # Verify load was called with correct parameter
        mock_load.assert_called_with(include_filtered=True)

        # Verify all nodes returned
        assert sorted(all_list) == ["read-file", "shell", "write-file"]
