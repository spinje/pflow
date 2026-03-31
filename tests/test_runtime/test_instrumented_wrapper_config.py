"""Tests for compute_node_config() and compute_config_hash() standalone functions.

These tests verify that the configuration hash used for workflow iteration cache
correctly captures all semantically relevant configuration (node type, static params,
template params, batch config) while excluding noise (e.g., _source_line metadata).

Migrated from wrapper-based tests to standalone function calls after the
wrappers were replaced by the engine (Task 135/138).
"""

from pflow.runtime.engine.instrumentation import compute_config_hash, compute_node_config
from pflow.runtime.engine.types import BatchConfig

# ===========================================================================
# Tests
# ===========================================================================


class TestComputeNodeConfig:
    """Tests for compute_node_config() output structure."""

    def test_template_params_included_in_config(self) -> None:
        """When template params exist, they should appear in the config
        under the 'template_params' key, separate from static params."""
        config = compute_node_config(
            node_type_name="DummyNode",
            static_params={"model": "gpt-4"},
            template_params={"prompt": "${input.text}"},
            batch_config=None,
        )

        assert "template_params" in config
        assert config["template_params"] == {"prompt": "${input.text}"}
        # Static params should be in the regular params
        assert config["params"].get("model") == "gpt-4"

    def test_batch_semantic_config_included(self) -> None:
        """Batch items_template, item_alias, error_handling, and max_retries
        should all appear under config['batch']."""
        batch = BatchConfig(
            items_template="${results.urls}",
            item_alias="url",
            error_handling="continue",
            max_retries=3,
        )

        config = compute_node_config(
            node_type_name="DummyNode",
            static_params={},
            template_params={},
            batch_config=batch,
        )

        assert "batch" in config
        assert config["batch"] == {
            "items_template": "${results.urls}",
            "item_alias": "url",
            "error_handling": "continue",
            "max_retries": 3,
        }

    def test_source_line_keys_excluded(self) -> None:
        """Params ending with '_source_line' (markdown parser noise) should be
        filtered from the config so they don't affect the hash."""
        config = compute_node_config(
            node_type_name="DummyNode",
            static_params={
                "command": "echo hello",
                "command_source_line": 42,
                "_source_line": 10,
                "file_path": "output.txt",
                "file_path_source_line": 43,
            },
            template_params={},
            batch_config=None,
        )

        param_keys = set(config["params"].keys())
        assert "command" in param_keys
        assert "file_path" in param_keys
        # All _source_line keys should be gone
        assert "command_source_line" not in param_keys
        assert "_source_line" not in param_keys
        assert "file_path_source_line" not in param_keys

    def test_batch_operational_config_excluded(self) -> None:
        """Operational batch settings (parallel, max_concurrent, retry_wait) must
        NOT appear in the config because they don't affect node output."""
        batch = BatchConfig(
            items_template="${data.items}",
            parallel=True,
            max_concurrent=8,
            retry_wait=2.5,
        )

        config = compute_node_config(
            node_type_name="DummyNode",
            static_params={},
            template_params={},
            batch_config=batch,
        )

        assert "batch" in config
        batch_keys = set(config["batch"].keys())
        # Only semantic keys should be present
        assert batch_keys == {"items_template", "item_alias", "error_handling", "max_retries"}
        # Operational keys must NOT leak into the config
        assert "parallel" not in batch_keys
        assert "max_concurrent" not in batch_keys
        assert "retry_wait" not in batch_keys

    def test_config_without_templates_or_batch(self) -> None:
        """A basic node without template or batch config should still produce
        a valid config with type and params."""
        config = compute_node_config(
            node_type_name="DummyNode",
            static_params={"command": "ls -la"},
            template_params={},
            batch_config=None,
        )

        assert config["type"] == "DummyNode"
        assert config["params"] == {"command": "ls -la"}
        # No template_params or batch keys when absent
        assert "template_params" not in config
        assert "batch" not in config


