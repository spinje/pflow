"""Tests for ExecutionCache class."""

import json
import time
from pathlib import Path

import pytest

from pflow.core.execution_cache import ExecutionCache


@pytest.fixture
def temp_cache_dir(monkeypatch, tmp_path):
    """Create temporary cache directory for testing."""
    cache_dir = tmp_path / ".pflow" / "cache" / "registry-run"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Mock Path.home() to use temp directory
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    return cache_dir


@pytest.fixture
def cache(temp_cache_dir):
    """Create ExecutionCache instance with temp directory."""
    return ExecutionCache()


class TestGenerateExecutionId:
    """Test execution ID generation."""

    def test_ids_are_unique(self):
        """Test consecutive IDs are unique."""
        id1 = ExecutionCache.generate_execution_id()
        id2 = ExecutionCache.generate_execution_id()
        id3 = ExecutionCache.generate_execution_id()

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3


class TestStore:
    """Test cache storage."""

    def test_store_saves_correct_structure(self, cache, temp_cache_dir):
        """Test cache file has correct JSON structure."""
        execution_id = "exec-1234567890-abcd1234"
        node_type = "test-node"
        params = {"param1": "value1", "param2": 42}
        outputs = {"result": ["item1", "item2"], "count": 2}

        cache.store(execution_id, node_type, params, outputs)

        cache_file = temp_cache_dir / f"{execution_id}.json"
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)

        assert data["execution_id"] == execution_id
        assert data["node_type"] == node_type
        assert data["params"] == params
        assert data["outputs"] == outputs
        assert "timestamp" in data
        assert data["ttl_hours"] == 24

    def test_store_with_binary_data(self, cache, temp_cache_dir):
        """Test binary data is encoded to base64."""
        execution_id = "exec-1234567890-abcd1234"
        binary_data = b"\x00\x01\x02\xff"
        outputs = {"binary_field": binary_data}

        cache.store(execution_id, "test-node", {}, outputs)

        cache_file = temp_cache_dir / f"{execution_id}.json"
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)

        # Binary should be encoded
        assert data["outputs"]["binary_field"]["__type"] == "base64"
        assert "data" in data["outputs"]["binary_field"]
        assert isinstance(data["outputs"]["binary_field"]["data"], str)

    def test_store_with_nested_binary(self, cache, temp_cache_dir):
        """Test nested binary data is encoded."""
        execution_id = "exec-1234567890-abcd1234"
        outputs = {
            "items": [
                {"name": "file1", "content": b"binary1"},
                {"name": "file2", "content": b"binary2"},
            ],
            "metadata": {"preview": b"preview_data"},
        }

        cache.store(execution_id, "test-node", {}, outputs)

        cache_file = temp_cache_dir / f"{execution_id}.json"
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)

        # Check nested binary encoding
        assert data["outputs"]["items"][0]["content"]["__type"] == "base64"
        assert data["outputs"]["items"][1]["content"]["__type"] == "base64"
        assert data["outputs"]["metadata"]["preview"]["__type"] == "base64"


class TestRetrieve:
    """Test cache retrieval."""

    def test_retrieve_nonexistent_returns_none(self, cache):
        """Test retrieve() returns None for nonexistent execution."""
        result = cache.retrieve("exec-9999999999-nonexist")
        assert result is None

    def test_retrieve_returns_stored_data(self, cache):
        """Test retrieve() returns correct data."""
        execution_id = "exec-1234567890-abcd1234"
        node_type = "test-node"
        params = {"param1": "value1"}
        outputs = {"result": "test result"}

        cache.store(execution_id, node_type, params, outputs)
        result = cache.retrieve(execution_id)

        assert result is not None
        assert result["execution_id"] == execution_id
        assert result["node_type"] == node_type
        assert result["params"] == params
        assert result["outputs"] == outputs

    def test_retrieve_decodes_binary(self, cache):
        """Test binary data is decoded from base64."""
        execution_id = "exec-1234567890-abcd1234"
        binary_data = b"\x00\x01\x02\xff"
        outputs = {"binary_field": binary_data}

        cache.store(execution_id, "test-node", {}, outputs)
        result = cache.retrieve(execution_id)

        # Binary should be decoded
        assert result["outputs"]["binary_field"] == binary_data
        assert isinstance(result["outputs"]["binary_field"], bytes)

    def test_retrieve_decodes_nested_binary(self, cache):
        """Test nested binary data is decoded."""
        execution_id = "exec-1234567890-abcd1234"
        binary1 = b"binary content 1"
        binary2 = b"binary content 2"
        preview = b"preview data"

        outputs = {
            "items": [
                {"name": "file1", "content": binary1},
                {"name": "file2", "content": binary2},
            ],
            "metadata": {"preview": preview},
        }

        cache.store(execution_id, "test-node", {}, outputs)
        result = cache.retrieve(execution_id)

        # Check nested binary decoding
        assert result["outputs"]["items"][0]["content"] == binary1
        assert result["outputs"]["items"][1]["content"] == binary2
        assert result["outputs"]["metadata"]["preview"] == preview


