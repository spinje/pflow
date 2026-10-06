"""Tests for settings CLI commands."""

import json
import re
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

    def test_show_masks_every_env_value_regardless_of_name(self, runner: CliRunner, isolated_settings: Path) -> None:
        """settings.env is the credential store: show masks every value, like list-env (#696).

        FAL_KEY / STRIPE_KEY are real provider-key names that the word-aware workflow-param rule
        (is_sensitive_parameter) does not flag — a name-based mask printed them in full.
        """
        runner.invoke(settings, ["set-env", "FAL_KEY", "FAKEVALUE-FAL-0000:abcd"])
        runner.invoke(settings, ["set-env", "STRIPE_KEY", "FAKEVALUE-STRIPE-0000"])
        runner.invoke(settings, ["set-env", "log_level", "debug"])
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        result = runner.invoke(settings, ["show"])

        assert result.exit_code == 0
        assert "FAKEVALUE-FAL" not in result.output
        assert "FAKEVALUE-STRIPE" not in result.output
        assert '"debug"' not in result.output
        # Presence: every key is listed with the same mask list-env uses, and other sections are untouched
        assert '"FAL_KEY": "FAK***"' in result.output
        assert '"STRIPE_KEY": "FAK***"' in result.output
        assert '"log_level": "deb***"' in result.output
        assert '"default_model": "openai/gpt-5.2"' in result.output

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

        # Assert: every env value masked (first 3 chars + ***)
        assert parsed["env"]["api_key"] == "你好1***"
        assert parsed["env"]["config"] == "🌍te***"


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
        # TTS narration settings (Task 174) surface here with their concrete defaults.
        assert "tts_model:        gemini-3.1-flash-tts-preview" in result.output
        assert "tts_voice:        Kore" in result.output

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
        # Bare "gemini-*" is normalized to "gemini/gemini-*" at write time
        runner.invoke(settings, ["llm", "set-default", "gemini-3-flash-preview"])

        result = runner.invoke(settings, ["llm", "show"])

        assert result.exit_code == 0
        assert "gemini/gemini-3-flash-preview (configured)" in result.output
        # Discovery and filtering should show they're using default_model
        assert "(using default_model → gemini/gemini-3-flash-preview)" in result.output


