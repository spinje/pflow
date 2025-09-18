"""
FIXED: Tests for MCP configuration management that actually test the real mechanisms.

Focus: Real atomic write testing, actual concurrent access, security validation.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.mcp import MCPServerManager


class TestAtomicWriteProtection:
    """Test that atomic writes ACTUALLY prevent corruption."""

    def test_atomic_write_mechanism_prevents_corruption(self):
        """Test the REAL atomic write mechanism (temp file + rename).

        Real Bug: If the atomic rename fails, the original config must remain intact.
        This tests the actual implementation, not mocked behavior.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            manager = MCPServerManager(config_path=config_path)

            # Add initial config
            manager.add_server("github", "stdio", "npx", ["@modelcontextprotocol/server-github"])

            # Read the original content
            original_content = config_path.read_text()
            original_data = json.loads(original_content)

            # Simulate atomic rename failure (the critical moment)
            with (
                patch("pathlib.Path.replace", side_effect=OSError("Disk full")),
                pytest.raises(OSError),
            ):  # Should propagate the error
                manager.add_server("slack", "stdio", "npx", ["@modelcontextprotocol/server-slack"])

            # CRITICAL: Original file must be untouched
            assert config_path.exists()
            assert config_path.read_text() == original_content

            # Verify content is still valid
            current_data = json.loads(config_path.read_text())
            assert current_data == original_data
            assert "github" in current_data["servers"]
            assert "slack" not in current_data["servers"]

            # Verify no temp files left behind (cleanup happened)
            temp_files = list(Path(tmpdir).glob(".mcp-servers-*.tmp"))
            assert len(temp_files) == 0, f"Temp files not cleaned: {temp_files}"

    def test_partial_write_doesnt_corrupt(self):
        """Test that partial writes to temp file don't affect original.

        Real Bug: If process crashes during temp file write, original must be safe.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            manager = MCPServerManager(config_path=config_path)

            # Add initial config
            manager.add_server("test1", "stdio", "cmd1", ["arg1"])
            original_mtime = config_path.stat().st_mtime

            # Simulate crash during temp file write
            original_mkstemp = tempfile.mkstemp

            def failing_mkstemp(*args, **kwargs):
                # Create temp file but simulate crash before writing completes
                fd, path = original_mkstemp(*args, **kwargs)
                os.write(fd, b'{"partial":')  # Incomplete JSON
                raise OSError("Process crashed during write")

            with patch("tempfile.mkstemp", side_effect=failing_mkstemp), pytest.raises(OSError):
                manager.add_server("test2", "stdio", "cmd2")

            # Original file must be unchanged
            assert config_path.stat().st_mtime == original_mtime
            config = manager.load()
            assert "test1" in config["servers"]
            assert "test2" not in config["servers"]


class TestConcurrentAccess:
    """Test REAL concurrent access scenarios."""

    def test_concurrent_writes_maintain_file_integrity(self):
        """Test that concurrent writes from multiple threads don't corrupt file.

        Real Bug: Multiple `pflow mcp add` commands running simultaneously
        could corrupt the config file. Last-write-wins is acceptable, but
        the file must always be valid JSON.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            results = []
            errors = []

            def add_server_concurrent(name: str, delay: float = 0):
                """Add server with random delay to create race conditions."""
                try:
                    time.sleep(delay)  # Create timing variations
                    manager = MCPServerManager(config_path=config_path)
                    manager.add_server(
                        name, "stdio", f"cmd_{name}", [f"arg_{name}"], env={f"KEY_{name}": f"value_{name}"}
                    )
                    results.append(name)
                except Exception as e:
                    errors.append((name, str(e)))

            # Start multiple threads simultaneously
            threads = []
            servers = [
                "github",
                "slack",
                "docker",
                "postgres",
                "redis",
                "nginx",
                "mysql",
                "mongodb",
                "rabbitmq",
                "kafka",
            ]

            for i, server in enumerate(servers):
                # Vary timing to create race conditions
                delay = 0.001 * (i % 3)  # 0, 0.001, or 0.002 seconds
                t = threading.Thread(target=add_server_concurrent, args=(server, delay))
                threads.append(t)

            # Start all threads at once
            for t in threads:
                t.start()

            # Wait for completion
            for t in threads:
                t.join(timeout=5)

            # Verify results
            assert len(errors) == 0, f"Unexpected errors: {errors}"

            # CRITICAL: File must be valid JSON
            with open(config_path) as f:
                final_config = json.load(f)  # Should not raise

            # Should have servers (last-write-wins means some may be overwritten)
            assert "servers" in final_config
            assert len(final_config["servers"]) > 0

            # At minimum one server should exist
            assert len(final_config["servers"]) >= 1

            # Verify structure is intact
            for _server_name, server_config in final_config["servers"].items():
                assert "command" in server_config
                assert "args" in server_config
                assert isinstance(server_config["args"], list)

    def test_read_during_write_doesnt_crash(self):
        """Test that reading config during write doesn't get partial data.

        Real Bug: Reading while another process is writing could return
        partial/corrupted data due to non-atomic writes.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"

            # Initialize with some data
            manager = MCPServerManager(config_path=config_path)
            manager.add_server("initial", "stdio", "cmd", [])

            read_errors = []

            def reader_thread():
                """Continuously read config file."""
                for _ in range(50):
                    try:
                        manager = MCPServerManager(config_path=config_path)
                        config = manager.load()
                        # Should always be valid
                        assert "servers" in config
                        time.sleep(0.001)
                    except Exception as e:
                        read_errors.append(str(e))

            def writer_thread():
                """Continuously write to config file."""
                for i in range(10):
                    manager = MCPServerManager(config_path=config_path)
                    manager.add_server(f"server_{i}", "stdio", f"cmd_{i}", [])
                    time.sleep(0.005)

            # Start reader and writer simultaneously
            reader = threading.Thread(target=reader_thread)
            writer = threading.Thread(target=writer_thread)

            reader.start()
            writer.start()

            reader.join(timeout=5)
            writer.join(timeout=5)

            # Should have no read errors (atomic writes prevent partial reads)
            assert len(read_errors) == 0, f"Read errors during concurrent access: {read_errors}"


class TestSecurityValidation:
    """Test security vulnerabilities that could be exploited."""

    def test_path_traversal_in_server_names_blocked(self):
        """Prevent directory traversal attacks in server names.

        Real Security Bug: Names like "../../../etc/passwd" could be used
        to write files outside the intended directory or cause parsing issues.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            manager = MCPServerManager(config_path=config_path)

            dangerous_names = [
                "../../../etc/passwd",
                "..\\..\\windows\\system32",
                "../../admin",
                "../parent",
                "..",
                ".",
                "/absolute/path",
                "\\windows\\path",
                "server/../etc",
                "server/../../root",
            ]

            for dangerous_name in dangerous_names:
                with pytest.raises(ValueError, match="Invalid server name"):
                    manager.add_server(dangerous_name, "stdio", "cmd", [])

    def test_command_injection_in_env_vars_safe(self):
        """Ensure environment variable templates can't execute commands.

        Real Security Bug: Malicious env var patterns could execute commands
        when expanded if not properly sanitized.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            manager = MCPServerManager(config_path=config_path)

            # These patterns should be stored safely without execution
            dangerous_patterns = [
                "${VAR;rm -rf /}",
                "${VAR && echo hacked}",
                "${VAR`whoami`}",
                "${VAR|tee /etc/passwd}",
                "$({NESTED})",
                "${${DOUBLE_EXPAND}}",
                "$(command substitution)",
                "`backtick execution`",
            ]

            # Should store these as literal strings, not execute
            for i, pattern in enumerate(dangerous_patterns):
                manager.add_server(f"test{i}", "stdio", "safe_cmd", [], env={"POTENTIALLY_DANGEROUS": pattern})

            # Verify they're stored as-is (not executed or modified)
            config = manager.load()
            for i, pattern in enumerate(dangerous_patterns):
                stored_value = config["servers"][f"test{i}"]["env"]["POTENTIALLY_DANGEROUS"]
                assert stored_value == pattern, f"Pattern was modified: {pattern} -> {stored_value}"

            # The patterns should be stored as literal strings
            # If they were executed, we'd see different content
            # For example, ${VAR`whoami`} would become the actual username
            raw_content = config_path.read_text()

            # These dangerous patterns should exist as literal strings
            assert "${VAR && echo hacked}" in raw_content  # Not executed
            assert "$(command substitution)" in raw_content  # Stored literally

            # But actual command outputs should NOT exist
            # (These would only appear if commands were executed)
            import getpass

            current_user = getpass.getuser()
            assert (
                current_user not in raw_content or "`whoami`" in raw_content
            )  # Username only from pattern, not execution

    def test_special_chars_in_server_names_handled(self):
        """Test that special characters in names don't break parsing.

        Real Bug: Node type parsing expects "mcp-server-tool" format.
        Special chars could break this parsing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "mcp-servers.json"
            manager = MCPServerManager(config_path=config_path)

            # These should be rejected to prevent downstream parsing issues
            invalid_names = [
                "server:with:colons",  # Could break parsing
                "server|with|pipes",
                "server;semicolon",
                "server&ampersand",
                "server$dollar",
                "server with spaces",
                "server\twith\ttabs",
                "server\nwith\nnewlines",
                "",  # Empty name
                " ",  # Just whitespace
            ]

            for name in invalid_names:
                with pytest.raises(ValueError):
                    manager.add_server(name, "stdio", "cmd", [])
