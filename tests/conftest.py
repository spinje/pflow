"""Root-level test configuration and fixtures."""

import copy
import os
import shutil
from pathlib import Path

import pytest

# Set BEFORE any test module imports litellm. Some test files do
# ``import litellm.exceptions`` at module top (test collection time —
# before conftest fixtures run), which would otherwise trigger LiteLLM's
# import-time httpx.get call to GitHub. Matches what
# ``pflow.core.litellm_runtime.configure_litellm_defaults`` sets in
# production paths. Uses ``setdefault`` so a developer running the suite
# with the var explicitly set (e.g. to ``False`` to test live-fetch
# behavior) isn't overridden.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from tests.shared.llm_mock import create_mock_llm_client


@pytest.fixture(autouse=True, scope="function")
def _block_upstream_cost_map_fetch(monkeypatch):
    """Block the upstream LiteLLM model_cost fetch in tests by default.

    ``pflow.core.litellm_runtime.ensure_model_priced`` performs an HTTPS GET
    to GitHub's raw URL on the first cost-map miss per process (see PR #424).
    Without this fixture, any test that calls ``complete()`` or
    ``get_model_pricing()`` with a non-bundled model name (e.g.
    ``some/exotic-model`` in ``test_cost_none_when_response_cost_missing``)
    would silently fire that network call. Worse: pflow latches the attempt
    after the first call, so the SECOND test in the same worker that hits
    a non-bundled model sees no network — making outcomes order-dependent.

    The fix is to pre-set ``_upstream_attempted = True`` so the helper's
    first-line latch short-circuits before any network code runs. Tests
    that explicitly exercise the merge path (e.g. the 5 tests in
    ``test_litellm_runtime.py::test_ensure_model_priced_*``) opt back in
    via the local ``reset_upstream_attempted`` fixture, which monkeypatches
    the flag back to ``False`` for that test only.

    The two validator-side flags (``_validator_upstream_attempted`` /
    ``_validator_upstream_fetch_succeeded``) are independent from the
    runtime flag — they back ``try_load_upstream_catalog`` (used by the
    LLM model-id preflight in step 9). They're pre-set to a "successful
    no-op" state so any test that exercises validate-time catalog checks
    sees a usable catalog without hitting the network.
    """
    from pflow.core import litellm_runtime

    monkeypatch.setattr(litellm_runtime, "_upstream_attempted", True)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_attempted", True)
    monkeypatch.setattr(litellm_runtime, "_validator_upstream_fetch_succeeded", True)


_FAKE_LLM_KEY_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture(autouse=True, scope="function")
def _inject_fake_llm_api_keys(monkeypatch, request):
    """Inject fake API keys for ALL canonical LLM providers under test.

    Pairs with ``mock_llm_client`` (which patches ``complete()``). The new
    step-9 LLM model-id preflight in ``WorkflowValidator`` runs BEFORE the
    adapter and rejects canonical-provider models when no API key is set —
    correct behavior in production, but tests that mock the LLM call still
    need the key check to pass.

    Skipped for tests under ``/llm/`` directories (real-API tests that need
    actual environment-provided keys).

    Tests marked ``@pytest.mark.no_fake_llm_keys`` get the OPPOSITE behavior:
    the fixture ALSO scrubs any leaked canonical env vars (``ANTHROPIC_API_KEY``,
    ``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ``GOOGLE_API_KEY``) so tests
    asserting the missing-key code path produce the right diagnostic without
    needing a per-test ``monkeypatch.delenv`` loop. ``GOOGLE_API_KEY`` is
    included because LiteLLM accepts it as a Gemini alias.
    """
    test_path = str(request.fspath)
    if "/llm/" in test_path or "\\llm\\" in test_path:
        yield
        return

    if request.node.get_closest_marker("no_fake_llm_keys"):
        # Strengthened semantics: actively scrub. A test using this marker
        # is asserting "no canonical key is configured" — and a developer's
        # actual shell may leak real keys into the process env. Scrubbing
        # here removes the trap where the test silently passes for the
        # wrong reason because the key WAS present.
        for var in _FAKE_LLM_KEY_VARS:
            monkeypatch.delenv(var, raising=False)
        yield
        return

    # Set if absent — don't override a key the test deliberately scrubs or sets.
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        if not os.environ.get(var):
            monkeypatch.setenv(var, f"test-{var}-fake")

    yield


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
    return reg.load(include_filtered=True)


def _create_registry_patcher(test_registry_path) -> callable:
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
                    self.load()
                finally:
                    _initializing.discard(p)

        return patched_registry_init

    return create_patched_init


