"""Minimal conftest for core tests that don't need the heavy fixtures."""

import pytest


@pytest.fixture(autouse=True, scope="function")
def isolate_pflow_config(tmp_path, monkeypatch):
    """Lightweight config isolation for core tests - no registry scanning needed."""
    # Just set the config path, don't scan nodes
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PFLOW_CONFIG_DIR", str(tmp_path / ".pflow"))


# Override the heavy mock_llm_calls with a no-op since core tests don't use LLMs
@pytest.fixture(autouse=True, scope="function")
def mock_llm_calls():
    """No-op override - core tests don't use LLMs."""
    pass
