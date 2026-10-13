"""Tests for settings management."""

import contextlib
import json
import logging
import os
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from pflow.core.settings import PflowSettings, RegistrySettings, SettingsManager

# POSIX permission bits are advisory-only on Windows (chmod is a near-no-op
# and st_mode always reports group/other read), so tests asserting exact
# mode bits or chmod-induced behavior are skipped there. The production
# counterpart: SettingsManager._validate_permissions early-returns on win32
# (pinned by test_validate_permissions_noop_on_windows below).
skip_win32_posix_perms = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits are advisory no-ops on Windows",
)


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

        assert env_vars == {"short": "*** (2 chars)", "medium": "*** (5 chars)", "long_key": "*** (12 chars)"}

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


class TestLLMDefaults:
    """Defaults for the TTS narration settings (Task 174)."""

    def test_tts_defaults(self) -> None:
        settings = PflowSettings()
        assert settings.llm.tts_model == "gemini-3.1-flash-tts-preview"
        assert settings.llm.tts_voice == "Kore"


class TestMaskValue:
    """``_mask_value`` shows a value's length only — never a prefix, which narrows a guess (#801 F26)."""

    def test_masks_to_the_length_whatever_the_value(self) -> None:
        assert SettingsManager._mask_value("") == "*** (0 chars)"
        assert SettingsManager._mask_value("ab") == "*** (2 chars)"
        assert SettingsManager._mask_value("r8_abc123xyz") == "*** (12 chars)"
        assert SettingsManager._mask_value("emoji🎉test") == "*** (10 chars)"


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


@skip_win32_posix_perms
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

    @skip_win32_posix_perms
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

    @skip_win32_posix_perms
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

    def test_validate_permissions_noop_on_windows(
        self, settings_manager: SettingsManager, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On win32 the check must not warn at all (Task 116 product fix).

        Windows st_mode always reports group/other read on regular files, so
        without the early return every Windows user with secrets would get a
        spurious "insecure permissions ... run chmod 600" warning on every
        load — and chmod 600 does nothing there.
        """
        import logging

        settings_manager.set_env("api_key", "secret")
        # World-readable + secrets: the exact condition that warns on POSIX
        os.chmod(settings_manager.settings_path, 0o644)

        monkeypatch.setattr(sys, "platform", "win32")
        with caplog.at_level(logging.WARNING):
            settings_manager._validate_permissions()

        assert not any("insecure permissions" in record.message.lower() for record in caplog.records)


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


class TestRetentionSettingAndFailedLoads:
    """Task 185: the retention window field, unknown keys kept through a save, and no save after a failed
    load (defaults written back would wipe the user's file — API keys included)."""

    def test_unknown_keys_survive_a_save(self, settings_manager: SettingsManager) -> None:
        settings_manager.settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_manager.settings_path.write_text(
            json.dumps({"from_a_newer_pflow": {"x": 1}, "runtime": {"future_key": "y"}, "env": {"K": "v"}}),
            encoding="utf-8",
        )

        settings_manager.set_env("OTHER", "w")

        saved = json.loads(settings_manager.settings_path.read_text(encoding="utf-8"))
        assert saved["from_a_newer_pflow"] == {"x": 1}
        assert saved["runtime"]["future_key"] == "y"
        assert saved["runtime"]["trace_retention_days"] == 14
        assert saved["env"] == {"K": "v", "OTHER": "w"}

    @pytest.mark.parametrize(
        "content",
        ['{"runtime": {"template_resolution_mode": "bogus"}, "env": {"API_KEY": "sk-1"}}', "{not json"],
        ids=["fails-validation", "not-json"],
    )
    def test_a_file_that_failed_to_load_is_never_overwritten(
        self, settings_manager: SettingsManager, content: str
    ) -> None:
        from pflow.core.user_errors import UserFriendlyError

        settings_manager.settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_manager.settings_path.write_text(content, encoding="utf-8")
        original = settings_manager.settings_path.read_bytes()

        assert settings_manager.load().env == {}  # defaults are in use...
        assert settings_manager.load_error is not None
        with pytest.raises(UserFriendlyError, match="could not be loaded"):
            settings_manager.set_env("NEW", "x")  # ...so a write would erase the file
        with pytest.raises(UserFriendlyError):
            settings_manager.save()

        assert settings_manager.settings_path.read_bytes() == original

    def test_a_fixed_file_loads_and_saves_again(self, settings_manager: SettingsManager) -> None:
        settings_manager.settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_manager.settings_path.write_text("{not json", encoding="utf-8")
        settings_manager.load()
        assert settings_manager.load_error is not None

        settings_manager.settings_path.write_text('{"env": {"K": "v"}}', encoding="utf-8")
        settings_manager.reload()
        settings_manager.set_env("OTHER", "w")

        assert settings_manager.load_error is None
        assert json.loads(settings_manager.settings_path.read_text(encoding="utf-8"))["env"] == {"K": "v", "OTHER": "w"}

    def test_the_cli_refuses_the_write_and_reset_still_recovers(self, tmp_path: Path) -> None:
        """The real surface: a settings command after a failed load exits 1 naming the file; `reset`
        (a fresh manager that never loaded) replaces it."""
        from click.testing import CliRunner

        from pflow.cli.main import cli

        path = tmp_path / ".pflow" / "settings.json"  # conftest points the default manager here
        path.write_text('{"runtime": {"trace_retention_days": -3}, "env": {"API_KEY": "sk-1"}}', encoding="utf-8")
        original = path.read_bytes()

        refused = CliRunner().invoke(cli, ["settings", "set-env", "NEW", "x"])
        assert refused.exit_code == 1
        assert "Settings file not saved" in refused.output and str(path) in refused.output
        assert path.read_bytes() == original

        reset = CliRunner().invoke(cli, ["settings", "reset"], input="y\n")
        assert reset.exit_code == 0, reset.output
        assert json.loads(path.read_text(encoding="utf-8"))["runtime"]["trace_retention_days"] == 14


@skip_win32_posix_perms
def test_two_managers_racing_warn_about_insecure_permissions_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Concurrent MCP requests build separate managers: their check-and-add on the shared warned-set must be
    one step. Each thread's membership answer waits (bounded) for the other thread's check — two threads
    answered before either adds both read "not yet warned"."""
    import pflow.core.settings as settings_module

    path = tmp_path / ".pflow" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"env": {"K": "v"}}), encoding="utf-8")
    path.chmod(0o644)
    both_checking = threading.Barrier(2, timeout=0.5)

    class RendezvousSet(set):  # type: ignore[type-arg]  # a plain set whose membership check meets the other thread
        def __contains__(self, item: object) -> bool:
            seen = super().__contains__(item)
            with contextlib.suppress(threading.BrokenBarrierError):
                both_checking.wait()  # the other thread checks before this one acts on its answer
            return seen

    monkeypatch.setattr(settings_module, "_WARNED", RendezvousSet())
    with caplog.at_level(logging.WARNING, logger="pflow.core.settings"):
        threads = [threading.Thread(target=SettingsManager(settings_path=path).load) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert sum("insecure permissions" in record.getMessage() for record in caplog.records) == 1