class TestListCachedExecutions:
    """Test listing cached executions."""

    def test_list_empty_cache(self, cache):
        """Test listing empty cache returns empty list."""
        result = cache.list_cached_executions()
        assert result == []

    def test_list_single_execution(self, cache):
        """Test listing single cached execution."""
        execution_id = "exec-1234567890-abcd1234"
        node_type = "test-node"

        cache.store(execution_id, node_type, {}, {})
        result = cache.list_cached_executions()

        assert len(result) == 1
        assert result[0]["execution_id"] == execution_id
        assert result[0]["node_type"] == node_type
        assert "timestamp" in result[0]

    def test_list_multiple_executions_sorted(self, cache):
        """Test listing returns executions sorted by timestamp (newest first)."""
        # Store with slight time delays
        exec1 = cache.generate_execution_id()
        cache.store(exec1, "node1", {}, {})

        time.sleep(0.01)  # Small delay

        exec2 = cache.generate_execution_id()
        cache.store(exec2, "node2", {}, {})

        result = cache.list_cached_executions()

        assert len(result) == 2
        # Newest first
        assert result[0]["execution_id"] == exec2
        assert result[1]["execution_id"] == exec1

    def test_list_skips_malformed_files(self, cache, temp_cache_dir):
        """Test listing skips malformed cache files."""
        # Create valid execution
        valid_id = "exec-1234567890-valid123"
        cache.store(valid_id, "node1", {}, {})

        # Create malformed cache file
        malformed_file = temp_cache_dir / "exec-9999999999-badfile.json"
        with open(malformed_file, "w") as f:
            f.write("{invalid json")

        # Create file with missing keys
        incomplete_file = temp_cache_dir / "exec-8888888888-incomplete.json"
        with open(incomplete_file, "w") as f:
            json.dump({"execution_id": "exec-8888888888-incomplete"}, f)  # Missing node_type

        result = cache.list_cached_executions()

        # Should only return valid execution
        assert len(result) == 1
        assert result[0]["execution_id"] == valid_id


class TestBinaryEncoding:
    """Test binary data encoding/decoding helpers."""

    def test_encode_simple_bytes(self, cache):
        """Test encoding simple bytes object."""
        data = b"test binary"
        encoded = cache._encode_binary(data)

        assert encoded["__type"] == "base64"
        assert isinstance(encoded["data"], str)

    def test_encode_dict_with_bytes(self, cache):
        """Test encoding dict containing bytes."""
        data = {"text": "normal", "binary": b"binary data"}
        encoded = cache._encode_binary(data)

        assert encoded["text"] == "normal"
        assert encoded["binary"]["__type"] == "base64"

    def test_encode_list_with_bytes(self, cache):
        """Test encoding list containing bytes."""
        data = ["text", b"binary1", b"binary2"]
        encoded = cache._encode_binary(data)

        assert encoded[0] == "text"
        assert encoded[1]["__type"] == "base64"
        assert encoded[2]["__type"] == "base64"

    def test_decode_base64_marker(self, cache):
        """Test decoding base64 marker dict."""
        import base64

        original = b"test data"
        encoded = {"__type": "base64", "data": base64.b64encode(original).decode("ascii")}

        decoded = cache._decode_binary(encoded)

        assert decoded == original
        assert isinstance(decoded, bytes)

    def test_decode_dict_with_base64(self, cache):
        """Test decoding dict with base64-encoded values."""
        import base64

        data = {
            "text": "normal",
            "binary": {"__type": "base64", "data": base64.b64encode(b"binary").decode("ascii")},
        }

        decoded = cache._decode_binary(data)

        assert decoded["text"] == "normal"
        assert decoded["binary"] == b"binary"

    def test_decode_list_with_base64(self, cache):
        """Test decoding list with base64-encoded values."""
        import base64

        data = [
            "text",
            {"__type": "base64", "data": base64.b64encode(b"binary1").decode("ascii")},
            {"__type": "base64", "data": base64.b64encode(b"binary2").decode("ascii")},
        ]

        decoded = cache._decode_binary(data)

        assert decoded[0] == "text"
        assert decoded[1] == b"binary1"
        assert decoded[2] == b"binary2"

    def test_roundtrip_encoding(self, cache):
        """Test encode then decode returns original data."""
        original = {
            "text": "hello",
            "number": 42,
            "binary": b"\x00\x01\x02\xff",
            "nested": {"more_binary": b"nested data", "text": "nested text"},
            "list": [b"item1", "item2", b"item3"],
        }

        encoded = cache._encode_binary(original)
        decoded = cache._decode_binary(encoded)

        assert decoded == original


