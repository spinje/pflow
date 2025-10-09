"""Tests for settings management."""

import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest

from pflow.core.settings import PflowSettings, RegistrySettings, SettingsManager


@pytest.fixture
def settings_manager(tmp_path: Path) -> SettingsManager:
    """Create a SettingsManager with temporary directory."""
    return SettingsManager(settings_path=tmp_path / ".pflow" / "settings.json")


@pytest.fixture
def sample_settings() -> PflowSettings:
    """Sample settings for testing."""
    return PflowSettings(version="1.0.0", registry=RegistrySettings(), env={"existing_key": "existing_value"})


class TestEnvManagement:
    """Test environment variable management methods."""

    def test_set_env_new_key(self, settings_manager: SettingsManager) -> None:
        """Test adding a new environment variable."""
        settings_manager.set_env("api_key", "secret_value")

        # Verify it was saved
        settings = settings_manager.load()
        assert "api_key" in settings.env
        assert settings.env["api_key"] == "secret_value"

    def test_set_env_overwrites_existing(self, settings_manager: SettingsManager) -> None:
        """Test overwriting an existing environment variable."""
        # Set initial value
        settings_manager.set_env("api_key", "old_value")

        # Overwrite
        settings_manager.set_env("api_key", "new_value")

        # Verify it was updated
        settings = settings_manager.load()
        assert settings.env["api_key"] == "new_value"

    def test_set_env_creates_file_if_not_exists(self, settings_manager: SettingsManager) -> None:
        """Test that set_env creates settings file if it doesn't exist."""
        assert not settings_manager.settings_path.exists()

        settings_manager.set_env("test_key", "test_value")

        assert settings_manager.settings_path.exists()

    def test_unset_env_existing_key(self, settings_manager: SettingsManager) -> None:
        """Test removing an existing environment variable."""
        # Set a key first
        settings_manager.set_env("api_key", "value")

        # Remove it
        result = settings_manager.unset_env("api_key")

        assert result is True
        settings = settings_manager.load()
        assert "api_key" not in settings.env

    def test_unset_env_nonexistent_key(self, settings_manager: SettingsManager) -> None:
        """Test removing a non-existent environment variable returns False."""
        result = settings_manager.unset_env("nonexistent_key")

        assert result is False

    def test_unset_env_idempotent(self, settings_manager: SettingsManager) -> None:
        """Test that unset_env can be called multiple times safely."""
        settings_manager.set_env("api_key", "value")

        # First removal should succeed
        assert settings_manager.unset_env("api_key") is True

        # Second removal should return False but not error
        assert settings_manager.unset_env("api_key") is False

    def test_get_env_existing(self, settings_manager: SettingsManager) -> None:
        """Test getting an existing environment variable."""
        settings_manager.set_env("api_key", "secret_value")

        value = settings_manager.get_env("api_key")

        assert value == "secret_value"

    def test_get_env_nonexistent_with_default(self, settings_manager: SettingsManager) -> None:
        """Test getting a non-existent key returns the default value."""
        value = settings_manager.get_env("nonexistent", "default_value")

        assert value == "default_value"

    def test_get_env_nonexistent_no_default(self, settings_manager: SettingsManager) -> None:
        """Test getting a non-existent key without default returns None."""
        value = settings_manager.get_env("nonexistent")

        assert value is None

    def test_list_env_masked(self, settings_manager: SettingsManager) -> None:
        """Test listing environment variables with masking."""
        settings_manager.set_env("short", "ab")
        settings_manager.set_env("medium", "abcde")
        settings_manager.set_env("long_key", "r8_abc123xyz")

        env_vars = settings_manager.list_env(mask_values=True)

        assert env_vars["short"] == "***"  # ≤3 chars
        assert env_vars["medium"] == "abc***"  # First 3 + ***
        assert env_vars["long_key"] == "r8_***"  # First 3 + ***

    def test_list_env_unmasked(self, settings_manager: SettingsManager) -> None:
        """Test listing environment variables without masking."""
        settings_manager.set_env("api_key", "secret_value")
        settings_manager.set_env("token", "abc123")

        env_vars = settings_manager.list_env(mask_values=False)

        assert env_vars["api_key"] == "secret_value"
        assert env_vars["token"] == "abc123"  # noqa: S105 - Test assertion, not a password

    def test_list_env_empty(self, settings_manager: SettingsManager) -> None:
        """Test listing environment variables when empty."""
        env_vars = settings_manager.list_env()

        assert env_vars == {}

    def test_list_env_returns_copy(self, settings_manager: SettingsManager) -> None:
        """Test that list_env returns a copy, not a reference."""
        settings_manager.set_env("api_key", "value")

        env_vars = settings_manager.list_env(mask_values=False)
        env_vars["api_key"] = "modified"

        # Original should be unchanged
        original_value = settings_manager.get_env("api_key")
        assert original_value == "value"


