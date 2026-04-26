"""Root-level test configuration and fixtures."""

import os
import shutil

import pytest

from tests.shared.llm_mock import create_mock_llm_client


@pytest.fixture(autouse=True, scope="function")
def mock_llm_client(monkeypatch, request):
    """Auto-applied fixture that mocks the pflow LiteLLM adapter.

    Patches ``pflow.core.llm_client.complete`` plus each consumer module's
    ``complete`` binding. After Task 158 Phase A.4-A.7 this is the sole LLM
    mock — the legacy ``mock_llm_calls`` (which patched ``llm.get_model``)
    was retired in A.8 once all production callers migrated to the adapter.

    Skipped for tests under ``/llm/`` directories — those exercise real LLM
    behavior when ``RUN_LLM_TESTS=1`` is set.
    """
    test_path = str(request.fspath)
    if "/llm/" in test_path or "\\llm\\" in test_path:
        yield
        return

    mock_client = create_mock_llm_client()

    monkeypatch.setattr("pflow.core.llm_client.complete", mock_client.complete)
    for module_attr in (
        "pflow.nodes.llm.llm.complete",
        "pflow.registry.discovery.complete",
        "pflow.registry.smart_filter.complete",
        "pflow.core.workflow.discovery.complete",
    ):
        monkeypatch.setattr(module_attr, mock_client.complete, raising=False)

    request.node.mock_llm_client = mock_client

    yield mock_client

    mock_client.reset()


def _import_test_modules() -> tuple:
    """Import required and optional modules for test isolation.

    Returns:
        tuple: (Registry, SettingsManager or None, MCPServerManager or None, WorkflowManager)
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

    # WorkflowManager is required
    try:
        from pflow.core.workflow.manager import WorkflowManager
    except ImportError as e:
        pytest.fail(f"WorkflowManager required for test isolation could not be imported: {e}")

    return Registry, SettingsManager, MCPServerManager, WorkflowManager


@pytest.fixture(scope="session")
def precomputed_core_registry_nodes(tmp_path_factory):
    """Precompute core registry nodes once per session to avoid repeated scans."""
    from pflow.registry.registry import Registry

    session_registry_path = tmp_path_factory.mktemp("session_core") / "registry.json"
    reg = Registry(session_registry_path)
    reg._auto_discover_core_nodes()  # safe in tests
    raw = reg._load_from_file()
    return raw.get("nodes", raw)


def _create_registry_patcher(test_registry_path, precomputed_nodes=None) -> callable:
    """Create a patcher function for Registry initialization.

    Args:
        test_registry_path: Path to use for test registry

    Returns:
        Function that patches Registry.__init__
    """
    from pathlib import Path

    _initializing = set()

    def create_patched_init(original_init):
        def patched_registry_init(self, *args, **kwargs):
            if "registry_path" not in kwargs and (len(args) < 1 or args[0] is None):
                kwargs["registry_path"] = test_registry_path
            original_init(self, *args, **kwargs)

            path = _get_registry_path(args, kwargs, test_registry_path)
            p = Path(path) if path else test_registry_path

            if _should_auto_load(p, test_registry_path, _initializing):
                _initializing.add(p)
                try:
                    if precomputed_nodes is not None:
                        self.save(precomputed_nodes)
                    else:
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


def _patch_workflow_manager(monkeypatch, WorkflowManager, test_workflows_path) -> None:
    """Patch WorkflowManager to use test path.

    Args:
        monkeypatch: Pytest monkeypatch fixture
        WorkflowManager: WorkflowManager class
        test_workflows_path: Path to use for test workflows
    """
    original_init = WorkflowManager.__init__

    def patched_workflow_init(self, *args, **kwargs):
        if "workflows_dir" not in kwargs and (len(args) < 1 or args[0] is None):
            kwargs["workflows_dir"] = test_workflows_path
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(WorkflowManager, "__init__", patched_workflow_init)


@pytest.fixture(autouse=True, scope="function")
def isolate_pflow_config(tmp_path, monkeypatch, precomputed_core_registry_nodes):
    """Ensure all tests use isolated pflow configuration paths.

    This fixture prevents tests from modifying the user's actual ~/.pflow directory
    by patching the default paths for Registry, SettingsManager, MCPServerManager,
    and WorkflowManager to use temporary directories.

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
    test_workflows_path = test_pflow_dir / "workflows"

    # Import required and optional modules
    Registry, SettingsManager, MCPServerManager, WorkflowManager = _import_test_modules()

    # Patch Registry to use temp path by default
    registry_patcher = _create_registry_patcher(test_registry_path, precomputed_core_registry_nodes)
    patched_registry_init = registry_patcher(Registry.__init__)
    monkeypatch.setattr(Registry, "__init__", patched_registry_init)

    # Patch SettingsManager, MCPServerManager, and WorkflowManager if available
    _patch_settings_manager(monkeypatch, SettingsManager, test_settings_path)
    _patch_mcp_server_manager(monkeypatch, MCPServerManager, test_mcp_servers_path)
    _patch_workflow_manager(monkeypatch, WorkflowManager, test_workflows_path)

    # Patch MemoizationCache to use isolated cache directory
    test_cache_path = test_pflow_dir / "cache" / "cache.db"
    try:
        from pflow.runtime.cache import MemoizationCache

        _original_cache_init = MemoizationCache.__init__

        def _patched_cache_init(self, db_path=None, ttl_seconds=86400.0, read_enabled=True):
            _original_cache_init(
                self, db_path=db_path or test_cache_path, ttl_seconds=ttl_seconds, read_enabled=read_enabled
            )

        monkeypatch.setattr(MemoizationCache, "__init__", _patched_cache_init)
    except ImportError:
        pass  # Graceful degradation if module is removed or renamed

    # Log the paths being used for debugging
    if os.environ.get("DEBUG_TEST_PATHS"):
        print("[test-isolation] Using isolated paths:")
        print(f"  Registry: {test_registry_path}")
        print(f"  Settings: {test_settings_path}")
        print(f"  MCP Servers: {test_mcp_servers_path}")
        print(f"  Workflows: {test_workflows_path}")

    yield {
        "pflow_dir": test_pflow_dir,
        "registry_path": test_registry_path,
        "settings_path": test_settings_path,
        "mcp_servers_path": test_mcp_servers_path,
        "workflows_path": test_workflows_path,
    }


# --- Subprocess test helpers (DRY for real shell tests) ---


@pytest.fixture(scope="session")
def uv_exe():
    """Return path to uv executable or skip if not found."""
    path = shutil.which("uv")
    if not path:
        pytest.skip("uv not found in PATH")
    return path


@pytest.fixture(scope="module")
def prepared_subprocess_env(tmp_path_factory, precomputed_core_registry_nodes):
    """Prepare isolated HOME and enable test nodes for subprocess CLI tests.

    Also ensures the registry is initialized by writing a precomputed registry file.
    """
    import json as _json
    from datetime import datetime

    import pflow as _pflow

    home = tmp_path_factory.mktemp("home_subprocess")
    (home / ".pflow").mkdir(parents=True, exist_ok=True)

    # Write precomputed registry file directly
    registry_path = home / ".pflow" / "registry.json"
    registry_data = {
        "version": _pflow.get_version(),
        "last_core_scan": datetime.now().isoformat(),
        "nodes": precomputed_core_registry_nodes,
    }
    registry_path.write_text(_json.dumps(registry_data, indent=2))

    env = os.environ.copy()
    env["HOME"] = str(home)
    return env
