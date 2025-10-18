"""Tests for settings.env integration with workflow execution."""

from pathlib import Path

import pytest

from pflow.core.settings import SettingsManager
from pflow.runtime.workflow_validator import prepare_inputs


@pytest.fixture
def sample_workflow_ir() -> dict:
    """Sample workflow IR with input declarations."""
    return {
        "ir_version": "0.1.0",
        "inputs": {
            "api_key": {"description": "API key for authentication", "type": "string", "required": True},
            "optional_param": {
                "description": "Optional parameter",
                "type": "string",
                "required": False,
                "default": "default_value",
            },
            "model": {"description": "Model to use", "type": "string", "required": True},
        },
        "nodes": [],
    }


@pytest.fixture
def settings_with_env(tmp_path: Path) -> dict:
    """Create settings.env dict with test values."""
    settings_path = tmp_path / "settings.json"
    manager = SettingsManager(settings_path=settings_path)
    manager.set_env("api_key", "env_api_key_value")
    manager.set_env("optional_param", "env_optional_value")
    return manager.load().env


class TestPrecedenceOrder:
    """Test input precedence: CLI > settings.env > workflow defaults."""

    def test_cli_param_overrides_settings_env(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test that CLI parameter overrides settings.env value."""
        provided_params = {"api_key": "cli_api_key", "model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        # api_key is in provided_params, so shouldn't be in defaults
        assert "api_key" not in defaults
        # model is in provided_params, not in defaults
        assert "model" not in defaults

    def test_cli_param_overrides_workflow_default(self, sample_workflow_ir: dict) -> None:
        """Test that CLI parameter overrides workflow default."""
        provided_params = {"api_key": "cli_api_key", "model": "cli_model", "optional_param": "cli_optional"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, {})

        assert errors == []
        # All provided via CLI, nothing in defaults
        assert defaults == {}

    def test_settings_env_overrides_workflow_default(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test that settings.env value overrides workflow default."""
        provided_params = {"model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        # api_key from settings.env
        assert defaults["api_key"] == "env_api_key_value"
        # optional_param from settings.env (overrides workflow default)
        assert defaults["optional_param"] == "env_optional_value"

    def test_workflow_default_used_when_no_cli_or_settings(self, sample_workflow_ir: dict) -> None:
        """Test that workflow default is used when no CLI or settings.env."""
        provided_params = {"api_key": "cli_api_key", "model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, {})

        assert errors == []
        # optional_param uses workflow default
        assert defaults["optional_param"] == "default_value"

    def test_full_precedence_chain_cli_wins(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test full precedence chain where CLI wins."""
        # All three sources available: CLI, settings.env, workflow default
        provided_params = {"optional_param": "cli_value", "api_key": "cli_key", "model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        # Everything from CLI, nothing in defaults
        assert defaults == {}

    def test_full_precedence_chain_settings_wins(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test precedence chain where settings.env wins over workflow default."""
        provided_params = {"model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        # optional_param from settings.env (not workflow default)
        assert defaults["optional_param"] == "env_optional_value"

    def test_multiple_inputs_mixed_sources(self, settings_with_env: dict) -> None:
        """Test multiple inputs from different sources."""
        workflow_ir = {
            "inputs": {
                "input_a": {"required": True},
                "input_b": {"required": True},
                "input_c": {"required": False, "default": "default_c"},
            }
        }
        # input_a from CLI, input_b from settings.env, input_c from default
        provided_params = {"input_a": "cli_a"}
        settings_env = {"input_b": "env_b"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["input_b"] == "env_b"  # From settings.env
        assert defaults["input_c"] == "default_c"  # From workflow default

    def test_error_when_required_missing_from_all_sources(self, sample_workflow_ir: dict) -> None:
        """Test error when required input missing from all sources."""
        provided_params = {}  # No CLI params
        settings_env = {}  # No settings.env

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        # Should have errors for both required inputs
        assert len(errors) == 2
        error_messages = [e[0] for e in errors]
        assert any("api_key" in msg for msg in error_messages)
        assert any("model" in msg for msg in error_messages)


class TestSettingsEnvPopulation:
    """Test that settings.env values populate workflow inputs."""

    def test_required_input_from_settings_env(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test required input provided via settings.env."""
        provided_params = {"model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        assert defaults["api_key"] == "env_api_key_value"

    def test_optional_input_from_settings_env(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test optional input provided via settings.env overrides default."""
        provided_params = {"api_key": "cli_key", "model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        # optional_param from settings.env, not workflow default
        assert defaults["optional_param"] == "env_optional_value"

    def test_multiple_inputs_from_settings_env(self, sample_workflow_ir: dict, settings_with_env: dict) -> None:
        """Test multiple inputs all from settings.env."""
        provided_params = {"model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_with_env)

        assert errors == []
        assert defaults["api_key"] == "env_api_key_value"
        assert defaults["optional_param"] == "env_optional_value"

    def test_partial_inputs_from_settings_env(self, sample_workflow_ir: dict) -> None:
        """Test some inputs from settings.env, some from CLI."""
        provided_params = {"api_key": "cli_key"}
        settings_env = {"model": "env_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["model"] == "env_model"
        assert defaults["optional_param"] == "default_value"  # Workflow default

    def test_settings_env_empty_dict(self, sample_workflow_ir: dict) -> None:
        """Test with empty settings.env (no keys configured)."""
        provided_params = {"api_key": "cli_key", "model": "cli_model"}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["optional_param"] == "default_value"

    def test_settings_env_none(self, sample_workflow_ir: dict) -> None:
        """Test with settings_env parameter as None (backward compatible)."""
        provided_params = {"api_key": "cli_key", "model": "cli_model"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, None)

        assert errors == []
        assert defaults["optional_param"] == "default_value"

    def test_settings_env_with_empty_string_value(self, sample_workflow_ir: dict) -> None:
        """Test that empty string value in settings.env is used (not skipped)."""
        provided_params = {"model": "cli_model"}
        settings_env = {"api_key": ""}  # Empty string

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == ""  # Empty string is valid


class TestBackwardCompatibility:
    """Test that existing behavior is preserved."""

    def test_prepare_inputs_without_settings_env_parameter(self, sample_workflow_ir: dict) -> None:
        """Test calling prepare_inputs() with only 2 parameters (backward compatible)."""
        provided_params = {"api_key": "cli_key", "model": "cli_model"}

        # Call without settings_env parameter (backward compatible)
        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params)

        assert errors == []
        assert defaults["optional_param"] == "default_value"

    def test_existing_workflows_without_settings(self, sample_workflow_ir: dict) -> None:
        """Test that workflows work exactly as before without settings.env."""
        provided_params = {"api_key": "cli_key", "model": "cli_model"}

        # No settings.env
        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, {})

        assert errors == []
        assert defaults["optional_param"] == "default_value"

    def test_missing_required_input_still_errors(self, sample_workflow_ir: dict) -> None:
        """Test that missing required inputs still produce errors."""
        provided_params = {}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, {})

        # Should error for missing required inputs
        assert len(errors) == 2

    def test_optional_input_default_still_works(self) -> None:
        """Test that optional input defaults still work as before."""
        workflow_ir = {
            "inputs": {
                "required_input": {"required": True},
                "optional_input": {"required": False, "default": "my_default"},
            }
        }
        provided_params = {"required_input": "value"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, {})

        assert errors == []
        assert defaults["optional_input"] == "my_default"

    def test_all_provided_via_cli_no_defaults(self, sample_workflow_ir: dict) -> None:
        """Test that when all inputs provided via CLI, no defaults are applied."""
        provided_params = {"api_key": "cli_key", "model": "cli_model", "optional_param": "cli_optional"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, {})

        assert errors == []
        assert defaults == {}  # Nothing in defaults


class TestErrorHandling:
    """Test error handling when settings fail to load."""

    def test_required_input_missing_clear_error_message(self, sample_workflow_ir: dict) -> None:
        """Test that error message is clear when required input missing."""
        provided_params = {"model": "cli_model"}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        assert len(errors) == 1
        error_msg = errors[0][0]
        assert "api_key" in error_msg
        assert "required" in error_msg.lower() or "requires" in error_msg.lower()

    def test_settings_env_with_extra_keys_ignored(self, sample_workflow_ir: dict) -> None:
        """Test that extra keys in settings.env are ignored."""
        provided_params = {"api_key": "cli_key", "model": "cli_model"}
        settings_env = {"extra_key_1": "value1", "extra_key_2": "value2", "optional_param": "env_value"}

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        assert errors == []
        # Only optional_param should be in defaults (extra keys ignored)
        assert defaults == {"optional_param": "env_value"}

    def test_settings_env_key_not_matching_input_name(self, sample_workflow_ir: dict) -> None:
        """Test that settings.env keys must exactly match input names."""
        provided_params = {"model": "cli_model"}
        settings_env = {"API_KEY": "env_key"}  # Wrong case

        errors, defaults, env_param_names = prepare_inputs(sample_workflow_ir, provided_params, settings_env)

        # Should error because api_key not provided (case-sensitive)
        assert len(errors) == 1
        assert "api_key" in errors[0][0]

    def test_workflow_without_inputs_section(self) -> None:
        """Test workflow that has no inputs section."""
        workflow_ir = {"ir_version": "0.1.0", "nodes": []}
        provided_params = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, {})

        assert errors == []
        assert defaults == {}

    def test_input_with_only_description(self) -> None:
        """Test input that only has description (implicitly required)."""
        workflow_ir = {"inputs": {"simple_input": {"description": "A simple input"}}}
        provided_params = {}
        settings_env = {"simple_input": "env_value"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["simple_input"] == "env_value"


class TestEndToEndIntegration:
    """Test complete integration scenarios."""

    def test_e2e_realistic_api_key_scenario(self, tmp_path: Path) -> None:
        """Test realistic scenario: workflow needs replicate_api_token from settings."""
        # Create settings with API token
        settings_path = tmp_path / "settings.json"
        manager = SettingsManager(settings_path=settings_path)
        manager.set_env("replicate_api_token", "r8_test_token_xyz")

        # Workflow requires the token
        workflow_ir = {
            "inputs": {
                "replicate_api_token": {"description": "Replicate API token", "required": True},
                "prompt": {"description": "Prompt for generation", "required": True},
            }
        }

        # User provides only the prompt via CLI
        provided_params = {"prompt": "generate an image"}
        settings_env = manager.load().env

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["replicate_api_token"] == "r8_test_token_xyz"  # noqa: S105 - Test data comparison

    def test_e2e_cli_override_in_workflow(self, tmp_path: Path) -> None:
        """Test that CLI parameter overrides settings.env in real scenario."""
        settings_path = tmp_path / "settings.json"
        manager = SettingsManager(settings_path=settings_path)
        manager.set_env("api_key", "old_key_from_settings")

        workflow_ir = {"inputs": {"api_key": {"required": True}}}

        # User explicitly provides key via CLI (overriding settings)
        provided_params = {"api_key": "new_key_from_cli"}
        settings_env = manager.load().env

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        # api_key is in provided_params, not in defaults
        assert "api_key" not in defaults

    def test_e2e_mixed_input_sources(self, tmp_path: Path) -> None:
        """Test inputs from multiple sources in realistic scenario."""
        settings_path = tmp_path / "settings.json"
        manager = SettingsManager(settings_path=settings_path)
        manager.set_env("openai_api_key", "sk-test-key")
        manager.set_env("temperature", "0.9")

        workflow_ir = {
            "inputs": {
                "openai_api_key": {"required": True},
                "model": {"required": True},
                "temperature": {"required": False, "default": "0.7"},
                "max_tokens": {"required": False, "default": "100"},
            }
        }

        # model from CLI, openai_api_key from settings, temperature from settings (overrides default)
        provided_params = {"model": "gpt-4"}
        settings_env = manager.load().env

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["openai_api_key"] == "sk-test-key"  # From settings
        assert defaults["temperature"] == "0.9"  # From settings (overrides default)
        assert defaults["max_tokens"] == "100"  # From workflow default

    def test_e2e_multiple_workflows_same_settings(self, tmp_path: Path) -> None:
        """Test that same settings work for multiple workflows."""
        settings_path = tmp_path / "settings.json"
        manager = SettingsManager(settings_path=settings_path)
        manager.set_env("github_token", "ghp_test_token")

        # Workflow 1: GitHub issue creator
        workflow1_ir = {"inputs": {"github_token": {"required": True}, "title": {"required": True}}}

        # Workflow 2: GitHub PR creator
        workflow2_ir = {"inputs": {"github_token": {"required": True}, "branch": {"required": True}}}

        settings_env = manager.load().env

        # Test workflow 1
        errors1, defaults1, env_param_names1 = prepare_inputs(workflow1_ir, {"title": "Bug report"}, settings_env)
        assert errors1 == []
        assert defaults1["github_token"] == "ghp_test_token"  # noqa: S105 - Test data comparison

        # Test workflow 2 (reusing same settings)
        errors2, defaults2, env_param_names2 = prepare_inputs(workflow2_ir, {"branch": "feature-branch"}, settings_env)
        assert errors2 == []
        assert defaults2["github_token"] == "ghp_test_token"  # noqa: S105 - Test data comparison

    def test_e2e_no_settings_file_fallback(self) -> None:
        """Test that workflows work when settings file doesn't exist."""
        workflow_ir = {"inputs": {"api_key": {"required": True}}}

        # No settings file, so settings_env is empty or None
        provided_params = {"api_key": "cli_key"}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        # Works fine without settings file


class TestShellEnvironmentVariables:
    """Test shell environment variable support for workflow inputs."""

    def test_shell_env_var_populates_required_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that shell env var satisfies required input."""
        # Set shell environment variable
        monkeypatch.setenv("api_key", "shell_value_123")

        workflow_ir = {"inputs": {"api_key": {"required": True, "description": "API key"}}}

        provided_params = {}  # No CLI params
        settings_env = {}  # No settings.env

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == "shell_value_123"

    def test_shell_env_var_populates_optional_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that shell env var populates optional input."""
        monkeypatch.setenv("timeout", "30")

        workflow_ir = {"inputs": {"timeout": {"required": False, "default": 10}}}

        provided_params = {}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["timeout"] == "30"

    def test_cli_param_overrides_shell_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that CLI parameter takes precedence over shell env var."""
        monkeypatch.setenv("api_key", "shell_value")

        workflow_ir = {"inputs": {"api_key": {"required": True}}}
        provided_params = {"api_key": "cli_value"}  # CLI wins
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert "api_key" not in defaults  # Already in provided_params
        # Verify CLI value is preserved (not overwritten)
        assert provided_params["api_key"] == "cli_value"

    def test_shell_env_var_overrides_settings_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that shell env var takes precedence over settings.env."""
        monkeypatch.setenv("api_key", "shell_value")

        workflow_ir = {"inputs": {"api_key": {"required": True}}}
        provided_params = {}
        settings_env = {"api_key": "settings_value"}  # Shell env wins

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == "shell_value"

    def test_shell_env_var_overrides_workflow_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that shell env var overrides workflow default value."""
        monkeypatch.setenv("timeout", "60")

        workflow_ir = {"inputs": {"timeout": {"required": False, "default": 30}}}

        provided_params = {}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["timeout"] == "60"  # Not 30

    def test_settings_env_used_when_no_shell_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test fallback to settings.env when shell env var not set."""
        # Ensure shell env var is NOT set
        monkeypatch.delenv("api_key", raising=False)

        workflow_ir = {"inputs": {"api_key": {"required": True}}}
        provided_params = {}
        settings_env = {"api_key": "settings_value"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == "settings_value"

    def test_full_precedence_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test complete precedence: CLI > shell env > settings.env > workflow default."""
        monkeypatch.setenv("key1", "shell_1")
        monkeypatch.setenv("key2", "shell_2")
        monkeypatch.setenv("key3", "shell_3")

        workflow_ir = {
            "inputs": {
                "key1": {"required": True},  # From CLI
                "key2": {"required": True},  # From shell env
                "key3": {"required": True},  # From settings.env (no shell)
                "key4": {"required": False, "default": "default_4"},  # From workflow default
            }
        }

        # Remove key3 from shell env to test fallback
        monkeypatch.delenv("key3", raising=False)

        provided_params = {"key1": "cli_1"}
        settings_env = {"key2": "settings_2", "key3": "settings_3", "key4": "settings_4"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        # key1 already in provided_params (CLI)
        assert defaults["key2"] == "shell_2"  # Shell env beats settings
        assert defaults["key3"] == "settings_3"  # Settings used (no shell env)
        assert defaults["key4"] == "settings_4"  # Settings beats workflow default

    def test_multiple_inputs_mixed_sources(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test workflow with inputs from different sources simultaneously."""
        monkeypatch.setenv("github_token", "ghp_from_shell")
        monkeypatch.setenv("api_key", "shell_api_key")

        workflow_ir = {
            "inputs": {
                "repo": {"required": True},  # From CLI
                "github_token": {"required": True},  # From shell env
                "api_key": {"required": True},  # From settings.env (overridden by shell)
                "branch": {"required": False, "default": "main"},  # From workflow default
            }
        }

        provided_params = {"repo": "user/repo"}
        settings_env = {"api_key": "settings_api_key", "github_token": "ghp_from_settings"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["github_token"] == "ghp_from_shell"  # noqa: S105 - Test data comparison
        assert defaults["api_key"] == "shell_api_key"  # Shell beats settings
        assert defaults["branch"] == "main"

    def test_shell_env_var_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that empty string in shell env var is preserved."""
        monkeypatch.setenv("api_key", "")

        workflow_ir = {"inputs": {"api_key": {"required": True}}}
        provided_params = {}
        settings_env = {"api_key": "non_empty_value"}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == ""  # Empty string is valid

    def test_shell_env_var_with_special_characters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that special characters in shell env vars are preserved."""
        special_value = "abc!@#$%^&*()_+-={}[]|:;<>,.?/"
        monkeypatch.setenv("api_key", special_value)

        workflow_ir = {"inputs": {"api_key": {"required": True}}}
        provided_params = {}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == special_value

    def test_shell_env_var_case_sensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that shell env var names are case-sensitive."""
        monkeypatch.setenv("api_key", "lowercase")
        monkeypatch.setenv("API_KEY", "uppercase")

        workflow_ir = {"inputs": {"api_key": {"required": True}, "API_KEY": {"required": True}}}

        provided_params = {}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert errors == []
        assert defaults["api_key"] == "lowercase"
        assert defaults["API_KEY"] == "uppercase"

    def test_shell_env_var_not_set_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test error when shell env var not set and no other sources available."""
        monkeypatch.delenv("api_key", raising=False)

        workflow_ir = {"inputs": {"api_key": {"required": True, "description": "API key"}}}
        provided_params = {}
        settings_env = {}

        errors, defaults, env_param_names = prepare_inputs(workflow_ir, provided_params, settings_env)

        assert len(errors) == 1
        assert "api_key" in errors[0][0]
        assert "required" in errors[0][0].lower() or "requires" in errors[0][0].lower()