class TestMaskValue:
    """Test the _mask_value static method."""

    def test_mask_value_empty_string(self) -> None:
        """Test masking an empty string."""
        result = SettingsManager._mask_value("")
        assert result == "***"

    def test_mask_value_one_char(self) -> None:
        """Test masking a single character."""
        result = SettingsManager._mask_value("a")
        assert result == "***"

    def test_mask_value_two_chars(self) -> None:
        """Test masking two characters."""
        result = SettingsManager._mask_value("ab")
        assert result == "***"

    def test_mask_value_three_chars(self) -> None:
        """Test masking three characters."""
        result = SettingsManager._mask_value("abc")
        assert result == "***"

    def test_mask_value_four_chars(self) -> None:
        """Test masking four characters."""
        result = SettingsManager._mask_value("abcd")
        assert result == "abc***"

    def test_mask_value_long_string(self) -> None:
        """Test masking a long string."""
        result = SettingsManager._mask_value("r8_abc123xyz")
        assert result == "r8_***"

    def test_mask_value_unicode(self) -> None:
        """Test masking unicode characters."""
        result = SettingsManager._mask_value("emoji🎉test")
        # Should show first 3 characters (including emoji)
        assert result.endswith("***")
        assert len(result) >= 6  # At least "xxx***"


class TestEnvIntegrationWithExistingSettings:
    """Test that env management integrates correctly with existing settings."""

    def test_env_operations_preserve_registry_settings(self, settings_manager: SettingsManager) -> None:
        """Test that env operations don't affect registry settings."""
        # Set up some registry settings
        settings = settings_manager.load()
        settings.registry.nodes.allow = ["file-*", "git-*"]
        settings.registry.nodes.deny = ["test-*"]
        settings_manager.save(settings)

        # Perform env operations
        settings_manager.set_env("api_key", "value1")
        settings_manager.set_env("token", "value2")
        settings_manager.unset_env("api_key")

        # Verify registry settings are unchanged
        final_settings = settings_manager.load()
        assert final_settings.registry.nodes.allow == ["file-*", "git-*"]
        assert final_settings.registry.nodes.deny == ["test-*"]
        assert "token" in final_settings.env
        assert "api_key" not in final_settings.env

    def test_env_operations_preserve_version(self, settings_manager: SettingsManager) -> None:
        """Test that env operations preserve the settings version."""
        # Set a custom version
        settings = settings_manager.load()
        settings.version = "2.0.0"
        settings_manager.save(settings)

        # Perform env operation
        settings_manager.set_env("key", "value")

        # Verify version is preserved
        final_settings = settings_manager.load()
        assert final_settings.version == "2.0.0"

    def test_multiple_env_operations_in_sequence(self, settings_manager: SettingsManager) -> None:
        """Test multiple env operations performed in sequence."""
        # Set multiple keys
        settings_manager.set_env("key1", "value1")
        settings_manager.set_env("key2", "value2")
        settings_manager.set_env("key3", "value3")

        # Update one
        settings_manager.set_env("key2", "updated_value")

        # Remove one
        settings_manager.unset_env("key3")

        # Verify final state
        env_vars = settings_manager.list_env(mask_values=False)
        assert env_vars == {"key1": "value1", "key2": "updated_value"}