def _patch_registry_load(monkeypatch, Registry, test_registry_path, precomputed_nodes) -> None:
    """Serve the default isolated test registry from memory.

    Most tests only need core node metadata to validate/compile workflows. Writing
    the same ~48K registry JSON into hundreds of per-test ``.pflow`` directories
    creates a lot of filesystem churn on macOS. Explicit registry-path tests are
    left untouched, and if a test writes the default registry path itself we fall
    back to the real disk-backed ``Registry.load`` behavior.
    """
    original_load = Registry.load

    def _filter_nodes(self, nodes, include_filtered: bool):
        if include_filtered:
            return nodes

        filtered_nodes = {}
        for node_name, node_data in nodes.items():
            module_path = node_data.get("module_path") or node_data.get("module") or node_data.get("file_path", "")
            if self.settings_manager.should_include_node(node_name, module_path):
                filtered_nodes[node_name] = node_data
        return filtered_nodes

    def patched_load(self, include_filtered: bool = False):
        registry_path = Path(self.registry_path)
        if registry_path == test_registry_path and not registry_path.exists():
            nodes = copy.deepcopy(precomputed_nodes)
            self._cached_nodes = nodes
            self._registry_version = self._get_version()
            self._registry_last_scan = self._now_iso()
            return _filter_nodes(self, nodes, include_filtered)

        return original_load(self, include_filtered=include_filtered)

    monkeypatch.setattr(Registry, "load", patched_load)


@pytest.fixture(autouse=True, scope="function")
def disable_trace_file_writes_by_default(monkeypatch, request):
    """Avoid trace-file I/O unless a test explicitly opts in.

    Runtime tests still get an in-memory ``WorkflowTraceCollector`` via
    ``ExecutionResult.trace``. Only the expensive side effect of writing JSON
    into ``~/.pflow/debug`` is disabled by default.

    Task 172 streaming: a run-scoped collector now flushes one JSONL line per node
    DURING the run (``record_node_execution`` → ``_flush_event`` → ``_open_stream``),
    so disabling ``save_to_file`` alone is no longer enough — without gating the
    lazy stream-open too, every non-``trace_files`` workflow run would write a real
    streamed file. ``_open_stream`` is the single entry point both per-event flush
    and ``finalize()`` route through, so no-op'ing it (``self._stream`` stays
    ``None``) makes both short-circuit. The ``save_to_file`` no-op still covers the
    buffer/test whole-file path (which opens its own handle, not via ``_open_stream``).
    """
    if request.node.get_closest_marker("trace_files"):
        yield
        return

    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    def _skip_save_to_file(_self):
        return None

    def _skip_open_stream(_self):
        return None

    monkeypatch.setattr(WorkflowTraceCollector, "save_to_file", _skip_save_to_file)
    monkeypatch.setattr(WorkflowTraceCollector, "_open_stream", _skip_open_stream)
    yield


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

    # Redirect both ``Path.home()`` calls AND ``$HOME``-driven path
    # resolution (``Path("~/...").expanduser()``, ``os.path.expanduser``,
    # subprocess env inheritance) at ``tmp_path``. The two are NOT
    # interchangeable per ``tests/CLAUDE.md`` — production code uses both
    # idioms (``Path.home()`` in ``runtime/workflow_trace.py``,
    # ``runtime/cache.py``, ``cli/commands/report.py``,
    # ``core/prompt_cache_analysis/trace_loading.py``; ``Path.expanduser()`` in
    # ``mcp/manager.py``, ``nodes/mcp/node.py``,
    # ``core/workflow/skill_service.py``). Patching both closes the
    # pre-existing leak where ``WorkflowTraceCollector.save_to_file`` and
    # ``_autoload_trace`` read/wrote the user's real ``~/.pflow/debug/``
    # during tests — which otherwise produces O(N-real-traces)
    # ``analyze-cache`` test slowdown on developer machines.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create temporary paths for each component
    test_registry_path = test_pflow_dir / "registry.json"
    test_settings_path = test_pflow_dir / "settings.json"
    test_mcp_servers_path = test_pflow_dir / "mcp-servers.json"
    test_workflows_path = test_pflow_dir / "workflows"

    # Import required and optional modules
    Registry, SettingsManager, MCPServerManager, WorkflowManager = _import_test_modules()

    # Patch Registry to use temp path by default
    registry_patcher = _create_registry_patcher(test_registry_path)
    patched_registry_init = registry_patcher(Registry.__init__)
    monkeypatch.setattr(Registry, "__init__", patched_registry_init)
    _patch_registry_load(monkeypatch, Registry, test_registry_path, precomputed_core_registry_nodes)

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


def set_isolated_home(env: dict[str, str], home: Path) -> None:
    """Point a subprocess env's home directory at an isolated path on every platform.

    Subprocess ``Path.home()`` reads ``USERPROFILE`` on Windows, not ``HOME``
    (mirrors the ``Path.home``-vs-``$HOME`` distinction documented on
    ``isolate_pflow_config`` above). Setting ``HOME`` alone leaves the child
    resolving the real ``~/.pflow`` via the stale ``USERPROFILE`` on win32 —
    a silent test-isolation leak, not a crash.
    """
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)


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
    registry_path.write_text(_json.dumps(registry_data, indent=2), encoding="utf-8")

    env = os.environ.copy()
    set_isolated_home(env, home)
    return env
