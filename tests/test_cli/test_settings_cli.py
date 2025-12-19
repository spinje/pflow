"""Tests for settings CLI commands."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from pflow.cli.commands.settings import settings
from pflow.core.settings import SettingsManager


@pytest.fixture
def runner() -> CliRunner:
    """Create Click CLI runner."""
    return CliRunner()


@pytest.fixture
def isolated_settings(tmp_path: Path, monkeypatch) -> Path:
    """Create isolated settings environment."""
    test_settings_path = tmp_path / ".pflow" / "settings.json"

    # Monkeypatch SettingsManager to use test path
    original_init = SettingsManager.__init__

    def mock_init(self, settings_path=None):
        # Use provided path if given, otherwise use isolated test path
        if settings_path is not None:
            original_init(self, settings_path=settings_path)
        else:
            original_init(self, settings_path=test_settings_path)

    monkeypatch.setattr(SettingsManager, "__init__", mock_init)
    return test_settings_path


class TestSetEnvCommand:
    """Test pflow settings set-env command."""

    def test_set_env_new_key(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting a new environment variable."""
        result = runner.invoke(settings, ["set-env", "test_key", "test_value"])

        assert result.exit_code == 0
        assert "✓ Set environment variable: test_key" in result.output
        assert "Value: tes***" in result.output

        # Verify it was actually saved
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.get_env("test_key") == "test_value"

    def test_set_env_overwrites_existing(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test overwriting an existing environment variable."""
        # Set initial value
        result1 = runner.invoke(settings, ["set-env", "api_key", "old_value"])
        assert result1.exit_code == 0

        # Overwrite
        result2 = runner.invoke(settings, ["set-env", "api_key", "new_value"])
        assert result2.exit_code == 0
        assert "✓ Set environment variable: api_key" in result2.output
        assert "Value: new***" in result2.output

        # Verify the new value
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.get_env("api_key") == "new_value"

    def test_set_env_with_empty_value(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting an environment variable with empty value."""
        result = runner.invoke(settings, ["set-env", "empty_key", ""])

        assert result.exit_code == 0
        assert "✓ Set environment variable: empty_key" in result.output
        assert "Value: ***" in result.output

        # Verify empty value was saved
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.get_env("empty_key") == ""

    def test_set_env_with_special_characters(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting values with special characters."""
        special_value = "abc!@#$%^&*()"
        result = runner.invoke(settings, ["set-env", "special_key", special_value])

        assert result.exit_code == 0
        assert "✓ Set environment variable: special_key" in result.output

        # Verify special characters preserved
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.get_env("special_key") == special_value

    def test_set_env_with_unicode(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting values with unicode characters."""
        unicode_value = "你好世界🌍"
        result = runner.invoke(settings, ["set-env", "unicode_key", unicode_value])

        assert result.exit_code == 0
        assert "✓ Set environment variable: unicode_key" in result.output

        # Verify unicode preserved
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.get_env("unicode_key") == unicode_value

    def test_set_env_displays_masked_value(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that set-env displays masked value in output."""
        result = runner.invoke(settings, ["set-env", "api_key", "r8_abc123xyz"])

        assert result.exit_code == 0
        assert "Value: r8_***" in result.output
        # Should NOT show full value
        assert "r8_abc123xyz" not in result.output

    def test_set_env_exit_code(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that set-env returns exit code 0 on success."""
        result = runner.invoke(settings, ["set-env", "key", "value"])
        assert result.exit_code == 0

    def test_set_env_creates_file_if_not_exists(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that set-env creates settings file if it doesn't exist."""
        assert not isolated_settings.exists()

        result = runner.invoke(settings, ["set-env", "key", "value"])

        assert result.exit_code == 0
        assert isolated_settings.exists()


class TestUnsetEnvCommand:
    """Test pflow settings unset-env command."""

    def test_unset_env_existing_key(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test removing an existing environment variable."""
        # Set a key first
        runner.invoke(settings, ["set-env", "api_key", "value"])

        # Remove it
        result = runner.invoke(settings, ["unset-env", "api_key"])

        assert result.exit_code == 0
        assert "✓ Removed environment variable: api_key" in result.output

        # Verify it was removed
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.get_env("api_key") is None

    def test_unset_env_nonexistent_key(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test graceful handling of removing non-existent key."""
        result = runner.invoke(settings, ["unset-env", "nonexistent_key"])

        assert result.exit_code == 0  # Still success (idempotent)
        assert "✗ Environment variable not found: nonexistent_key" in result.output

    def test_unset_env_idempotent(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that unset-env can be called multiple times safely."""
        # Set a key
        runner.invoke(settings, ["set-env", "api_key", "value"])

        # First removal should succeed
        result1 = runner.invoke(settings, ["unset-env", "api_key"])
        assert result1.exit_code == 0
        assert "✓ Removed environment variable: api_key" in result1.output

        # Second removal should return not found but still exit 0
        result2 = runner.invoke(settings, ["unset-env", "api_key"])
        assert result2.exit_code == 0
        assert "✗ Environment variable not found: api_key" in result2.output

    def test_unset_env_success_message(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test success message format."""
        runner.invoke(settings, ["set-env", "key", "value"])
        result = runner.invoke(settings, ["unset-env", "key"])

        assert "✓ Removed environment variable: key" in result.output

    def test_unset_env_not_found_message(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test not found message format."""
        result = runner.invoke(settings, ["unset-env", "missing_key"])

        assert "✗ Environment variable not found: missing_key" in result.output

    def test_unset_env_exit_code_success(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test exit code when key is removed."""
        runner.invoke(settings, ["set-env", "key", "value"])
        result = runner.invoke(settings, ["unset-env", "key"])

        assert result.exit_code == 0

    def test_unset_env_exit_code_not_found(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test exit code when key not found (should still be 0)."""
        result = runner.invoke(settings, ["unset-env", "nonexistent"])

        assert result.exit_code == 0  # Idempotent operation


class TestListEnvCommand:
    """Test pflow settings list-env command."""

    def test_list_env_empty(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test listing when no environment variables configured."""
        result = runner.invoke(settings, ["list-env"])

        assert result.exit_code == 0
        assert "No environment variables configured" in result.output

    def test_list_env_single_variable(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test listing with single environment variable."""
        runner.invoke(settings, ["set-env", "api_key", "secret_value"])

        result = runner.invoke(settings, ["list-env"])

        assert result.exit_code == 0
        assert "Environment variables:" in result.output
        assert "api_key: sec***" in result.output

    def test_list_env_multiple_variables(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test listing with multiple environment variables."""
        runner.invoke(settings, ["set-env", "key1", "value1"])
        runner.invoke(settings, ["set-env", "key2", "value2"])
        runner.invoke(settings, ["set-env", "key3", "value3"])

        result = runner.invoke(settings, ["list-env"])

        assert result.exit_code == 0
        assert "Environment variables:" in result.output
        assert "key1: val***" in result.output
        assert "key2: val***" in result.output
        assert "key3: val***" in result.output

    def test_list_env_default_masked(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that values are masked by default."""
        runner.invoke(settings, ["set-env", "api_key", "r8_abc123xyz"])

        result = runner.invoke(settings, ["list-env"])

        assert result.exit_code == 0
        assert "r8_***" in result.output
        # Should NOT show full value
        assert "r8_abc123xyz" not in result.output

    def test_list_env_with_show_values_flag(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test --show-values flag displays full values."""
        runner.invoke(settings, ["set-env", "api_key", "r8_abc123xyz"])

        result = runner.invoke(settings, ["list-env", "--show-values"])

        assert result.exit_code == 0
        assert "r8_abc123xyz" in result.output
        # Should NOT show masked value
        assert "r8_***" not in result.output

    def test_list_env_warning_when_unmasked(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test warning is displayed when showing unmasked values."""
        runner.invoke(settings, ["set-env", "key", "value"])

        result = runner.invoke(settings, ["list-env", "--show-values"])

        assert result.exit_code == 0
        assert "⚠️  Displaying unmasked values" in result.output

    def test_list_env_sorted_output(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that output is sorted alphabetically."""
        runner.invoke(settings, ["set-env", "zebra", "value1"])
        runner.invoke(settings, ["set-env", "apple", "value2"])
        runner.invoke(settings, ["set-env", "middle", "value3"])

        result = runner.invoke(settings, ["list-env", "--show-values"])

        assert result.exit_code == 0
        # Check that apple comes before middle which comes before zebra
        output = result.output
        apple_pos = output.index("apple")
        middle_pos = output.index("middle")
        zebra_pos = output.index("zebra")
        assert apple_pos < middle_pos < zebra_pos

    def test_list_env_short_values(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that short values are masked as ***."""
        runner.invoke(settings, ["set-env", "short", "ab"])

        result = runner.invoke(settings, ["list-env"])

        assert result.exit_code == 0
        assert "short: ***" in result.output

    def test_list_env_long_values(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that long values show first 3 chars + ***."""
        runner.invoke(settings, ["set-env", "long", "abcdefghij"])

        result = runner.invoke(settings, ["list-env"])

        assert result.exit_code == 0
        assert "long: abc***" in result.output

    def test_list_env_exit_code(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that list-env returns exit code 0."""
        result = runner.invoke(settings, ["list-env"])
        assert result.exit_code == 0


class TestShowCommand:
    """Test pflow settings show command."""

    def test_show_masks_sensitive_env_vars(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that sensitive env vars are masked in show output."""
        # Setup: Add sensitive env vars
        runner.invoke(settings, ["set-env", "api_key", "secret123456"])
        runner.invoke(settings, ["set-env", "password", "pass123456"])
        runner.invoke(settings, ["set-env", "token", "tok123456"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Assert: Full values NOT in output
        assert "secret123456" not in result.output
        assert "pass123456" not in result.output
        assert "tok123456" not in result.output

        # Assert: Masked values ARE in output
        assert "sec***" in result.output
        assert "pas***" in result.output
        assert "tok***" in result.output

    def test_show_does_not_mask_non_sensitive_vars(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that non-sensitive env vars are not masked."""
        # Setup: Add non-sensitive var
        runner.invoke(settings, ["set-env", "log_level", "debug"])
        runner.invoke(settings, ["set-env", "timeout", "30"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Assert: Full values are visible
        assert '"log_level": "debug"' in result.output
        assert '"timeout": "30"' in result.output

    def test_show_mixed_sensitive_and_non_sensitive(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test show with both sensitive and non-sensitive vars."""
        # Setup: Add mix of vars
        runner.invoke(settings, ["set-env", "api_key", "key123456"])
        runner.invoke(settings, ["set-env", "debug_mode", "true"])
        runner.invoke(settings, ["set-env", "password", "pass123456"])
        runner.invoke(settings, ["set-env", "timeout", "60"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Assert: Sensitive masked
        assert "key123456" not in result.output
        assert "pass123456" not in result.output
        assert "key***" in result.output
        assert "pas***" in result.output

        # Assert: Non-sensitive visible
        assert '"debug_mode": "true"' in result.output
        assert '"timeout": "60"' in result.output

    def test_show_with_empty_env(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test show with no environment variables."""
        result = runner.invoke(settings, ["show"])

        assert result.exit_code == 0
        assert '"env": {}' in result.output

    def test_show_masks_short_sensitive_values(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that short sensitive values are fully masked as ***."""
        # Setup: Add short sensitive values
        runner.invoke(settings, ["set-env", "api_key", "ab"])
        runner.invoke(settings, ["set-env", "token", "x"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Assert: Short values fully masked
        assert '"api_key": "***"' in result.output
        assert '"token": "***"' in result.output

        # Assert: Original values not visible
        assert '"ab"' not in result.output
        assert '"x"' not in result.output

    def test_show_preserves_allow_deny_lists(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that allow and deny lists are not affected by masking."""
        # Setup: Add filters
        runner.invoke(settings, ["allow", "test:*"])
        runner.invoke(settings, ["deny", "dangerous:*"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Assert: Filters shown correctly (JSON format may vary)
        assert "test:*" in result.output
        assert "dangerous:*" in result.output
        assert result.exit_code == 0

    def test_show_exit_code(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that show returns exit code 0."""
        result = runner.invoke(settings, ["show"])
        assert result.exit_code == 0

    def test_show_displays_settings_path(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that show displays the settings file path."""
        result = runner.invoke(settings, ["show"])

        assert result.exit_code == 0
        assert "Settings file:" in result.output
        assert str(isolated_settings) in result.output

    def test_show_masks_various_sensitive_keywords(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test masking for various sensitive keyword patterns."""
        # Setup: Add vars with different sensitive keywords
        runner.invoke(settings, ["set-env", "access_token", "access123"])
        runner.invoke(settings, ["set-env", "auth_token", "auth456"])
        runner.invoke(settings, ["set-env", "client_secret", "secret789"])
        runner.invoke(settings, ["set-env", "private_key", "key012"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Assert: All masked
        assert "access123" not in result.output
        assert "auth456" not in result.output
        assert "secret789" not in result.output
        assert "key012" not in result.output

        assert "acc***" in result.output
        assert "aut***" in result.output
        assert "sec***" in result.output
        assert "key***" in result.output

    def test_show_json_structure_valid(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that show outputs valid JSON structure."""
        import json

        # Setup: Add some env vars
        runner.invoke(settings, ["set-env", "api_key", "test123"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Extract JSON using brace counting
        output = result.output
        json_start = output.find("{")
        assert json_start != -1, "No JSON found in output"

        # Count braces to find the matching closing brace
        brace_count = 0
        json_end = json_start
        for i in range(json_start, len(output)):
            if output[i] == "{":
                brace_count += 1
            elif output[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break

        json_output = output[json_start:json_end]

        # Parse JSON to verify it's valid
        try:
            parsed = json.loads(json_output)
            assert "env" in parsed
            assert isinstance(parsed["env"], dict)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON output: {e}")

    def test_show_with_unicode_values(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that show handles unicode in env values correctly."""
        import json

        # Setup: Add unicode values
        runner.invoke(settings, ["set-env", "api_key", "你好123"])
        runner.invoke(settings, ["set-env", "config", "🌍test"])

        # Run show command
        result = runner.invoke(settings, ["show"])

        # Extract JSON using brace counting
        output = result.output
        json_start = output.find("{")
        assert json_start != -1, "No JSON found in output"

        # Count braces to find the matching closing brace
        brace_count = 0
        json_end = json_start
        for i in range(json_start, len(output)):
            if output[i] == "{":
                brace_count += 1
            elif output[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    json_end = i + 1
                    break

        json_output = output[json_start:json_end]
        parsed = json.loads(json_output)

        # Assert: Sensitive masked (first 3 chars + ***)
        assert parsed["env"]["api_key"] == "你好1***"

        # Assert: Non-sensitive visible
        assert parsed["env"]["config"] == "🌍test"


# ============================================================================
# LLM Settings Subgroup Tests
# ============================================================================


class TestLLMShowCommand:
    """Test pflow settings llm show command."""

    def test_llm_show_default_state(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test llm show with no settings configured."""
        result = runner.invoke(settings, ["llm", "show"])

        assert result.exit_code == 0
        assert "LLM Model Settings:" in result.output
        assert "default_model:" in result.output
        assert "discovery_model:" in result.output
        assert "filtering_model:" in result.output

    def test_llm_show_with_configured_default(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test llm show when default_model is configured."""
        # Set a default model
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        result = runner.invoke(settings, ["llm", "show"])

        assert result.exit_code == 0
        assert "gpt-5.2 (configured)" in result.output

    def test_llm_show_with_all_configured(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test llm show when all settings are configured."""
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])
        runner.invoke(settings, ["llm", "set-discovery", "anthropic/claude-sonnet-4-5"])
        runner.invoke(settings, ["llm", "set-filtering", "gemini-3-flash-preview"])

        result = runner.invoke(settings, ["llm", "show"])

        assert result.exit_code == 0
        assert "gpt-5.2 (configured)" in result.output
        assert "anthropic/claude-sonnet-4-5 (configured)" in result.output
        assert "gemini-3-flash-preview (configured)" in result.output

    def test_llm_show_resolution_order(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that show displays resolution order information."""
        result = runner.invoke(settings, ["llm", "show"])

        assert result.exit_code == 0
        assert "Resolution order:" in result.output
        assert "To configure:" in result.output

    def test_llm_show_default_used_as_fallback(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that show displays when default_model is used as fallback for discovery/filtering."""
        # Set only default_model, not discovery or filtering
        runner.invoke(settings, ["llm", "set-default", "gemini-3-flash-preview"])

        result = runner.invoke(settings, ["llm", "show"])

        assert result.exit_code == 0
        assert "gemini-3-flash-preview (configured)" in result.output
        # Discovery and filtering should show they're using default_model
        assert "(using default_model → gemini-3-flash-preview)" in result.output


class TestLLMSetDefaultCommand:
    """Test pflow settings llm set-default command."""

    def test_set_default_model(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting default model."""
        result = runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        assert result.exit_code == 0
        assert "✓ Set default_model: gpt-5.2" in result.output

        # Verify it was saved
        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.default_model == "gpt-5.2"

    def test_set_default_model_with_provider_prefix(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting model with provider prefix."""
        result = runner.invoke(settings, ["llm", "set-default", "anthropic/claude-sonnet-4-5"])

        assert result.exit_code == 0
        assert "✓ Set default_model: anthropic/claude-sonnet-4-5" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.default_model == "anthropic/claude-sonnet-4-5"

    def test_set_default_overwrites_existing(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that setting default model overwrites existing value."""
        runner.invoke(settings, ["llm", "set-default", "old-model"])
        result = runner.invoke(settings, ["llm", "set-default", "new-model"])

        assert result.exit_code == 0
        assert "✓ Set default_model: new-model" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.default_model == "new-model"


class TestLLMSetDiscoveryCommand:
    """Test pflow settings llm set-discovery command."""

    def test_set_discovery_model(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting discovery model."""
        result = runner.invoke(settings, ["llm", "set-discovery", "anthropic/claude-sonnet-4-5"])

        assert result.exit_code == 0
        assert "✓ Set discovery_model: anthropic/claude-sonnet-4-5" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.discovery_model == "anthropic/claude-sonnet-4-5"

    def test_set_discovery_overwrites_existing(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that setting discovery model overwrites existing value."""
        runner.invoke(settings, ["llm", "set-discovery", "old-model"])
        result = runner.invoke(settings, ["llm", "set-discovery", "new-model"])

        assert result.exit_code == 0

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.discovery_model == "new-model"


class TestLLMSetFilteringCommand:
    """Test pflow settings llm set-filtering command."""

    def test_set_filtering_model(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting filtering model."""
        result = runner.invoke(settings, ["llm", "set-filtering", "gemini-2.5-flash-lite"])

        assert result.exit_code == 0
        assert "✓ Set filtering_model: gemini-2.5-flash-lite" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.filtering_model == "gemini-2.5-flash-lite"

    def test_set_filtering_overwrites_existing(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that setting filtering model overwrites existing value."""
        runner.invoke(settings, ["llm", "set-filtering", "old-model"])
        result = runner.invoke(settings, ["llm", "set-filtering", "new-model"])

        assert result.exit_code == 0

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.filtering_model == "new-model"


class TestLLMUnsetCommand:
    """Test pflow settings llm unset command."""

    def test_unset_default(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test unsetting default_model."""
        # First set a value
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        # Then unset it
        result = runner.invoke(settings, ["llm", "unset", "default"])

        assert result.exit_code == 0
        assert "✓ Removed default_model" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.default_model is None

    def test_unset_discovery(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test unsetting discovery_model."""
        runner.invoke(settings, ["llm", "set-discovery", "anthropic/claude-sonnet-4-5"])

        result = runner.invoke(settings, ["llm", "unset", "discovery"])

        assert result.exit_code == 0
        assert "✓ Removed discovery_model" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.discovery_model is None

    def test_unset_filtering(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test unsetting filtering_model."""
        runner.invoke(settings, ["llm", "set-filtering", "gemini-3-flash-preview"])

        result = runner.invoke(settings, ["llm", "unset", "filtering"])

        assert result.exit_code == 0
        assert "✓ Removed filtering_model" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.filtering_model is None

    def test_unset_all(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test unsetting all LLM settings at once."""
        # Set all values
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])
        runner.invoke(settings, ["llm", "set-discovery", "anthropic/claude-sonnet-4-5"])
        runner.invoke(settings, ["llm", "set-filtering", "gemini-3-flash-preview"])

        # Unset all
        result = runner.invoke(settings, ["llm", "unset", "all"])

        assert result.exit_code == 0
        assert "✓ Removed all LLM settings" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.default_model is None
        assert loaded.llm.discovery_model is None
        assert loaded.llm.filtering_model is None

    def test_unset_when_not_set(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test unsetting a value that is not set."""
        result = runner.invoke(settings, ["llm", "unset", "default"])

        assert result.exit_code == 0
        assert "default_model is not set" in result.output

    def test_unset_invalid_setting(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that invalid setting name is rejected."""
        result = runner.invoke(settings, ["llm", "unset", "invalid"])

        assert result.exit_code != 0
        # Click should show valid choices
        assert "Invalid value" in result.output or "invalid" in result.output.lower()


class TestLLMSubgroupHelp:
    """Test help output for LLM subgroup."""

    def test_llm_help(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that llm subgroup shows help."""
        result = runner.invoke(settings, ["llm", "--help"])

        assert result.exit_code == 0
        assert "Manage LLM model settings" in result.output
        assert "show" in result.output
        assert "set-default" in result.output
        assert "set-discovery" in result.output
        assert "set-filtering" in result.output
        assert "unset" in result.output

    def test_llm_set_default_help(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test set-default command help."""
        result = runner.invoke(settings, ["llm", "set-default", "--help"])

        assert result.exit_code == 0
        assert "Set the default model" in result.output


class TestLLMSettingsPersistence:
    """Test that LLM settings are properly persisted to file."""

    def test_settings_persist_across_reloads(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that settings persist across manager reloads."""
        # Set values
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])
        runner.invoke(settings, ["llm", "set-discovery", "anthropic/claude-sonnet-4-5"])

        # Create a new manager and load
        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()

        assert loaded.llm.default_model == "gpt-5.2"
        assert loaded.llm.discovery_model == "anthropic/claude-sonnet-4-5"

    def test_llm_settings_in_show_output(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that LLM settings appear in global settings show."""
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        result = runner.invoke(settings, ["show"])

        assert result.exit_code == 0
        # The llm section should be in the JSON output
        assert '"llm"' in result.output
        assert '"default_model": "gpt-5.2"' in result.output