class TestEnvEdgeCases:
    """Test edge cases for environment variable management."""

    def test_env_with_special_characters_in_value(self, settings_manager: SettingsManager) -> None:
        """Test that values with special characters are preserved."""
        special_value = "abc!@#$%^&*(){}[]|\\:;\"'<>,.?/~`"
        settings_manager.set_env("special_key", special_value)

        value = settings_manager.get_env("special_key")
        assert value == special_value

    def test_env_with_unicode_in_value(self, settings_manager: SettingsManager) -> None:
        """Test that unicode characters in values are preserved."""
        unicode_value = "你好世界🌍"
        settings_manager.set_env("unicode_key", unicode_value)

        value = settings_manager.get_env("unicode_key")
        assert value == unicode_value

    def test_env_with_whitespace_in_key(self, settings_manager: SettingsManager) -> None:
        """Test that keys with whitespace are handled."""
        # Note: This should work - validation happens at CLI/workflow level
        settings_manager.set_env("key with spaces", "value")

        value = settings_manager.get_env("key with spaces")
        assert value == "value"

    def test_env_with_empty_string_value(self, settings_manager: SettingsManager) -> None:
        """Test that empty string values are preserved."""
        settings_manager.set_env("empty_key", "")

        value = settings_manager.get_env("empty_key")
        assert value == ""
        assert "empty_key" in settings_manager.list_env(mask_values=False)

    def test_env_with_very_long_value(self, settings_manager: SettingsManager) -> None:
        """Test that very long values are handled correctly."""
        long_value = "x" * 10000
        settings_manager.set_env("long_key", long_value)

        value = settings_manager.get_env("long_key")
        assert value == long_value
        assert len(value) == 10000

    def test_env_key_case_sensitive(self, settings_manager: SettingsManager) -> None:
        """Test that environment variable keys are case-sensitive."""
        settings_manager.set_env("ApiKey", "value1")
        settings_manager.set_env("apikey", "value2")
        settings_manager.set_env("APIKEY", "value3")

        # All three should exist as separate keys
        env_vars = settings_manager.list_env(mask_values=False)
        assert len(env_vars) == 3
        assert env_vars["ApiKey"] == "value1"
        assert env_vars["apikey"] == "value2"
        assert env_vars["APIKEY"] == "value3"


