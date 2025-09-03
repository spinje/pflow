"""Test HTTP node discovery and registration."""

import tempfile
from pathlib import Path

from src.pflow.registry.registry import Registry


def test_http_node_discovered():
    """Test that HTTP node is discovered by the registry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = Path(tmpdir) / "test_registry.json"
        registry = Registry(registry_path)

        # Load triggers auto-discovery for core nodes
        nodes = registry.load()

        # Check node is discovered
        assert "http" in nodes, "HTTP node not found in registry"

        # Check metadata was extracted
        http_metadata = nodes["http"]
        assert http_metadata is not None
        assert http_metadata["class_name"] == "HttpNode"
        assert http_metadata["module"] == "pflow.nodes.http.http"
        assert "docstring" in http_metadata
        assert "Make HTTP requests" in http_metadata["docstring"]

        # Check interface was extracted
        assert "interface" in http_metadata
        interface = http_metadata["interface"]
        assert "inputs" in interface
        assert "outputs" in interface
        assert "params" in interface

        # Verify critical interface elements
        inputs = interface["inputs"]
        assert any("url" in i["key"] for i in inputs), "URL not found in inputs"

        outputs = interface["outputs"]
        assert any("response" in o["key"] for o in outputs), "Response not found in outputs"
        assert any("status_code" in o["key"] for o in outputs), "Status code not found in outputs"

        params = interface["params"]
        assert any("auth_token" in p["key"] for p in params), "auth_token not found in params"
        assert any("api_key" in p["key"] for p in params), "api_key not found in params"
