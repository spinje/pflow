# Implementation Plan: Require Explicit LLM Model Configuration (Option A)

## Goal

Remove implicit model defaults. Require users to explicitly configure their LLM model through one of three methods:
1. Specify in workflow IR
2. Configure in `~/.pflow/settings.json`
3. Set via `llm models default`

Fail at **compile time** with clear guidance if none configured.

---

## Design Principles

1. **Explicit over implicit** - No magic, no surprises
2. **Fail early** - Compile time error, not runtime
3. **Helpful errors** - Guide users to fix the issue
4. **Provider agnostic** - Works with ANY llm-supported provider
5. **Node independence** - LLM node still works standalone (keeps its default for direct use)

---

## Resolution Order

```
┌─────────────────────────────────────────────────────────────┐
│ 1. IR params["model"] (explicit in workflow)                │
│    → Use as-is                                              │
└─────────────────────────┬───────────────────────────────────┘
                          │ not set
┌─────────────────────────▼───────────────────────────────────┐
│ 2. settings.llm.default_model                               │
│    → Use configured value                                   │
└─────────────────────────┬───────────────────────────────────┘
                          │ not set
┌─────────────────────────▼───────────────────────────────────┐
│ 3. llm library default (llm models default)                 │
│    → Use llm's configured default                           │
└─────────────────────────┬───────────────────────────────────┘
                          │ not set
┌─────────────────────────▼───────────────────────────────────┐
│ 4. CompilationError                                         │
│    → Fail with helpful setup instructions                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Implementation Steps

### Step 1: Add `default_model` to Settings

**File**: `src/pflow/core/settings.py`

**Change**: Add `default_model` field to `LLMSettings` class

```python
class LLMSettings(BaseModel):
    """LLM model configuration.

    These settings control which LLM models are used for:
    - User workflow LLM nodes (default_model)
    - Discovery commands (discovery_model)
    - Smart filtering (filtering_model)

    The planner always uses Anthropic for its advanced features.

    Examples:
        # Set default model for all LLM nodes
        {"default_model": "gpt-5.2"}

        # Different models for different purposes
        {
            "default_model": "gemini-3-flash-preview",
            "discovery_model": "anthropic/claude-sonnet-4-5",
            "filtering_model": "gemini-2.5-flash-lite"
        }
    """

    default_model: Optional[str] = Field(
        default=None,
        description="Default model for LLM nodes in user workflows. "
                    "If not set, falls back to llm library's default model.",
    )
    discovery_model: Optional[str] = Field(
        default=None,
        description="Model for discovery commands. None = auto-detect.",
    )
    filtering_model: Optional[str] = Field(
        default=None,
        description="Model for smart field filtering. None = auto-detect.",
    )