class TestLLMSetDefaultCommand:
    """Test pflow settings llm set-default command."""

    def test_set_default_model(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test setting default model."""
        # Bare "gpt-*" is normalized to "openai/gpt-*" at write time
        result = runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        assert result.exit_code == 0
        assert "✓ Set default_model: openai/gpt-5.2" in result.output

        # Verify the normalized name was saved
        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.default_model == "openai/gpt-5.2"

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
        # Bare "gemini-*" is normalized to "gemini/gemini-*" at write time
        result = runner.invoke(settings, ["llm", "set-filtering", "gemini-2.5-flash-lite"])

        assert result.exit_code == 0
        assert "✓ Set filtering_model: gemini/gemini-2.5-flash-lite" in result.output

        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()
        assert loaded.llm.filtering_model == "gemini/gemini-2.5-flash-lite"

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
        # Set values — bare "gpt-*" is normalized to "openai/gpt-*" at write time;
        # already-prefixed names pass through unchanged
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])
        runner.invoke(settings, ["llm", "set-discovery", "anthropic/claude-sonnet-4-5"])

        # Create a new manager and load
        manager = SettingsManager(settings_path=isolated_settings)
        loaded = manager.load()

        assert loaded.llm.default_model == "openai/gpt-5.2"
        assert loaded.llm.discovery_model == "anthropic/claude-sonnet-4-5"

    def test_tts_setters_round_trip_and_unset_restores_defaults(
        self, runner: CliRunner, isolated_settings: Path
    ) -> None:
        """set-tts-model / set-tts-voice persist verbatim (no LiteLLM prefix normalization —
        TTS ids aren't LiteLLM-routed) and `unset` restores the BUILT-IN defaults (these fields
        have concrete defaults, unlike the model trio's revert-to-auto-detection)."""
        set_model = runner.invoke(settings, ["llm", "set-tts-model", "gemini-4-tts"])
        set_voice = runner.invoke(settings, ["llm", "set-tts-voice", "Puck"])
        assert set_model.exit_code == 0 and "tts_model: gemini-4-tts" in set_model.output
        assert set_voice.exit_code == 0 and "tts_voice: Puck" in set_voice.output

        shown = runner.invoke(settings, ["llm", "show"])
        assert "tts_model:        gemini-4-tts" in shown.output
        assert "tts_voice:        Puck" in shown.output

        unset_voice = runner.invoke(settings, ["llm", "unset", "tts-voice"])
        assert unset_voice.exit_code == 0 and "Kore" in unset_voice.output
        loaded = SettingsManager(settings_path=isolated_settings).load()
        assert loaded.llm.tts_voice == "Kore"
        assert loaded.llm.tts_model == "gemini-4-tts"  # untouched by the voice unset

    def test_llm_unset_all_also_resets_tts_to_defaults(self, runner: CliRunner, isolated_settings: Path) -> None:
        runner.invoke(settings, ["llm", "set-tts-voice", "Puck"])
        runner.invoke(settings, ["llm", "unset", "all"])

        loaded = SettingsManager(settings_path=isolated_settings).load()
        assert loaded.llm.tts_voice == "Kore"
        assert loaded.llm.tts_model == "gemini-3.1-flash-tts-preview"

    def test_llm_show_names_the_tts_setters(self, runner: CliRunner, isolated_settings: Path) -> None:
        # The "To configure:" block must cover EVERY field show displays — displaying config
        # without naming its setter strands the agent (the pre-followup gap).
        result = runner.invoke(settings, ["llm", "show"])
        assert "set-tts-model" in result.output
        assert "set-tts-voice" in result.output

    def test_llm_settings_in_show_output(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Test that LLM settings appear in global settings show."""
        # Bare "gpt-*" is normalized to "openai/gpt-*" at write time
        runner.invoke(settings, ["llm", "set-default", "gpt-5.2"])

        result = runner.invoke(settings, ["show"])

        assert result.exit_code == 0
        # The llm section should be in the JSON output with the normalized name
        assert '"llm"' in result.output
        assert '"default_model": "openai/gpt-5.2"' in result.output


# ============================================================================
# Registry Settings Subgroup Tests
# ============================================================================


# Characterization oracle for `pflow settings llm providers` with no key set
# anywhere. Captured from the pre-#606 command; the table moved into
# core/llm_providers.py without changing a byte of this output. Since then:
# the anyscale row is gone (LiteLLM no longer routes it).
_PROVIDERS_TABLE_NO_KEYS = """\
PROVIDER      ENV VARS                                                STATUS
ai21          AI21_API_KEY                                            -
anthropic     ANTHROPIC_API_KEY                                       -
azure         AZURE_API_KEY and AZURE_API_BASE and AZURE_API_VERSION  -
baseten       BASETEN_API_KEY                                         -
bedrock       AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY             -
              (Or use AWS IAM role / ~/.aws/credentials)
cerebras      CEREBRAS_API_KEY                                        -
cohere        COHERE_API_KEY                                          -
databricks    DATABRICKS_API_KEY                                      -
deepinfra     DEEPINFRA_API_KEY                                       -
deepseek      DEEPSEEK_API_KEY                                        -
fireworks_ai  FIREWORKS_AI_API_KEY                                    -
gemini        GEMINI_API_KEY or GOOGLE_API_KEY                        -
groq          GROQ_API_KEY                                            -
huggingface   HUGGINGFACE_API_KEY                                     -
mistral       MISTRAL_API_KEY                                         -
openai        OPENAI_API_KEY                                          -
openrouter    OPENROUTER_API_KEY                                      -
perplexity    PERPLEXITYAI_API_KEY                                    -
replicate     REPLICATE_API_KEY                                       -
together_ai   TOGETHERAI_API_KEY                                      -
              (Note: not TOGETHER_API_KEY)
vertex_ai     VERTEXAI_PROJECT and VERTEXAI_LOCATION                  -
              (Or use gcloud GOOGLE_APPLICATION_CREDENTIALS)
voyage        VOYAGE_API_KEY                                          -
xai           XAI_API_KEY                                             -
hosted_vllm   (no key needed)                                         n/a
              (Typically no auth required)
ollama        OLLAMA_API_BASE                                         n/a
              (URL of local Ollama server, not a key)
vllm          (no key needed)                                         n/a
              (Typically no auth required)

Showing 26 curated provider(s).
Convention for unlisted providers: <PROVIDER>_API_KEY (matches slash-prefix).
Set a key:  pflow settings set-env <ENV_VAR> "<value>"
Models per provider: pflow settings llm models <provider>
Full LiteLLM list: https://docs.litellm.ai/docs/providers
"""

# JSON counterpart of the oracle above: (name, env_vars, semantics, status, note) per row, in output order.
_PROVIDERS_JSON_NO_KEYS: list[tuple[str, tuple[str, ...], str, str, str | None]] = [
    ("ai21", ("AI21_API_KEY",), "single", "-", None),
    ("anthropic", ("ANTHROPIC_API_KEY",), "single", "-", None),
    ("azure", ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"), "and", "-", None),
    ("baseten", ("BASETEN_API_KEY",), "single", "-", None),
    ("bedrock", ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"), "and", "-", "Or use AWS IAM role / ~/.aws/credentials"),
    ("cerebras", ("CEREBRAS_API_KEY",), "single", "-", None),
    ("cohere", ("COHERE_API_KEY",), "single", "-", None),
    ("databricks", ("DATABRICKS_API_KEY",), "single", "-", None),
    ("deepinfra", ("DEEPINFRA_API_KEY",), "single", "-", None),
    ("deepseek", ("DEEPSEEK_API_KEY",), "single", "-", None),
    ("fireworks_ai", ("FIREWORKS_AI_API_KEY",), "single", "-", None),
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "or", "-", None),
    ("groq", ("GROQ_API_KEY",), "single", "-", None),
    ("huggingface", ("HUGGINGFACE_API_KEY",), "single", "-", None),
    ("mistral", ("MISTRAL_API_KEY",), "single", "-", None),
    ("openai", ("OPENAI_API_KEY",), "single", "-", None),
    ("openrouter", ("OPENROUTER_API_KEY",), "single", "-", None),
    ("perplexity", ("PERPLEXITYAI_API_KEY",), "single", "-", None),
    ("replicate", ("REPLICATE_API_KEY",), "single", "-", None),
    ("together_ai", ("TOGETHERAI_API_KEY",), "single", "-", "Note: not TOGETHER_API_KEY"),
    (
        "vertex_ai",
        ("VERTEXAI_PROJECT", "VERTEXAI_LOCATION"),
        "and",
        "-",
        "Or use gcloud GOOGLE_APPLICATION_CREDENTIALS",
    ),
    ("voyage", ("VOYAGE_API_KEY",), "single", "-", None),
    ("xai", ("XAI_API_KEY",), "single", "-", None),
    ("hosted_vllm", (), "local", "n/a", "Typically no auth required"),
    ("ollama", ("OLLAMA_API_BASE",), "local", "n/a", "URL of local Ollama server, not a key"),
    ("vllm", (), "local", "n/a", "Typically no auth required"),
]

# Every env-var-shaped token in the oracle, so each test starts from a clean slate.
_PROVIDER_ENV_VARS = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b", _PROVIDERS_TABLE_NO_KEYS)))


def _status_by_name(output: str) -> dict[str, str]:
    """Map provider name -> STATUS column from the text table (rows only, not notes)."""
    rows = [line.split() for line in output.splitlines()[1:] if line and not line.startswith(" ")]
    return {cells[0]: cells[-1] for cells in rows if cells[-1] in {"set", "-", "n/a"}}


class TestLLMProvidersCommand:
    """Test pflow settings llm providers — output shape and key status."""

    @pytest.fixture(autouse=True)
    def _no_provider_keys(self, monkeypatch: pytest.MonkeyPatch, isolated_settings: Path) -> None:
        for var in _PROVIDER_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_text_table_unchanged(self, runner: CliRunner) -> None:
        result = runner.invoke(settings, ["llm", "providers"])
        assert result.exit_code == 0
        assert result.output == _PROVIDERS_TABLE_NO_KEYS

    def test_json_output_unchanged(self, runner: CliRunner) -> None:
        result = runner.invoke(settings, ["llm", "providers", "--output-format", "json"])
        assert result.exit_code == 0
        expected = [
            {"name": name, "env_vars": list(env_vars), "semantics": semantics, "status": status, "note": note}
            for name, env_vars, semantics, status, note in _PROVIDERS_JSON_NO_KEYS
        ]
        # Byte-exact: key order and indentation are part of the agent-facing contract.
        assert result.output == json.dumps(expected, indent=2) + "\n"

    def test_keyword_filters_case_insensitively(self, runner: CliRunner) -> None:
        result = runner.invoke(settings, ["llm", "providers", "GEM", "--output-format", "json"])
        assert result.exit_code == 0
        # Gemini's env-var order is semantic (canonical first governs which key is sent).
        assert json.loads(result.output) == [
            {
                "name": "gemini",
                "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                "semantics": "or",
                "status": "-",
                "note": None,
            }
        ]

    def test_status_follows_env_var_semantics(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "g-key")  # gemini alias: "or" is satisfied
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "a-key")  # bedrock: "and" is only half satisfied
        monkeypatch.setenv("GROQ_API_KEY", "q-key")  # curated single-key row

        status = _status_by_name(runner.invoke(settings, ["llm", "providers"]).output)

        assert status["gemini"] == "set"
        assert status["bedrock"] == "-"
        assert status["groq"] == "set"
        assert status["anthropic"] == "-"
        assert status["ollama"] == "n/a"

    def test_status_is_what_the_runtime_would_use_under_empty_export(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, isolated_settings: Path
    ) -> None:
        """An exported-but-empty var must not hide a key stored in settings.

        inject_settings_env_vars() never overwrites a var already in os.environ,
        even an empty one, so the empty value is what the process sees.
        Registry providers still get the stored key (the adapter passes
        resolve_provider_api_key() explicitly), so they are "set". Curated-only
        providers are resolved by LiteLLM from os.environ, so their status must
        come from os.environ, not from settings. (Injection itself is skipped
        under pytest; this pins which source each row type reads.)
        """
        manager = SettingsManager(settings_path=isolated_settings)
        manager.set_env("ANTHROPIC_API_KEY", "sk-stored")
        manager.set_env("GROQ_API_KEY", "gq-stored")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("GROQ_API_KEY", "")

        status = _status_by_name(runner.invoke(settings, ["llm", "providers"]).output)

        assert status["anthropic"] == "set"
        assert status["groq"] == "-"


# A small catalog in LiteLLM's shape: 12 anthropic models (over the overview cap of 10),
# entries the listing must drop, and ids from other providers that contain "anthropic".
_MODELS_CATALOG: dict[str, dict[str, object]] = {
    **{
        f"claude-{family}-4-{n}": {"litellm_provider": "anthropic", "mode": "chat"}
        for family in ("opus", "sonnet")
        for n in range(1, 7)
    },
    "gpt-x": {"litellm_provider": "openai", "mode": "chat"},
    "gpt-y": {"litellm_provider": "openai", "mode": "responses"},
    "ft:gpt-x": {"litellm_provider": "openai", "mode": "chat"},
    "text-embedding-z": {"litellm_provider": "openai", "mode": "embedding"},
    "groq/llama-a": {"litellm_provider": "groq", "mode": "chat"},
    "command-r": {"litellm_provider": "cohere_chat", "mode": "chat"},
    "anthropic.claude-opus-9": {"litellm_provider": "bedrock_converse", "mode": "chat"},
    "openrouter/anthropic/claude-opus-9": {"litellm_provider": "openrouter", "mode": "chat"},
    "ollama/llama3": {"litellm_provider": "ollama", "mode": "chat"},
}

_MODELS_NEXT_STEPS = """\
Next steps:
  pflow settings llm models <provider>       a provider's full list, even without its key
  pflow settings llm models <keyword>        filter your providers' models by name (e.g. opus)
  pflow settings llm providers               every provider and the env var it needs
  pflow settings llm show                    the default model pflow resolves
Not listed? Any LiteLLM model works as <provider>/<model> (validation may warn it is not in the catalog).
"""

_MODELS_OVERVIEW = (
    """\
Source: live LiteLLM catalog
Up to 10 per provider, ordered by name (higher versions first) — not a ranking.

anthropic (configured)
  anthropic/claude-sonnet-4-6
  anthropic/claude-sonnet-4-5
  anthropic/claude-sonnet-4-4
  anthropic/claude-sonnet-4-3
  anthropic/claude-sonnet-4-2
  anthropic/claude-sonnet-4-1
  anthropic/claude-opus-4-6
  anthropic/claude-opus-4-5
  anthropic/claude-opus-4-4
  anthropic/claude-opus-4-3
  see all 12: pflow settings llm models anthropic

openai (configured)
  openai/gpt-y
  openai/gpt-x

"""
    + _MODELS_NEXT_STEPS
)

_NO_KEYS_GUIDANCE = """\
No LLM provider keys configured.
Set one:             pflow settings set-env ANTHROPIC_API_KEY "<key>"   (every provider: pflow settings llm providers)
Browse without one:  pflow settings llm models <provider>   (e.g. anthropic, or ollama for local models)
"""


class TestLLMModelsCommand:
    """pflow settings llm models — what it lists, how it labels, where each message goes."""

    @pytest.fixture(autouse=True)
    def _catalog_without_keys(self, monkeypatch: pytest.MonkeyPatch, isolated_settings: Path) -> None:
        from pflow.core import litellm_runtime
        from pflow.core.llm_providers import CURATED_PROVIDERS

        for var in {v for p in CURATED_PROVIDERS for v in p.env_vars}:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(litellm_runtime.import_litellm(), "model_cost", _MODELS_CATALOG)
        monkeypatch.setattr(litellm_runtime, "try_load_upstream_catalog", lambda: True)

    @pytest.fixture
    def runner(self) -> CliRunner:
        # click 8.1 mixes stderr into result.output unless told not to; stream routing is under test here.
        return CliRunner(mix_stderr=False)

    def _run(self, runner: CliRunner, *args: str):
        result = runner.invoke(settings, ["llm", "models", *args])
        assert result.exit_code == 0, result.stderr
        return result

    def test_overview_samples_configured_providers(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
        result = self._run(runner)
        assert result.stdout == _MODELS_OVERVIEW
        assert result.stderr == ""

    def test_see_all_rung_leads_to_the_complete_list(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        out = self._run(runner, "anthropic").stdout
        assert out.count("  anthropic/claude-") == 12
        assert "see all" not in out
        assert "  narrow: pflow settings llm models anthropic <keyword>" in out
        assert "not a ranking" not in out  # the ordering disclaimer belongs to the capped sample only

    def test_provider_name_selects_exactly_that_provider(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-r")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "a")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "b")
        out = self._run(runner, "anthropic").stdout
        assert "anthropic (no key — set ANTHROPIC_API_KEY)" in out
        assert "openrouter" not in out
        assert "bedrock" not in out
        # ...while those providers do list anthropic-named models when asked for by keyword.
        keyword_out = self._run(runner, "claude-opus-9").stdout
        assert "  openrouter/anthropic/claude-opus-9" in keyword_out
        assert "  bedrock/anthropic.claude-opus-9" in keyword_out

    @pytest.mark.parametrize(
        ("provider", "expected"),
        [
            ("groq", "groq (no key — set GROQ_API_KEY)\n  groq/llama-a\n"),
            ("gemini", "gemini (no key — set GEMINI_API_KEY or GOOGLE_API_KEY)\n"),
            (
                "bedrock",
                "bedrock (no key — set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)\n"
                "  (Or use AWS IAM role / ~/.aws/credentials)\n  bedrock/anthropic.claude-opus-9\n",
            ),
            ("cohere", "cohere (no key — set COHERE_API_KEY)\n  cohere/command-r\n"),
            (
                "ollama",
                "ollama (local — no key needed)\n"
                "  (catalog ids — your server runs only the models it has pulled)\n  ollama/llama3\n",
            ),
            (
                "vllm",
                "vllm (local — no key needed)\n  No usable models in LiteLLM's catalog — pass the id your provider"
                " serves as vllm/<model> (setup: https://docs.litellm.ai/docs/providers)\n",
            ),
        ],
    )
    def test_provider_block_labels(self, runner: CliRunner, provider: str, expected: str) -> None:
        out = self._run(runner, provider).stdout
        assert expected in out
        missing_key_rung = 'pflow settings set-env <ENV_VAR> "<key>"'
        assert (missing_key_rung in out) == ("(no key —" in expected)

    def test_key_stored_in_settings_counts_as_configured(self, runner: CliRunner, isolated_settings: Path) -> None:
        SettingsManager(settings_path=isolated_settings).set_env("ANTHROPIC_API_KEY", "sk-stored")
        out = self._run(runner).stdout
        assert "anthropic (configured)" in out
        assert "openai" not in out

    def test_model_keyword_filters_configured_providers(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-o")
        out = self._run(runner, "OPUS").stdout
        assert "anthropic (configured)" in out
        assert out.count("  anthropic/claude-opus-4-") == 6
        assert "sonnet" not in out
        assert "openai" not in out  # no match there, so the block is dropped

    def test_narrow_rung_keeps_the_active_keywords(self, runner: CliRunner) -> None:
        out = self._run(runner, "anthropic", "claude").stdout
        assert "  narrow: pflow settings llm models anthropic claude <keyword>" in out
        # Each keyword alone matches more than the combination: every one must apply.
        narrowed = self._run(runner, "anthropic", "sonnet", "4-6").stdout
        assert [line for line in narrowed.splitlines() if line.startswith("  anthropic/")] == [
            "  anthropic/claude-sonnet-4-6"
        ]

    def test_no_keys_prints_guidance_to_stderr(self, runner: CliRunner) -> None:
        result = self._run(runner)
        assert result.stdout == ""
        assert result.stderr == _NO_KEYS_GUIDANCE
        with_keyword = self._run(runner, "opus")
        assert "Browse without one:  pflow settings llm models <provider> opus   (" in with_keyword.stderr

    def test_no_keys_json_keeps_its_shape(self, runner: CliRunner) -> None:
        result = self._run(runner, "--output-format", "json")
        assert result.stdout == json.dumps({"source": "live", "providers": []}, indent=2) + "\n"
        assert result.stderr == _NO_KEYS_GUIDANCE

    def test_empty_result_says_what_was_searched(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        result = self._run(runner, "xyzzy")
        assert result.stdout == ""
        assert 'No models match "xyzzy" in your configured providers (anthropic).' in result.stderr
        assert "Search a provider without its key:  pflow settings llm models <provider> xyzzy" in result.stderr
        json_result = self._run(runner, "xyzzy", "--output-format", "json")
        assert json.loads(json_result.stdout) == {"source": "live", "providers": []}

    def test_near_miss_provider_name_suggests_the_real_one(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        stderr = self._run(runner, "vertex").stderr
        assert '"vertex" is not a provider name — did you mean: pflow settings llm models vertex_ai' in stderr

    def test_named_no_match_points_at_a_runnable_full_list(self, runner: CliRunner) -> None:
        stderr = self._run(runner, "anthropic", "openai", "xyzzy").stderr
        assert 'No models match "xyzzy" in anthropic, openai.' in stderr
        rung = "Full list:  pflow settings llm models anthropic openai"
        assert rung in stderr
        out = self._run(runner, *rung.split("models ", 1)[1].split()).stdout
        assert "anthropic (" in out
        assert "openai (" in out

    def test_json_lists_every_model_with_auth_fields(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        overview = json.loads(self._run(runner, "--output-format", "json").stdout)
        assert len(overview["providers"][0]["models"]) == 12  # never capped
        result = self._run(runner, "gemini", "cohere", "--output-format", "json")
        expected = {
            "source": "live",
            "providers": [
                {
                    "name": "cohere",
                    "env_vars": ["COHERE_API_KEY"],
                    "semantics": "single",
                    "status": "-",
                    "note": None,
                    "models": ["cohere/command-r"],
                },
                {
                    "name": "gemini",
                    "env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
                    "semantics": "or",
                    "status": "-",
                    "note": None,
                    "models": [],
                },
            ],
        }
        assert result.stdout == json.dumps(expected, indent=2) + "\n"
        assert result.stderr == ""

    def test_settings_help_lists_the_command_beside_providers(self, runner: CliRunner) -> None:
        lines = runner.invoke(settings, ["--help"]).output.splitlines()
        providers = next(line for line in lines if "pflow settings llm providers" in line)
        models = next(line for line in lines if "pflow settings llm models" in line)
        assert lines.index(models) == lines.index(providers) + 1
        assert models.index("pflow") == providers.index("pflow")
        assert models.index("#") == providers.index("#")

    def test_offline_label_names_the_bundled_version(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        from importlib.metadata import version

        from pflow.core import litellm_runtime

        monkeypatch.setattr(litellm_runtime, "try_load_upstream_catalog", lambda: False)
        out = self._run(runner, "groq").stdout
        assert out.startswith(f"Source: offline snapshot (LiteLLM {version('litellm')}; live catalog unreachable)")
        assert json.loads(self._run(runner, "groq", "--output-format", "json").stdout)["source"] == "offline"


class TestLLMModelsCatalogSource:
    """The live/offline label against the real upstream-merge code, with the network stubbed."""

    @pytest.fixture(autouse=True)
    def _real_catalog_copy(self, monkeypatch: pytest.MonkeyPatch, reset_upstream_attempted) -> None:
        import copy

        litellm = reset_upstream_attempted.import_litellm()
        monkeypatch.setattr(litellm, "model_cost", copy.deepcopy(litellm.model_cost))

    def test_live_fetch_adds_upstream_only_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import copy
        from unittest.mock import MagicMock

        import httpx

        from pflow.core.litellm_runtime import import_litellm

        catalog = import_litellm().model_cost
        bundled_key = "claude-sonnet-4-5"
        bundled_before = copy.deepcopy(catalog[bundled_key])
        upstream = {
            "claude-pflow-upstream-only": {"litellm_provider": "anthropic", "mode": "chat"},
            bundled_key: {"litellm_provider": "anthropic", "mode": "chat", "max_tokens": 1},
        }
        monkeypatch.setattr(
            httpx, "get", lambda *a, **k: MagicMock(raise_for_status=lambda: None, json=lambda: upstream)
        )

        result = CliRunner(mix_stderr=False).invoke(settings, ["llm", "models", "anthropic"])

        assert result.exit_code == 0
        assert result.stdout.startswith("Source: live LiteLLM catalog\n")
        assert "  anthropic/claude-pflow-upstream-only\n" in result.stdout
        assert "  anthropic/claude-sonnet-4-5\n" in result.stdout
        assert catalog[bundled_key] == bundled_before

    def test_failed_fetch_falls_back_to_the_bundled_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        def unreachable(*args: object, **kwargs: object) -> None:
            raise httpx.ConnectError("offline")

        monkeypatch.setattr(httpx, "get", unreachable)

        result = CliRunner(mix_stderr=False).invoke(settings, ["llm", "models", "anthropic"])

        assert result.exit_code == 0
        assert result.stdout.startswith("Source: offline snapshot (LiteLLM ")
        assert "  anthropic/claude-sonnet-4-5\n" in result.stdout
        assert result.stderr == ""


class TestLLMNodeModelsHint:
    """The llm node's `model` help points at the listing on every describe surface, with no network."""

    _POINTER = "List usable models: pflow settings llm models · API key env vars: pflow settings llm providers"

    @pytest.fixture(autouse=True)
    def _no_catalog_fetch(self, monkeypatch: pytest.MonkeyPatch):
        from unittest.mock import Mock

        from pflow.core import litellm_runtime

        fetch = Mock(return_value=True)
        monkeypatch.setattr(litellm_runtime, "try_load_upstream_catalog", fetch)
        yield
        fetch.assert_not_called()

    def test_mcp_describe(self) -> None:
        from pflow.cli.commands.mcp import mcp

        result = CliRunner().invoke(mcp, ["describe", "llm"])
        assert result.exit_code == 0
        assert self._POINTER in result.output

    def test_guide_renders_the_pointer_once(self) -> None:
        from pflow.guide import compose_guide

        guide = compose_guide(["llm"])
        assert self._POINTER in guide
        assert guide.count("pflow settings llm providers") == 1

    def test_mcp_server_registry_describe(self) -> None:
        from pflow.mcp_server.services.registry_service import RegistryService

        assert self._POINTER in RegistryService.describe_nodes(["llm"])


class TestRegistryOutputModeCommand:
    """Test `pflow settings output-mode`."""

    def test_output_mode_show_default(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Show command displays current mode (default: smart)."""
        result = runner.invoke(settings, ["output-mode"])
        assert result.exit_code == 0
        assert "smart" in result.output

    @pytest.mark.parametrize("mode", ["smart", "structure", "full"])
    def test_output_mode_set_and_persist(self, runner: CliRunner, isolated_settings: Path, mode: str) -> None:
        """Set command updates mode and persists to settings."""
        result = runner.invoke(settings, ["output-mode", mode])
        assert result.exit_code == 0
        assert f"✓ Set registry output mode: {mode}" in result.output

        # Verify persistence
        manager = SettingsManager(settings_path=isolated_settings)
        assert manager.load().registry.output_mode == mode

    def test_output_mode_invalid_rejected(self, runner: CliRunner, isolated_settings: Path) -> None:
        """Invalid mode is rejected by Click.Choice."""
        result = runner.invoke(settings, ["output-mode", "invalid"])
        assert result.exit_code != 0


def test_removed_settings_registry_subgroup_shows_migration(runner: CliRunner) -> None:
    """'pflow settings registry' was flattened — show a clear migration message."""
    result = runner.invoke(settings, ["registry", "output-mode"])
    assert result.exit_code != 0
    assert "'settings registry' was removed" in result.output
    assert "pflow settings output-mode" in result.output
