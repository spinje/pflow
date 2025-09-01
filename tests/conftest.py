"""Root-level test configuration and fixtures."""

import os

import pytest

from tests.shared.llm_mock import create_mock_get_model


@pytest.fixture(autouse=True, scope="function")
def mock_llm_calls(monkeypatch, request):
    """Auto-applied fixture that mocks all LLM calls to prevent API usage.

    This fixture is automatically applied to ALL tests except those in llm/ directories
    which are meant to test real LLM behavior when RUN_LLM_TESTS=1 is set.
    """
    # Skip mocking for tests in llm/ directories
    test_path = str(request.fspath)
    if "/llm/" in test_path or "\\llm\\" in test_path:
        # These tests should use real LLM when RUN_LLM_TESTS=1
        yield
        return

    # Create and apply the mock
    mock_get_model = create_mock_get_model()
    monkeypatch.setattr("llm.get_model", mock_get_model)

    # Make the mock available to tests that want to configure it
    request.node.mock_llm = mock_get_model

    yield mock_get_model

    # Clean up after test
    mock_get_model.reset()


@pytest.fixture
def mock_llm_responses(request):
    """Fixture to configure LLM mock responses for specific tests.

    Usage:
        def test_something(mock_llm_responses):
            mock_llm_responses.set_response(
                "anthropic/claude-sonnet-4-0",
                WorkflowDecision,
                {"found": True, "workflow_name": "test"}
            )
    """
    # Get the auto-applied mock from the node
    if hasattr(request.node, "mock_llm"):
        return request.node.mock_llm

    # Fallback if not using auto-mock (shouldn't happen)
    return create_mock_get_model()


@pytest.fixture(autouse=True, scope="session")
def enable_test_nodes():
    """Enable test nodes for all test runs.

    This ensures that test nodes like 'echo' are available during testing,
    even though they're hidden from users by default.
    """
    # Store original value
    original = os.environ.get("PFLOW_INCLUDE_TEST_NODES")

    # Enable test nodes for all tests
    os.environ["PFLOW_INCLUDE_TEST_NODES"] = "true"

    yield

    # Restore original value after tests
    if original is None:
        os.environ.pop("PFLOW_INCLUDE_TEST_NODES", None)
    else:
        os.environ["PFLOW_INCLUDE_TEST_NODES"] = original


def _import_test_modules() -> tuple:
    """Import required and optional modules for test isolation.

    Returns:
        tuple: (Registry, SettingsManager or None, MCPServerManager or None)
    """
    # Registry is required
    try:
        from pflow.registry.registry import Registry
    except ImportError as e:
        pytest.fail(f"Registry required for test isolation could not be imported: {e}")

    # SettingsManager is optional
    try:
        from pflow.core.settings import SettingsManager
    except ImportError:
        SettingsManager = None  # type: ignore[assignment]

    # MCPServerManager is optional
    try:
        from pflow.mcp.manager import MCPServerManager
    except ImportError:
        MCPServerManager = None  # type: ignore[assignment]

    return Registry, SettingsManager, MCPServerManager


def _create_registry_patcher(test_registry_path) -> callable:
    """Create a patcher function for Registry initialization.

    Args:
        test_registry_path: Path to use for test registry

    Returns:
        Function that patches Registry.__init__
    """
    from pathlib import Path

    # Track initialization to prevent recursion
    _initializing = set()

    def create_patched_init(original_init):
        def patched_registry_init(self, *args, **kwargs):
            # Use temp path if no explicit path provided
            if "registry_path" not in kwargs and (len(args) < 1 or args[0] is None):
                kwargs["registry_path"] = test_registry_path
            original_init(self, *args, **kwargs)

            # Only auto-load for test registries, avoiding recursion
            path = _get_registry_path(args, kwargs, test_registry_path)
            p = Path(path) if path else test_registry_path

            if _should_auto_load(p, test_registry_path, _initializing):
                _initializing.add(p)
                try:
                    self.load()
                finally:
                    _initializing.discard(p)

        return patched_registry_init

    return create_patched_init