class TestSensitiveParameterMasking:
    """Test sensitive parameter masking in cache storage."""

    def test_store_masks_sensitive_parameters(self, tmp_path):
        """Test that sensitive parameters are masked in cache files."""
        cache = ExecutionCache()
        cache.cache_dir = tmp_path

        # Sensitive parameters that should be masked
        sensitive_params = {
            "api_key": "sk-secret-key-12345",
            "password": "my-password",
            "token": "ghp_token123",
            "auth_token": "bearer-token-abc",
            "secret": "super-secret-value",
            "normal_param": "visible-value",
            "count": 42,
        }

        # Store with sensitive params
        execution_id = cache.generate_execution_id()
        cache.store(
            execution_id=execution_id,
            node_type="test-node",
            params=sensitive_params,
            outputs={"result": "success"},
        )

        # Read cache file directly
        cache_file = tmp_path / f"{execution_id}.json"
        with open(cache_file) as f:
            cache_data = json.load(f)

        # Verify sensitive values are masked
        assert cache_data["params"]["api_key"] == "<REDACTED>"
        assert cache_data["params"]["password"] == "<REDACTED>"  # noqa: S105
        assert cache_data["params"]["token"] == "<REDACTED>"  # noqa: S105
        assert cache_data["params"]["auth_token"] == "<REDACTED>"  # noqa: S105
        assert cache_data["params"]["secret"] == "<REDACTED>"  # noqa: S105

        # Verify normal values are not masked
        assert cache_data["params"]["normal_param"] == "visible-value"
        assert cache_data["params"]["count"] == 42

    def test_store_handles_none_params(self, tmp_path):
        """Test that store() handles None params gracefully."""
        cache = ExecutionCache()
        cache.cache_dir = tmp_path

        execution_id = cache.generate_execution_id()

        # Test with None
        cache.store(
            execution_id=execution_id,
            node_type="test-node",
            params=None,
            outputs={"result": "success"},
        )

        # Verify cache file exists and has empty params
        cache_file = tmp_path / f"{execution_id}.json"
        with open(cache_file) as f:
            cache_data = json.load(f)

        assert cache_data["params"] == {}

    def test_store_handles_empty_params(self, tmp_path):
        """Test that store() handles empty dict params gracefully."""
        cache = ExecutionCache()
        cache.cache_dir = tmp_path

        execution_id = cache.generate_execution_id()

        # Test with empty dict
        cache.store(
            execution_id=execution_id,
            node_type="test-node",
            params={},
            outputs={"result": "success"},
        )

        # Verify cache file exists and has empty params
        cache_file = tmp_path / f"{execution_id}.json"
        with open(cache_file) as f:
            cache_data = json.load(f)

        assert cache_data["params"] == {}

    def test_retrieve_returns_masked_params(self, tmp_path):
        """Test that retrieve() returns params as they were stored (masked)."""
        cache = ExecutionCache()
        cache.cache_dir = tmp_path

        # Store with sensitive param
        execution_id = cache.generate_execution_id()
        cache.store(
            execution_id=execution_id,
            node_type="test-node",
            params={"api_key": "sk-secret-12345", "username": "john"},
            outputs={"result": "success"},
        )

        # Retrieve cache
        retrieved = cache.retrieve(execution_id)

        # Should return masked value as stored
        assert retrieved["params"]["api_key"] == "<REDACTED>"
        assert retrieved["params"]["username"] == "john"

    def test_case_insensitive_masking(self, tmp_path):
        """Test that masking works case-insensitively."""
        cache = ExecutionCache()
        cache.cache_dir = tmp_path

        # Various case combinations
        params = {
            "API_KEY": "sk-uppercase",
            "Api_Key": "sk-mixedcase",
            "api_key": "sk-lowercase",
            "PASSWORD": "pwd-uppercase",
            "normal": "visible",
        }

        execution_id = cache.generate_execution_id()
        cache.store(
            execution_id=execution_id,
            node_type="test-node",
            params=params,
            outputs={"result": "success"},
        )

        # Read cache file directly
        cache_file = tmp_path / f"{execution_id}.json"
        with open(cache_file) as f:
            cache_data = json.load(f)

        # All variations should be masked
        assert cache_data["params"]["API_KEY"] == "<REDACTED>"
        assert cache_data["params"]["Api_Key"] == "<REDACTED>"
        assert cache_data["params"]["api_key"] == "<REDACTED>"
        assert cache_data["params"]["PASSWORD"] == "<REDACTED>"  # noqa: S105
        assert cache_data["params"]["normal"] == "visible"