class TestConfigHash:
    """Tests for compute_config_hash() determinism and sensitivity."""

    def test_changing_template_param_changes_hash(self) -> None:
        """Two configs differing only in a template param value must produce
        different hashes -- this is the core cache invalidation signal."""
        config_a = compute_node_config(
            node_type_name="DummyNode",
            static_params={"model": "gpt-4"},
            template_params={"prompt": "${input.text}"},
            batch_config=None,
        )
        config_b = compute_node_config(
            node_type_name="DummyNode",
            static_params={"model": "gpt-4"},
            template_params={"prompt": "${input.summary}"},
            batch_config=None,
        )

        hash_a = compute_config_hash(config_a)
        hash_b = compute_config_hash(config_b)

        assert hash_a != hash_b, "Different template params must produce different hashes"

    def test_source_line_change_does_not_change_hash(self) -> None:
        """Changing _source_line values (line numbers shift when editing the
        .pflow.md file) must NOT change the hash, because node behavior is
        unchanged."""
        config_before = compute_node_config(
            node_type_name="DummyNode",
            static_params={
                "command": "echo hello",
                "command_source_line": 10,
            },
            template_params={},
            batch_config=None,
        )
        config_after = compute_node_config(
            node_type_name="DummyNode",
            static_params={
                "command": "echo hello",
                "command_source_line": 25,
            },
            template_params={},
            batch_config=None,
        )

        hash_before = compute_config_hash(config_before)
        hash_after = compute_config_hash(config_after)

        assert hash_before == hash_after, "_source_line metadata must be excluded from the hash"

    def test_hash_is_deterministic(self) -> None:
        """Calling compute_config_hash twice on identical config produces the
        same result (no randomness)."""
        config = compute_node_config(
            node_type_name="DummyNode",
            static_params={"model": "gpt-4"},
            template_params={"prompt": "${input.text}"},
            batch_config=None,
        )

        assert compute_config_hash(config) == compute_config_hash(config)

    def test_changing_static_param_changes_hash(self) -> None:
        """Changing a static (non-template) parameter must also change the hash."""
        config_a = compute_node_config(
            node_type_name="DummyNode",
            static_params={"command": "echo hello"},
            template_params={},
            batch_config=None,
        )
        config_b = compute_node_config(
            node_type_name="DummyNode",
            static_params={"command": "echo goodbye"},
            template_params={},
            batch_config=None,
        )

        hash_a = compute_config_hash(config_a)
        hash_b = compute_config_hash(config_b)

        assert hash_a != hash_b

    def test_changing_batch_semantic_config_changes_hash(self) -> None:
        """Changing batch error_handling (semantic) must change the hash."""
        config_a = compute_node_config(
            node_type_name="DummyNode",
            static_params={},
            template_params={},
            batch_config=BatchConfig(
                items_template="${data.items}",
                error_handling="fail_fast",
            ),
        )
        config_b = compute_node_config(
            node_type_name="DummyNode",
            static_params={},
            template_params={},
            batch_config=BatchConfig(
                items_template="${data.items}",
                error_handling="continue",
            ),
        )

        hash_a = compute_config_hash(config_a)
        hash_b = compute_config_hash(config_b)

        assert hash_a != hash_b

    def test_changing_batch_operational_config_does_not_change_hash(self) -> None:
        """Changing parallel or max_concurrent (operational) must NOT change
        the hash since they don't affect the computed result."""
        config_a = compute_node_config(
            node_type_name="DummyNode",
            static_params={},
            template_params={},
            batch_config=BatchConfig(
                items_template="${data.items}",
                parallel=False,
                max_concurrent=4,
            ),
        )
        config_b = compute_node_config(
            node_type_name="DummyNode",
            static_params={},
            template_params={},
            batch_config=BatchConfig(
                items_template="${data.items}",
                parallel=True,
                max_concurrent=16,
            ),
        )

        hash_a = compute_config_hash(config_a)
        hash_b = compute_config_hash(config_b)

        assert hash_a == hash_b, "Operational batch config (parallel, max_concurrent) should be excluded from hash"