def _get_registry_path(args, kwargs, default_path):
    """Extract the registry path from function arguments.

    Args:
        args: Positional arguments
        kwargs: Keyword arguments
        default_path: Default path to use

    Returns:
        The registry path to use
    """
    if "registry_path" in kwargs:
        return kwargs["registry_path"]
    elif len(args) > 0:
        return args[0]
    else:
        return default_path


def _should_auto_load(path, test_registry_path, initializing_set) -> bool:
    """Check if registry should auto-load nodes.

    Args:
        path: Path to check
        test_registry_path: Test registry path
        initializing_set: Set tracking initialization

    Returns:
        bool: True if should auto-load
    """
    return path == test_registry_path and not path.exists() and path not in initializing_set


def _patch_settings_manager(monkeypatch, SettingsManager, test_settings_path) -> None:
    """Patch SettingsManager to use test path.

    Args:
        monkeypatch: Pytest monkeypatch fixture
        SettingsManager: SettingsManager class or None
        test_settings_path: Path to use for test settings
    """
    if SettingsManager is None:
        return

    original_init = SettingsManager.__init__

    def patched_settings_init(self, *args, **kwargs):
        if "settings_path" not in kwargs and (len(args) < 1 or args[0] is None):
            kwargs["settings_path"] = test_settings_path
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(SettingsManager, "__init__", patched_settings_init)


def _patch_mcp_server_manager(monkeypatch, MCPServerManager, test_mcp_servers_path) -> None:
    """Patch MCPServerManager to use test path.

    Args:
        monkeypatch: Pytest monkeypatch fixture
        MCPServerManager: MCPServerManager class or None
        test_mcp_servers_path: Path to use for test MCP servers
    """
    if MCPServerManager is None:
        return

    monkeypatch.setattr(MCPServerManager, "DEFAULT_CONFIG_PATH", test_mcp_servers_path)

    original_init = MCPServerManager.__init__

    def patched_mcp_init(self, *args, **kwargs):
        if "config_path" not in kwargs and (len(args) < 1 or args[0] is None):
            kwargs["config_path"] = test_mcp_servers_path
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(MCPServerManager, "__init__", patched_mcp_init)


@pytest.fixture(autouse=True, scope="function")
def isolate_pflow_config(tmp_path, monkeypatch):
    """Ensure all tests use isolated pflow configuration paths.

    This fixture prevents tests from modifying the user's actual ~/.pflow directory
    by patching the default paths for Registry, SettingsManager, and MCPServerManager
    to use temporary directories.

    This is applied automatically to ALL tests to ensure complete isolation.

    WARNING: This fixture automatically populates test registries with core nodes
    via Registry.load(). Tests that need empty registries should create them with
    an explicit path.

    Returns:
        dict: Paths used for test isolation (for debugging or special test needs)
    """
    # Create a temporary .pflow directory for this test
    test_pflow_dir = tmp_path / ".pflow"
    test_pflow_dir.mkdir(parents=True, exist_ok=True)

    # Create temporary paths for each component
    test_registry_path = test_pflow_dir / "registry.json"
    test_settings_path = test_pflow_dir / "settings.json"
    test_mcp_servers_path = test_pflow_dir / "mcp-servers.json"

    # Import required and optional modules
    Registry, SettingsManager, MCPServerManager = _import_test_modules()

    # Patch Registry to use temp path by default
    registry_patcher = _create_registry_patcher(test_registry_path)
    patched_registry_init = registry_patcher(Registry.__init__)
    monkeypatch.setattr(Registry, "__init__", patched_registry_init)

    # Patch SettingsManager and MCPServerManager if available
    _patch_settings_manager(monkeypatch, SettingsManager, test_settings_path)
    _patch_mcp_server_manager(monkeypatch, MCPServerManager, test_mcp_servers_path)

    # Log the paths being used for debugging
    if os.environ.get("DEBUG_TEST_PATHS"):
        print("[test-isolation] Using isolated paths:")
        print(f"  Registry: {test_registry_path}")
        print(f"  Settings: {test_settings_path}")
        print(f"  MCP Servers: {test_mcp_servers_path}")

    yield {
        "pflow_dir": test_pflow_dir,
        "registry_path": test_registry_path,
        "settings_path": test_settings_path,
        "mcp_servers_path": test_mcp_servers_path,
    }
