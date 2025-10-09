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