class TestAtomicOperations:
    """Test atomic file operations for save()."""

    def test_atomic_save_no_partial_writes(
        self, settings_manager: SettingsManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that save is atomic - failure doesn't corrupt existing file."""
        # Create initial valid settings
        settings_manager.set_env("key1", "value1")

        # Simulate a JSON serialization failure by mocking json.dump
        original_dump = json.dump

        def failing_dump(*args: object, **kwargs: object) -> None:
            raise ValueError("Simulated serialization failure")

        monkeypatch.setattr(json, "dump", failing_dump)

        settings = settings_manager.load()
        settings.env["key2"] = "value2"

        # Attempt to save should fail
        with pytest.raises(ValueError, match="Simulated serialization failure"):
            settings_manager.save(settings)

        # Restore json.dump
        monkeypatch.setattr(json, "dump", original_dump)

        # Reload from disk (clear cache) - should show original file unchanged
        loaded = settings_manager.reload()
        assert loaded.env["key1"] == "value1"
        assert "key2" not in loaded.env

    def test_atomic_save_cleanup_on_failure(
        self, settings_manager: SettingsManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that temp files are cleaned up on save failure."""
        settings_manager.set_env("key1", "value1")

        # Force a save failure by making os.replace fail
        original_replace = os.replace

        def failing_replace(*args: object, **kwargs: object) -> None:
            raise OSError("Simulated file system error")

        monkeypatch.setattr(os, "replace", failing_replace)

        settings = settings_manager.load()
        settings.env["key2"] = "value2"

        with pytest.raises(OSError, match="Simulated file system error"):
            settings_manager.save(settings)

        # Restore os.replace
        monkeypatch.setattr(os, "replace", original_replace)

        # Check for leftover temp files
        parent_dir = settings_manager.settings_path.parent
        temp_files = list(parent_dir.glob(".settings.*.tmp"))
        assert len(temp_files) == 0, "Temp files should be cleaned up"

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """Test that save creates parent directory if missing."""
        nested_path = tmp_path / "deep" / "nested" / ".pflow" / "settings.json"
        manager = SettingsManager(nested_path)

        assert not nested_path.parent.exists()

        manager.set_env("key", "value")

        assert nested_path.exists()
        assert nested_path.parent.exists()


class TestFilePermissions:
    """Test file permission handling."""

    def test_file_permissions_after_save(self, settings_manager: SettingsManager) -> None:
        """Test that settings file has 0o600 permissions after save."""
        settings_manager.set_env("api_key", "secret")

        # Check file permissions
        file_stat = settings_manager.settings_path.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)

        # Should be 0o600 (owner read/write only)
        expected_mode = stat.S_IRUSR | stat.S_IWUSR
        assert file_mode == expected_mode, f"Expected {oct(expected_mode)}, got {oct(file_mode)}"

    def test_file_permissions_after_env_update(self, settings_manager: SettingsManager) -> None:
        """Test that permissions are maintained after env updates."""
        settings_manager.set_env("key1", "value1")

        # Update multiple times
        settings_manager.set_env("key2", "value2")
        settings_manager.set_env("key1", "updated")
        settings_manager.unset_env("key2")

        # Permissions should still be 0o600
        file_stat = settings_manager.settings_path.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        expected_mode = stat.S_IRUSR | stat.S_IWUSR

        assert file_mode == expected_mode, f"Expected {oct(expected_mode)}, got {oct(file_mode)}"

    def test_permissions_on_new_file(self, settings_manager: SettingsManager) -> None:
        """Test that new files are created with correct permissions."""
        assert not settings_manager.settings_path.exists()

        settings_manager.set_env("first_key", "first_value")

        # First save should set correct permissions
        file_stat = settings_manager.settings_path.stat()
        file_mode = stat.S_IMODE(file_stat.st_mode)
        expected_mode = stat.S_IRUSR | stat.S_IWUSR

        assert file_mode == expected_mode


class TestPermissionValidation:
    """Test permission validation (defense-in-depth)."""

    def test_validate_permissions_warns_on_insecure(
        self, settings_manager: SettingsManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that validation warns when file has insecure permissions with secrets."""
        import logging

        # Create file with API key
        settings_manager.set_env("api_key", "secret")

        # Manually change permissions to insecure (simulate user error)
        os.chmod(settings_manager.settings_path, 0o644)

        # Validation should warn
        with caplog.at_level(logging.WARNING):
            settings_manager._validate_permissions()

        # Should have warning about insecure permissions
        assert any("insecure permissions" in record.message.lower() for record in caplog.records)
        assert any("0o644" in record.message for record in caplog.records)

    def test_validate_permissions_ok_on_secure(
        self, settings_manager: SettingsManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that validation doesn't warn when permissions are secure."""
        import logging

        # Create file with API key (should be 0o600 from Phase 1b)
        settings_manager.set_env("api_key", "secret")

        # Validation should not warn
        with caplog.at_level(logging.WARNING):
            settings_manager._validate_permissions()

        # Should have no warnings
        assert not any("insecure permissions" in record.message.lower() for record in caplog.records)

    def test_validate_permissions_skips_if_no_env(
        self, settings_manager: SettingsManager, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that validation skips warning if no env variables set."""
        import logging

        # Create empty settings
        settings = settings_manager.load()
        settings_manager.save(settings)

        # Manually make insecure
        os.chmod(settings_manager.settings_path, 0o644)

        # Validation should not warn (no secrets to protect)
        with caplog.at_level(logging.WARNING):
            settings_manager._validate_permissions()

        # Should have no warnings
        assert not any("insecure permissions" in record.message.lower() for record in caplog.records)

    def test_validate_permissions_handles_missing_file(self, settings_manager: SettingsManager) -> None:
        """Test that validation handles missing file gracefully."""
        # File doesn't exist yet
        assert not settings_manager.settings_path.exists()

        # Should not raise exception
        settings_manager._validate_permissions()


class TestConcurrentAccess:
    """Test concurrent access to settings."""

    def test_concurrent_env_updates_different_keys(self, settings_manager: SettingsManager) -> None:
        """Test concurrent updates to different keys."""
        results = {"errors": [], "successes": []}
        lock = threading.Lock()

        def update_env(key: str, value: str) -> None:
            try:
                settings_manager.set_env(key, value)
                with lock:
                    results["successes"].append(key)
            except Exception as e:
                with lock:
                    results["errors"].append(e)

        # Start 5 threads updating different keys
        threads = []
        for i in range(5):
            t = threading.Thread(target=update_env, args=(f"key_{i}", f"value_{i}"))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All operations should succeed
        assert len(results["successes"]) == 5, f"Expected 5 successes, got {len(results['successes'])}"
        assert len(results["errors"]) == 0, f"Unexpected errors: {results['errors']}"

        # Verify all keys present
        final_env = settings_manager.list_env(mask_values=False)
        assert len(final_env) == 5
        for i in range(5):
            assert final_env[f"key_{i}"] == f"value_{i}"

    def test_concurrent_same_key_updates(self, settings_manager: SettingsManager) -> None:
        """Test concurrent updates to the same key (last write wins)."""
        results = {"errors": [], "successes": []}
        lock = threading.Lock()

        def update_same_key(value: str) -> None:
            try:
                settings_manager.set_env("shared_key", value)
                with lock:
                    results["successes"].append(value)
            except Exception as e:
                with lock:
                    results["errors"].append(e)

        # Start 5 threads updating the same key
        threads = []
        values = [f"value_{i}" for i in range(5)]
        for value in values:
            t = threading.Thread(target=update_same_key, args=(value,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All writes should succeed (atomic operations)
        assert len(results["successes"]) == 5
        assert len(results["errors"]) == 0

        # Final value should be one of the written values (last write wins)
        final_value = settings_manager.get_env("shared_key")
        assert final_value in values

    def test_concurrent_read_write(self, settings_manager: SettingsManager) -> None:
        """Test concurrent reads and writes."""
        settings_manager.set_env("test_key", "initial")

        results = {"reads": [], "writes": [], "errors": []}
        lock = threading.Lock()

        def read_env() -> None:
            try:
                for _ in range(10):
                    value = settings_manager.get_env("test_key")
                    with lock:
                        results["reads"].append(value)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    results["errors"].append(e)

        def write_env(value: str) -> None:
            try:
                for _ in range(10):
                    settings_manager.set_env("test_key", value)
                    with lock:
                        results["writes"].append(value)
                    time.sleep(0.001)
            except Exception as e:
                with lock:
                    results["errors"].append(e)

        # Start 2 readers and 2 writers
        threads = []
        threads.append(threading.Thread(target=read_env))
        threads.append(threading.Thread(target=read_env))
        threads.append(threading.Thread(target=write_env, args=("writer1",)))
        threads.append(threading.Thread(target=write_env, args=("writer2",)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should occur
        assert len(results["errors"]) == 0

        # All reads should return valid values (never corrupted)
        for read_value in results["reads"]:
            assert read_value in ["initial", "writer1", "writer2"]

        # All writes should succeed
        assert len(results["writes"]) == 20