```

**Settings JSON structure**:
```json
{
  "version": "1.0.0",
  "llm": {
    "default_model": "gpt-5.2",
    "discovery_model": null,
    "filtering_model": null
  }
}
```

---

### Step 2: Add Helper Functions to llm_config.py

**File**: `src/pflow/core/llm_config.py`

**Add two new functions**:

```python
def get_llm_cli_default_model() -> Optional[str]:
    """Get the default model configured in llm CLI.

    Runs `llm models default` to check if user has configured
    a default model in Simon Willison's llm library.

    Returns:
        Model name string or None if not configured

    Note:
        Returns None (not error) if llm CLI not installed or fails.
        This is a fallback, not a requirement.
    """
    # Skip in test environment to avoid subprocess issues
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    llm_path = _get_validated_llm_path()
    if not llm_path:
        return None

    try:
        result = subprocess.run(
            [llm_path, "models", "default"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            default_model = result.stdout.strip()
            logger.debug(f"Found llm CLI default model: {default_model}")
            return default_model
    except subprocess.TimeoutExpired:
        logger.debug("Timeout checking llm default model")
    except Exception as e:
        logger.debug(f"Failed to check llm default model: {e}")

    return None


def get_default_workflow_model() -> Optional[str]:
    """Get the default model for user workflow LLM nodes.

    Resolution order:
    1. settings.llm.default_model (pflow settings)
    2. llm CLI default model (llm models default)
    3. None (caller should fail with helpful error)

    This function does NOT auto-detect based on API keys.
    Users must explicitly configure their preferred model.

    Returns:
        Model name string or None if nothing configured

    Example:
        >>> model = get_default_workflow_model()
        >>> if model is None:
        >>>     raise CompilationError("No model configured", ...)
    """
    # 1. Check pflow settings first
    try:
        from pflow.core.settings import SettingsManager
        settings = SettingsManager().load()
        if settings.llm.default_model:
            logger.debug(f"Using pflow settings default_model: {settings.llm.default_model}")
            return settings.llm.default_model
    except Exception as e:
        logger.debug(f"Failed to load settings for default_model: {e}")

    # 2. Check llm CLI default
    llm_default = get_llm_cli_default_model()
    if llm_default:
        logger.debug(f"Using llm CLI default model: {llm_default}")
        return llm_default

    # 3. Nothing configured
    logger.debug("No default workflow model configured")
    return None


def get_model_not_configured_help(node_id: str) -> str:
    """Get helpful error message when no model is configured.

    Args:
        node_id: The LLM node ID for context in message

    Returns:
        Multi-line string with setup instructions
    """
    return f"""No model specified for LLM node '{node_id}' and no default configured.

Configure a default model using one of these methods:

  1. Specify in workflow (per-node):
     {{"id": "{node_id}", "type": "llm", "params": {{"model": "gpt-5.2", "prompt": "..."}}}}

  2. Set pflow default (recommended, applies to all workflows):
     Add to ~/.pflow/settings.json:
     {{"llm": {{"default_model": "gpt-5.2"}}}}

  3. Set llm library default (applies to all llm usage):
     llm models default gpt-5.2

To see available models: llm models list
To see configured keys: llm keys list"""
```

---

### Step 3: Update Compiler to Inject Model or Fail

**File**: `src/pflow/runtime/compiler.py`

**Location**: `_create_single_node()` function, after line 601

**Change**: Add model injection/validation for LLM nodes

```python
def _create_single_node(
    node_data: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
    enable_namespacing: bool,
    template_resolution_mode: str,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
) -> Any:
    node_id = node_data["id"]
    node_type = node_data["type"]
    params = node_data.get("params", {})

    # === NEW: Inject default model for LLM nodes ===
    if node_type == "llm" and "model" not in params:
        from pflow.core.llm_config import get_default_workflow_model, get_model_not_configured_help

        default_model = get_default_workflow_model()

        if default_model:
            # Inject the configured default
            params = {**params, "model": default_model}
            logger.info(
                f"Injecting default model '{default_model}' for LLM node '{node_id}'",
                extra={
                    "phase": "node_instantiation",
                    "node_id": node_id,
                    "default_model": default_model,
                    "source": "settings_or_llm_default",
                },
            )
        else:
            # No model configured anywhere - fail with helpful message
            raise CompilationError(
                message=f"No model configured for LLM node '{node_id}'",
                phase="node_instantiation",
                node_id=node_id,
                node_type=node_type,
                suggestion=get_model_not_configured_help(node_id),
            )
    # === END NEW ===

    logger.debug(
        "Creating node instance",
        extra={"phase": "node_instantiation", "node_id": node_id, "node_type": node_type},
    )

    # ... rest of function unchanged
```

**Important**:
- Create new params dict (`{**params, "model": ...}`) to avoid mutating IR
- Use `logger.info` (not debug) so users see which model was injected
- Fail with `CompilationError` which has proper formatting

---

### Step 4: Keep LLM Node Default (for Independence)

**File**: `src/pflow/nodes/llm/llm.py`

**No change needed**. The node keeps its hardcoded default:

```python
"model": self.params.get("model", "gemini-3-flash-preview")
```

**Rationale**:
- Node remains independent - works standalone without pflow compiler
- In pflow context, compiler ALWAYS injects model (from settings/llm/or fails)
- The hardcoded default is never reached when using pflow

**Update docstring** to clarify this:

```python
"""General-purpose LLM node for text processing.

Interface:
- Params: model: str  # Model to use (injected by pflow, or gemini-3-flash-preview if used standalone)
...
"""
```

---

### Step 5: Add Tests

**File**: `tests/test_runtime/test_compiler_llm_model.py` (new file)

```python
"""Test LLM model injection and validation in compiler."""

import pytest
from unittest.mock import patch, MagicMock

from pflow.runtime.compiler import _create_single_node, CompilationError


class TestLLMModelInjection:
    """Test LLM node model injection at compile time."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry with LLM node."""
        registry = MagicMock()
        registry.load.return_value = {
            "llm": {
                "module": "pflow.nodes.llm.llm",
                "class_name": "LLMNode",
                "type": "core",
                "interface": {"params": [{"name": "model"}, {"name": "prompt"}]}
            }
        }
        return registry

    def test_uses_explicit_model_from_ir(self, mock_registry):
        """Model specified in IR is used, not overridden."""
        node_data = {
            "id": "my-llm",
            "type": "llm",
            "params": {"model": "gpt-5.2", "prompt": "Hi"}
        }

        with patch("pflow.runtime.compiler.get_default_workflow_model") as mock_get:
            mock_get.return_value = "different-model"

            # Should NOT call get_default_workflow_model since model is specified
            # (Actually it won't be called because of the "model" not in params check)
            node = _create_single_node(
                node_data, mock_registry, {}, False, "strict"
            )

            # Verify explicit model preserved (check via set_params call)
            # ... assertions

    def test_injects_settings_default_model(self, mock_registry):
        """Uses settings.llm.default_model when no model in IR."""
        node_data = {
            "id": "my-llm",
            "type": "llm",
            "params": {"prompt": "Hi"}  # No model
        }

        with patch("pflow.runtime.compiler.get_default_workflow_model") as mock_get:
            mock_get.return_value = "gpt-5.2"  # From settings

            node = _create_single_node(
                node_data, mock_registry, {}, False, "strict"
            )

            # Verify model was injected
            # ... assertions

    def test_injects_llm_cli_default(self, mock_registry):
        """Uses llm CLI default when no settings configured."""
        node_data = {
            "id": "my-llm",
            "type": "llm",
            "params": {"prompt": "Hi"}
        }

        with patch("pflow.runtime.compiler.get_default_workflow_model") as mock_get:
            mock_get.return_value = "claude-3-sonnet"  # From llm CLI

            node = _create_single_node(
                node_data, mock_registry, {}, False, "strict"
            )

            # Verify model was injected
            # ... assertions

    def test_fails_when_no_model_configured(self, mock_registry):
        """Raises CompilationError when no model configured anywhere."""
        node_data = {
            "id": "my-llm",
            "type": "llm",
            "params": {"prompt": "Hi"}
        }

        with patch("pflow.runtime.compiler.get_default_workflow_model") as mock_get:
            mock_get.return_value = None  # Nothing configured

            with pytest.raises(CompilationError) as exc_info:
                _create_single_node(
                    node_data, mock_registry, {}, False, "strict"
                )

            error = exc_info.value
            assert "my-llm" in str(error)
            assert "No model configured" in str(error)
            assert "settings.json" in error.suggestion
            assert "llm models default" in error.suggestion

    def test_non_llm_nodes_not_affected(self, mock_registry):
        """Non-LLM nodes don't trigger model injection."""
        mock_registry.load.return_value = {
            "read-file": {
                "module": "pflow.nodes.file.read_file",
                "class_name": "ReadFileNode",
                "type": "core",
                "interface": {}
            }
        }

        node_data = {
            "id": "reader",
            "type": "read-file",
            "params": {"path": "/tmp/x"}
        }

        with patch("pflow.runtime.compiler.get_default_workflow_model") as mock_get:
            # Should not be called for non-llm nodes
            node = _create_single_node(
                node_data, mock_registry, {}, False, "strict"
            )

            mock_get.assert_not_called()

    def test_does_not_mutate_original_ir(self, mock_registry):
        """Model injection creates new dict, doesn't mutate IR."""
        original_params = {"prompt": "Hi"}
        node_data = {
            "id": "my-llm",
            "type": "llm",
            "params": original_params
        }

        with patch("pflow.runtime.compiler.get_default_workflow_model") as mock_get:
            mock_get.return_value = "gpt-5.2"

            _create_single_node(
                node_data, mock_registry, {}, False, "strict"
            )

            # Original params should not be mutated
            assert "model" not in original_params
```

**File**: `tests/test_core/test_llm_config_workflow_model.py` (new file)

```python
"""Test get_default_workflow_model and related functions."""

import pytest
from unittest.mock import patch, MagicMock

from pflow.core.llm_config import (
    get_default_workflow_model,
    get_llm_cli_default_model,
    get_model_not_configured_help,
)


class TestGetDefaultWorkflowModel:
    """Test workflow model resolution."""

    def test_returns_settings_default_model(self):
        """Returns settings.llm.default_model when configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = "gpt-5.2"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            result = get_default_workflow_model()

            assert result == "gpt-5.2"

    def test_falls_back_to_llm_cli_default(self):
        """Falls back to llm CLI default when settings not configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = None

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch("pflow.core.llm_config.get_llm_cli_default_model") as mock_cli:
                mock_cli.return_value = "claude-3-sonnet"

                result = get_default_workflow_model()

                assert result == "claude-3-sonnet"

    def test_returns_none_when_nothing_configured(self):
        """Returns None when nothing is configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = None

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch("pflow.core.llm_config.get_llm_cli_default_model") as mock_cli:
                mock_cli.return_value = None

                result = get_default_workflow_model()

                assert result is None

    def test_settings_takes_priority_over_llm_cli(self):
        """Settings default_model takes priority over llm CLI default."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = "settings-model"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch("pflow.core.llm_config.get_llm_cli_default_model") as mock_cli:
                mock_cli.return_value = "cli-model"

                result = get_default_workflow_model()

                # Settings wins
                assert result == "settings-model"
                # llm CLI not even checked
                mock_cli.assert_not_called()


class TestGetLlmCliDefaultModel:
    """Test llm CLI default model detection."""

    def test_returns_model_when_configured(self):
        """Returns model name when llm has default configured."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="gpt-4o\n"
                )

                result = get_llm_cli_default_model()

                assert result == "gpt-4o"

    def test_returns_none_when_no_default(self):
        """Returns None when llm has no default configured."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout=""  # No default
                )

                result = get_llm_cli_default_model()

                assert result is None

    def test_returns_none_when_llm_not_installed(self):
        """Returns None when llm CLI not found."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = None

            result = get_llm_cli_default_model()

            assert result is None

    def test_returns_none_on_timeout(self):
        """Returns None on subprocess timeout."""
        import subprocess

        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("llm", 2)

                result = get_llm_cli_default_model()

                assert result is None

    def test_skipped_in_test_environment(self):
        """Returns None when PYTEST_CURRENT_TEST is set."""
        with patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "test_foo.py"}):
            # Should return None without even checking llm
            result = get_llm_cli_default_model()
            assert result is None


class TestGetModelNotConfiguredHelp:
    """Test help message generation."""

    def test_includes_node_id(self):
        """Help message includes the node ID."""
        help_text = get_model_not_configured_help("my-custom-llm")
        assert "my-custom-llm" in help_text

    def test_includes_all_configuration_methods(self):
        """Help message shows all three configuration methods."""
        help_text = get_model_not_configured_help("test-node")

        assert "params" in help_text  # Method 1: IR params
        assert "settings.json" in help_text  # Method 2: pflow settings
        assert "llm models default" in help_text  # Method 3: llm CLI

    def test_includes_discovery_commands(self):
        """Help message includes helpful discovery commands."""
        help_text = get_model_not_configured_help("test-node")

        assert "llm models list" in help_text
        assert "llm keys list" in help_text
```

---

## Files Changed Summary

| File | Change |
|------|--------|
| `src/pflow/core/settings.py` | Add `default_model` field to `LLMSettings` |
| `src/pflow/core/llm_config.py` | Add `get_default_workflow_model()`, `get_llm_cli_default_model()`, `get_model_not_configured_help()` |
| `src/pflow/runtime/compiler.py` | Inject default model or fail in `_create_single_node()` |
| `src/pflow/nodes/llm/llm.py` | Update docstring only (code unchanged) |
| `tests/test_runtime/test_compiler_llm_model.py` | New test file |
| `tests/test_core/test_llm_config_workflow_model.py` | New test file |

---

## Expected Behavior

### Scenario 1: Model in workflow IR
```json
{"type": "llm", "params": {"model": "gpt-5.2", "prompt": "Hi"}}
```
**Result**: Uses `gpt-5.2` ✓

### Scenario 2: No model in IR, settings configured
```json
// ~/.pflow/settings.json
{"llm": {"default_model": "claude-3-sonnet"}}

// workflow.json
{"type": "llm", "params": {"prompt": "Hi"}}
```
**Result**: Uses `claude-3-sonnet` ✓ (logged: "Injecting default model 'claude-3-sonnet'")

### Scenario 3: No model in IR, no settings, llm default configured
```bash
llm models default gpt-4o
```
```json
{"type": "llm", "params": {"prompt": "Hi"}}
```
**Result**: Uses `gpt-4o` ✓

### Scenario 4: Nothing configured
```json
{"type": "llm", "params": {"prompt": "Hi"}}
```
**Result**: CompilationError with helpful message ✓

```
Error: No model configured for LLM node 'my-llm'

Configure a default model using one of these methods:

  1. Specify in workflow (per-node):
     {"id": "my-llm", "type": "llm", "params": {"model": "gpt-5.2", "prompt": "..."}}

  2. Set pflow default (recommended, applies to all workflows):
     Add to ~/.pflow/settings.json:
     {"llm": {"default_model": "gpt-5.2"}}

  3. Set llm library default (applies to all llm usage):
     llm models default gpt-5.2

To see available models: llm models list
To see configured keys: llm keys list
```

---

## Migration / Breaking Change

**This is a breaking change** for users who:
1. Don't specify model in workflows
2. Don't have settings.default_model configured
3. Don't have `llm models default` configured
4. Were relying on the hardcoded `gemini-3-flash-preview` default

**Mitigation**: The error message is clear and actionable. Users can fix with one command:
```bash
llm models default gemini-3-flash-preview  # Restore old behavior
```

Or configure pflow settings once:
```bash
echo '{"llm": {"default_model": "gemini-3-flash-preview"}}' > ~/.pflow/settings.json
```

---

## Implementation Order

1. **Step 1**: Add `default_model` to settings.py
2. **Step 2**: Add helper functions to llm_config.py
3. **Step 3**: Update compiler.py
4. **Step 4**: Update LLM node docstring
5. **Step 5**: Add tests
6. **Step 6**: Run full test suite
7. **Step 7**: Update progress log

---

## Questions Resolved

| Question | Answer |
|----------|--------|
| What if user has OpenAI but node defaults to Gemini? | Not a problem - we require explicit config |
| What if settings.default_model key missing? | Falls back to llm CLI default, then fails |
| What about OpenRouter, Ollama, etc.? | Works - we use whatever user configures |
| Provider-specific detection? | None needed - llm library handles validation |

---

Ready for your review. Should I proceed with implementation?
