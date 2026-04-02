"""Test that settings-based node filtering works correctly.

These tests verify critical security and functionality aspects:
1. Denied nodes don't leak to LLM context (security)
2. Test environment override works (CI critical)
"""

import json


def test_denied_nodes_not_in_llm_context(tmp_path):
    """Critical: Ensure denied nodes don't leak to LLM prompts.

    This test verifies that when nodes are denied via settings,
    they are completely hidden from the LLM component-discovery context.
    This is a security feature to prevent access to dangerous operations.
    """
    from pflow.core.settings import SettingsManager
    from pflow.registry import Registry
    from pflow.registry.context_builder import build_component_context

    # Create registry with known nodes
    registry_path = tmp_path / "registry.json"
    registry_data = {
        "version": "0.0.0",
        "nodes": {
            "shell": {
                "module": "pflow.nodes.shell.shell",
                "class_name": "ShellNode",
                "type": "core",
                "interface": {
                    "description": "Execute shell commands.",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": [],
                },
            },
            "http": {
                "module": "pflow.nodes.http.http",
                "class_name": "HttpNode",
                "type": "core",
                "interface": {
                    "description": "Make HTTP requests.",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": [],
                },
            },
            "llm": {
                "module": "pflow.nodes.llm.llm",
                "class_name": "LLMNode",
                "type": "core",
                "interface": {
                    "description": "LLM text processing.",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": [],
                },
            },
        },
    }
    registry_path.write_text(json.dumps(registry_data))

    # Create settings that deny http
    settings_path = tmp_path / "settings.json"
    settings_data = {
        "version": "1.0.0",
        "registry": {"nodes": {"allow": ["*"], "deny": ["http", "pflow.nodes.http.*"]}},
    }
    settings_path.write_text(json.dumps(settings_data))

    # Wire up registry with custom settings
    sm = SettingsManager(settings_path=settings_path)
    registry = Registry(registry_path=registry_path)
    registry._settings_manager = sm

    # Load filtered and build LLM context
    metadata = registry.load(include_filtered=False)
    context = build_component_context(
        selected_node_ids=list(metadata.keys()),
        selected_workflow_names=[],
        registry_metadata=metadata,
    )

    # Denied node must not appear as a section header in LLM context
    assert "### http\n" not in context, "http node leaked to LLM context"

    # Allowed nodes must be present
    assert "### shell\n" in context, "shell node should be in context"
    assert "### llm\n" in context, "llm node should be in context"


def test_deny_rules_filter_nodes_from_registry(tmp_path):
    """Critical: Ensure deny rules in settings actually filter nodes.

    This test verifies that changing deny rules in settings
    changes which nodes are visible in the registry. The deny
    rules are the primary mechanism for restricting node access.
    """
    from pflow.core.settings import SettingsManager
    from pflow.registry import Registry

    # Create registry with known nodes
    registry_path = tmp_path / "registry.json"
    registry_data = {
        "version": "0.0.0",
        "nodes": {
            "shell": {"module": "pflow.nodes.shell.shell", "class_name": "ShellNode", "type": "core"},
            "llm": {"module": "pflow.nodes.llm.llm", "class_name": "LLMNode", "type": "core"},
            "http": {"module": "pflow.nodes.http.http", "class_name": "HttpNode", "type": "core"},
            "read-file": {"module": "pflow.nodes.file.read_file", "class_name": "ReadFileNode", "type": "core"},
        },
    }
    registry_path.write_text(json.dumps(registry_data))

    # Test 1: With restrictive deny rules, nodes are filtered out
    restrictive_settings = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": ["llm", "http"]},
        },
    }
    restrictive_settings_path = tmp_path / "restrictive_settings.json"
    restrictive_settings_path.write_text(json.dumps(restrictive_settings))

    sm_restrictive = SettingsManager(restrictive_settings_path)
    registry = Registry(registry_path=registry_path)
    registry._settings_manager = sm_restrictive

    filtered_nodes = registry.load(include_filtered=False)
    assert "llm" not in filtered_nodes, "llm should be denied by restrictive rules"
    assert "http" not in filtered_nodes, "http should be denied by restrictive rules"
    assert "shell" in filtered_nodes, "shell should be allowed"
    assert "read-file" in filtered_nodes, "read-file should be allowed"

    # Test 2: With permissive settings, all nodes are visible
    permissive_settings = {
        "version": "1.0.0",
        "registry": {
            "nodes": {"allow": ["*"], "deny": []},
        },
    }
    permissive_settings_path = tmp_path / "permissive_settings.json"
    permissive_settings_path.write_text(json.dumps(permissive_settings))

    sm_permissive = SettingsManager(permissive_settings_path)
    registry2 = Registry(registry_path=registry_path)
    registry2._settings_manager = sm_permissive

    all_nodes = registry2.load(include_filtered=False)
    assert "llm" in all_nodes, "llm should be visible with permissive rules"
    assert "http" in all_nodes, "http should be visible with permissive rules"
    assert "shell" in all_nodes, "shell should be visible with permissive rules"
    assert len(all_nodes) > len(filtered_nodes), "Permissive rules should show more nodes"
